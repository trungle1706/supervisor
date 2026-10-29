"""Read models and form parsers of the agent factory pages (WP-F2, flag ``AGENT_FACTORY``).

The routes (``factory_routes.py``) stay thin. Here: the catalogue cards, the portfolio strip, the
data of each editor step, and one pure parser per step that turns a posted form into a new
definition dict. A parser never validates; ``FactoryStore.save_draft`` does, with
``agent_definition_v1`` and the registry, and names the field of any refusal. The editor cannot
write a definition the schema refuses.
"""

from __future__ import annotations

import copy
import functools
import re
from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import PermissionDenied
from supervisor.console import factory_ux5
from supervisor.console.context import ConsoleContext
from supervisor.factory import caps, golden, helpers, linter, registry
from supervisor.factory.preview import MAX_EXPORTS, dry_preview
from supervisor.factory.schemas.facts_v1 import export_card
from supervisor.factory.store import FactoryError, FactoryStore, permits
from supervisor.factory.templates import list_templates

STEPS = (
    "template",
    "policy",
    "checklist",
    "tools",
    "instructions",
    "harness",
    "guardians",
    "preview",
    "golden",
)
STATE_PILL = {
    "draft": "warn",
    "tested": "info",
    "approved": "teal",
    "live": "ok",
    "retired": "neutral",
}


@functools.lru_cache(maxsize=1)
def tool_registry() -> registry.ToolRegistry:
    return registry.load_tools()


@functools.lru_cache(maxsize=1)
def group_registry() -> registry.GroupRegistry:
    return registry.load_groups()


def store(ctx: ConsoleContext) -> FactoryStore:
    return FactoryStore(ctx.state, ctx.tables, ctx.clock, tool_registry(), group_registry())


def helper_store(ctx: ConsoleContext) -> helpers.HelperStore:
    return helpers.HelperStore(ctx.state, ctx.clock)


def actor(me: Any) -> str:
    if getattr(me, "kind", "user") != "user":
        raise PermissionDenied("editing an agent needs a signed-in person")
    return str(me.user_id)


def may_edit(me: Any, owner_group: str) -> bool:
    return getattr(me, "kind", "user") == "user" and permits(
        me.roles, owner_group, group_registry(), getattr(me, "groups", None)
    )


def require_edit(me: Any, owner_group: str) -> str:
    who = actor(me)
    if not may_edit(me, owner_group):
        raise PermissionDenied(f"your role may not edit the agents of the group {owner_group}")
    return who


# ------------------------------------------------------------------------------ catalogue


def _gate_card(ctx: ConsoleContext, row: Mapping[str, Any]) -> dict[str, Any]:
    """WP-F3: the last gate result and the live version (empty without a table read when off)."""
    from supervisor.console import factory_gate_view as fgv

    return fgv.card_extra(ctx, row)


def all_steps(ctx: ConsoleContext) -> tuple[str, ...]:
    from supervisor.console import factory_gate_view as fgv

    return fgv.steps(ctx)


def card(ctx: ConsoleContext, me: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    d = row["definition"]
    group = group_registry().get(row["owner_group"])
    return {
        "id": row["id"],
        "version": row["version"],
        "name": d.get("name", row["id"]),
        "description": d.get("description", ""),
        "dimension_id": row["dimension_id"],
        "owner_group": row["owner_group"],
        "owner_label": group.label if group else row["owner_group"],
        "state": row["state"],
        "state_pill": STATE_PILL.get(row["state"], "neutral"),
        "checklist_size": len(d.get("checklist") or []),
        "golden_size": len(golden.all_gate_cases(ctx.settings.data_dir, row["id"])),
        **_gate_card(ctx, row),
        "can_edit": may_edit(me, row["owner_group"]),
        "updated_at": row.get("updated_at"),
    }


def catalogue_data(
    ctx: ConsoleContext, me: Any, group: str = "", dimension: str = "", state: str = ""
) -> dict[str, Any]:
    st = store(ctx)
    rows = st.list_agents(
        owner_group=group if group in caps.GROUPS else None,
        dimension_id=dimension if dimension in caps.DIMENSIONS else None,
        state=state if state in caps.LIFECYCLE_STATES else None,
    )
    groups = group_registry()
    creatable = [
        {"dimension_id": t["dimension_id"], "label": t["label_en"]}
        for t in list_templates()
        if (g := groups.owner_of(t["dimension_id"])) is not None and may_edit(me, g.group_id)
    ]
    strip = []
    for p in st.portfolio():
        agents = [r for r in st.list_agents(dimension_id=p["dimension_id"])]
        strip.append({**p, "agents": len(agents)})
    return {
        "fa": {
            "cards": [card(ctx, me, r) for r in rows],
            "portfolio": strip,
            "creatable": creatable,
            "group": group,
            "dimension": dimension,
            "state": state,
            "groups": [g.group_id for g in groups.groups],
            "dimensions": list(caps.DIMENSIONS),
            "states": list(caps.LIFECYCLE_STATES),
        }
    }


# ------------------------------------------------------------------------------ editor


def load_row(ctx: ConsoleContext, agent_id: str, version: str = "") -> dict[str, Any]:
    if not caps.ID_RE.match(agent_id or ""):
        raise FactoryError("invalid_definition", "id: not an agent id")
    row = store(ctx).get(agent_id, version or None)
    if row is None:
        raise FactoryError("not_found", f"agent {agent_id} does not exist")
    return row


def editor_data(
    ctx: ConsoleContext, me: Any, agent_id: str, version: str = "", step: str = "template"
) -> dict[str, Any]:
    if step not in all_steps(ctx):
        raise FactoryError("bad_step", f"step must be one of {', '.join(all_steps(ctx))}")
    st = store(ctx)
    row = load_row(ctx, agent_id, version)
    defn = row["definition"]
    group = group_registry().get(row["owner_group"])
    editable = row["state"] == "draft" and may_edit(me, row["owner_group"])
    data: dict[str, Any] = {
        "agent": card(ctx, me, row),
        "row_version": row["row_version"],
        "defn": defn,
        "step": step,
        "steps": all_steps(ctx),
        "version": row["version"],
        "versions": [{"version": v["version"], "state": v["state"]} for v in st.versions(agent_id)],
        "editable": editable,
        "can_new_version": may_edit(me, row["owner_group"])
        and not any(v["state"] == "draft" for v in st.versions(agent_id)),
        "can_retire": may_edit(me, row["owner_group"]) and row["state"] == "draft",
        "group": group,
        "caps": caps,
        "model_ready": helpers.model_ready(ctx.settings),
        "lint": [i.as_dict() for i in linter.lint_definition(defn)],
        "events": list(reversed(st.events(agent_id, row["version"])))[:15],
    }
    data.update(_step_extra(ctx, st, row, step, me))
    if ctx.settings.console_ux5:  # --- UX5 G6 ---
        data["stages"] = factory_ux5.stages(data["steps"])
        data["ux_events"] = factory_ux5.event_rows(data["events"])
    return {"ed": data}


def _step_extra(
    ctx: ConsoleContext, st: FactoryStore, row: Mapping[str, Any], step: str, me: Any = None
) -> dict[str, Any]:
    defn = row["definition"]
    out: dict[str, Any] = {}
    if step == "template":
        out["template"] = next(
            (t for t in list_templates() if t["dimension_id"] == row["dimension_id"]), None
        )
    elif step == "tools":
        visible = tool_registry().visible_to(row["owner_group"])
        chosen = {t["tool_id"]: t for t in defn.get("tools") or []}
        out["tools_view"] = [
            {
                "tool_id": t.tool_id,
                "label": t.label,
                "kind": t.kind,
                "scopes": t.scope,
                "data_class": t.data_class,
                "modes": t.modes,
                "on": t.tool_id in chosen,
                "mode": chosen.get(t.tool_id, {}).get("mode", "read"),
                "scope": chosen.get(t.tool_id, {}).get("scope") or "",
            }
            for t in visible
        ]
    elif step == "harness":
        hitl = defn.get("harness", {}).get("hitl", {})
        out["perm_of"] = {p["tool_id"]: p["mode"] for p in hitl.get("permissions", [])}
    elif step == "checklist":
        out["drafts"] = _drafts(ctx, row, "checklist_drafter")
    elif step == "preview":
        out["plan"] = None
        out["picked"] = ""
        out["nodes"] = fact_nodes(ctx)
        out["drafts"] = _drafts(ctx, row, "result_explainer", status="")
    elif step == "gate":
        from supervisor.console import factory_gate_view as fgv

        out["gate"] = fgv.gate_data(ctx, me, row)
    elif step == "golden":
        cases = golden.load_cases(ctx.settings.data_dir, row["id"])
        # The golden set is the checklist cases plus the gate cases (one count everywhere). Gate
        # cases carry ``expected: {checklist_id: verdict}``, so the stratification counts them all.
        every = golden.all_gate_cases(ctx.settings.data_dir, row["id"])
        out["strat"] = golden.gate_stratification(every, [c["id"] for c in defn["checklist"]])
        out["golden_total"] = len(every)
        out["checklist_total"] = len(cases)
        out["golden_min"] = caps.GOLDEN_MIN_CASES
        from supervisor.console import factory_gate_view as fgv

        out["gate_on"] = fgv.on(ctx)
        if out["gate_on"]:
            out["gate_cases"] = len(golden.all_gate_cases(ctx.settings.data_dir, row["id"]))
            out["gate_labels"] = len(golden.load_labels(ctx.settings.data_dir, row["id"]))
        out["cases"] = cases[:50]
        out["drafts"] = _drafts(ctx, row, "golden_generator")
    return out


def _drafts(
    ctx: ConsoleContext, row: Mapping[str, Any], helper: str, status: str = "draft"
) -> list[dict[str, Any]]:
    rows = helper_store(ctx).list(row["id"], helper, status or None)
    return [r for r in rows if r["version"] == row["version"]]


def fact_nodes(ctx: ConsoleContext) -> list[str]:
    """Node ids that have a stored facts card (at most 50, sorted)."""
    seen = {str(r["node_id"]) for r in ctx.state.query("onboard_facts")}
    return sorted(seen)[:50]


def preview_data(ctx: ConsoleContext, row: Mapping[str, Any], nodes_raw: str) -> dict[str, Any]:
    from supervisor.onboard.facts import FactsService

    ids = [n for n in re.split(r"[,\s]+", nodes_raw or "") if n][:MAX_EXPORTS]
    svc = FactsService(ctx.settings, ctx.state, ctx.clock, tables=ctx.tables)
    exports = [export_card(svc.card(n)) for n in ids]
    exports = [{**e, "node_id": n} for e, n in zip(exports, ids, strict=True)]
    if not exports:
        exports = [{"node_id": "(no stored facts chosen)", "attempt_n": None, "facts": []}]
    kinds = {t.tool_id: t.kind for t in tool_registry().tools}
    return dry_preview(row["definition"], exports, kinds)


# ------------------------------------------------------------------------------ form parsers


def _int(raw: str, field: str, default: int | None = None) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return default
    if not (raw.isascii() and raw.isdigit() and len(raw) < 10):
        raise FactoryError("invalid_definition", f"{field}: must be a whole number")
    return int(raw)


def _split(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;\n,]+", raw or "") if p.strip()]


def apply_template(defn: dict[str, Any], f: Mapping[str, str]) -> dict[str, Any]:
    defn["name"] = (f.get("name") or "").strip()
    defn["description"] = (f.get("description") or "").strip()
    defn["eval_pack"] = (f.get("eval_pack") or defn["eval_pack"]).strip()
    return defn


def apply_policy(defn: dict[str, Any], f: Mapping[str, str]) -> dict[str, Any]:
    refs = defn.setdefault("policy_refs", [])
    op = f.get("op", "")
    if op == "drop":
        i = _int(f.get("index", ""), "policy_refs")
        if i is None or i >= len(refs):
            raise FactoryError("invalid_definition", "policy_refs: no such row")
        refs.pop(i)
    elif op == "add":
        source = f.get("source", "regkb")
        doc_id = (f.get("doc_id") or "").strip()
        if source == "regkb":
            from supervisor.console import regkb_view

            try:
                regkb_view.check_instrument(doc_id)
            except Exception:  # noqa: BLE001 - one message for an unknown instrument
                raise FactoryError(
                    "invalid_definition",
                    f"policy_refs.doc_id: {doc_id!r} is not a RegKB instrument",
                ) from None
        refs.append(
            {
                "doc_id": doc_id,
                "source": source,
                "version": _int(f.get("ref_version", ""), "policy_refs.version", 1),
                "sections": _split(f.get("sections", "")),
            }
        )
    else:
        raise FactoryError("bad_op", "op must be add or drop")
    return defn


def apply_checklist(defn: dict[str, Any], f: Mapping[str, str]) -> dict[str, Any]:
    items = defn.setdefault("checklist", [])
    op = f.get("op", "")
    item_id = (f.get("id") or "").strip()
    if op == "drop":
        kept = [c for c in items if c["id"] != item_id]
        if len(kept) == len(items):
            raise FactoryError("invalid_definition", f"checklist: no item {item_id}")
        defn["checklist"] = kept
        # an approval point that named the dropped item goes with it
        hitl = defn.get("harness", {}).get("hitl", {})
        hitl["approval_points"] = [
            a
            for a in hitl.get("approval_points", [])
            if not (a["kind"] == "checklist" and a["ref"] == item_id)
        ]
        return defn
    if op not in ("add", "edit"):
        raise FactoryError("bad_op", "op must be add, edit or drop")
    new = {
        "id": item_id,
        "question": (f.get("question") or "").strip(),
        "evidence": [k for k in caps.EVIDENCE_KINDS if f.get(f"ev_{k}")],
        "severity": f.get("severity", "medium"),
        "pass_rule": (f.get("pass_rule") or "").strip(),
    }
    existing = next((i for i, c in enumerate(items) if c["id"] == item_id), None)
    if op == "add":
        if existing is not None:
            raise FactoryError("invalid_definition", f"checklist: item {item_id} already exists")
        items.append(new)
    else:
        if existing is None:
            raise FactoryError("invalid_definition", f"checklist: no item {item_id}")
        items[existing] = new
    return defn


def apply_tools(
    defn: dict[str, Any], f: Mapping[str, str], visible: list[registry.Tool]
) -> dict[str, Any]:
    tools = []
    for t in visible:
        if not f.get(f"use_{t.tool_id}"):
            continue
        ref: dict[str, Any] = {"tool_id": t.tool_id, "mode": f.get(f"mode_{t.tool_id}", "read")}
        scope = (f.get(f"scope_{t.tool_id}") or "").strip()
        if scope:
            ref["scope"] = scope
        tools.append(ref)
    defn["tools"] = tools
    keep = {t["tool_id"] for t in tools}
    hitl = defn.setdefault("harness", {}).setdefault("hitl", {})
    hitl["permissions"] = [p for p in hitl.get("permissions", []) if p["tool_id"] in keep]
    return defn


def apply_instructions(defn: dict[str, Any], f: Mapping[str, str]) -> dict[str, Any]:
    defn["instructions"] = (f.get("instructions") or "").replace("\r\n", "\n")
    issues = linter.lint_definition(defn)
    blocking = [i for i in issues if i.severity == "error"]
    if blocking:
        raise FactoryError("lint", "instructions: " + "; ".join(i.message for i in blocking))
    return defn


def apply_harness(defn: dict[str, Any], f: Mapping[str, str]) -> dict[str, Any]:
    h = defn.setdefault("harness", {})
    chosen = [s for s in caps.CONTEXT_SOURCES if f.get(f"src_{s}")]
    order = {
        s: (_int(f.get(f"order_{s}", ""), f"harness.context.order_{s}", 99) or 99) for s in chosen
    }
    h["context"] = {
        "sources": sorted(chosen, key=lambda s: (order[s], caps.CONTEXT_SOURCES.index(s))),
        "budget_tokens": _int(
            f.get("budget_tokens", ""), "harness.context.budget_tokens", caps.CONTEXT_BUDGET_DEFAULT
        ),
        "max_document_chars": _int(
            f.get("max_document_chars", ""),
            "harness.context.max_document_chars",
            caps.MAX_DOCUMENT_CHARS_DEFAULT,
        ),
        "progressive": True,
    }
    mem_on = bool(f.get("system_memory"))
    h["memory"] = {"run": "scratchpad", "system_memory": mem_on, "cross_run": "off"}
    if mem_on:
        h["memory"]["retention_days"] = _int(
            f.get("retention_days", ""), "harness.memory.retention_days"
        )
        h["memory"]["fields"] = [m for m in caps.MEMORY_FIELDS if f.get(f"memf_{m}")]
    points = []
    for line in _split(f.get("approval_points", "")):
        kind, _, ref = line.partition(":")
        points.append({"kind": kind.strip(), "ref": ref.strip()})
    perms = []
    for t in defn.get("tools") or []:
        mode = f.get(f"perm_{t['tool_id']}", "")
        if mode:
            perms.append({"tool_id": t["tool_id"], "mode": mode})
    h["hitl"] = {"approval_points": points, "permissions": perms}
    h["verification"] = {
        "verifier": f.get("verifier", "rules"),
        "validators": [v for v in caps.EXTRA_VALIDATORS if f.get(f"val_{v}")],
    }
    mode = f.get("loop_mode", "single_pass")
    loop: dict[str, Any] = {
        "mode": mode,
        "max_iterations": _int(f.get("max_iterations", ""), "harness.loop.max_iterations", 1),
        "stop_when": [s for s in caps.STOP_WHEN if f.get(f"stop_{s}")] or ["all_answered"],
        "loop_evaluator": f.get("loop_evaluator", "rules"),
        "budget_tokens": _int(
            f.get("loop_budget_tokens", ""), "harness.loop.budget_tokens", caps.LOOP_BUDGET_DEFAULT
        ),
    }
    ms = _int(f.get("min_score", ""), "harness.loop.min_score")
    if ms is not None:
        loop["min_score"] = ms
    h["loop"] = loop
    h["system_prompt"] = {"preamble": caps.PREAMBLE}
    return defn


def apply_guardians(defn: dict[str, Any], f: Mapping[str, str]) -> dict[str, Any]:
    extra = [g for g in _split(f.get("extra", "")) if g not in caps.MANDATORY_GUARDIANS]
    defn["guardians"] = [*caps.MANDATORY_GUARDIANS, *dict.fromkeys(extra)]
    return defn


def apply_step(row: Mapping[str, Any], step: str, form: Mapping[str, str]) -> dict[str, Any]:
    """The definition of ``row`` with the posted step applied (a private copy)."""
    defn = copy.deepcopy(row["definition"])
    if step == "template":
        return apply_template(defn, form)
    if step == "policy":
        return apply_policy(defn, form)
    if step == "checklist":
        return apply_checklist(defn, form)
    if step == "tools":
        return apply_tools(defn, form, list(tool_registry().visible_to(row["owner_group"])))
    if step == "instructions":
        return apply_instructions(defn, form)
    if step == "harness":
        return apply_harness(defn, form)
    if step == "guardians":
        return apply_guardians(defn, form)
    raise FactoryError("bad_step", f"step {step} has nothing to save")
