"""The register workflow v2 (WP-N3): start, step views, save a step, submit.

Every write goes through an existing service: ``SystemService`` (system, team, link),
``AgentRegistry`` (agent row), ``ClassificationService`` (Decision 33 draft and the answers),
``GuardianService`` (a binding row only for a feature set off), the task service (intake tasks).
This module adds no table write of its own but the ``registration_draft`` row.

Nothing is applied: the classification stays a draft, the system stays ``draft`` in stage
``initiation``, the agent starts in SHADOW (or the state its policy manifest gives)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from supervisor.console import systems_wizard as wiz
from supervisor.core.errors import SupervisorError
from supervisor.governance import decision33 as d33
from supervisor.governance import duties_gap as dg
from supervisor.governance import guardians as gd
from supervisor.governance import model as gm
from supervisor.governance.register_v2 import duties as dut
from supervisor.governance.register_v2 import model as rm
from supervisor.governance.register_v2 import suggest
from supervisor.governance.register_v2.draft import DraftStore
from supervisor.governance.systems import ALL
from supervisor.inventory.autoregister import GovernanceConfig
from supervisor.inventory.store import InventoryStore

log = logging.getLogger("supervisor.governance")

TASK_POLICY = ("SYS-REG-POLICY", "Add the agent to the policy")
TASK_SPID = ("SYS-REG-SPID", "Map the service principal identity")
SOURCE_TAG = "register_v2"
# the instance flag a feature needs (docs/guardian-bindings.md); detectors share one flag
FLAG_OF: dict[str, str] = {
    gd.SESSION: "SESSION_MONITOR_ENABLED",
    "judge_t2_sample": "JUDGE_ENABLED + JUDGE_T2_SAMPLE_BP",
    "judge_challenger": "JUDGE_ENABLED + JUDGE_CHALLENGER_MODEL",
    "monitor_quality": "QUALITY_ENABLED",
    "monitor_fairness": "FAIRNESS_ENABLED",
    "monitor_split_payment": "MULTIAGENT_ENABLED",
    "monitor_drift": "DRIFT_ENABLED",
    "document_intake": "DETECTORS_ENABLED + DOCUMENT_INTAKE_ENABLED",
}
DETECTOR_FLAG = "DETECTORS_ENABLED"


# ------------------------------------------------------------------------------ helpers


def store_of(ctx: Any) -> DraftStore:
    return DraftStore(ctx.state, ctx.clock)


def duties_on(ctx: Any) -> bool:
    """The Duties step is part of this instance's workflow (CONSOLE_REGISTER_DUTIES)."""
    return dut.enabled(ctx.settings)


def duties_view(
    ctx: Any, draft: Mapping[str, Any], query: Mapping[str, str], posted: Mapping[str, str] | None
) -> dict[str, Any]:
    """Step "Duties": the matrix rows, filtered and paged by the query (``f``, ``p``)."""
    raw_page = str(query.get("p") or "1")
    if not (raw_page.isascii() and raw_page.isdigit()) or int(raw_page) < 1 or len(raw_page) > 6:
        raise rm.RegisterError("p", "must be a page number")
    return dut.view(
        ctx, draft, flt=str(query.get("f") or "gaps"), page=int(raw_page), posted=posted
    )


def total_steps(ctx: Any) -> int:
    return rm.n_steps(duties_on(ctx))


def scoped(ctx: Any, me: Any) -> bool:
    return bool(ctx.systems.scope_for(me) is not ALL)


def policy_agents(ctx: Any) -> dict[str, Any]:
    try:
        return dict(ctx.runtime.gateway.states.policy.current().doc.agents)
    except Exception:  # noqa: BLE001 - no policy known: no agent is known
        return {}


def policy_doc(ctx: Any) -> Any:
    try:
        return ctx.runtime.gateway.states.policy.current().doc
    except Exception:  # noqa: BLE001
        return None


def sp_mapped(ctx: Any, agent_id: str) -> bool | None:
    """Whether a service principal is mapped to the agent in ``config/agent_identities.yaml``;
    None when the file cannot be read."""
    from supervisor.adapters.auth.agent_creds_identity import AgentIdentityMap

    try:
        path = ctx.settings.ingress_identities_file
        return agent_id in AgentIdentityMap.from_file(path).all_agents()
    except Exception:  # noqa: BLE001 - a reason on the page, not a failure
        return None


def values_of(draft: Mapping[str, Any]) -> dict[str, Any]:
    return dict(draft["data"]["v"])


def mark(draft: Mapping[str, Any], field: str) -> str:
    """Where the shown value of a field comes from: ``scan|policy`` (equals the suggestion),
    ``person`` (differs from the suggestion or has none), or ``''`` (not set)."""
    v = draft["data"]["v"].get(field)
    s = draft["data"]["sg"].get(field)
    if v in ("", None) and field not in rm.BOOLS:
        return ""
    if s is not None and s["value"] == v:
        return str(s["source"])
    return "person"


def system_draft(ctx: Any, me: Any, draft: Mapping[str, Any]) -> dict[str, Any]:
    """The ``SystemService.register`` draft from the saved values. Raises RegisterError for a
    required field that is still empty (named by field)."""
    v = values_of(draft)
    out: dict[str, Any] = {}
    for f in ("name", "owner_user", "owner_team", "purpose"):
        out[f] = v.get(f) or ""
    for f in ("system_type", "org_role", "user_segment", "personal_data", "human_control"):
        out[f] = v.get(f) or ""
    if v.get("autonomy_level"):
        out["autonomy_level"] = v["autonomy_level"]
    out["money_movement"] = bool(v.get("money_movement"))
    out["credit_decision"] = bool(v.get("credit_decision"))
    if scoped(ctx, me):
        out["owner_user"] = str(me.user_id)
    tags = {"source": SOURCE_TAG, "kind": v.get("kind") or "other"}
    if draft["source_kind"] == "scan" and draft.get("source_ref"):
        tags["node_id"] = str(draft["source_ref"])
    for k in ("agent_id", "model_family", "data_sources"):
        if v.get(k):
            tags[k] = str(v[k])[:120]
    out["tags"] = tags
    missing = [
        f
        for f in ("name", "owner_user", "owner_team", "purpose", "system_type", "org_role")
        if out.get(f) in ("", None)
    ]
    missing += [
        f for f in ("user_segment", "personal_data", "human_control") if out.get(f) in ("", None)
    ]
    if missing:
        raise rm.RegisterError(missing[0], "is required")
    return out


def fields_of(ctx: Any, me: Any, draft: Mapping[str, Any]) -> dict[str, Any]:
    """Normalised row fields of the draft (service validation; writes nothing)."""
    try:
        return gm.normalise_draft(system_draft(ctx, me, draft))
    except gm.SystemsError as exc:
        text = str(exc)
        field = text.split(":", 1)[0].strip() if ":" in text else "draft"
        raise rm.RegisterError(field if " " not in field else "draft", text) from None


# ------------------------------------------------------------------------------ start


def fact_rows(ctx: Any, node_id: str) -> list[dict[str, Any]]:
    """The rule and model facts of the newest built card of the node (WP-O2); empty with
    ONBOARD_FACTS off or when no card was built, so the prefill is as before."""
    if not getattr(ctx.settings, "onboard_facts", False):
        return []
    from supervisor.onboard.facts import FactsService

    try:
        card = FactsService(ctx.settings, ctx.state, ctx.clock).card(node_id)
    except SupervisorError:
        return []
    return [r for r in card["rows"] if r["kind"] != "summary"]


def start(ctx: Any, me: Any, node_id: str = "", agent_id: str = "") -> dict[str, Any]:
    """Make a draft with the prefill of a scanned node, of a policy-only agent, or blank."""
    if me.kind != "user":
        raise rm.RegisterError("user", "registering needs a signed-in person")
    uid = str(me.user_id)
    node_id, agent_id = (node_id or "").strip(), (agent_id or "").strip()
    if node_id and agent_id:
        raise rm.RegisterError("from", "give a scanned object or an agent, not both")
    sg: dict[str, Any] = {}
    kind, ref = "blank", None
    if node_id:
        if not rm.ID_RE.match(node_id):
            raise rm.RegisterError("from", "is not a node id")
        graph = InventoryStore(ctx.state, ctx.clock).load_graph()
        node = graph.nodes.get(node_id)
        if node is None or node.status == "gone":
            raise rm.RegisterError("from", "this scanned object does not exist")
        if ctx.state.query("system_component", {"ref_id": node_id}):
            raise rm.RegisterError("from", "this object is already linked to an AI system")
        if scoped(ctx, me) and node.status != "unmanaged":
            raise rm.RegisterError("from", "this object is not a candidate for registration")
        sg = suggest.from_node(graph, node, GovernanceConfig.load(), fact_rows(ctx, node_id))
        kind, ref = "scan", node_id
    elif agent_id:
        if not rm.ID_RE.match(agent_id):
            raise rm.RegisterError("agent", "must match ^[A-Za-z0-9_.:@-]{1,128}$")
        manifest = policy_agents(ctx).get(agent_id)
        if manifest is None:
            raise rm.RegisterError("agent", "this agent is not in the deployed policy")
        if ctx.state.get("agent", {"agent_id": agent_id}) is not None:
            raise rm.RegisterError("agent", "this agent already has a registry row")
        sg = suggest.from_agent(agent_id, manifest, fact_rows(ctx, agent_id))
        kind, ref = "policy", agent_id
    values = {
        f: sg[f]["value"]
        for f in rm.STEP1
        if f in sg and sg[f]["value"] not in ("", None)  # step 2 waits for a click
    }
    if scoped(ctx, me) or "owner_user" not in values:
        values["owner_user"] = uid
    return store_of(ctx).create(uid, kind, ref, values, sg)


# ------------------------------------------------------------------------------ steps 3-5


def _full_or_none(ctx: Any, me: Any, draft: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        return fields_of(ctx, me, draft)
    except SupervisorError:
        return None


def gaps(ctx: Any, me: Any, draft: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The pre-deployment checks as rows ``{key, status ok|gap|info, fix_key, detail}``."""
    v = values_of(draft)
    agent_id = str(v.get("agent_id") or "")
    rows: list[dict[str, Any]] = []
    ready = draft["data"].get("check") or {}
    if ready.get("total") is not None:
        ok = int(ready["total"]) >= 80
        rows.append(
            {
                "key": "rg2_chk_readiness",
                "status": "ok" if ok else "gap",
                "fix_key": "" if ok else "rg2_fix_readiness",
                "detail": str(ready["total"]),
            }
        )
    else:
        rows.append(
            {
                "key": "rg2_chk_readiness",
                "status": "info",
                "fix_key": "rg2_fix_readiness_run",
                "detail": "",
            }
        )
    if not agent_id:
        rows.append(
            {"key": "rg2_chk_policy", "status": "info", "fix_key": "rg2_fix_no_agent", "detail": ""}
        )
        return rows
    doc = policy_doc(ctx)
    manifest = policy_agents(ctx).get(agent_id)
    if manifest is None:
        rows.append(
            {
                "key": "rg2_chk_policy",
                "status": "gap",
                "fix_key": "rg2_fix_policy_missing",
                "detail": agent_id,
            }
        )
    else:
        n_rules = sum(1 for r in (doc.rules if doc else []) if r.in_scope(agent_id))
        rows.append(
            {
                "key": "rg2_chk_policy",
                "status": "ok",
                "fix_key": "",
                "detail": agent_id,
            }
        )
        rows.append(
            {
                "key": "rg2_chk_rules",
                "status": "ok" if n_rules else "gap",
                "fix_key": "" if n_rules else "rg2_fix_rules",
                "detail": str(n_rules),
            }
        )
    n_tools = len(doc.tools) if doc else 0
    rows.append(
        {
            "key": "rg2_chk_tools",
            "status": "ok" if n_tools else "gap",
            "fix_key": "" if n_tools else "rg2_fix_tools",
            "detail": str(n_tools),
        }
    )
    mapped = sp_mapped(ctx, agent_id)
    rows.append(
        {
            "key": "rg2_chk_sp",
            "status": "info" if mapped is None else ("ok" if mapped else "gap"),
            "fix_key": "" if mapped else "rg2_fix_sp",
            "detail": "",
        }
    )
    return rows


def run_readiness(ctx: Any, me: Any, draft: dict[str, Any], repo_path: str) -> dict[str, Any]:
    """Run the readiness advisor on the folder (optional) and keep the result in the draft."""
    from supervisor.console.listing import ListingError

    repo_path = (repo_path or "").strip()
    if len(repo_path) > rm.MAX_REPO:
        raise rm.RegisterError("repo_path", "is too long")
    data = dict(draft["data"])
    data["repo_path"] = repo_path
    try:
        result = wiz.readiness(me, repo_path, ctx.settings)
    except ListingError as exc:
        raise rm.RegisterError("repo_path", str(exc)) from None
    if result.get("total") is not None:
        result["band"] = result.get("band") or wiz.band_of(int(result["total"]))
    data["check"] = result
    return store_of(ctx).save(draft, data=data, step=3)


def class_view(ctx: Any, me: Any, draft: Mapping[str, Any]) -> dict[str, Any]:
    """Step 4: the Decision 33 questions with the answers the rules derive now, merged with
    the answers the person gave, the proposed outcome and the rule that fired."""
    full = _full_or_none(ctx, me, draft)
    if full is None:
        return {"ready": False, "questions": [], "outcome": None}
    flow = ctx.classification.flow()
    answers = d33.derive(flow, wiz._facts_of({**full, "owner_user": full["owner_user"]}))  # noqa: SLF001
    for qid, a in (draft["data"].get("q") or {}).items():
        if qid in answers and a.get("answer") in d33.ANSWERS:
            answers[qid] = d33.entry(a["answer"], "person", str(a.get("justification") or ""))
    dec = d33.decide(flow, answers)
    qs = [
        {
            "id": q.id,
            "text_en": q.text_en,
            "text_vi": q.text_vi,
            "source": answers[q.id]["source"],
            "answer": answers[q.id]["answer"] or "",
            "why": answers[q.id].get("justification") or "",
        }
        for q in flow.questions
    ]
    level = "high" if dec.outcome == "high_risk" else None
    inherited = None
    if draft["source_kind"] == "scan" and draft.get("source_ref"):
        graph = InventoryStore(ctx.state, ctx.clock).load_graph()
        inherited = suggest.inherited_level(graph, str(draft["source_ref"]))
    return {
        "ready": True,
        "questions": qs,
        "outcome": dec.outcome,
        "rule_id": dec.rule_id or "",
        "reason": dec.reason,
        "complete": bool(dec.complete),
        "level": level,
        "inherited": inherited,
    }


def guardian_view(ctx: Any, me: Any, draft: Mapping[str, Any]) -> dict[str, Any]:
    """Step 5: the floor (locked on), the bindable features with the proposed state, and for a
    feature the instance has off the flag it needs."""
    full = _full_or_none(ctx, me, draft)
    floor_rows = wiz._floor_preview(ctx, full) if full is not None else None  # noqa: SLF001
    floor = {f["slug"]: f["rules"] for f in floor_rows or []}
    bindings = gd.guardian_bindings_on(ctx.settings)
    det = gd.detector_entries(ctx.settings)
    off = set(draft["data"].get("off") or [])
    rows = []
    for slug in gd.bindable_slugs(ctx.settings):
        if slug in gd.NEVER_BINDABLE:
            continue
        has = gd.instance_on(ctx.settings, slug, det)
        locked = slug in floor
        rows.append(
            {
                "slug": slug,
                "group": gd.group_of(slug),
                "locked": locked,
                "floor_rules": floor.get(slug, []),
                "instance_on": has,
                "needs": "" if has else FLAG_OF.get(slug, DETECTOR_FLAG),
                "off": slug in off and not locked and has,
                "why": (draft["data"].get("off_why") or {}).get(slug, ""),
                "bindable": bindings and has and not locked,
            }
        )
    doc = policy_doc(ctx)
    agent_id = str(values_of(draft).get("agent_id") or "")
    rules = (
        [r.id for r in doc.rules if r.in_scope(agent_id)] if doc is not None and agent_id else []
    )
    return {
        "rows": rows,
        "floor_known": floor_rows is not None,
        "bindings_on": bindings,
        "policy_rules": sorted(set(rules)),
        "agent_in_policy": agent_id in policy_agents(ctx) if agent_id else False,
    }


def review_view(ctx: Any, me: Any, draft: Mapping[str, Any]) -> dict[str, Any]:
    v = values_of(draft)
    agent_id = str(v.get("agent_id") or "")
    plan = agent_plan(ctx, agent_id, draft)
    tasks = [t for t, _ in wiz.TASKS]
    if plan["task_policy"]:
        tasks.append(TASK_POLICY[0])
    if plan["task_spid"]:
        tasks.append(TASK_SPID[0])
    problems = []
    try:
        fields_of(ctx, me, draft)
    except SupervisorError as exc:
        problems.append(str(exc))
    cls = class_view(ctx, me, draft)
    return {
        "values": v,
        "marks": {f: mark(draft, f) for f in (*rm.STEP1, *rm.STEP2)},
        "plan": plan,
        "tasks": tasks,
        "off": [s for s in draft["data"].get("off") or []],
        "q_n": len(draft["data"].get("q") or {}),
        "problems": problems,
        "outcome": cls["outcome"] if cls["ready"] else None,
        "rule_id": cls.get("rule_id", ""),
        "readiness": (draft["data"].get("check") or {}).get("total"),
        "duties": dut.review(ctx, draft) if duties_on(ctx) else None,
        "source_kind": draft["source_kind"],
        "node": draft.get("source_ref") if draft["source_kind"] == "scan" else None,
    }


def agent_plan(ctx: Any, agent_id: str, draft: Mapping[str, Any]) -> dict[str, Any]:
    """What the submit will do about the agent: create the row, link an existing row, or open
    the task "Add the agent to the policy"."""
    plan = {
        "agent_id": agent_id,
        "create_row": False,
        "link_row": False,
        "task_policy": False,
        "task_spid": False,
        "needs_flag": "",
    }
    if not agent_id:
        return plan
    exists = ctx.state.get("agent", {"agent_id": agent_id}) is not None
    known = agent_id in policy_agents(ctx)
    if exists:
        plan["link_row"] = True
    elif known and ctx.settings.agents_api_enabled:
        plan["create_row"] = True
        plan["link_row"] = True
    else:
        plan["task_policy"] = True
        if known and not ctx.settings.agents_api_enabled:
            plan["needs_flag"] = "AGENTS_API_ENABLED"
    plan["task_spid"] = sp_mapped(ctx, agent_id) is False
    return plan


# ------------------------------------------------------------------------------ save a step


def save_step(
    ctx: Any, me: Any, draft: dict[str, Any], step: int, form: Mapping[str, str], *, stay: bool
) -> dict[str, Any]:
    """Validate and store one step. ``stay`` (save for later): required fields may stay empty.
    Returns the changed draft. A bad value is a RegisterError that names the field."""
    duties = duties_on(ctx)
    n = rm.n_steps(duties)
    if not 1 <= step <= n:
        raise rm.RegisterError("step", f"must be 1 to {n}")
    key = rm.key_of(step, duties)
    data = {k: (dict(v) if isinstance(v, dict) else v) for k, v in draft["data"].items()}
    accept = (form.get("accept") or "").strip()
    strict = not stay and not accept
    if key in rm.FIELDS_OF_KEY:
        vals = rm.clean_step(step, form, data["v"], strict=strict)
        data["v"] = {**data["v"], **vals}
        if key == "identify" and scoped(ctx, me):
            data["v"]["owner_user"] = str(me.user_id)
        if accept:
            _accept(data, step, accept)
        if key == "identify" and strict:
            _check_name_and_team(ctx, me, data["v"])
    elif key == "check":
        repo = (form.get("repo_path") or "").strip()
        if len(repo) > rm.MAX_REPO:
            raise rm.RegisterError("repo_path", "is too long")
        data["repo_path"] = repo
        if repo and form.get("run"):
            draft = store_of(ctx).save(draft, data=data)
            return run_readiness(ctx, me, draft, repo)
    elif key == "duties":
        answers = dut.answers_from(form, data.get("duties_answers") or {})
        if answers:
            data["duties_answers"] = answers
        else:
            data.pop("duties_answers", None)
    elif key == "class":
        data["q"] = _answers_from(ctx, form, data["q"])
    elif key == "guardians":
        data["off"] = _off_from(ctx, me, draft, form)
        data["off_why"] = _why_from(ctx, me, draft, form)
    return store_of(ctx).save(draft, data=data, step=step if stay else min(step + 1, n))


def _accept(data: dict[str, Any], step: int, which: str) -> None:
    """One click: the suggested value of one field (or of every field of the step)."""
    fields = rm.FIELDS_OF_STEP[step]
    for f in fields if which == "*" else (which,):
        if f not in fields:
            raise rm.RegisterError("accept", "is not a field of this step")
        s = data["sg"].get(f)
        if s is not None:
            data["v"][f] = s["value"]


def _check_name_and_team(ctx: Any, me: Any, v: Mapping[str, Any]) -> None:
    svc = ctx.systems
    try:
        svc._check_team_in_scope(me, v["owner_team"])  # noqa: SLF001 - the one scope rule
        svc._unique_name(v["name"])  # noqa: SLF001
    except gm.SystemsError as exc:
        field = "name" if "name" in str(exc) else "owner_team"
        raise rm.RegisterError(field, str(exc)) from None


def _answers_from(ctx: Any, form: Mapping[str, str], current: Mapping[str, Any]) -> dict[str, Any]:
    flow = ctx.classification.flow()
    out = dict(current)
    for qid in flow.ids:
        if f"a_{qid}" not in form:
            continue
        raw = form.get(f"a_{qid}", "")
        why = (form.get(f"j_{qid}") or "").strip()
        if raw not in ("", "yes", "no"):
            raise rm.RegisterError(f"a_{qid}", "must be yes, no or empty")
        if len(why) > rm.MAX_ANSWER_WHY:
            raise rm.RegisterError(f"j_{qid}", f"at most {rm.MAX_ANSWER_WHY} characters")
        if raw:
            out[qid] = {"answer": raw, "justification": why}
        else:
            out.pop(qid, None)
    return out


def _off_from(ctx: Any, me: Any, draft: Mapping[str, Any], form: Mapping[str, str]) -> list[str]:
    """The features the person sets off: the slugs in the form field ``off`` (one per box)."""
    if "bind_form" not in form:
        return list(draft["data"].get("off") or [])
    view = guardian_view(ctx, me, draft)
    if not view["bindings_on"]:
        return []
    # a box ``on_<slug>`` that is missing means the person set the feature off
    return sorted(
        r["slug"] for r in view["rows"] if r["bindable"] and f"on_{r['slug']}" not in form
    )


def _why_from(
    ctx: Any, me: Any, draft: Mapping[str, Any], form: Mapping[str, str]
) -> dict[str, str]:
    """The optional reason per feature (form field ``why_<slug>``); kept as typed."""
    current = dict(draft["data"].get("off_why") or {})
    if "bind_form" not in form:
        return current
    out: dict[str, str] = {}
    for r in guardian_view(ctx, me, draft)["rows"]:
        if not r["bindable"]:
            continue
        why = (form.get(f"why_{r['slug']}") or "").strip()
        if len(why) > rm.MAX_ANSWER_WHY:
            raise rm.RegisterError(f"why_{r['slug']}", f"at most {rm.MAX_ANSWER_WHY} characters")
        if any(ord(c) < 32 and c not in "\n\t" for c in why):
            raise rm.RegisterError(f"why_{r['slug']}", "has control characters")
        if why:
            out[r["slug"]] = why
    return out


# ------------------------------------------------------------------------------ submit


def _task(ctx: Any, system_id: str, spec: tuple[str, str], actor: str) -> bool:
    """One intake task on the system (same way as the wizard's tasks). A repeat is a no-op."""
    template_id, title = spec
    tasks = ctx.tasks
    try:
        row = tasks._row_for(  # noqa: SLF001 - the one place that writes a task for a system
            system_id,
            "initiation",
            template_id=template_id,
            kind="custom",
            title=title,
            owner_role="owner",
            required=True,
            due_days=wiz.TASK_DUE_DAYS,
            evidence_kind="none",
            evidence_ref=None,
            level="low",
            d33_class="unclassified",
            actor=actor,
        )
        return bool(tasks._insert(row, actor))  # noqa: SLF001
    except Exception:  # noqa: BLE001 - a system without its task is still a system
        log.exception("register_v2: could not open task %s", template_id)
        return False


def _step(out: list[dict[str, str]], key: str, status: str, detail: str = "") -> None:
    out.append({"key": key, "status": status, "detail": detail})


def submit(ctx: Any, me: Any, draft: dict[str, Any]) -> dict[str, Any]:
    """The writes of the draft, in one call. Nothing is written when a field is bad (the first
    check is the same validation the service does). After the system exists, a later step that
    fails is reported on the result page (``steps``) and never undoes the system."""
    if draft["status"] != "draft":
        raise rm.RegisterError("draft_id", f"this draft is {draft['status']}")
    actor = str(me.user_id)
    fields_of(ctx, me, draft)  # raises on a bad or empty field before anything is written
    v = values_of(draft)
    agent_id = str(v.get("agent_id") or "")
    plan = agent_plan(ctx, agent_id, draft)
    sysdraft = system_draft(ctx, me, draft)
    # claim the draft first (optimistic version check): a second submit of the same draft, even a
    # concurrent one, finds it submitted or loses the version race, and writes nothing
    draft = store_of(ctx).save(draft, step=total_steps(ctx), status="submitted")
    try:
        out = ctx.systems.register(sysdraft, actor, for_user=me)
    except BaseException:
        # nothing was written: give the draft back so the person can fix it
        store_of(ctx).release(draft)
        raise
    sid = str(out["system_id"])
    draft = store_of(ctx).keep_system(draft, sid)
    data = draft["data"]
    steps: list[dict[str, str]] = []
    _step(steps, "rg2_w_system", "ok", sid)
    _step(steps, "rg2_w_team", "ok", str(sysdraft["owner_user"]))
    # --- the agent row (only when the policy knows the id and the API is on) ---
    if agent_id and plan["create_row"]:
        try:
            _create_agent(ctx, me, agent_id)
            _step(steps, "rg2_w_agent", "ok", agent_id)
        except Exception as exc:  # noqa: BLE001 - e.g. the policy changed since the plan
            if not isinstance(exc, SupervisorError):
                log.exception("register_v2: agent row failed")
            plan["link_row"] = False
            plan["task_policy"] = True
            _step(
                steps,
                "rg2_w_agent",
                "failed",
                str(exc)[:200] if isinstance(exc, SupervisorError) else "",
            )
    elif agent_id:
        _step(steps, "rg2_w_agent", "skipped", agent_id)
    # --- the links ---
    if agent_id and plan["link_row"]:
        _guard(
            steps,
            "rg2_w_link_agent",
            lambda: ctx.systems.link(sid, "agent", agent_id, actor, for_user=me),
        )
    if draft["source_kind"] == "scan" and draft.get("source_ref"):
        ref = _first_scan_ref(ctx, str(draft["source_ref"]))
        _guard(
            steps,
            "rg2_w_link_node",
            lambda: ctx.systems.link(
                sid,
                "node",
                str(draft["source_ref"]),
                actor,
                source="workspace_scan",
                evidence_ref=ref,
            ),
        )
    # --- the Decision 33 draft (never applied) and the answers the person gave ---
    answers = data.get("q") or {}

    def classify() -> Any:
        ctx.classification.draft(sid, actor)
        if answers:
            ctx.classification.edit(
                sid,
                actor,
                {
                    q: {"answer": a["answer"], "justification": a.get("justification", "")}
                    for q, a in answers.items()
                },
            )

    _guard(steps, "rg2_w_class", classify)
    # --- bindings: a row only for a feature set off ---
    for slug in data.get("off") or []:
        _guard(
            steps,
            "rg2_w_binding",
            lambda s=slug: ctx.guardians.set(
                sid, s, "off", actor, (data.get("off_why") or {}).get(s) or "register workflow"
            ),
            detail=slug,
        )
    # --- duties (WP-L2): obligation_status rows and the gap tasks ---
    if duties_on(ctx):
        counts: dict[str, int] = {}

        def write_duties() -> None:
            counts.update(dut.write(ctx, draft, sid, str(sysdraft["owner_user"]), actor))

        _guard(steps, "rg2_w_duties", write_duties)
        if counts:
            steps[-1]["detail"] = f"{counts['rows']} / {counts['tasks']}"
        if dg.enabled(ctx.settings):  # WP-L3: the risk line of the open duty groups
            dg.sync_risk(ctx, ctx.systems.get(sid), actor)
    # --- tasks ---
    opened = wiz.open_tasks(ctx, sid, actor)
    if plan["task_policy"] and _task(ctx, sid, TASK_POLICY, actor):
        opened.append(TASK_POLICY[0])
    if plan["task_spid"] and _task(ctx, sid, TASK_SPID, actor):
        opened.append(TASK_SPID[0])
    _step(steps, "rg2_w_tasks", "ok", ", ".join(opened))
    result = {
        "system_id": sid,
        "steps": steps,
        "tasks": opened,
        "agent_id": agent_id,
        "plan": plan,
        "draft_id": draft["draft_id"],
    }
    store_of(ctx).record_result(draft, result)
    return result


def result_view(ctx: Any, me: Any, draft: Mapping[str, Any]) -> dict[str, Any]:
    """The result page: what was written and the next actions."""
    res = dict(draft["data"].get("result") or {})
    sid = str(res.get("system_id") or "")
    system = ctx.systems.get(sid)
    res["system"] = system
    res["sp_mapped"] = sp_mapped(ctx, res["agent_id"]) if res.get("agent_id") else None
    return res


def _guard(steps: list[dict[str, str]], key: str, fn: Any, detail: str = "") -> None:
    try:
        fn()
        _step(steps, key, "ok", detail)
    except SupervisorError as exc:
        _step(steps, key, "failed", f"{detail} {exc}".strip()[:200])
    except Exception:  # noqa: BLE001 - reported on the page; the system stays
        log.exception("register_v2: step %s failed", key)
        _step(steps, key, "failed", detail)


def _first_scan_ref(ctx: Any, node_id: str) -> str:
    row = ctx.state.get("inventory_node", {"node_id": node_id})
    if row is None:
        return ""
    for e in rm.json_of(row.get("evidence"), []):
        if isinstance(e, dict) and e.get("source") == "workspace_scan":
            return str(e.get("ref", ""))[:200]
    return ""


def _create_agent(ctx: Any, me: Any, agent_id: str) -> None:
    """The agent row, through the registry, from the policy manifest (the registry refuses a
    value that differs from the policy for an agent the policy defines)."""
    from supervisor.gateway.agents_routes import registry_of

    m = policy_agents(ctx)[agent_id]
    body = {
        "agent_id": agent_id,
        "name": str(m.name),
        "owner_team": str(m.owner_team),
        "owner_user": str(m.owner_user),
        "risk_tier": str(m.risk_tier),
        "host_type": str(m.host_type),
        "plug_point": str(m.plug_point),
        "model_family": str(m.model_family),
    }
    registry_of(ctx).register(body, str(me.user_id), me.roles)
