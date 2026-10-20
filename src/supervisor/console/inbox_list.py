"""Inbox list (WP-UX2): filter, sort and page over the notices of ``ctx.inbox``.

Pure functions. The mark-read action stays in ``routes.inbox_read`` (permission ``inbox.read``,
two ``console_action`` rows). A bad filter or page is a ``ListingError`` (HTTP 400)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from supervisor.console.listing import (
    ListingError,
    paginate,
    parse_int,
    parse_sort,
    query_string,
    sort_rows,
)

STATUSES = ("unread", "read", "queued")
COLUMNS = ("ts", "channel", "status")
PAGE_SIZE = 25
_CHANNEL = re.compile(r"^[A-Za-z0-9_.:@-]{1,64}$")


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    status = query.get("status") or ""
    if status and status not in STATUSES:
        raise ListingError("unknown notice status filter")
    channel = query.get("channel") or ""
    if channel and not _CHANNEL.match(channel):
        raise ListingError("invalid channel filter")
    parse_int(query.get("page"), "page", 1)
    return {
        "status": status,
        "channel": channel,
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }


def list_view(notices: list[dict[str, Any]], query: Mapping[str, str]) -> dict[str, Any]:
    """Data for ``inbox.html`` / ``_inbox_rows.html``."""
    p = parse_params(query)
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "ts", "desc")
    rows = [
        n
        for n in notices
        if (not p["status"] or n.get("status") == p["status"])
        and (not p["channel"] or n.get("channel") == p["channel"])
    ]
    rows = sort_rows(rows, col, direction)
    page = paginate(rows, parse_int(p["page"], "page", 1), PAGE_SIZE)
    base = {k: p[k] for k in ("status", "channel")}
    return {
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "status_opts": [(s, f"inbox_st_{s}") for s in STATUSES],
        "channel_opts": [
            (c, c) for c in sorted({n["channel"] for n in notices if n.get("channel")})
        ],
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
    }
