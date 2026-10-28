"""The Duties tab of the system page and its buttons (WP-L3, ``RISK_DUTIES``).

The rules are in ``governance/duties_gap.py``; this module is the console side: the view model of
the tab (``obligation_status`` rows grouped by instrument, then coverage), the filter and the
paging, what a person may press, and the audit note of each button (fixed text, counts and the
first 12 characters of the SHA-256 of a typed reason or evidence reference; the typed text is
never written to ``console_action``).

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import PermissionDenied
from supervisor.console.listing import ListingError, paginate, parse_int, query_string
from supervisor.core import rbac
from supervisor.governance import duties_gap as dg


def person(me: Any) -> str:
    if getattr(me, "kind", "") != "user":
        raise PermissionDenied("this action needs a signed-in person")
    return str(me.user_id)


def is_on(ctx: Any) -> bool:
    return dg.enabled(ctx.settings)


def ensure_on(ctx: Any) -> None:
    dg.ensure_on(ctx)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def audit_note(action: str, before: str, after: str, n: int, typed: str | None = None) -> str:
    """``action before>after n=3`` and, when a person typed text, ``text_sha=<12 hex>``."""
    note = f"{action} {before}>{after} n={n}"
    if typed:
        note += " text_sha=" + _sha(typed)
    return note


def may_edit(me: Any, system: Mapping[str, Any]) -> bool:
    user = getattr(me, "kind", "") == "user"
    return bool(
        user and rbac.allowed(me.roles, "systems.edit") and system.get("status") != "archived"
    )


def may_waive(me: Any, system: Mapping[str, Any]) -> bool:
    user = getattr(me, "kind", "") == "user"
    return bool(
        user and rbac.allowed(me.roles, "systems.approve") and system.get("status") != "archived"
    )


# ------------------------------------------------------------------------------ the buttons


def _targets(ctx: Any, system: Mapping[str, Any], form: Mapping[str, str]) -> list[dict[str, Any]]:
    return dg.pick(dg.rows_of(ctx.state, str(system["system_id"])), form)


def do_close(
    ctx: Any, me: Any, system: Mapping[str, Any], form: Mapping[str, str]
) -> tuple[dict[str, Any], str]:
    dg.ensure_on(ctx)
    actor = person(me)
    targets = _targets(ctx, system, form)
    out = dg.close(
        ctx, actor, system, targets, form.get("closing_control"), form.get("evidence_ref")
    )
    return out, audit_note(
        "duty_close", "open", "closed", out["n"], f"{out['control']}|{form.get('evidence_ref')}"
    )


def do_waive(
    ctx: Any, me: Any, system: Mapping[str, Any], form: Mapping[str, str]
) -> tuple[dict[str, Any], str]:
    dg.ensure_on(ctx)
    actor = person(me)
    targets = _targets(ctx, system, form)
    out = dg.waive(ctx, actor, system, targets, form.get("reason"))
    return out, audit_note("duty_waive", "open", "waived", out["n"], form.get("reason"))


def do_reevaluate(ctx: Any, me: Any, system: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    dg.ensure_on(ctx)
    actor = person(me)
    out = dg.reevaluate(ctx, actor, system)
    return out, (
        f"duty_reevaluate rows={out['rows_before']}>{out['rows_after']} "
        f"updated={out['updated']} added={out['added']}"
    )


# ------------------------------------------------------------------------------ page data


def header(ctx: Any, system: Mapping[str, Any]) -> dict[str, Any]:
    """The gap closure score for the header of the system page."""
    rows = dg.rows_of(ctx.state, str(system["system_id"]))
    return {**dg.score(rows), "open_groups": len(dg.open_groups(rows)), "rows": len(rows)}


def _info(kb: Any, oid: str) -> dict[str, str]:
    try:
        o = kb.get(oid)
        return {
            "article": o.article_ref,
            "duty": o.summary_en,
            "number": o.number or o.instrument_id,
        }
    except Exception:  # noqa: BLE001 - an id RegKB no longer knows is still listed
        return {"article": "", "duty": "", "number": ""}


def _keep(row: Mapping[str, Any], flt: str) -> bool:
    if flt == "all":
        return True
    if flt == "needs_answer":
        return row["applies"] == "needs_answer"
    return row["applies"] == "yes" and row["status"] == flt


def tab_data(
    ctx: Any, me: Any, system: Mapping[str, Any], query: Mapping[str, str]
) -> dict[str, Any]:
    """View model of the Duties tab: score, filter counts, one page of rows in blocks of
    (instrument, coverage), the block counts over the whole group, what the person may press."""
    flt = query.get("f") or "open"
    if flt not in dg.FILTERS:
        raise ListingError(f"filter f must be one of {', '.join(dg.FILTERS)}")
    page_no = parse_int(query.get("p"), "page p", 1)
    sid = str(system["system_id"])
    rows = dg.rows_of(ctx.state, sid)
    kb = dg.kb_of(ctx)
    today = ctx.clock.now().date()
    shown = [r for r in rows if _keep(r, flt)]
    page = paginate(shown, page_no, dg.PAGE_SIZE)
    totals: dict[tuple[str, str], dict[str, int]] = {}
    for r in rows:
        if r["applies"] == "yes":
            t = totals.setdefault(dg.group_key(r), {"open": 0, "closed": 0, "waived": 0})
            if r["status"] in t:
                t[str(r["status"])] += 1
    blocks: list[dict[str, Any]] = []
    for r in page.items:
        key = dg.group_key(r)
        if not blocks or blocks[-1]["key"] != key:
            inst = kb_number(kb, key[0])
            blocks.append(
                {
                    "key": key,
                    "instrument_id": key[0],
                    "instrument": inst,
                    "coverage": key[1],
                    "counts": totals.get(key, {}),
                    "actionable": key[1] in ("partial", "none")
                    and totals.get(key, {}).get("open", 0) > 0,
                    "rows": [],
                }
            )
        due = dg.as_date(r["due_date"])
        info = _info(kb, str(r["obligation_id"]))
        blocks[-1]["rows"].append(
            {
                **{
                    k: r[k] for k in ("status_id", "obligation_id", "applies", "coverage", "status")
                },
                **info,
                "owner": r["owner_user"],
                "due": due.isoformat() if due else "",
                "overdue": bool(due and due < today and r["status"] == "open"),
                "closing_control": r["closing_control"] or "",
                "note": str(r["note"] or ""),
                "can_act": r["applies"] == "yes" and r["status"] == "open",
            }
        )
    sc = dg.score(rows)
    counts = {f: sum(1 for r in rows if _keep(r, f)) for f in dg.FILTERS}
    base = {"tab": "duties", "f": flt}
    return {
        "du_on": True,
        "du_score": {**sc, "open_groups": len(dg.open_groups(rows))},
        "du_rows_n": len(rows),
        "du_filter": flt,
        "du_filters": dg.FILTERS,
        "du_counts": counts,
        "du_blocks": blocks,
        "du_page": page,
        "du_shown": len(shown),
        "du_qs": query_string(base),
        "du_can_edit": may_edit(me, system),
        "du_can_waive": may_waive(me, system),
        "du_is_owner": dg._is_owner(system, str(getattr(me, "user_id", ""))),  # noqa: SLF001
        "du_choices": dg.control_choices(ctx) if may_edit(me, system) else {},
        "du_banner": dg.BANNER,
        "du_min_waive": dg.MIN_WAIVE,
        "du_max_evidence": dg.MAX_EVIDENCE,
        "du_risk_id": dg.risk_id_of(sid),
        "du_today": today.isoformat() if isinstance(today, dt.date) else "",
    }


def kb_number(kb: Any, instrument_id: str) -> str:
    return dg.kb_name(kb, instrument_id)
