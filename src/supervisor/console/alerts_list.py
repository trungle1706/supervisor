"""Alerts page (WP-UX2): filter, sort, page and row drawer over the WP21 ``alert`` rows.

The acknowledge action itself stays in ``routes.alert_ack`` (permission ``alert.ack``, two
``console_action`` rows, the ``alert_ack`` record); this module only reads. Filters are checked
against allow-lists or an id pattern; a bad value is a ``ListingError`` (HTTP 400)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import SEVERITIES
from supervisor.console.listing import (
    ListingError,
    paginate,
    parse_int,
    parse_sort,
    query_string,
    sort_rows,
)

STATUSES = ("open", "acknowledged", "closed")
COLUMNS = ("ts", "severity", "rule_id", "agent", "status")
PAGE_SIZE = 20
FETCH_LIMIT = 1000
_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
_KEYS = {
    "severity": lambda a: _SEV_RANK.get(a["severity"], -1),
    "agent": lambda a: a.get("agent_id") or a.get("group_value") or None,
}


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    """Canonical list parameters (empty string = not set). Raises ListingError."""
    status = query.get("status") or ""
    if status and status not in (*STATUSES, "all"):
        raise ListingError("unknown alert status filter")
    severity = query.get("severity") or ""
    if severity and severity not in SEVERITIES:
        raise ListingError("unknown severity filter")
    out = {"status": status, "severity": severity}
    for key, what in (("agent", "agent filter"), ("rule", "rule filter")):
        value = query.get(key) or ""
        if value and not _ID.match(value):
            raise ListingError(f"invalid {what}")
        out[key] = value
    parse_int(query.get("page"), "page", 1)  # validates the text; paginate() checks the range
    out.update(
        sort=query.get("sort") or "", dir=query.get("dir") or "", page=query.get("page") or ""
    )
    return out


def _agent_of(a: Mapping[str, Any]) -> str:
    return str(a.get("agent_id") or a.get("group_value") or "")


def _matches(a: Mapping[str, Any], p: Mapping[str, str]) -> bool:
    if p["status"] == "":
        if a["status"] not in ("open", "acknowledged"):  # the default view hides closed
            return False
    elif p["status"] != "all" and a["status"] != p["status"]:
        return False
    if p["severity"] and a["severity"] != p["severity"]:
        return False
    if p["agent"] and _agent_of(a) != p["agent"]:
        return False
    return not (p["rule"] and a["rule_id"] != p["rule"])


def _qs(p: Mapping[str, str], **override: str) -> str:
    return query_string({k: p[k] for k in ("status", "severity", "agent", "rule")}, **override)


def list_view(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    """Data for ``alerts.html`` / ``_alerts_list.html``."""
    p = parse_params(query)
    counts = ctx.alerts.counts()
    everything = ctx.alerts.list(limit=FETCH_LIMIT)
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "ts", "desc")
    rows = [a for a in everything if _matches(a, p)]
    rows = sort_rows(rows, col, direction, _KEYS)
    page = paginate(rows, parse_int(p["page"], "page", 1), PAGE_SIZE)
    base = {k: p[k] for k in ("status", "severity", "agent", "rule")}
    tiles = [
        {
            "label": "alerts_active",
            "n": counts.get("open", 0) + counts.get("acknowledged", 0),
            "on": p["status"] == "",
            "qs": _qs(p, status=""),
        }
    ]
    for s in STATUSES:
        tiles.append(
            {
                "label": f"alerts_st_{s}",
                "n": counts.get(s, 0),
                "on": p["status"] == s,
                "qs": _qs(p, status=s),
            }
        )
    return {
        "alert_counts": counts,
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "tiles": tiles,
        "severity_opts": [(s, s) for s in reversed(SEVERITIES)],
        "agent_opts": [(a, a) for a in sorted({_agent_of(a) for a in everything} - {""})],
        "rule_opts": [(r, r) for r in sorted({a["rule_id"] for a in everything})],
        "base_qs": query_string(base),  # filters only
        "list_qs": query_string({**base, "sort": col, "dir": direction}),  # + sort, no page
    }


def drawer_view(ctx: Any, alert_id: str) -> dict[str, Any]:
    """The full alert row for the drawer. Unknown id: ListingError (HTTP 400)."""
    if not _ID.match(alert_id or ""):
        raise ListingError("invalid alert id")
    row = ctx.state.get("alert", {"alert_id": alert_id})
    if row is None:
        raise ListingError(f"alert {alert_id[:64]} does not exist")
    from supervisor.analytics.decisions import safe_id, shown_id

    row = {**row, "correlation_id": shown_id(row.get("correlation_id"))}  # WP39 review (R2)
    shown = {
        k: row.get(k)
        for k in (
            "alert_id",
            "rule_id",
            "severity",
            "status",
            "agent_id",
            "window_count",
            "threshold",
            "window_s",
            "case_id",
            "chain_lane",
            "chain_seq",
            "entry_hash",
            "route_status",
            "acknowledged_by",
            "correlation_id",
        )
    }
    return {
        "settings_v2": bool(getattr(ctx.settings, "console_decisions_v2", False)),
        "corr_link": safe_id(row.get("correlation_id")),
        "al": row,
        "agent": _agent_of(row),
        "json_text": json.dumps(shown, sort_keys=True, indent=2, default=str),
    }
