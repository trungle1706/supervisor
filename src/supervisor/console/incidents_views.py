"""Incidents tab of Cases & alerts (WP-G5): filter, sort, page and row drawer over the
``incident`` rows of the governance loop. This module only reads; the transition itself is the
audited route in ``incidents_routes`` (permission ``incidents.transition``). Filters are checked
against allow-lists or an id pattern; a bad value is a ``ListingError`` (HTTP 400)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import SEVERITIES
from supervisor.console import ux3
from supervisor.console.listing import (
    ListingError,
    paginate,
    parse_int,
    parse_sort,
    query_string,
    sort_rows,
)
from supervisor.core import rbac
from supervisor.core.canonical import parse_ts
from supervisor.core.errors import NotFoundError
from supervisor.governance.incidents import STATUSES, TITLES, IncidentError

COLUMNS = ("opened_at", "severity", "kind", "agent", "status")
PAGE_SIZE = 20
_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
_KEYS = {
    "severity": lambda r: _SEV_RANK.get(r["severity"], -1),
    "agent": lambda r: r.get("agent_id") or None,
}
FILTERS = ("status", "severity", "kind", "agent")


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    p = {
        "status": ux3.choice(query, "status", (*STATUSES, "all")),
        "severity": ux3.choice(query, "severity", SEVERITIES),
        "kind": ux3.choice(query, "kind", TITLES),
        "agent": ux3.ident(query, "agent"),
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }
    parse_int(p["page"], "page", 1)
    return p


def _dt(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for k in ("opened_at", "closed_at"):
        if isinstance(out.get(k), str):
            out[k] = parse_ts(out[k])
    return out


def _qs(p: Mapping[str, str], **override: str) -> str:
    return query_string({k: p[k] for k in FILTERS}, **override)


def list_view(ctx: Any, me: Any, query: Mapping[str, str]) -> dict[str, Any]:
    p = parse_params(query)
    svc = ctx.incidents
    try:
        everything = [_dt(r) for r in svc.list_incidents(me, {"status": "all"})]
        rows = [_dt(r) for r in svc.list_incidents(me, {k: p[k] for k in FILTERS if p[k]})]
    except IncidentError as exc:
        raise ListingError(str(exc)) from None
    counts = dict.fromkeys(STATUSES, 0)
    for r in everything:
        counts[str(r["status"])] += 1
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "opened_at", "desc")
    rows = sort_rows(rows, col, direction, _KEYS)  # type: ignore[assignment]
    page = paginate(rows, parse_int(p["page"], "page", 1), PAGE_SIZE)
    base = {k: p[k] for k in FILTERS}
    tiles = [
        {
            "label": "inc_active",
            "n": sum(counts[s] for s in STATUSES if s != "closed"),
            "on": p["status"] == "",
            "qs": _qs(p, status=""),
        }
    ]
    for s in STATUSES:
        tiles.append(
            {
                "label": f"inc_st_{s}",
                "n": counts[s],
                "on": p["status"] == s,
                "qs": _qs(p, status=s),
            }
        )
    return {
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "tiles": tiles,
        "inc_counts": counts,
        "severity_opts": [(s, s) for s in reversed(SEVERITIES)],
        "kind_opts": [(k, f"inc_kind_{k}") for k in TITLES],
        "agent_opts": [(a, a) for a in sorted({str(r["agent_id"]) for r in everything} - {"-"})],
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
        "can_move": getattr(me, "kind", "") == "user"
        and rbac.allowed(me.roles, "incidents.transition"),
    }


def drawer_view(ctx: Any, me: Any, incident_id: str) -> dict[str, Any]:
    try:
        row = ctx.incidents.get(incident_id, me)
    except NotFoundError:
        raise ListingError(f"incident {incident_id[:64]} does not exist") from None
    inc = _dt(row)
    return {
        "inc": inc,
        "json_text": json.dumps(row, sort_keys=True, indent=2, default=str),
        "can_move": getattr(me, "kind", "") == "user"
        and rbac.allowed(me.roles, "incidents.transition"),
    }


def system_incidents(ctx: Any, system_id: str) -> list[dict[str, Any]]:
    """The incidents of one system, newest first, for the Reports tab of the system page."""
    return [_dt(r) for r in ctx.incidents.for_system(system_id)]
