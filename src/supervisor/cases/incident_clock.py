"""Incident report clock (WP19): preliminary and formal report deadlines.

Source: Decree 142/2026/ND-CP Art. 19(3) and 19(4), as recorded in
``regulations/vn/decree-142-2026.yaml`` (VN-DEC142-2026-A19.03-01, -A19.04-01) and
``docs/regulations.md``. Circular 53/2026/TT-NHNN refers back to this rule.

* Preliminary report (form AI01a) within **72 hours** of confirming the incident when it is
  urgent, else within **5 working days** of confirmation (Art. 19(3)(a), (b)).
* Formal report on the remediation result within **15 days from the date the preliminary
  report was submitted** (Art. 19(4)).

There is NO 24-hour clock in the signed Circular 53. ``cases.report_due_at`` and
``SbvClocks`` (detected + 24 h / 5 days) are DEPRECATED: they stay for old readers only.

ASSUMPTIONS (the bank must confirm with counsel):

* "Confirmation time" (Art. 19(3)(c)) is taken as the detection time of the case
  (earliest related verdict, else the time the case opened).
* Urgent means severity critical or high (``urgency_for``). The Decree defines urgent by
  incident type (loss of life, essential services, uncontrollable harm), which a severity
  cannot decide; a reviewer should re-class.
* "15 days" are calendar days (the text says ``15 ngay``, not working days).
* Working days are Monday to Friday minus the dates in the holiday file, counted in
  Vietnam local time (UTC+7, no DST).

Pure functions: no I/O except ``load_holidays``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import yaml

from supervisor.core.errors import SupervisorError

log = logging.getLogger("supervisor.cases.incident_clock")

VN_TZ = timezone(timedelta(hours=7), "ICT")  # Vietnam has no DST: a fixed offset is exact
URGENT_WINDOW = timedelta(hours=72)
STANDARD_WORKING_DAYS = 5
FORMAL_WINDOW = timedelta(days=15)
Urgency = Literal["urgent", "standard"]
URGENT_SEVERITIES = ("critical", "high")


def load_holidays(path: Path | str | None) -> frozenset[date]:
    """Holiday dates from a yaml file ``holidays: [YYYY-MM-DD, ...]``.

    A missing file gives an empty set and a warning. A file that cannot be parsed gives
    ``SupervisorError``.
    """
    if not path:
        return frozenset()
    p = Path(path)
    if not p.is_file():
        log.warning("holiday file %s not found: only weekends are non-working days", p)
        return frozenset()
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        items = (data or {}).get("holidays") or []
        if not isinstance(items, list):
            raise ValueError("'holidays' must be a list")
        out: set[date] = set()
        for item in items:
            if isinstance(item, datetime):
                raise ValueError(f"{item!r} is not a plain date")
            out.add(item if isinstance(item, date) else date.fromisoformat(str(item)))
    except (yaml.YAMLError, ValueError, AttributeError, OSError) as exc:
        raise SupervisorError(f"holiday file {p.name} is not valid: {exc}") from exc
    return frozenset(out)


def is_working_day(d: date, holidays: frozenset[date] | set[date] = frozenset()) -> bool:
    """Monday to Friday and not a holiday."""
    return d.weekday() < 5 and d not in holidays


def add_working_days(
    start: datetime,
    n: int,
    holidays: frozenset[date] | set[date] = frozenset(),
    tz: timezone = VN_TZ,
) -> datetime:
    """``start`` plus ``n`` working days, in Vietnam local time, same local time of day.

    The detection day is day 0 (even when it is a working day). Day k is the k-th working
    day after it. Friday 10:00 + 5 = next Friday 10:00. Saturday 10:00 + 5 counts from
    Monday (Monday is day 1): next Friday 10:00. Returned in UTC.
    """
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    if n < 0:
        raise ValueError("n must be >= 0")
    local = start.astimezone(tz)
    day = local.date()
    left = n
    while left > 0:
        day += timedelta(days=1)
        if is_working_day(day, holidays):
            left -= 1
    return local.replace(year=day.year, month=day.month, day=day.day).astimezone(UTC)


def urgency_for(severity: str) -> Urgency:
    """ASSUMPTION (bank to confirm): critical and high are urgent, the rest standard."""
    return "urgent" if severity in URGENT_SEVERITIES else "standard"


@dataclass(frozen=True)
class IncidentClock:
    detected: datetime
    urgency: Urgency
    prelim_due: datetime
    formal_due: datetime


def formal_due_from(base: datetime) -> datetime:
    """Formal report due: 15 calendar days after ``base`` (Art. 19(4))."""
    return base + FORMAL_WINDOW


def compute_clock(
    detected_at: datetime,
    urgency: Urgency,
    holidays: frozenset[date] | set[date] = frozenset(),
    *,
    prelim_sent_at: datetime | None = None,
) -> IncidentClock:
    """Deadlines for an incident.

    ``formal_due`` counts from the actual preliminary submission time when given (Art.
    19(4): "from the date of submitting the preliminary report"), else from the
    preliminary due date (the latest legal submission time).
    """
    if urgency == "urgent":
        prelim_due = detected_at + URGENT_WINDOW
    else:
        prelim_due = add_working_days(detected_at, STANDARD_WORKING_DAYS, holidays)
    formal_due = formal_due_from(prelim_sent_at or prelim_due)
    return IncidentClock(detected_at, urgency, prelim_due, formal_due)


__all__ = [
    "IncidentClock",
    "VN_TZ",
    "add_working_days",
    "compute_clock",
    "formal_due_from",
    "is_working_day",
    "load_holidays",
    "urgency_for",
]
