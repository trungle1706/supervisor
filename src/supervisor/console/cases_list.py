"""Cases list (WP-UX2): sort, page and row drawer over the case rows of ``readmodels.case_rows``.

The filters (severity, status, agent, opened-by) are checked by the route; this module only
sorts and pages. The service already returns cases by severity (critical first) and age, so
the default sort keeps that order. An unknown sort column falls back to the default (the
column list is an allow-list); a bad page is a ``ListingError`` (HTTP 400)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import SEVERITIES
from supervisor.console.listing import paginate, parse_int, parse_sort, query_string, sort_rows

COLUMNS = ("severity", "agent_id", "clock", "status", "assignee")
SIGNOFF_COLUMNS = ("severity", "agent_id", "clock", "missing")
PAGE_SIZE = 25
_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}  # low .. critical
_KEYS = {
    "severity": lambda c: _SEV_RANK.get(c["severity"], -1),
    "clock": lambda c: (c.get("clock") or {}).get("used_bp") if c.get("clock") else None,
    "assignee": lambda c: c.get("assignee") or None,
    "missing": lambda c: c.get("missing"),
}


def list_view(
    items: list[dict[str, Any]],
    filters: Mapping[str, str],
    query: Mapping[str, str],
    columns: tuple[str, ...] = COLUMNS,
) -> dict[str, Any]:
    """Sorted, paged rows plus the strings the table macros need."""
    col, direction = parse_sort(query.get("sort"), query.get("dir"), columns, "severity", "desc")
    rows = sort_rows(items, col, direction, _KEYS)
    page = paginate(rows, parse_int(query.get("page"), "page", 1), PAGE_SIZE)
    base = {k: v for k, v in filters.items() if v}
    return {
        "page": page,
        "sort_col": col,
        "sort_dir": direction,
        "base_qs": query_string(base),  # filters only
        "list_qs": query_string({**base, "sort": col, "dir": direction}),  # + sort, no page
    }


def drawer_view(row: dict[str, Any], agent_known: bool) -> dict[str, Any]:
    """Data of the case drawer: the case row (``readmodels.case_rows``), whether its agent
    has a detail page, and a small JSON text for Copy JSON."""
    return {
        "c": row,
        "agent_known": agent_known,
        "json_text": json.dumps(
            {
                "case_id": row["case_id"],
                "agent_id": row["agent_id"],
                "severity": row["severity"],
                "status": row["status"],
                "assignee": row.get("assignee"),
                "sources": row.get("sources"),
            },
            sort_keys=True,
            indent=2,
        ),
    }
