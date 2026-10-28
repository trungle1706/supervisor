"""Portfolio blocks of My overview (WP-C4, OVERVIEW_PORTFOLIO): Classification and Risk assessment.

Read only; no table is added. Both blocks call the service functions behind the two summary APIs
(``ClassificationV2Service.summary`` and ``risk_dimensions.summary``), so the totals equal the
system pages. Every number is an integer; a share is an integer percent (largest remainder, so
the bars add up to 100).

Classification: one bar per outcome and one for "not classified" (no approved record yet).
Risk assessment: eight dimension columns by system rows (at most ``GRID_ROWS``; the systems with
the most failed types come first), the portfolio total per column (pass, open = not_started +
in_progress, fail, waived, not applicable) and the count of systems with a type past
``valid_until``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from supervisor.core.errors import SupervisorError
from supervisor.governance import classification_v2 as c2
from supervisor.governance import risk_dimensions as rd

GRID_ROWS = 50
OUTCOME_ORDER = ("prohibited", "high_certify", "high_self", "medium", "low", "not_system")
NONE_OUTCOME = "none"  # the filter value and bar key of "not classified"
OFF_MESSAGE = (
    "overview_portfolio_off: the portfolio blocks are off "
    "(OVERVIEW_PORTFOLIO=1 turns them on; needs CONSOLE_OVERVIEW_V4 and GOVERNANCE_ENABLED)"
)


class PortfolioError(SupervisorError):
    """Blocks off or a bad filter (HTTP 400)."""


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "overview_portfolio", False)
        and getattr(settings, "console_overview_v4", False)
        and getattr(settings, "governance_enabled", False)
    )


def require_on(settings: Any) -> None:
    if not enabled(settings):
        raise PortfolioError(OFF_MESSAGE)


def percents(counts: list[int], total: int) -> list[int]:
    """Integer percents of ``total`` by the largest-remainder rule; they sum to 100 when the
    counts sum to ``total`` and ``total`` > 0."""
    if total <= 0:
        return [0 for _ in counts]
    base = [n * 100 // total for n in counts]
    rest = 100 - sum(base)
    order = sorted(range(len(counts)), key=lambda i: (-(counts[i] * 100 % total), i))
    for i in order[: max(rest, 0)]:
        if counts[i]:
            base[i] += 1
    return base


def _past(value: Any, now: dt.datetime) -> bool:
    """True when the ``valid_until`` date (inclusive) is before today."""
    if isinstance(value, dt.datetime):
        day = value.date()
    elif isinstance(value, dt.date):
        day = value
    elif isinstance(value, str) and value:
        try:
            day = dt.date.fromisoformat(value[:10])
        except ValueError:
            return False
    else:
        return False
    return day < now.date()


# ----------------------------------------------------------------------------- classification


def classification_block(ctx: Any, system_ids: list[str]) -> dict[str, Any]:
    if not c2.enabled(ctx.settings):
        return {"on": False}
    s = ctx.classification_v2.summary(system_ids)
    counts: Mapping[str, int] = s["counts"]
    order = [o for o in OUTCOME_ORDER if o in counts] + [
        o for o in counts if o not in OUTCOME_ORDER
    ]
    not_classified = int(s["systems_n"]) - int(s["approved_n"])
    values = [int(counts[o]) for o in order] + [not_classified]
    pcts = percents(values, int(s["systems_n"]))
    keys = [*order, NONE_OUTCOME]
    return {
        "on": True,
        "systems_n": int(s["systems_n"]),
        "approved_n": int(s["approved_n"]),
        "not_classified_n": not_classified,
        "waiting_for_approval_n": int(s["waiting_for_approval_n"]),
        "review_due_n": int(s["review_due_n"]),
        "bars": [
            {"outcome": k, "count": n, "pct": p} for k, n, p in zip(keys, values, pcts, strict=True)
        ],
    }


def outcome_filter(ctx: Any, system_ids: list[str], outcome: str) -> set[str]:
    """Ids among ``system_ids`` whose approved outcome is ``outcome`` (``none``: no approved
    record). Used by the systems list. Unknown outcome: HTTP 400."""
    svc = ctx.classification_v2  # approved_outcomes checks the flag
    valid = {*svc.tree().outcomes, NONE_OUTCOME}
    if outcome not in valid:
        raise PortfolioError(f"outcome must be one of {', '.join(sorted(valid))}")
    got = svc.approved_outcomes(system_ids)
    want = None if outcome == NONE_OUTCOME else outcome
    return {sid for sid, o in got.items() if o == want}


# ----------------------------------------------------------------------------- risk assessment


def risk_block(ctx: Any, systems: list[Mapping[str, Any]]) -> dict[str, Any]:
    """``systems``: the rows of the caller's scope. Archived systems are left out, as in
    ``GET /v1/risk-dimensions/summary``."""
    if not rd.enabled(ctx.settings):
        return {"on": False}
    env = rd.Env.from_console(ctx)
    live = [r for r in systems if r.get("status") != "archived"]
    ids = [str(r["system_id"]) for r in live]
    s = rd.summary(env, ids)
    dims = [d["dimension_id"] for d in s["dimensions"]]
    totals = []
    for d in s["dimensions"]:
        totals.append(
            {
                "dimension_id": d["dimension_id"],
                "label_en": d["label_en"],
                "pass": int(d["pass"]),
                "open": int(d["not_started"]) + int(d["in_progress"]),
                "fail": int(d["fail"]),
                "waived": int(d["waived"]),
                "not_applicable": int(d["not_applicable"]),
            }
        )
    now = ctx.clock.now()
    wanted = set(ids)
    cells: dict[str, dict[str, str]] = {sid: {} for sid in ids}
    past: set[str] = set()
    for r in ctx.state.query("risk_dimension_status", {}):
        sid = str(r["system_id"])
        if sid not in wanted or r["dimension_id"] not in dims:
            continue
        cells[sid][str(r["dimension_id"])] = str(r["status"])
        if _past(r.get("valid_until"), now):
            past.add(sid)
    names = {str(r["system_id"]): str(r.get("name") or r["system_id"]) for r in live}
    rows = []
    for sid in ids:
        by = {d: cells[sid].get(d, "not_started") for d in dims}
        rows.append(
            {
                "system_id": sid,
                "name": names[sid],
                "cells": by,
                "fail_n": sum(1 for v in by.values() if v == "fail"),
            }
        )
    rows.sort(key=lambda x: (-x["fail_n"], x["name"].lower(), x["system_id"]))
    return {
        "on": True,
        "systems_n": int(s["systems"]),
        "dimensions": totals,
        "dimension_ids": dims,
        "past_valid_until_n": len(past),
        "rows_total": len(rows),
        "rows": rows[:GRID_ROWS],
        "more_n": max(len(rows) - GRID_ROWS, 0),
    }


# ----------------------------------------------------------------------------- the two together


def block_data(ctx: Any, systems: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Both blocks for the given scope rows. Raises ``PortfolioError`` while the flag is off."""
    require_on(ctx.settings)
    return {
        "classification": classification_block(ctx, [str(r["system_id"]) for r in systems]),
        "risk": risk_block(ctx, systems),
    }


def api_body(ctx: Any, me: Any) -> dict[str, Any]:
    """Body of ``GET /v1/portfolio``: the blocks over every system the caller may see."""
    require_on(ctx.settings)
    svc = ctx.systems
    return block_data(ctx, svc.list_systems(svc.scope_for(me), {}))
