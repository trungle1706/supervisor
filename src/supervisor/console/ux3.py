"""Shared input checks for the WP-UX3 list pages (decisions, traces, policies, audit).

Pure helpers, no I/O. Every filter value is checked against an allow-list or a strict pattern;
a bad value is a ``ListingError`` (HTTP 400), never a 500 and never part of a SQL string (the
store takes equality filters through named parameters only)."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Mapping

from supervisor.console.listing import ListingError

TOKEN = re.compile(r"^[A-Za-z0-9_.:@ -]{0,64}$")
ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
# time-range keys -> seconds ("" = no limit)
RANGES: dict[str, int] = {"1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}


def token(query: Mapping[str, str], name: str) -> str:
    """A short free-text filter: letters, digits and . _ : @ - and space only (64 max)."""
    value = (query.get(name) or "").strip()
    if not TOKEN.match(value):
        raise ListingError(f"{name}: letters, digits and . _ : @ - only (64 max)")
    return value


def ident(query: Mapping[str, str], name: str) -> str:
    """An id filter (agent, rule, tool, actor): empty or a plain identifier."""
    value = (query.get(name) or "").strip()
    if value and not ID.match(value):
        raise ListingError(f"{name}: not a valid id")
    return value


def choice(query: Mapping[str, str], name: str, allowed: Iterable[str]) -> str:
    value = query.get(name) or ""
    if value and value not in tuple(allowed):
        raise ListingError(f"unknown {name} filter")
    return value


def range_start(now: dt.datetime, key: str) -> dt.datetime | None:
    """Start of the time range ``key`` (None = all time)."""
    secs = RANGES.get(key)
    return now - dt.timedelta(seconds=secs) if secs else None
