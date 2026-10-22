"""Governance tools (WP-G6): scope ``governance.read`` and ``governance.write``.

Reads return what the console shows to the same person: the systems in the scope of the app
(``SystemService.scope_for``), ids and enums, masked text. Writes are drafts only and go through
the same services as the API, so the same validation, the same scoping and the same chain records
apply. A write tool has no way to classify a system, approve a stage, accept a risk, change a
risk level, close an incident or turn a guardian off; the registry refuses such names.
"""

from __future__ import annotations

import json
from typing import Any

from supervisor.core.errors import NotFoundError
from supervisor.governance import kpis as kpi_mod
from supervisor.governance.model import (
    LINK_ROLES,
    REF_KINDS,
    SystemsError,
    check_ref_id,
    choice,
    normalise_draft,
)
from supervisor.governance.systems import system_id_for
from supervisor.mcp_server.common import (
    LIMIT_SPEC,
    actor_of,
    agents_of_system,
    limit_of,
    mask_deep,
    mask_row,
    pick,
    plain,
    sees_everything,
    systems_on,
    visible_agent_ids,
    visible_system,
)
from supervisor.mcp_server.registry import Registry, Tool

KINDS = ("system", "risk", "control", "incident", "review")
# Fields a draft may not carry: they are decisions of people (classification, risk level).
DRAFT_REFUSED = (
    "decision33_class",
    "risk_level",
    "risk_level_source",
    "risk_justification",
    "business_impact",
    "autonomy_level",
    "status",
    "lifecycle_stage",
)
# Free-text fields, by entity: every one goes through the masker before it leaves (review H1).
SYSTEM_TEXT = ("name", "purpose", "owner_team", "risk_justification")
RISK_TEXT_KEYS = ("title", "description", "treatment_note", "marginal_note", "owner")
CONTROL_TEXT = ("title", "objective", "owner", "notes", "description")
INCIDENT_TEXT = ("title", "root_cause", "affected_scope")
REVIEW_TEXT = ("title", "reopen_reason")
TASK_TEXT = ("title", "evidence_ref", "waive_reason")
SYSTEM_FIELDS = (
    "system_id",
    "name",
    "owner_user",
    "owner_team",
    "system_type",
    "lifecycle_stage",
    "status",
    "risk_level",
    "effective_risk_level",
    "decision33_class",
    "autonomy_level",
    "components_n",
    "team_n",
)
RISK_FIELDS = (
    "risk_id",
    "title",
    "category",
    "agent_id",
    "node_id",
    "treatment",
    "status",
    "inherent_score",
    "residual_band",
    "residual_score",
    "review_overdue",
    "agents",
)
CONTROL_FIELDS = (
    "control_id",
    "title",
    "control_type",
    "implemented_by",
    "status",
    "owner",
    "matrix_n",
    "risk_n",
    "sources_n",
)
INCIDENT_FIELDS = (
    "incident_id",
    "system_id",
    "agent_id",
    "kind",
    "severity",
    "title",
    "status",
    "opened_at",
    "closed_at",
)
REVIEW_FIELDS = (
    "review_id",
    "system_id",
    "kind",
    "title",
    "status",
    "reviewer_user",
    "locked",
    "completed_at",
)
TASK_FIELDS = (
    "task_id",
    "agent_id",
    "template_id",
    "kind",
    "stage",
    "title",
    "owner_role",
    "required",
    "status",
    "due_at",
    "overdue",
    "evidence_kind",
)


def _str_filters(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or any(not isinstance(v, str) for v in raw.values()):
        raise SystemsError("filters must be an object with text values")
    return {str(k): v for k, v in raw.items()}


# ------------------------------------------------------------------------------ reads


def _risk_visible(call: Any, row: dict[str, Any]) -> bool:
    if sees_everything(call):
        return True
    mine = visible_agent_ids(call)
    return bool(mine & {str(a).lower() for a in row.get("agents") or []})


def list_entities(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    kind, filters, limit = a["kind"], _str_filters(a.get("filters")), limit_of(a)
    ctx, s = call.ctx, call.ctx.settings
    svc = systems_on(call)
    scope = svc.scope_for(call.principal)
    if kind == "system":
        rows = [
            mask_row(call, pick(r, SYSTEM_FIELDS), SYSTEM_TEXT)
            for r in svc.list_systems(scope, filters)
        ]
    elif kind == "risk":
        if not s.risk_register_enabled:
            raise SystemsError("the risk register is off (RISK_REGISTER_ENABLED=1)")
        rows = [
            mask_row(call, pick(r, RISK_FIELDS), RISK_TEXT_KEYS)
            for r in ctx.risks.list_risks(filters)
            if _risk_visible(call, r)
        ]
    elif kind == "control":
        if not s.controls_enabled:
            raise SystemsError("the control catalogue is off (CONTROLS_ENABLED=1)")
        rows = [
            mask_row(call, pick(r, CONTROL_FIELDS), CONTROL_TEXT)
            for r in ctx.controls.list_controls(filters)
        ]
    elif kind == "incident":
        if not s.governance_actions_enabled:
            raise SystemsError("incidents are off (GOVERNANCE_ACTIONS_ENABLED=1)")
        rows = [
            mask_row(call, pick(r, INCIDENT_FIELDS), INCIDENT_TEXT)
            for r in ctx.incidents.list_incidents(call.principal, filters)
        ]
    else:  # review
        rows = []
        for r in svc.list_systems(scope, {}):
            if filters.get("system") and filters["system"] != r["system_id"]:
                continue
            for rv in ctx.reviews.list_reviews(str(r["system_id"])):
                if not filters.get("status") or rv["status"] == filters["status"]:
                    rows.append(mask_row(call, pick(rv, REVIEW_FIELDS), REVIEW_TEXT))
    return {"kind": kind, "count": len(rows), "truncated": len(rows) > limit, "items": rows[:limit]}


def get_entity(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    kind, eid = a["kind"], a["id"]
    ctx = call.ctx
    svc = systems_on(call)
    if kind == "system":
        item = mask_row(call, svc.get(visible_system(call, eid)), SYSTEM_TEXT, ("tags",))
        item["components"] = [
            mask_row(call, c, ("evidence_ref",)) for c in item.get("components") or []
        ]
        return {"kind": kind, "item": item}
    if kind == "risk":
        if not ctx.settings.risk_register_enabled:
            raise SystemsError("the risk register is off (RISK_REGISTER_ENABLED=1)")
        row = ctx.risks.get(eid)
        if not _risk_visible(call, row):
            raise NotFoundError(f"risk {eid} does not exist")
        return {"kind": kind, "item": mask_row(call, plain(row), RISK_TEXT_KEYS)}
    if kind == "control":
        if not ctx.settings.controls_enabled:
            raise SystemsError("the control catalogue is off (CONTROLS_ENABLED=1)")
        return {"kind": kind, "item": mask_row(call, plain(ctx.controls.get(eid)), CONTROL_TEXT)}
    if kind == "incident":
        if not ctx.settings.governance_actions_enabled:
            raise SystemsError("incidents are off (GOVERNANCE_ACTIONS_ENABLED=1)")
        item = plain(ctx.incidents.get(eid, call.principal))
        return {"kind": kind, "item": mask_row(call, item, INCIDENT_TEXT)}
    row = ctx.state.get("review", {"review_id": eid})
    if row is None:
        raise NotFoundError(f"review {eid} does not exist")
    sid = visible_system(call, str(row["system_id"]))
    item = mask_row(call, plain(ctx.reviews.get(sid, eid)), REVIEW_TEXT, ("reports",))
    return {"kind": kind, "item": item}


def _task_owner_ids(call: Any, system_id: str) -> set[str]:
    return {system_id.lower(), *(x.lower() for x in agents_of_system(call, system_id))}


def list_tasks(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    sid = visible_system(call, a["system_id"])
    if not call.ctx.settings.controls_enabled:
        raise SystemsError("the task list is off (CONTROLS_ENABLED=1)")
    owners = _task_owner_ids(call, sid)
    rows = [t for t in call.ctx.tasks.list_tasks() if str(t["agent_id"]).lower() in owners]
    return {
        "system_id": sid,
        "count": len(rows),
        "items": [mask_row(call, pick(t, TASK_FIELDS), TASK_TEXT) for t in rows[: limit_of(a)]],
    }


def transparency_report(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    sid = visible_system(call, a["system_id"])
    if not call.ctx.settings.transparency_enabled:
        raise SystemsError("transparency reports are off (TRANSPARENCY_ENABLED=1)")
    out = []
    for agent in agents_of_system(call, sid):
        data, info = call.ctx.transparency.report(agent, a["variant"])
        out.append({"agent_id": agent, "info": plain(info), "report": mask_deep(call, plain(data))})
    return {"system_id": sid, "variant": a["variant"], "agents": out}


def kpis(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    systems_on(call)
    return plain(kpi_mod.compute(call.ctx, call.principal))  # type: ignore[no-any-return]


# ------------------------------------------------------------------------------ writes


def _target_system(a: dict[str, Any]) -> tuple[str | None, str | None]:
    return "system", a.get("system_id")


def register_system(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    svc = systems_on(call)
    draft = a["draft"]
    refused = sorted(set(DRAFT_REFUSED) & set(draft))
    if refused:
        raise SystemsError(
            f"a draft cannot carry {', '.join(refused)}: the class, the risk level and the "
            "stage are set by people in the console (a new system is unclassified, initiation)"
        )
    actor = actor_of(call)
    if draft.get("owner_user") not in (None, "", actor):
        raise SystemsError(
            f"owner_user must be {actor} (or left out): an app registers a system as its own "
            "draft; a person takes the ownership over in the console"
        )
    draft = {**draft, "owner_user": actor}
    fields = normalise_draft(draft)  # the same validation as POST /v1/systems
    svc._check_team_in_scope(call.principal, fields["owner_team"])  # noqa: SLF001
    svc._unique_name(fields["name"])  # noqa: SLF001
    if not apply:
        return {
            "action": "register_system",
            "system_id": system_id_for(fields["name"]),
            "status": "draft",
            "lifecycle_stage": "initiation",
            "decision33_class": "unclassified",
            "fields": mask_row(call, plain(fields), SYSTEM_TEXT, ("tags",)),
        }
    out = svc.register(draft, actor, for_user=call.principal)
    return {
        "system_id": out["system_id"],
        "status": out["status"],
        "lifecycle_stage": out["lifecycle_stage"],
        "decision33_class": out["decision33_class"],
        "next": "a person classifies the system in the console; classification_draft prepares it",
    }


def link_component(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    svc = systems_on(call)
    sid = visible_system(call, a["system_id"])
    kind = choice(a["ref_kind"], REF_KINDS, "ref_kind")
    role = choice(a.get("role") or "component_of", LINK_ROLES, "role")
    ref = check_ref_id(a["ref_id"])
    if not apply:
        return {
            "action": "link_component",
            "system_id": sid,
            "ref_kind": kind,
            "ref_id": ref,
            "role": role,
        }
    out = svc.link(sid, kind, ref, actor_of(call), role=role, for_user=call.principal)
    return {
        "system_id": sid,
        "components": [
            pick(c, ("component_id", "ref_kind", "ref_id", "role")) for c in out["components"]
        ],
    }


RISK_TEXT = ("title", "description", "category", "owner", "treatment_note", "review_date")


def propose_risk(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    from supervisor.risk import model as rm

    systems_on(call)
    ctx = call.ctx
    if not ctx.settings.risk_register_enabled:
        raise SystemsError("the risk register is off (RISK_REGISTER_ENABLED=1)")
    sid = visible_system(call, a["system_id"])
    linked = {x.lower(): x for x in agents_of_system(call, sid)}
    agent = linked.get(str(a["agent_id"]).lower())
    if agent is None:
        raise SystemsError(f"agent {a['agent_id']} is not linked to AI system {sid}")
    if a.get("treatment") == "accept":
        raise SystemsError(
            "a proposal cannot accept a risk: accepting is a decision of a person in the console"
        )
    data = {
        k: a.get(k)
        for k in (
            *RISK_TEXT,
            "inherent_likelihood",
            "inherent_impact",
            "treatment",
            "residual_likelihood",
            "residual_impact",
        )
        if a.get(k) is not None
    }
    data.update(agent_id=agent, status="draft")
    fields = rm.normalise(data, source="manual")  # the same validation as POST /v1/risks
    if not apply:
        return {
            "action": "propose_risk",
            "system_id": sid,
            "status": "draft",
            "fields": mask_row(
                call, plain({k: fields[k] for k in fields if k != "source"}), RISK_TEXT_KEYS
            ),
        }
    row = ctx.risks.create(data, actor_of(call))
    return {
        "risk_id": row["risk_id"],
        "status": row["status"],
        "next": "a person reviews the draft in the console and makes it active",
    }


def complete_task(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    ctx = call.ctx
    systems_on(call)
    if not ctx.settings.controls_enabled:
        raise SystemsError("the task list is off (CONTROLS_ENABLED=1)")
    task = ctx.tasks.get(a["task_id"])
    owner = str(task["agent_id"]).lower()
    visible = ctx.systems.list_systems(ctx.systems.scope_for(call.principal), {})
    if not any(owner in _task_owner_ids(call, str(s["system_id"])) for s in visible):
        raise NotFoundError(f"task {a['task_id']} does not exist")
    role = str(task["owner_role"])
    if task["kind"] == "move" or role == "approver":
        raise SystemsError(
            "this task is a lifecycle move or belongs to an approver: a person closes it in the "
            "console"
        )
    if role not in call.principal.roles:
        raise SystemsError(
            f"task {a['task_id']} belongs to role {role}; the roles of this app are "
            f"{', '.join(sorted(call.principal.roles))}"
        )
    if not apply:
        return {
            "action": "complete_task",
            "task_id": a["task_id"],
            "title": mask_row(call, task, ("title",))["title"],
            "from_status": task["status"],
            "to_status": "done",
            "evidence_kind": task["evidence_kind"],
        }
    out = ctx.tasks.done(a["task_id"], call.principal, a.get("evidence_ref"))
    return {"task_id": out["task_id"], "status": out["status"]}


def _masked_classification(call: Any, view: Any) -> dict[str, Any]:
    out = plain(view)
    out["answers"] = [mask_row(call, x, ("justification",)) for x in out.get("answers") or []]
    return out  # type: ignore[no-any-return]


def _protected_draft(call: Any, system_id: str) -> dict[str, Any] | None:
    """The open draft of the system when a person made it or edited it; the app never replaces
    it (making a draft again resets the answers)."""
    rows = [
        dict(r)
        for r in call.ctx.state.query("classification", {"system_id": system_id})
        if r["status"] == "draft"
    ]
    for row in sorted(rows, key=lambda r: str(r["created_at"]), reverse=True):
        raw = row.get("answers")
        try:
            answers = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        except (TypeError, ValueError):
            answers = {}
        edited = any(
            isinstance(v, dict) and v.get("source") == "person" and v.get("answer") is not None
            for v in answers.values()
        )
        if edited or not str(row["created_by"]).startswith("mcp:"):
            return row
    return None


def classification_draft(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    sid = visible_system(call, a["system_id"])
    kept = _protected_draft(call, sid)
    if kept is not None:
        return {
            "action": "classification_draft",
            "system_id": sid,
            "written": False,
            "refused": True,
            "reason": "an open draft made or edited by a person exists; the server does not "
            "replace it. A person continues it in the console.",
            "classification": _masked_classification(call, call.ctx.classification.view(kept)),
        }
    if not apply:
        return {
            "action": "classification_draft",
            "system_id": sid,
            "makes": "a draft Decision 33 classification from the rules",
            "applies": False,
        }
    view = call.ctx.classification.draft(sid, actor_of(call))
    return {
        "system_id": sid,
        "classification": _masked_classification(call, view),
        "next": "a person edits and applies the classification in the console; the server "
        "has no tool for that",
    }


def _target_task(a: dict[str, Any]) -> tuple[str | None, str | None]:
    return "task", a.get("task_id")


ID = {"type": "string", "maxLength": 128}


def register(reg: Registry) -> None:
    r = reg.register
    r(
        Tool(
            "list_entities",
            "List entities in the scope of this app: kind system, risk, control, incident or "
            "review. filters is an object of text values (for systems: status, owner_team, "
            "lifecycle_stage, risk, system_type, q).",
            "governance.read",
            {
                "properties": {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "filters": {"type": "object"},
                    "limit": LIMIT_SPEC,
                },
                "required": ["kind"],
            },
            list_entities,
        )
    )
    r(
        Tool(
            "get_entity",
            "One entity by kind and id (review: the review id).",
            "governance.read",
            {
                "properties": {"kind": {"type": "string", "enum": list(KINDS)}, "id": ID},
                "required": ["kind", "id"],
            },
            get_entity,
        )
    )
    r(
        Tool(
            "list_tasks",
            "The lifecycle tasks of an AI system and of its linked agents.",
            "governance.read",
            {"properties": {"system_id": ID, "limit": LIMIT_SPEC}, "required": ["system_id"]},
            list_tasks,
        )
    )
    r(
        Tool(
            "transparency_report",
            "The latest signed transparency report (or a preview) of each agent of an AI "
            "system. Variant: regulator, customer or internal.",
            "governance.read",
            {
                "properties": {
                    "system_id": ID,
                    "variant": {"type": "string", "enum": ["regulator", "customer", "internal"]},
                },
                "required": ["system_id", "variant"],
            },
            transparency_report,
        )
    )
    r(
        Tool(
            "kpis",
            "Governance KPIs (coverage, quality, speed) for the systems in scope; the figures of "
            "GET /v1/kpis and of the Governance overview.",
            "governance.read",
            {"properties": {}},
            kpis,
        )
    )
    r(
        Tool(
            "register_system",
            "Register an AI system as a draft in initiation, unclassified. draft: name, "
            "owner_team, purpose, system_type, org_role, user_segment, personal_data, "
            "human_control (+ optional business_owner, money_movement, credit_decision, tags). "
            "The app is the owner of the draft (owner_user may be left out). It cannot set the "
            "class, the risk level, the autonomy level or the stage.",
            "governance.write",
            {"properties": {"draft": {"type": "object"}}, "required": ["draft"]},
            register_system,
            write=True,
            permission="systems.edit",
            target=lambda a: ("system", None),
        )
    )
    r(
        Tool(
            "link_component",
            "Link an agent or an inventory node to an AI system.",
            "governance.write",
            {
                "properties": {
                    "system_id": ID,
                    "ref_kind": {"type": "string", "enum": list(REF_KINDS)},
                    "ref_id": ID,
                    "role": {"type": "string", "enum": list(LINK_ROLES)},
                },
                "required": ["system_id", "ref_kind", "ref_id"],
            },
            link_component,
            write=True,
            permission="systems.edit",
            target=_target_system,
        )
    )
    r(
        Tool(
            "propose_risk",
            "Propose a risk for an agent of an AI system. It is stored as a draft, never "
            "active, and never with treatment accept.",
            "governance.write",
            {
                "properties": {
                    "system_id": ID,
                    "agent_id": ID,
                    "title": {"type": "string", "maxLength": 200},
                    "description": {"type": "string", "maxLength": 2000},
                    "category": {"type": "string"},
                    "inherent_likelihood": {"type": "integer", "minimum": 1, "maximum": 5},
                    "inherent_impact": {"type": "integer", "minimum": 1, "maximum": 5},
                    "treatment": {"type": "string", "enum": ["avoid", "mitigate", "transfer"]},
                    "treatment_note": {"type": "string", "maxLength": 2000},
                    "residual_likelihood": {"type": "integer", "minimum": 1, "maximum": 5},
                    "residual_impact": {"type": "integer", "minimum": 1, "maximum": 5},
                    "owner": {"type": "string", "maxLength": 128},
                    "review_date": {"type": "string", "maxLength": 10},
                },
                "required": [
                    "system_id",
                    "agent_id",
                    "title",
                    "category",
                    "inherent_likelihood",
                    "inherent_impact",
                    "treatment",
                    "owner",
                ],
            },
            propose_risk,
            write=True,
            permission="risks.edit",
            target=lambda a: ("risk", None),
        )
    )
    r(
        Tool(
            "complete_task",
            "Mark a task done. Only a task that belongs to a role this app holds, in a system "
            "in its scope; a lifecycle move or an approver task is refused.",
            "governance.write",
            {
                "properties": {"task_id": ID, "evidence_ref": {"type": "string", "maxLength": 200}},
                "required": ["task_id"],
            },
            complete_task,
            write=True,
            permission="tasks.edit",
            target=_target_task,
        )
    )
    r(
        Tool(
            "classification_draft",
            "Prepare a draft Decision 33 classification of an AI system from the rules. It "
            "never applies it; a person does that in the console.",
            "governance.write",
            {"properties": {"system_id": ID}, "required": ["system_id"]},
            classification_draft,
            write=True,
            permission="systems.edit",
            target=_target_system,
        )
    )
