"""Time parsing and second-precision text, shared by services (audit D2, D3).

``core.canonical.parse_ts`` and ``format_ts`` (strict, microsecond RFC 3339 for chain payloads)
are a different tool and stay as they are.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

_ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


def _utc(value: dt.datetime) -> dt.datetime:
    """A naive datetime is read as UTC; an aware one is converted to UTC."""
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def parse_utc(value: Any) -> dt.datetime | None:
    """A ``datetime`` or an ISO 8601 text (``Z`` or an offset, or naive = UTC) as an aware UTC
    ``datetime``. Returns None for None, empty text, junk, or any other type."""
    if isinstance(value, dt.datetime):
        return _utc(value)
    if isinstance(value, str) and value:
        try:
            return _utc(dt.datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def parse_utc_strict(value: Any) -> dt.datetime:
    """Like ``parse_utc`` but raises ``ValueError`` when the value is not a time. A value that
    is neither a ``datetime`` nor text is read through ``str()``."""
    if isinstance(value, dt.datetime):
        return _utc(value)
    return _utc(dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def iso_z(value: dt.datetime) -> str:
    """Second-precision UTC text with a ``Z`` suffix, e.g. ``2026-10-30T08:00:00Z``.
    A naive datetime is read as UTC."""
    return _utc(value).strftime(_ISO_Z)
