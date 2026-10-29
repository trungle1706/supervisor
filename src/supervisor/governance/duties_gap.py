"""Duties of an AI system in the risk register and as gap work (WP-L3, flag ``RISK_DUTIES``).

WP-L2 writes one ``obligation_status`` row for each duty that applies to a system (or needs an
answer) and one task for each group "instrument x coverage class". This module works on those
rows. The unit of work is the group (``duties.gap_groups``), not the single duty:

* ``score``       gap closure score: closed / (open + closed) over the applying rows, integer
                  percent, ``None`` when there is no row.
* ``close``       an open row (or all open rows of a group) becomes closed. It needs a closing
                  control (a Supervisor control id from the catalogue, or ``manual:<id>`` of a bank
                  control from ``regulations/internal`` or a bank process of ``controls.yaml``) and
                  an evidence reference.
* ``waive``       an open row becomes waived. Reason of 20 characters or more; the owner of the
                  system cannot waive a duty of the own system.
* ``reevaluate``  run the matrix again on the stored answers (and the facts rows); update
                  ``applies`` and ``coverage`` of the rows; nothing is deleted.
* ``sync_risk``   one risk line of kind ``duties_gap`` per system with open groups, through the
                  risk service. All groups closed: the line is retired.
* ``sweep``       reminder task: one per system per week for open duties due within 30 days.

The thresholds of the risk register stay illustrative. Advisory only. Not legal advice. Bank
counsel must confirm.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any

from supervisor.advisory.compliance import deadlines
from supervisor.core.errors import ConcurrencyError, SupervisorError
from supervisor.governance.register_v2 import duties as dut
from supervisor.governance.register_v2 import model as rm

log = logging.getLogger("supervisor.governance")

BANNER = dut.BANNER
FILTERS: tuple[str, ...] = ("open", "closed", "waived", "needs_answer", "all")
PAGE_SIZE = dut.PAGE_SIZE
MIN_WAIVE = 20
MAX_REASON = 500
MAX_EVIDENCE = 200
RISK_PREFIX = "RSK-DUTY-"
DUE_TEMPLATE = "DUTY-DUE-"
SWEEP_DAYS = 30
DEFAULT_DUE_DAYS = 14
REVIEW_DAYS = 30
MAX_RISK_LINKS = 25
COVERAGE_RANK = {"none": 0, "partial": 1, "unknown": 2, "full": 3}
_CONTROL = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_CTRL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
OPEN_STATE = "open"


class DutyError(SupervisorError):
    """A refusal of a duty action (HTTP 400). The message starts with ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def enabled(settings: Any) -> bool:
    """RISK_DUTIES is on and what it needs is on."""
    return bool(
        getattr(settings, "risk_duties", False)
        and getattr(settings, "governance_enabled", False)
        and getattr(settings, "console_systems_enabled", False)
    )


def ensure_on(ctx: Any) -> None:
    if not enabled(ctx.settings):
        raise DutyError(
            "risk_duties_off",
            "duties in the risk register are off (RISK_DUTIES=1 turns them on; it needs "
            "GOVERNANCE_ENABLED and CONSOLE_SYSTEMS_ENABLED)",
        )


# ------------------------------------------------------------------------------ small helpers


def _on(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true")


def as_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _today(clock: Any) -> dt.date:
    return clock.now().date()


def rows_of(state: Any, system_id: str) -> list[dict[str, Any]]:
    """Every ``obligation_status`` row of the system, in a stable order."""
    rows = [dict(r) for r in state.query("obligation_status", {"system_id": system_id})]
    rows.sort(
        key=lambda r: (
            str(r["instrument_id"]),
            COVERAGE_RANK.get(str(r["coverage"]), 9),
            str(r["obligation_id"]),
        )
    )
    return rows


def score(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Gap closure score over the applying rows: ``pct`` = closed / (open + closed) as an
    integer percent (rounded down); ``None`` when no applying row is open or closed. Waived rows
    are counted apart and stay out of the figure."""
    n = {"open": 0, "closed": 0, "waived": 0}
    for r in rows:
        if r["applies"] == "yes" and r["status"] in n:
            n[str(r["status"])] += 1
    base = n["open"] + n["closed"]
    return {
        "pct": (n["closed"] * 100 // base) if base else None,
        "open": n["open"],
        "closed": n["closed"],
        "waived": n["waived"],
    }


def group_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["instrument_id"]), str(row["coverage"])


def open_groups(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Groups (instrument, coverage partial or none) that still hold an open applying row."""
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        if (
            r["applies"] == "yes"
            and r["status"] == OPEN_STATE
            and r["coverage"] in ("partial", "none")
        ):
            out.setdefault(group_key(r), []).append(dict(r))
    return dict(sorted(out.items()))


def kb_of(ctx_or_settings: Any) -> Any:
    from supervisor.console.compliance_view import kb_for

    settings = getattr(ctx_or_settings, "settings", ctx_or_settings)
    return kb_for(settings)


def _clean(text: Any, limit: int, code: str, what: str, minimum: int = 1) -> str:
    value = text.strip() if isinstance(text, str) else ""
    if len(value) < minimum:
        raise DutyError(code, f"{what} needs at least {minimum} characters")
    if len(value) > limit:
        raise DutyError(code, f"{what} is longer than {limit} characters")
    if _CTRL_CHARS.search(value):
        raise DutyError(code, f"{what} has control characters")
    return value


# ------------------------------------------------------------------------------ the control


def manual_controls(ctx: Any) -> frozenset[str]:
    """Bank controls a duty may be closed with: the obligations of the internal rule files in
    ``REGKB_INTERNAL_DIR`` (``regulations/internal``) and the bank processes of
    ``controls.yaml``."""
    from supervisor.advisory.compliance.facts import _controls_yaml

    kb = kb_of(ctx)
    ids = {o.id for o in kb.obligations.values() if o.instrument_kind == "internal"}
    ids |= set((_controls_yaml().get("process") or {}).keys())
    return frozenset(ids)


def check_control(ctx: Any, value: Any) -> str:
    """The closing control as stored: a catalogue control id, or ``manual:<bank control id>``."""
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise DutyError("control_required", "a closing control is needed to close a duty")
    if text.startswith("manual:"):
        cid = text[len("manual:") :]
        if not _CONTROL.match(cid) or cid not in manual_controls(ctx):
            raise DutyError(
                "bad_control",
                "manual: needs the id of a bank control from regulations/internal "
                "(an internal obligation id or a bank process of controls.yaml)",
            )
        return "manual:" + cid
    if not _CONTROL.match(text):
        raise DutyError("bad_control", "the control id has characters that are not allowed")
    try:
        row = ctx.state.get("control", {"control_id": text})
    except Exception:  # noqa: BLE001 - an old store without the control catalogue
        row = None
    if row is None or str(row["status"]) == "retired":
        raise DutyError(
            "bad_control", f"control {text[:64]} is not in the control catalogue (or is retired)"
        )
    return text


def control_choices(ctx: Any) -> dict[str, list[str]]:
    """The ids a person can type: catalogue controls and manual bank controls (for the form)."""
    try:
        cat = sorted(
            str(r["control_id"]) for r in ctx.state.query("control") if r["status"] != "retired"
        )
    except Exception:  # noqa: BLE001
        cat = []
    return {"catalogue": cat[:200], "manual": sorted(manual_controls(ctx))[:200]}


# ------------------------------------------------------------------------------ pick the rows


def pick(rows: list[dict[str, Any]], form: Mapping[str, str]) -> list[dict[str, Any]]:
    """The rows an action works on: one row (``status_id``) or a group (``group`` =
    ``<instrument id>|<coverage>``). Only open applying rows are picked for a group."""
    chosen = {k[4:] for k, v in form.items() if k.startswith("sel_") and v}  # UX5 bulk bar
    if chosen and not (form.get("status_id") or form.get("group")):
        picked_many = [
            r
            for r in rows
            if r["status_id"] in chosen and r["applies"] == "yes" and r["status"] == OPEN_STATE
        ]
        if not picked_many:
            raise DutyError("nothing_to_do", "none of the selected duties is open")
        return picked_many
    sid = (form.get("status_id") or "").strip()
    group = (form.get("group") or "").strip()
    if bool(sid) == bool(group):
        raise DutyError("target_required", "name one duty (status_id) or one group (group)")
    if sid:
        for r in rows:
            if r["status_id"] == sid:
                return [r]
        raise DutyError("duty_not_found", f"duty row {sid[:40]} is not a row of this system")
    inst, _, cov = group.rpartition("|")
    if not inst or cov not in ("partial", "none"):
        raise DutyError("bad_group", "a group is <instrument id>|partial or <instrument id>|none")
    picked = [
        r
        for r in rows
        if r["instrument_id"] == inst
        and r["coverage"] == cov
        and r["applies"] == "yes"
        and r["status"] == OPEN_STATE
    ]
    if not picked:
        raise DutyError("nothing_to_do", "this group has no open duty")
    return picked


def _need_open(row: Mapping[str, Any]) -> None:
    if row["applies"] != "yes":
        raise DutyError(
            "needs_answer",
            f"duty {row['obligation_id']} is not known to apply yet: answer the open question "
            "and re-evaluate first",
        )
    if row["status"] != OPEN_STATE:
        raise DutyError("not_open", f"duty {row['obligation_id']} is already {row['status']}")


def _store(ctx: Any, row: Mapping[str, Any], changes: Mapping[str, Any]) -> None:
    try:
        ctx.state.update(
            "obligation_status",
            {"status_id": row["status_id"]},
            dict(changes),
            int(row["row_version"]),
        )
    except ConcurrencyError:
        raise DutyError(
            "changed", f"duty {row['obligation_id']} was changed by someone else; reload"
        ) from None


def _note(event: str, old: Any) -> str:
    tail = str(old or "")
    if tail.startswith(BANNER):
        tail = tail[len(BANNER) :].strip()
    text = f"{BANNER} {event}"
    if tail:
        text += f" | before: {tail}"
    return text[:1000]


# ------------------------------------------------------------------------------ close, waive


def close(
    ctx: Any,
    actor: str,
    system: Mapping[str, Any],
    targets: list[dict[str, Any]],
    control: Any,
    evidence_ref: Any,
) -> dict[str, Any]:
    """Close the picked rows with a closing control and an evidence reference. Everything is
    checked before the first write."""
    cid = check_control(ctx, control)
    ref = _clean(evidence_ref, MAX_EVIDENCE, "evidence_required", "the evidence reference")
    for r in targets:
        _need_open(r)
    day = _today(ctx.clock).isoformat()
    for r in targets:
        _store(
            ctx,
            r,
            {
                "status": "closed",
                "closing_control": cid,
                "note": _note(f"closed by {actor} on {day} with {cid}; evidence: {ref}", r["note"]),
            },
        )
    risk = sync_risk(ctx, system, actor)
    return {
        "n": len(targets),
        "control": cid,
        "risk": risk,
        "tasks_closed": _close_group_tasks(ctx, system, targets),
    }


def _close_group_tasks(ctx: Any, system: Mapping[str, Any], targets: list[dict[str, Any]]) -> int:
    """WP-L4 (REGULATOR_PACK): the last closed row of a gap group closes the group task. Off: 0.
    A failure never undoes the close."""
    if not getattr(ctx.settings, "regulator_pack", False):
        return 0
    try:
        from supervisor.governance import duty_evidence as de

        keys = {group_key(r) for r in targets if r["coverage"] in ("partial", "none")}
        return de.close_group_tasks(de.Env.from_console(ctx), str(system["system_id"]), keys)
    except Exception:  # noqa: BLE001
        log.exception("duties: could not close the group task of %s", system.get("system_id"))
        return 0


def _is_owner(system: Mapping[str, Any], user: str) -> bool:
    from supervisor.governance.lifecycle import same

    if same(str(system.get("owner_user") or ""), user):
        return True
    return any(
        same(str(m.get("user_id") or ""), user) and m.get("team_role") == "system_owner"
        for m in system.get("team") or []
        if m.get("active", True)
    )


def waive(
    ctx: Any,
    actor: str,
    system: Mapping[str, Any],
    targets: list[dict[str, Any]],
    reason: Any,
) -> dict[str, Any]:
    """Waive the picked rows. Reason of 20 characters or more. The owner of the system cannot
    waive a duty of the own system (a second person with ``systems.approve`` does)."""
    text = _clean(reason, MAX_REASON, "reason_too_short", "the waiver reason", MIN_WAIVE)
    if _is_owner(system, actor):
        raise DutyError(
            "owner_cannot_waive",
            "the owner of a system cannot waive a duty of the own system; "
            "a second person with approval rights does it",
        )
    for r in targets:
        _need_open(r)
    day = _today(ctx.clock).isoformat()
    for r in targets:
        _store(
            ctx,
            r,
            {"status": "waived", "note": _note(f"waived by {actor} on {day}: {text}", r["note"])},
        )
    risk = sync_risk(ctx, system, actor)
    return {"n": len(targets), "risk": risk}


# ------------------------------------------------------------------------------ re-evaluate

_FACT_AUTONOMY = {
    "L0": "l0_rule_based",
    "L1": "l1_assistive",
    "L2": "l2_workflow_step",
    "L3": "l3_tool_using_supervised",
}


def stored_draft(ctx: Any, system_id: str) -> dict[str, Any] | None:
    """The submitted register draft that made this system (its answers of the Duties step)."""
    try:
        drafts = ctx.state.query("registration_draft", {"status": "submitted"})
    except Exception:  # noqa: BLE001 - an old store without the register tables
        return None
    for d in drafts:
        data = rm.json_of(d.get("data"), {})
        if str((data.get("result") or {}).get("system_id") or "") == system_id:
            return {**dict(d), "data": data}
    return None


def _facts_autonomy(ctx: Any, node_ids: Iterable[str]) -> str | None:
    """The autonomy level found in the source of a candidate (``onboard_facts``, kind
    ``autonomy``, active rows), as a registry level name; ``None`` when unknown or no table."""
    for nid in sorted(set(node_ids)):
        try:
            facts = ctx.state.query("onboard_facts", {"node_id": nid})
        except Exception:  # noqa: BLE001 - WP-O2 not merged, or no such table
            return None
        for f in facts:
            if f["kind"] == "autonomy" and _on(f["active"]) and f["name"] in _FACT_AUTONOMY:
                return _FACT_AUTONOMY[str(f["name"])]
    return None


def pseudo_draft(ctx: Any, system: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """A draft-shaped record for the matrix: the system row as the answers, the stored draft
    answers of the Duties step on top, and the autonomy level of the facts rows when the system
    has none. Returns the record and 1 when a facts row was used."""
    sid = str(system["system_id"])
    stored = stored_draft(ctx, sid)
    comps = [c for c in system.get("components") or [] if c.get("active", True)]
    agents = sorted(str(c["ref_id"]) for c in comps if c["ref_kind"] == "agent")
    nodes = [str(c["ref_id"]) for c in comps if c["ref_kind"] == "node"]
    v: dict[str, Any] = {
        "name": system.get("name"),
        "owner_team": system.get("owner_team"),
        "purpose": system.get("purpose"),
        "user_segment": system.get("user_segment"),
        "personal_data": system.get("personal_data"),
        "org_role": system.get("org_role"),
        "money_movement": bool(system.get("money_movement")),
        "credit_decision": bool(system.get("credit_decision")),
        "human_control": system.get("human_control"),
        "autonomy_level": system.get("autonomy_level"),
        "agent_id": agents[0]
        if agents
        else ((stored or {}).get("data", {}).get("v") or {}).get("agent_id"),
    }
    answers: dict[str, Any] = {}
    if stored is not None:
        answers = dict(stored["data"].get("duties_answers") or {})
        if stored.get("source_ref"):
            nodes.append(str(stored["source_ref"]))
    used = 0
    if str(v.get("autonomy_level") or "unspecified") == "unspecified":
        level = _facts_autonomy(ctx, nodes)
        if level:
            v["autonomy_level"], used = level, 1
    draft = {
        "draft_id": (stored or {}).get("draft_id") or f"sys_{sid}",
        "source_kind": "blank",
        "source_ref": None,
        "data": {"v": v, "duties_answers": answers},
    }
    return draft, used


def due_for(kb: Any, obligation_id: str, today: dt.date) -> dt.date | None:
    """The effective date of the instrument of a duty when it is still ahead (deadlines.py)."""
    try:
        eff = deadlines.deadline_for(kb.get(obligation_id), kb).effective
    except Exception:  # noqa: BLE001 - an id RegKB no longer knows keeps its due date
        return None
    d = as_date(eff.date) if eff is not None else None
    return d if d is not None and d > today else None


def reevaluate(ctx: Any, actor: str, system: Mapping[str, Any]) -> dict[str, Any]:
    """Run the matrix on the stored answers and update the rows. A row keeps its status (a
    closed or waived duty stays closed or waived); ``applies``, ``coverage`` and, for an open
    row, the due date change. A duty that now applies and has no row gets one. No row is deleted."""
    sid = str(system["system_id"])
    draft, facts = pseudo_draft(ctx, system)
    matrix = dut.matrix_of(ctx, draft)
    kb = kb_of(ctx)
    today = _today(ctx.clock)
    now = ctx.clock.now()
    have = {r["obligation_id"]: r for r in rows_of(ctx.state, sid)}
    out = {
        "checked": len(matrix.rows),
        "rows_before": len(have),
        "updated": 0,
        "added": 0,
        "became_yes": 0,
        "due_set": 0,
        "facts_used": facts,
    }
    owner = str(system.get("owner_user") or actor)
    for r in matrix.rows:
        cov = dut.coverage_of(r) if r.applies == "yes" else "unknown"
        eff = dut.effective_date(r)
        row = have.get(r.obligation_id)
        if row is None:
            if r.applies == "no":
                continue
            ctx.state.insert(
                "obligation_status",
                {
                    "status_id": dut.status_id(sid, r.obligation_id),
                    "system_id": sid,
                    "obligation_id": r.obligation_id,
                    "instrument_id": r.instrument_id,
                    "applies": r.applies,
                    "coverage": cov,
                    "status": OPEN_STATE,
                    "owner_user": owner,
                    "due_date": (eff or (today + dt.timedelta(days=DEFAULT_DUE_DAYS)))
                    if r.applies == "yes"
                    else eff,
                    "closing_control": None,
                    "note": f"{BANNER} {r.status_reason}"[:1000],
                    "created_at": now,
                },
            )
            out["added"] += 1
            continue
        changes: dict[str, Any] = {}
        if row["applies"] != r.applies:
            changes["applies"] = r.applies
        if row["coverage"] != cov:
            changes["coverage"] = cov
        if row["status"] == OPEN_STATE:
            ahead = due_for(kb, r.obligation_id, today)
            current = as_date(row["due_date"])
            if ahead is not None and current != ahead:
                changes["due_date"] = ahead
                out["due_set"] += 1
            elif r.applies == "yes" and row["applies"] != "yes" and current is None:
                # a needs_answer row that becomes yes gets a due date
                changes["due_date"] = eff or (today + dt.timedelta(days=DEFAULT_DUE_DAYS))
                out["due_set"] += 1
        if changes:
            if row["applies"] != "yes" and r.applies == "yes":
                out["became_yes"] += 1
            _store(ctx, row, changes)
            out["updated"] += 1
    out["rows_after"] = len(rows_of(ctx.state, sid))
    out["tasks"] = _gap_tasks(ctx, sid, matrix, actor)
    out["risk"] = sync_risk(ctx, system, actor)
    return out


def _gap_tasks(ctx: Any, system_id: str, matrix: Any, actor: str) -> int:
    """One task per open group of the new matrix (WP-L2 template ids: a repeat is a no-op)."""
    opened = 0
    open_now = open_groups(rows_of(ctx.state, system_id))
    for key, group in dut.gap_groups(matrix.rows).items():
        if key not in open_now:
            continue
        try:
            if dut._task(ctx, system_id, key, group, actor):  # noqa: SLF001
                opened += 1
        except Exception:  # noqa: BLE001 - a group without its task is still a set of duty rows
            log.exception("duties: could not open the task for %s", key)
    return opened


# ------------------------------------------------------------------------------ the risk line


def risk_id_of(system_id: str) -> str:
    return RISK_PREFIX + hashlib.sha256(system_id.encode()).hexdigest()[:16].upper()


def _binding_vn(kb: Any, instrument_id: str) -> bool:
    try:
        inst = kb.instrument(instrument_id)
    except Exception:  # noqa: BLE001 - an instrument RegKB no longer knows is a reference
        return False
    return bool(inst.binding is True and inst.jurisdiction == "VN")


def risk_points(groups: Iterable[tuple[bool, str]]) -> tuple[int, int]:
    """(likelihood, impact), whole numbers 1 to 5, for the open groups. ``groups`` is
    ``(binding Vietnamese instrument, coverage)``. Likelihood grows with the number of open
    groups; impact is the highest of the groups: a binding VN instrument weighs more than an
    international reference framework, coverage none more than partial. ILLUSTRATIVE, like the
    risk bands."""
    items = list(groups)
    n = len(items)
    likelihood = 2 if n <= 2 else 3 if n <= 5 else 4 if n <= 9 else 5
    impact = max((_impact(b, c) for b, c in items), default=2)
    return likelihood, impact


def _impact(binding: bool, coverage: str) -> int:
    if binding:
        return 5 if coverage == "none" else 4
    return 3 if coverage == "none" else 2


def sync_risk(ctx: Any, system: Mapping[str, Any], actor: str) -> str:
    """Open, update or retire the risk line of the system. Returns ``opened``, ``updated``,
    ``closed``, ``unchanged`` or ``none``; ``error`` when the risk service refused (the duty rows
    are stored in any case)."""
    try:
        return _sync_risk(ctx, system, actor)
    except Exception:  # noqa: BLE001 - never undo a duty action because the line failed
        log.exception("duties: risk line failed for %s", system.get("system_id"))
        return "error"


def _sync_risk(ctx: Any, system: Mapping[str, Any], actor: str) -> str:
    sid = str(system["system_id"])
    rid = risk_id_of(sid)
    svc = ctx.risks
    rows = rows_of(ctx.state, sid)
    groups = open_groups(rows)
    cur = ctx.state.get("risk", {"risk_id": rid})
    if not groups:
        if cur is not None and cur["status"] != "retired":
            svc.update_managed(rid, {"status": "retired"}, actor, source="duties")
            return "closed"
        return "none"
    kb = kb_of(ctx)
    today = _today(ctx.clock)
    meta = [(key, _binding_vn(kb, key[0])) for key in groups]
    likelihood, impact = risk_points((b, key[1]) for key, b in meta)
    ordered = sorted(meta, key=lambda m: (not m[1], m[0][1] != "none", m[0]))
    shown = "; ".join(
        f"{kb_name(kb, key[0])} {key[1]} {len(groups[key])}" for key, _ in ordered[:6]
    )
    desc = (
        f"{BANNER} {len(groups)} duty groups of this system are open "
        f"(instrument, coverage, open duties): {shown}"
        + (f"; and {len(groups) - 6} more" if len(groups) > 6 else "")
    )[:2000]
    comps = [c for c in system.get("components") or [] if c.get("active", True)]
    agents = sorted(str(c["ref_id"]) for c in comps if c["ref_kind"] == "agent")
    owner = str(system.get("owner_user") or actor)[:128]
    review = as_date(cur["review_date"]) if cur is not None else None
    if review is None or review <= today:
        review = today + dt.timedelta(days=REVIEW_DAYS)
    fields: dict[str, Any] = {
        "title": f"Open regulatory duties: {system.get('name')}"[:200],
        "description": desc,
        "category": "duties_gap",
        "agent_id": agents[0] if agents else sid,
        "node_id": None,
        "inherent_likelihood": likelihood,
        "inherent_impact": impact,
        "marginal_risk": None,
        "marginal_note": None,
        "treatment": "mitigate",
        "treatment_note": None,
        "residual_likelihood": likelihood,
        "residual_impact": impact,
        "owner": owner,
        "review_date": review,
        "status": "active",
    }
    links = _links(svc, groups, ordered)
    if cur is None:
        svc.create(fields, actor, risk_id=rid, source="duties", links=links)
        return "opened"
    changes = {k: v for k, v in fields.items() if _differs(cur.get(k), v)}
    moved = _sync_links(svc, rid, links, actor)
    if changes:
        svc.update_managed(rid, changes, actor, source="duties")
        return "updated"
    return "updated" if moved else "unchanged"


def kb_name(kb: Any, instrument_id: str) -> str:
    try:
        return str(kb.instrument(instrument_id).number or instrument_id)
    except Exception:  # noqa: BLE001
        return instrument_id


def _differs(old: Any, new: Any) -> bool:
    if isinstance(new, dt.date):
        return as_date(old) != new
    return bool(old != new and not (old in (None, "") and new in (None, "")))


def _links(
    svc: Any,
    groups: Mapping[tuple[str, str], list[dict[str, Any]]],
    ordered: list[tuple[tuple[str, str], bool]],
) -> list[tuple[str, str]]:
    """Evidence references of the line: one obligation id (a ``matrix`` link) per open group,
    the first id of the group; only ids the reference catalogue knows."""
    out: list[tuple[str, str]] = []
    cat = svc._fresh()  # noqa: SLF001 - same catalogue the service checks a link against
    for key, _ in ordered:
        oid = min(str(r["obligation_id"]) for r in groups[key])
        if cat.exists("matrix", oid):
            out.append(("matrix", oid))
        if len(out) >= MAX_RISK_LINKS:
            break
    return sorted(set(out))


def _sync_links(svc: Any, rid: str, want: list[tuple[str, str]], actor: str) -> bool:
    have = {(x["kind"], x["target"]) for x in svc.links(rid)}
    wanted = set(want)
    for kind, target in sorted(wanted - have):
        svc.add_link(rid, kind, target, actor)
    for kind, target in sorted(have - wanted):
        svc.remove_link(rid, kind, target, actor)
    return bool(wanted ^ have)


# ------------------------------------------------------------------------------ overview


def scores_by_system(state: Any, system_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """``{system_id: {pct, open, closed, waived, open_groups}}`` for the systems that have rows
    (one read of ``obligation_status``)."""
    wanted = set(system_ids)
    by: dict[str, list[dict[str, Any]]] = {}
    for r in state.query("obligation_status"):
        if r["system_id"] in wanted:
            by.setdefault(str(r["system_id"]), []).append(dict(r))
    return {sid: {**score(rs), "open_groups": len(open_groups(rs))} for sid, rs in by.items()}


def overview_row(state: Any, system_ids: Iterable[str]) -> dict[str, Any]:
    """The ``duties`` dimension of the assessment completion block of My overview."""
    scores = [s for s in scores_by_system(state, system_ids).values() if s["pct"] is not None]
    avg = (sum(s["pct"] for s in scores) // len(scores)) if scores else None
    return {
        "key": "duties",
        "done": sum(1 for s in scores if s["open_groups"] == 0),
        "of": len(scores),
        "bp": (avg * 100) if avg is not None else None,
        "avg": avg,
        "open_systems": sum(1 for s in scores if s["open_groups"] > 0),
    }


# ------------------------------------------------------------------------------ the sweep


def sweep(state: Any, clock: Any, tasks: Any, settings: Any) -> dict[str, Any]:
    """Reminder tasks. For every system (not archived) with an open applying duty due within 30
    days (or past due) one task is opened for the ISO week of now. The template id holds the
    week, so a second run in the same week opens nothing. Due dates of open rows are first set
    to the effective date of the instrument when that date is ahead."""
    kb = kb_of(settings)
    now = clock.now()
    today = now.date()
    horizon = today + dt.timedelta(days=SWEEP_DAYS)
    year, week, _ = today.isocalendar()
    template = f"{DUE_TEMPLATE}{year}W{week:02d}"
    by: dict[str, list[dict[str, Any]]] = {}
    for r in state.query("obligation_status"):
        by.setdefault(str(r["system_id"]), []).append(dict(r))
    out = {"systems": 0, "tasks": 0, "rows": 0, "due_updated": 0}
    for sysrow in state.query("ai_system"):
        sid = str(sysrow["system_id"])
        if sid not in by or sysrow["status"] == "archived":
            continue
        due: list[dict[str, Any]] = []
        for row in by[sid]:
            if row["applies"] != "yes" or row["status"] != OPEN_STATE:
                continue
            ahead = due_for(kb, str(row["obligation_id"]), today)
            if ahead is not None and as_date(row["due_date"]) != ahead:
                try:
                    state.update(
                        "obligation_status",
                        {"status_id": row["status_id"]},
                        {"due_date": ahead},
                        int(row["row_version"]),
                    )
                    row["due_date"] = ahead
                    out["due_updated"] += 1
                except ConcurrencyError:
                    pass
            d = as_date(row["due_date"])
            if d is not None and d <= horizon:
                due.append(row)
        if not due:
            continue
        out["systems"] += 1
        out["rows"] += len(due)
        ids = sorted(str(r["obligation_id"]) for r in due)
        shown = ", ".join(ids[:20]) + (f", ... and {len(ids) - 20} more" if len(ids) > 20 else "")
        ahead_days = sorted(d for d in (as_date(r["due_date"]) for r in due) if d and d > today)
        trow = tasks._row_for(  # noqa: SLF001 - the one place that writes a task for a system
            sid,
            str(sysrow["lifecycle_stage"]),
            template_id=template,
            kind="custom",
            title=f"{len(ids)} {'duty is' if len(ids) == 1 else 'duties are'} due within "
            f"{SWEEP_DAYS} days (week {year}W{week:02d})",
            owner_role="owner",
            required=False,
            due_days=7,
            evidence_kind="none",
            evidence_ref=f"{BANNER} {shown}",
            level="low",
            d33_class="unclassified",
            actor="system:duties_sweep",
        )
        if ahead_days:
            d0 = ahead_days[0]
            trow["due_at"] = dt.datetime(d0.year, d0.month, d0.day, tzinfo=dt.UTC)
        if tasks._insert(trow, "system:duties_sweep"):  # noqa: SLF001
            out["tasks"] += 1
    return out


__all__ = [
    "BANNER",
    "FILTERS",
    "DutyError",
    "close",
    "enabled",
    "reevaluate",
    "score",
    "sweep",
    "sync_risk",
    "waive",
]
