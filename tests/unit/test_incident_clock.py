"""WP19: incident clock math (Decree 142 Art. 19): 72 h urgent, 5 working days, +15 days."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from supervisor.cases.incident_clock import (
    VN_TZ,
    add_working_days,
    compute_clock,
    is_working_day,
    load_holidays,
    urgency_for,
)
from supervisor.config import REPO_ROOT
from supervisor.core.errors import SupervisorError

HOLIDAYS = load_holidays(REPO_ROOT / "config" / "vn_holidays.yaml")


def ict(y: int, m: int, d: int, h: int = 10) -> datetime:
    return datetime(y, m, d, h, 0, tzinfo=VN_TZ).astimezone(UTC)


def test_urgent_is_72_hours() -> None:
    t = ict(2026, 10, 16)
    c = compute_clock(t, "urgent", HOLIDAYS)
    assert c.prelim_due == t + timedelta(hours=72)
    assert c.formal_due == c.prelim_due + timedelta(days=15)


def test_standard_five_working_days_across_a_weekend() -> None:
    fri = ict(2026, 10, 16)  # Friday
    assert fri.astimezone(VN_TZ).weekday() == 4
    assert add_working_days(fri, 5, frozenset()) == ict(2026, 10, 23)
    wed = ict(2026, 10, 14)
    assert add_working_days(wed, 5, frozenset()) == ict(2026, 10, 21)


def test_standard_across_tet_holiday() -> None:
    fri = ict(2026, 2, 13)  # 16-20 Feb are holidays in the file
    assert add_working_days(fri, 5, HOLIDAYS) == ict(2026, 2, 27)
    assert add_working_days(fri, 5, frozenset()) == ict(2026, 2, 20)


def test_detected_on_saturday_counts_from_monday() -> None:
    sat = ict(2026, 10, 17)
    assert sat.astimezone(VN_TZ).weekday() == 5
    assert add_working_days(sat, 5, frozenset()) == ict(2026, 10, 23)
    assert add_working_days(sat, 1, frozenset()) == ict(2026, 10, 19)


def test_same_local_time_of_day_and_utc_result() -> None:
    t = ict(2026, 10, 16, 23)  # 23:00 ICT = 16:00 UTC
    out = add_working_days(t, 1, frozenset())
    assert out.astimezone(VN_TZ).hour == 23 and out.tzinfo == UTC


def test_formal_counts_from_sent_time_when_known() -> None:
    t = ict(2026, 10, 16)
    sent = t + timedelta(hours=10)
    c = compute_clock(t, "urgent", HOLIDAYS, prelim_sent_at=sent)
    assert c.formal_due == sent + timedelta(days=15)


def test_urgency_for() -> None:
    assert [urgency_for(s) for s in ("critical", "high", "medium", "low")] == [
        "urgent",
        "urgent",
        "standard",
        "standard",
    ]


def test_is_working_day() -> None:
    assert not is_working_day(date(2026, 10, 17), frozenset())
    assert not is_working_day(date(2026, 9, 2), HOLIDAYS)
    assert is_working_day(date(2026, 10, 15), HOLIDAYS)


def test_load_holidays_missing_and_bad(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert load_holidays(tmp_path / "none.yaml") == frozenset()
    assert "not found" in caplog.text
    bad = tmp_path / "bad.yaml"
    bad.write_text("holidays: not-a-list\n", encoding="utf-8")
    with pytest.raises(SupervisorError):
        load_holidays(bad)
    bad.write_text("holidays: [2026-13-45x]\n", encoding="utf-8")
    with pytest.raises(SupervisorError):
        load_holidays(bad)
    assert date(2026, 2, 17) in HOLIDAYS
