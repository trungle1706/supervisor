"""The nine-step register workflow (WP-C3, ``REGISTER_V3``): view models and step saves.

The draft, the submit and the old services stay in ``register_v2``; this module adds what the
nine steps need on top: the key of the source, the facts prefill with its "from facts" markers,
the AI type flags, the system record made at step 3, the duties prefill, the stage approval request.
Every write goes through an existing service. Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from supervisor.core.errors import SupervisorError
from supervisor.governance import model as gm
from supervisor.governance.register_v2 import duties as dut
from supervisor.governance.register_v2 import model as rm
from supervisor.governance.register_v2 import suggest
from supervisor.governance.register_v3 import flags as fl
from supervisor.governance.register_v3 import strip

log = logging.getLogger("supervisor.governance")

MIN_SKIP = 10
FLAGS_NEEDED = ("register_v3", "console_register_v2", "classification_v2", "risk_dimensions")


def enabled(settings: Any) -> bool:
    """The nine-step workflow is part of this instance: the flag and what it needs are on."""
    return all(getattr(settings, f, False) for f in FLAGS_NEEDED) and bool(
        getattr(settings, "governance_enabled", False)
    )


def needs_text(settings: Any) -> str:
    """Empty when fine (flag off, or on with its needs); else the 400 text."""
    if not getattr(settings, "register_v3", False) or enabled(settings):
        return ""
    miss = [
        n.upper()
        for n in (
            "console_register_v2",
            "classification_v2",
            "risk_dimensions",
            "governance_enabled",
        )
        if not getattr(settings, n, False)
    ]
    return "REGISTER_V3 needs " + ", ".join(miss)


def on(ctx: Any) -> bool:
    return enabled(ctx.settings)


def keys() -> tuple[str, ...]:
    return rm.STEP_KEYS_V3


def src_key(draft: Mapping[str, Any]) -> str:
    """The key the intake attempts and the facts card of this draft are stored under: the scanned
    node, the policy agent, or (a blank draft) the draft id."""
    k = str(draft["data"].get("src_key") or "")
    if k:
        return k
    if draft["source_kind"] in ("scan", "policy") and draft.get("source_ref"):
        return str(draft["source_ref"])
    return str(draft["draft_id"])


def sid_of(draft: Mapping[str, Any]) -> str:
    return str(draft["data"].get("sys") or "")


def bump(data: dict[str, Any], key: str) -> None:
    att = dict(data.get("step_attempts") or {})
    att[key] = int(att.get(key, 0)) + 1
    data["step_attempts"] = att


# ------------------------------------------------------------------------------ facts


def facts_card(ctx: Any, draft: Mapping[str, Any]) -> dict[str, Any] | None:
    if not getattr(ctx.settings, "onboard_facts", False):
        return None
    from supervisor.onboard.facts import FactsService

    try:
        return FactsService(ctx.settings, ctx.state, ctx.clock, tables=ctx.tables).card(
            src_key(draft)
        )
    except SupervisorError:
        return None


def facts_export(ctx: Any, draft: Mapping[str, Any]) -> dict[str, Any] | None:
    """The facts v1 export of the draft's source (as GET /v1/facts/{id}/export)."""
    card = facts_card(ctx, draft)
    if not card or card.get("attempt_n") is None:
        return None
    from supervisor.factory.schemas.facts_v1 import export_card

    try:
        return export_card(card)
    except Exception:  # noqa: BLE001 - a card the export cannot hold: no prefill
        return None


def apply_facts_prefill(ctx: Any, draft: Mapping[str, Any], data: dict[str, Any]) -> bool:
    """Fill the fields of step 3 from the facts v1 export. A field the person typed or changed is
    kept. Each filled field is noted in ``ai_from`` (the "from facts" marker). Returns whether a
    facts card was used."""
    export = facts_export(ctx, draft)
    if export is None:
        return False
    rows = export["facts"]
    found: dict[str, Any] = {}
    suggest.apply_facts(found, rows)
    v = dict(data["v"])
    sg = dict(data["sg"])
    mark = dict(data.get("ai_from") or {})
    for f, s in found.items():
        old = sg.get(f)
        untouched = v.get(f) in ("", None) or (
            f in mark and old is not None and old.get("value") == v.get(f)
        )
        sg[f] = s
        if untouched:
            v[f] = s["value"]
            mark[f] = str(s.get("fact") or "facts")
    flags = fl.derive(v, rows)
    typ = fl.propose_type(flags)
    sg["system_type"] = suggest.sg(typ, "rg3_why_type_flags", "scan")
    if v.get("system_type") in ("", None):
        v["system_type"] = typ
        mark["system_type"] = "flags"
    data["v"], data["sg"], data["ai_from"] = v, sg, mark
    data["ai_from_attempt"] = export["attempt_n"]
    return True


def rule_flags(ctx: Any, draft: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, bool]:
    export = facts_export(ctx, draft)
    return fl.derive(values, export["facts"] if export else [])


# ------------------------------------------------------------------------------ step 3


def _accept(data: dict[str, Any], which: str) -> None:
    fields = (*rm.STEP1, *rm.STEP2)
    for f in fields if which == "*" else (which,):
        if f not in fields:
            raise rm.RegisterError("accept", "is not a field of this step")
        s = data["sg"].get(f)
        if s is not None:
            data["v"][f] = s["value"]


def save_identify(
    ctx: Any,
    me: Any,
    draft: dict[str, Any],
    data: dict[str, Any],
    form: Mapping[str, str],
    strict: bool,
) -> None:
    from supervisor.governance.register_v2 import service as rs

    accept = (form.get("accept") or "").strip()
    if accept:
        _accept(data, accept)
    v = dict(data["v"])
    for step in (1, 2):
        v.update(rm.clean_step(step, form, v, strict=strict))
    if rs.scoped(ctx, me):
        v["owner_user"] = str(me.user_id)
    data["v"] = v
    # an ``ai_from`` marker stays only while the field still holds what the facts gave
    mark = dict(data.get("ai_from") or {})
    for f in list(mark):
        s = data["sg"].get(f)
        if s is None or s["value"] != v.get(f):
            mark.pop(f)
    data["ai_from"] = mark
    posted = None
    if "flags_form" in form:
        posted = {f: rm.on(form.get(f"flag_{f}", "")) for f in fl.FLAGS}
    export = facts_export(ctx, draft)
    rule = fl.derive(v, export["facts"] if export else [])
    flags, src = fl.settle(rule, posted)
    data["ai_flags"], data["ai_flag_src"] = flags, src
    if strict and not accept:
        ensure_system(ctx, me, draft, data)


def system_changes(
    ctx: Any, me: Any, draft: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any]:
    from supervisor.governance.register_v2 import service as rs

    like = {**draft, "data": data}
    sysdraft = rs.system_draft(ctx, me, like)
    sysdraft["tags"] = {**sysdraft["tags"], **fl.tags_of(data.get("ai_flags") or {})}
    return sysdraft


def ensure_system(ctx: Any, me: Any, draft: dict[str, Any], data: dict[str, Any]) -> str:
    """Make the AI system record (status ``draft``, stage ``initiation``) the first time step 3 is
    saved, then keep it in step with the page. The record id is kept in ``data['sys']``."""
    from supervisor.governance.register_v2 import service as rs

    actor = str(me.user_id)
    sid = str(data.get("sys") or "")
    try:
        if not sid:
            rs._check_name_and_team(ctx, me, data["v"])  # noqa: SLF001
            sysdraft = system_changes(ctx, me, draft, data)
            rs.fields_of(ctx, me, {**draft, "data": data})  # a bad field is named
            out = ctx.systems.register(sysdraft, actor, for_user=me)
            data["sys"] = str(out["system_id"])
            return str(data["sys"])
        cur = ctx.systems.get(sid)
        if cur["status"] != "draft":
            raise rm.RegisterError(
                "step", f"the system is {cur['status']}; it cannot be changed here"
            )
        want = system_changes(ctx, me, draft, data)
        if want.get("owner_user") == cur["owner_user"]:
            want.pop("owner_user")
        changes = {k: val for k, val in want.items() if k in gm.EDITABLE and cur.get(k) != val}
        if changes:
            ctx.systems.update_fields(sid, changes, actor, for_user=me)
        return sid
    except gm.SystemsError as exc:
        text = str(exc)
        field = text.split(":", 1)[0].strip() if ":" in text else "name"
        raise rm.RegisterError(field if " " not in field else "name", text) from None


# ------------------------------------------------------------------------------ duties prefill


def class_level(ctx: Any, draft: Mapping[str, Any]) -> dict[str, Any]:
    """The level of the newest classification record of the system (approved or waiting)."""
    sid = sid_of(draft)
    if not sid or not getattr(ctx.settings, "classification_v2", False):
        return {"level": "", "outcome": "", "status": "", "record": ""}
    try:
        got = ctx.classification_v2.get(sid)
    except SupervisorError:
        return {"level": "", "outcome": "", "status": "", "record": ""}
    rec = got["current"] or got["pending"]
    if not rec:
        return {"level": "", "outcome": "", "status": "", "record": ""}
    return {
        "level": str(rec["level"] or ""),
        "outcome": rec["outcome"],
        "status": rec["status"],
        "record": rec["classification_id"],
    }


def apply_duty_prefill(ctx: Any, draft: Mapping[str, Any], data: dict[str, Any]) -> None:
    """Answers of the Duties step the AI type flags settle (customer facing, decisions about
    customers). A person's answer is kept. The marker is in ``duty_from``."""
    flags = data.get("ai_flags")
    if not flags:
        return
    answers = dict(data.get("duties_answers") or {})
    frm = dict(data.get("duty_from") or {})
    want = {
        "Q-customer_facing": bool(flags.get("customer_facing")),
        "Q-decisions_affecting_customers": bool(flags.get("decides")),
    }
    for qid, val in want.items():
        if qid in answers and qid not in frm:
            continue  # the person answered it
        answers[qid] = val
        frm[qid] = "ai_type"
    data["duties_answers"] = answers
    data["duty_from"] = frm


def _article_match(covered: str, ref: str) -> bool:
    return covered == ref or covered.startswith(ref + "(") or ref.startswith(covered + "(")


def duty_marks(ctx: Any, draft: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Duty rows the earlier steps settle: by the level of the classification record (the entries of
    the ``duties`` step in the strip file) and by the articles of the assessment prefill file
    (``read_duties_prefill``). Each: ``{obligation_id, instrument, article, applies, coverage,
    from, confirmed, ref}``."""
    if not draft["data"]["v"].get("user_segment"):
        return []
    m = dut.matrix_of(ctx, draft)
    by_id = {r.obligation_id: r for r in m.rows}
    out: dict[str, dict[str, Any]] = {}
    lv = class_level(ctx, draft)
    if lv["level"]:
        for e in strip.load()["duties"]:
            ok = (
                not e.when
                or (e.when == "high" and lv["level"] in strip.HIGHISH)
                or (e.when == "medium_high" and lv["level"] in (*strip.HIGHISH, "medium"))
            )
            r = by_id.get(e.id)
            if ok and r is not None:
                out[e.id] = _mark(r, "classification", False, lv["record"])
    sid = sid_of(draft)
    if sid and getattr(ctx.settings, "onboard_orchestrator", False):
        from supervisor.onboard import orchestrator as orch

        doc = orch.read_duties_prefill(ctx.settings, sid, ctx.state)
        for c in (doc or {}).get("covered", []):
            for r in m.rows:
                if r.instrument_id == "VN-TT53-2026" and any(
                    _article_match(str(a), r.article_ref) for a in c.get("articles", [])
                ):
                    out[r.obligation_id] = _mark(
                        r, "assessment", bool(c.get("confirmed")), str(c.get("report_ref") or "")
                    )
    return sorted(out.values(), key=lambda x: x["obligation_id"])


def _mark(r: Any, source: str, confirmed: bool, ref: str) -> dict[str, Any]:
    return {
        "obligation_id": r.obligation_id,
        "instrument": r.instrument_number or r.instrument_id,
        "article": r.article_ref,
        "applies": r.applies,
        "coverage": dut.coverage_of(r),
        "from": source,
        "confirmed": confirmed,
        "ref": ref,
    }


# ------------------------------------------------------------------------------ save a step


def clean_skip(raw: str) -> str:
    text = (raw or "").strip()
    if len(text) < MIN_SKIP:
        raise rm.RegisterError("skip_reason", f"at least {MIN_SKIP} characters")
    if len(text) > rm.MAX_ANSWER_WHY or any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise rm.RegisterError(
            "skip_reason", f"at most {rm.MAX_ANSWER_WHY} characters, no control characters"
        )
    return text


def save_step(
    ctx: Any, me: Any, draft: dict[str, Any], step: int, form: Mapping[str, str], *, stay: bool
) -> dict[str, Any]:
    """Validate and store one of the nine steps; the same rules as ``register_v2``: ``stay`` keeps
    required fields open, a bad value is a RegisterError that names the field."""
    from supervisor.governance.register_v2 import service as rs

    n = len(rm.STEP_KEYS_V3)
    if not 1 <= step <= n:
        raise rm.RegisterError("step", f"must be 1 to {n}")
    key = rm.STEP_KEYS_V3[step - 1]
    data = {k: (dict(v) if isinstance(v, dict) else v) for k, v in draft["data"].items()}
    strict = not stay and not (form.get("accept") or "").strip()
    store = rs.store_of(ctx)
    if key == "source":
        if form.get("skip") or (form.get("skip_reason") and not _has_attempt(ctx, draft)):
            data["skip_source"] = clean_skip(str(form.get("skip_reason") or ""))
        elif _has_attempt(ctx, draft):
            data.pop("skip_source", None)
        elif (
            strict
            and getattr(ctx.settings, "onboard_intake", False)
            and not data.get("skip_source")
        ):
            raise rm.RegisterError(
                "source", "upload a source or give a reason to go on without one"
            )
    elif key == "facts":
        apply_facts_prefill(ctx, draft, data)
    elif key == "identify":
        save_identify(ctx, me, draft, data, form, strict)
    elif key == "assess":
        apply_duty_prefill(ctx, draft, data)
    elif key == "duties":
        if form.get("prefill"):
            apply_duty_prefill(ctx, draft, data)
        answers = dut.answers_from(form, data.get("duties_answers") or {})
        frm = dict(data.get("duty_from") or {})
        old = data.get("duties_answers") or {}
        for qid in list(frm):  # a changed answer is the person's now
            if answers.get(qid) != old.get(qid) or qid not in answers:
                frm.pop(qid)
        if answers:
            data["duties_answers"] = answers
        else:
            data.pop("duties_answers", None)
        data["duty_from"] = frm
    elif key == "guardians":
        data["off"] = rs._off_from(ctx, me, draft, form)  # noqa: SLF001
        data["off_why"] = rs._why_from(ctx, me, draft, form)  # noqa: SLF001
    bump(data, key)
    return store.save(draft, data=data, step=step if stay else min(step + 1, n))


def _has_attempt(ctx: Any, draft: Mapping[str, Any]) -> bool:
    if not getattr(ctx.settings, "onboard_intake", False):
        return False
    from supervisor.onboard.intake import IntakeService

    got = IntakeService(ctx.settings, ctx.state, ctx.clock, ctx.tables).attempts(src_key(draft))
    return any(a.get("status") != "failed" for a in got)


# ------------------------------------------------------------------------------ submit


def stage_target(ctx: Any, system: Mapping[str, Any]) -> str:
    """The next stage after the current one whose move needs an approval; empty when none."""
    cur = str(system["lifecycle_stage"])
    stages = gm.LIFECYCLE_STAGES
    for s in stages[stages.index(cur) + 1 :]:
        if ctx.lifecycle.needs_approval(s):
            return s
    return ""


def request_stage(ctx: Any, sid: str, actor: str) -> dict[str, Any]:
    """The stage approval request that is the submit action of step 8 (the same service call as the
    button of WP-P1). Returns ``{status ok|skipped|failed, detail}``."""
    system = ctx.systems.get(sid)
    to = stage_target(ctx, system)
    if not to:
        return {"status": "skipped", "detail": ""}
    try:
        row = ctx.lifecycle.request(sid, to, actor, "register workflow: submitted for approval")
    except SupervisorError as exc:
        return {"status": "failed", "detail": str(exc)[:200]}
    return {"status": "ok", "detail": f"{row['approval_id']} -> {to}"}


def on_abandon(ctx: Any, me: Any, draft: Mapping[str, Any]) -> None:
    """An abandoned draft that made a system record archives it (nothing else is deleted)."""
    sid = sid_of(draft)
    if not sid:
        return
    try:
        if ctx.systems.get(sid)["status"] == "draft":
            ctx.systems.archive(sid, str(me.user_id))
    except SupervisorError:
        log.exception("register_v3: could not archive the system of an abandoned draft")


# ------------------------------------------------------------------------------ view models


def strip_of(ctx: Any, draft: dict[str, Any], key: str) -> dict[str, Any]:
    try:
        return strip.evaluate(ctx, draft, key)
    except SupervisorError as exc:
        log.warning("register_v3: strip: %s", exc)
        return {"step": key, "attempt": 0, "rows": [], "counts": {}}


def step_view(
    ctx: Any,
    me: Any,
    draft: dict[str, Any],
    key: str,
    query: Mapping[str, str],
    posted: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Template variables of one of the nine steps (on top of the old ones)."""
    from supervisor.governance.register_v2 import service as rs

    s = ctx.settings
    out: dict[str, Any] = {
        "v3": True,
        "ai_from": dict(draft["data"].get("ai_from") or {}),
        "live": {
            "source": bool(s.onboard_intake),
            "facts": bool(s.onboard_facts),
            "assess": bool(s.onboard_orchestrator),
            "guardians": bool(s.onboard_predeploy),
        },
        "sid": sid_of(draft),
        "src_key": src_key(draft),
    }
    sid = out["sid"]
    if key == "source":
        from supervisor.console import intake_routes

        out["ik"] = intake_routes.panel_data(ctx, me, out["src_key"])["ik"]
        out["skip"] = str(draft["data"].get("skip_source") or "")
    elif key == "facts":
        from supervisor.console import facts_routes

        out["fk"] = facts_routes.panel_data(ctx, me, out["src_key"])["fk"]
    elif key == "identify":
        out["kinds"] = rm.KINDS
        out["choices"] = rm.CHOICES
        v = rs.values_of(draft)
        export = facts_export(ctx, draft)
        rule = fl.derive(v, export["facts"] if export else [])
        out["flags"] = dict(draft["data"].get("ai_flags") or rule)
        out["flag_src"] = dict(draft["data"].get("ai_flag_src") or dict.fromkeys(fl.FLAGS, "rule"))
        out["flag_rule"] = rule
        out["flag_names"] = fl.FLAGS
        out["proposed_type"] = fl.propose_type(out["flags"])
        out["facts_attempt"] = export["attempt_n"] if export else None
    elif key == "classify":
        out["cv"] = None
        if sid:
            from supervisor.console import classify_routes

            out["cv"] = classify_routes.panel_data(ctx, me, sid)["cv"]
    elif key == "assess":
        out["system"] = None
        if sid:
            from supervisor.console import systems_riskdim

            system = ctx.systems.get(sid)
            out["system"] = system
            out.update(systems_riskdim.tab_data(ctx, me, system))
            out["s"] = system
    elif key == "duties":
        out["duty"] = rs.duties_view(ctx, draft, query, posted)
        out["marks_duty"] = duty_marks(ctx, draft) if out["duty"]["ready"] else []
        out["duty_from"] = dict(draft["data"].get("duty_from") or {})
        out["level"] = class_level(ctx, draft)
    elif key == "guardians":
        out["g"] = rs.guardian_view(ctx, me, draft)
        out["sg_on"] = False
        if sid:  # WP-G4: the smart guardian proposal (SMART_GUARDIAN)
            from supervisor.console import smart_guardian_view

            sys_row = ctx.systems.get(sid)
            out.update(smart_guardian_view.panel_data(ctx, me, sys_row))
        out["pd"] = None
        if s.onboard_predeploy:
            from supervisor.console import predeploy_routes

            out["pd"] = predeploy_routes.panel_data(ctx, me, out["src_key"])["pd"]
    elif key == "review":
        out["r"] = rs.review_view(ctx, me, draft)
        system = ctx.systems.get(sid) if sid else None
        out["stage_to"] = stage_target(ctx, system) if system else ""
        out["level"] = class_level(ctx, draft)
        out["flags"] = dict(draft["data"].get("ai_flags") or {})
    out["strip"] = strip_of(ctx, draft, key)
    return out
