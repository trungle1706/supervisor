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


def _render(src: str, ux5: bool, **ctx: object) -> str:
    from supervisor.console import routes

    t = i18n.translator("en", ux5=ux5)
    return routes._env.from_string(src).render(t=t, ux5=ux5, lang="en", **ctx)  # noqa: SLF001


def test_na_macro_puts_the_reason_in_a_tooltip_under_ux5() -> None:
    src = "{% import '_v3.html' as v3 with context %}{{ v3.na('nv3_na_risks_off') }}"
    reason_on = i18n.translator("en", ux5=True)("nv3_na_risks_off")
    reason = i18n.translator("en")("nv3_na_risks_off")
    on, off = _render(src, True), _render(src, False)
    assert f'title="{reason_on}"' in on and f"</span> {reason_on}</p>" not in on
    assert f"</span> {reason}</p>" in off


def test_compliance_note_is_one_chip_under_ux5() -> None:
    on = _render("{% include '_compliance_note.html' %}", True)
    off = _render("{% include '_compliance_note.html' %}", False)
    assert "u5-chip" in on and "data-compliance-advisory" not in on
    assert "data-compliance-advisory" in off


def test_table_pager_uses_the_u5_look_under_ux5() -> None:
    from types import SimpleNamespace

    page = SimpleNamespace(page=2, pages=3, prev=1, next=3, first=26, last=50, total=70)
    src = "{% import '_c_table.html' as tb with context %}{{ tb.pager(page, '/x', '/x/rows', '') }}"
    on, off = _render(src, True, page=page), _render(src, False, page=page)
    assert "u5-pager" in on and 'rel="next"' in on and "u5-pager" not in off
    assert 'class="pager"' in off


def test_decision_panel_text_under_ux5() -> None:
    t = i18n.translator("en", ux5=True)
    assert t("you_are_a", role="admin") == "Your role: admin."
    assert t("signoffs_n", n=0) == "0 of 2 so far."
    assert i18n.translator("en", ux5=True)("nv3_activity") == "Gate decisions"
    assert i18n.translator("en")("nv3_activity") == "Activity"
