"""Read models for the console screens (WP12). Pure functions over the stores; no writes.

The console shows times in Vietnam time (ICT, UTC+7): "today" is the ICT calendar day.
Counts come from the append-only tables (``agent_event``, ``verdict``, ``chain_*``) and the
state tables (``agent``, ``cases``). Stores only filter by equality, so a scan is ordered
newest first and capped at ``SCAN_CAP`` rows; a capped count is shown with a "+".
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from supervisor.cases.service import TRANSITIONS

ICT = dt.timezone(dt.timedelta(hours=7))
SCAN_CAP = 20000
OPEN_STATUSES = (*TRANSITIONS.keys(), "escalated", "resolved")
STOP_ACTIONS = ("block", "pause")


# ---------------------------------------------------------------------------- small helpers


def ict(value: dt.datetime | None) -> dt.datetime | None:
    return value.astimezone(ICT) if value is not None else None


def hhmm(value: dt.datetime | None, seconds: bool = False) -> str:
    if value is None:
        return "-"
    return ict(value).strftime("%H:%M:%S" if seconds else "%H:%M")  # type: ignore[union-attr]


def day_start(now: dt.datetime) -> dt.datetime:
    """Midnight of the ICT day that contains ``now`` (aware, UTC)."""
    local = now.astimezone(ICT)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.UTC)


def greeting_key(now: dt.datetime) -> str:
    hour = now.astimezone(ICT).hour
    if 4 <= hour < 12:
        return "greet_morning"
    if 12 <= hour < 18:
        return "greet_afternoon"
    return "greet_evening"


def first_name(me: Any) -> str:
    """Vietnamese names put the given name last ("Nguyễn Văn An" -> "An"). A label with a
    note in brackets ("Payments Ops lead (owner)") is used as it is, without the note."""
    name = (getattr(me, "display_name", "") or "").strip()
    if not name:
        uid = str(getattr(me, "user_id", "") or "")
        return uid.split("@")[0] or uid
    if "(" in name:
        return name.split("(")[0].strip() or name
    parts = name.split()
    return parts[-1] if len(parts) >= 2 else name


def initials(me: Any) -> str:
    name = (getattr(me, "display_name", "") or "").split("(")[0].strip()
    if name:
        parts = name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return name[:2].upper()
    uid = str(getattr(me, "user_id", "") or "?")
    return uid[:2].upper()


def main_role(me: Any) -> str:
    order = ("admin", "approver", "reviewer", "owner", "auditor")
    roles = set(getattr(me, "roles", ()) or ())
    for r in order:
        if r in roles:
            return r
    return "service" if getattr(me, "kind", "") == "service_principal" else "viewer"


def median(values: Sequence[int]) -> int | None:
    """Nearest-rank median (always one of the values), as in docs/metrics.md."""
    vals = sorted(values)
    if not vals:
        return None
    return vals[(len(vals) + 1) // 2 - 1]


def is_demo_store(settings: Any) -> bool:
    from supervisor.demo.session import MARKER

    try:
        return (Path(settings.data_dir) / MARKER).is_file()
    except (OSError, TypeError):
        return False


def open_cases(ctx: Any) -> list[dict[str, Any]]:
    return ctx.cases.list_cases(statuses=OPEN_STATUSES)


# ---------------------------------------------------------------------------- shell


def shell(ctx: Any, me: Any) -> dict[str, Any]:
    """Header data for every full page: counts on the pills, environment badge, identity."""
    agents = ctx.state.query("agent")
    cases = open_cases(ctx)
    try:
        unread = sum(1 for n in ctx.inbox.list() if n.get("status") == "unread")
    except Exception:  # noqa: BLE001 - the badge is a convenience, never a page failure
        unread = 0
    return {
        "agents_n": len(agents),
        "cases_n": len(cases),
        "critical_n": sum(1 for c in cases if c["severity"] == "critical"),
        "demo": is_demo_store(ctx.settings),
        "mode": ctx.settings.supervisor_mode,
        "unread": unread,
        "initials": initials(me),
        "first_name": first_name(me),
        "role": main_role(me),
    }


def jloads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def as_list(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
