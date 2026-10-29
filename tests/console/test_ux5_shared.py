"""UX5-S: shared parts and consistency polish."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

from supervisor.console import i18n, overview_v3, readmodels

TEMPLATES = Path(i18n.__file__).parent / "templates"


def test_nearest_clock_uses_the_incident_deadline_in_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The overview clock is the preliminary/formal deadline, not the 24 h report_due_at."""
    now = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.UTC)
    h = dt.timedelta(hours=1)
    near = {
        "severity": "high",
        "status": "open",
        "report_due_at": now + 30 * h,  # old 24 h value: must be ignored
        "incident_detected_at": now - 2 * h,
        "prelim_report_due_at": now + 10 * h,
        "formal_report_due_at": now + 100 * h,
    }
    sent = {**near, "prelim_report_sent_at": now, "formal_report_due_at": now + 50 * h}
    monkeypatch.setattr(readmodels, "open_cases", lambda ctx: [sent, near])
    clock = overview_v3._nearest_clock(None, now)  # noqa: SLF001
    assert clock is not None and clock["secs"] == 10 * 3600 and not clock["overdue"]
    monkeypatch.setattr(readmodels, "open_cases", lambda ctx: [])
    assert overview_v3._nearest_clock(None, now) is None  # noqa: SLF001


def test_templates_use_only_t_for_text() -> None:
    """One way to add UI text: no `tx(` and no `x5` dict in any template."""
    for path in TEMPLATES.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\btx\(|\bx5\.|\bx5\[", text), path.name


def test_ux5_new_keys_are_in_the_base_table_with_both_languages() -> None:
    from supervisor.console import i18n_ux5_g5, i18n_ux5_g6

    table = i18n.table()
    for key, pair in {**i18n_ux5_g5.NEW, **i18n_ux5_g6.ALL}.items():
        assert table[key] == pair and all(pair), key
