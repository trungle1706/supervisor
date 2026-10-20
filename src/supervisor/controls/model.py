"""Control catalogue model (WP30, ADR D30): vocabularies and validation.

Pure Python. No SQL, no web, no Databricks imports. A control is an action the bank or the
product takes. One control covers many obligations (compliance matrix rows) and many risks
(WP29), and it names the evidence that shows it works: gate rules, assurance packs and
monitors are observed at runtime; detector slugs and document references are only recorded.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from typing import Any

from supervisor.core.errors import SupervisorError

CONTROL_TYPES: tuple[str, ...] = ("preventive", "detective", "corrective")
IMPLEMENTERS: tuple[str, ...] = ("product", "bank")
STATUSES: tuple[str, ...] = ("draft", "active", "retired")
SOURCES: tuple[str, ...] = ("manual", "import", "starter")
# matrix = an obligation id of the compliance matrix; risk = a risk id of the WP29 register.
COVER_KINDS: tuple[str, ...] = ("matrix", "risk")
# Observed at runtime: they can make a control working or failing (same facts as WP29).
RUNTIME_KINDS: tuple[str, ...] = ("rule", "pack", "monitor")
# Recorded and checked for existence, never counted as working (a fact about a design is not
# a fact about behaviour).
REF_KINDS: tuple[str, ...] = ("detector", "document")
EVIDENCE_KINDS: tuple[str, ...] = RUNTIME_KINDS + REF_KINDS
MAP_KINDS: tuple[str, ...] = COVER_KINDS + EVIDENCE_KINDS
ANY_AGENT = "*"

STATUS_WORKING = "working"
STATUS_FAILING = "failing"
STATUS_NO_DATA = "no_data"
EVIDENCE_STATUSES: tuple[str, ...] = (STATUS_WORKING, STATUS_FAILING, STATUS_NO_DATA)

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_TARGET = re.compile(r"^[A-Za-z0-9_.:@/#-]{1,128}$")
MAX_TITLE = 200
MAX_TEXT = 2000
MAX_OWNER = 128
MAX_MAPS = 200
MAX_SCOPE_AGENTS = 100


class ControlError(SupervisorError):
    """Bad control input or an operation the catalogue refuses (HTTP 400 at a route)."""


class ControlsOff(ControlError):
    """CONTROLS_ENABLED is off (HTTP 400)."""


def ensure_on(settings: Any) -> None:
    """ControlsOff (HTTP 400) unless CONTROLS_ENABLED is on."""
    if not settings.controls_enabled:
        raise ControlsOff(
            "The control catalogue is off (CONTROLS_ENABLED=1 turns it on); "
            "python -m supervisor.controls import config/controls fills it"
        )


def check_id(value: Any, what: str = "control id") -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise ControlError(f"{what} must be 1 to 64 characters from A-Z a-z 0-9 _ . : -")
    return value


def check_target(kind: str, target: Any) -> str:
    if kind not in MAP_KINDS:
        raise ControlError(f"map kind must be one of {', '.join(MAP_KINDS)}")
    if not isinstance(target, str) or not _TARGET.match(target):
        raise ControlError("map target must be 1 to 128 characters from A-Z a-z 0-9 _ . : @ / # -")
    return target


def _text(value: Any, what: str, limit: int, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise ControlError(f"{what} is required")
        return None
    if not isinstance(value, str):
        raise ControlError(f"{what} must be text")
    text = value.strip()
    if len(text) > limit:
        raise ControlError(f"{what} is longer than {limit} characters")
    if required and not text:
        raise ControlError(f"{what} is required")
    return text or None


def _choice(value: Any, allowed: tuple[str, ...], what: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ControlError(f"{what} must be one of {', '.join(allowed)}")
    return value


def parse_date(value: Any, what: str = "review_date") -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ControlError(f"{what} must be a date like 2027-01-31")


def scope_of(value: Any) -> list[str]:
    """The agents a control applies to: ``["*"]`` or a sorted list of agent ids."""
    if value is None or value == "":
        return [ANY_AGENT]
    if not isinstance(value, (list, tuple)) or not value:
        raise ControlError("agents must be a list of agent ids, or [*]")
    if len(value) > MAX_SCOPE_AGENTS:
        raise ControlError(f"agents has more than {MAX_SCOPE_AGENTS} entries")
    out: list[str] = []
    for a in value:
        if a == ANY_AGENT:
            out.append(ANY_AGENT)
        else:
            out.append(check_id(a, "agent id").lower())
    if ANY_AGENT in out:
        if len(out) > 1:
            raise ControlError("agents: [*] cannot be mixed with agent ids")
        return [ANY_AGENT]
    return sorted(set(out))


# Fields a person may change with an update.
EDITABLE: tuple[str, ...] = (
    "title",
    "objective",
    "control_type",
    "implemented_by",
    "owner",
    "status",
    "review_date",
    "agents",
)


def normalise(data: Mapping[str, Any], *, source: str = "manual") -> dict[str, Any]:
    """Validate a control record and return the row fields (no id, no timestamps).

    Raises ControlError with a message for the user. The rule that an active control needs a
    map (what it covers and what shows it works) is checked by the service, which sees the map.
    """
    status = _choice(data.get("status", "draft"), STATUSES, "status")
    out: dict[str, Any] = {
        "title": _text(data.get("title"), "title", MAX_TITLE, required=True),
        "objective": _text(data.get("objective"), "objective", MAX_TEXT, required=True),
        "control_type": _choice(data.get("control_type"), CONTROL_TYPES, "type"),
        "implemented_by": _choice(data.get("implemented_by"), IMPLEMENTERS, "implemented_by"),
        "owner": _text(data.get("owner"), "owner", MAX_OWNER, required=True),
        "status": status,
        "review_date": parse_date(data.get("review_date")),
        "scope_agents": scope_of(data.get("agents")),
        "source": _choice(source, SOURCES, "source"),
    }
    if status == "active" and out["review_date"] is None:
        raise ControlError("an active control needs a review_date")
    return out
