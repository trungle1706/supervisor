"""UX5 G1 (overview family): My overview, governance and supervisor overview, gate decisions,
workflows, inbox, search, health, My agents render bounded pages with the new text under
CONSOLE_UX5; the off path stays as it was."""

from __future__ import annotations

import html
import re

import pytest

from supervisor.console import i18n, i18n_ux5, i18n_ux5_g1, inbox_list, portfolio
from supervisor.console.ux5 import top
from tests.governance.conftest import mounted, on, restore_app  # noqa: F401  (fixtures)

from .conftest import Console
from .test_c4_portfolio import pf, pfall, seeded_pf  # noqa: F401  (fixtures)


def main(html: str) -> str:
    return html.split('id="main"', 1)[1].split("</main>", 1)[0]


def words(html: str) -> int:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", main(html), flags=re.S)
    return len(re.sub(r"<[^>]+>", " ", text).split())


@pytest.fixture
def ux(seeded_pf: Console, monkeypatch: pytest.MonkeyPatch) -> Console:  # noqa: F811
    for flag in ("console_ux5", "console_decisions_enabled", "console_decisions_v2"):
        monkeypatch.setattr(seeded_pf.ctx.settings, flag, True)
    return seeded_pf


# ------------------------------------------------------------------ My overview
def test_my_overview_is_bounded_and_follows_the_board(ux: Console) -> None:
    r = ux.get("/console/?scope=all")
    assert r.status_code == 200
    h = r.text
    assert 'data-version="5"' in h and "ux5_g1.css" in h
    assert words(h) < 1100
    for text in (
        "Assessment progress",
        "Autonomy level",
        "Risk class",
        "Risk assessments past their review date",
        "Progress by step",
    ):
        assert text in h
    # attention block comes first, then the strip, then the panels
    assert h.index("data-banner=") < h.index("data-totals") < h.index("data-assess")
    assert h.index("data-assess") < h.index("data-bars") < h.index("data-grid")
    # no stacked bar, no system cards, no candidate table, no 50-row table
    assert "stackbar" not in h and "data-cards" not in h and "cand-rows" not in h
    assert h.count("<tr data-system=") <= 5
    assert "Duties closed" not in h or "Duties closed, average" in h


def test_my_overview_past_review_rows_top5_oldest_first(ux: Console) -> None:
    h = ux.get("/console/?scope=all").text
    ids = re.findall(r'<tr data-system="([^"]+)"', h)
    assert 1 <= len(ids) <= 5
    block = portfolio.risk_block(ux.ctx, [{"system_id": s, "name": s, "status": "x"} for s in ids])
    dates = [r["oldest"] for r in block["past_rows"]]
    assert dates == sorted(dates)


def test_my_overview_vietnamese(ux: Console) -> None:
    h = ux.get("/console/?scope=all&lang=vi").text
    assert "Tiến độ đánh giá" in h and "Mức tự chủ" in h and "Phân loại rủi ro" in h


def test_my_overview_off_path_unchanged(
    seeded_pf: Console,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    h = seeded_pf.get("/console/?scope=all").text
    assert "data-cards" in h and "Assessment completion" in h and "ux5_g1" not in h
    assert "past_rows" not in str(portfolio.risk_block(seeded_pf.ctx, [])), (
        "the extra list exists only under UX5"
    )


def test_past_rows_only_under_ux5(seeded_pf: Console, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    rows = [{"system_id": s, "name": s, "status": "x"} for s in seeded_pf.ids.values()]  # type: ignore[attr-defined]
    assert "past_rows" not in portfolio.risk_block(seeded_pf.ctx, rows)
    monkeypatch.setattr(seeded_pf.ctx.settings, "console_ux5", True)
    got = portfolio.risk_block(seeded_pf.ctx, rows)
    assert [r["oldest"] for r in got["past_rows"]] == ["2026-01-01", "2026-02-01"]


# ------------------------------------------------------------------ governance, supervisor
def test_governance_overview_folds_the_zero_rows(ux: Console) -> None:
    r = ux.get("/console/governance?scope=all")
    assert r.status_code == 200
    h = r.text
    assert words(h) < 400
    assert h.count("<tr>") < 60
    assert "Control readiness by system" in h and "Advisory, not legal advice" in h
    assert "Systems by autonomy level" not in h and "Not measured" in h or "%" in h


def test_supervisor_overview_folds_identical_rows(ux: Console) -> None:
    r = ux.get("/console/supervisor?scope=all")
    assert r.status_code == 200
    h = r.text
    assert words(h) < 400
    assert "Agents with stops or gaps" in h and 'data-chain="unverified"' in h
    assert "DETECTORS_ENABLED" not in h and "shown" in h


# ------------------------------------------------------------------ the other pages
@pytest.mark.parametrize(
    ("url", "text"),
    [
        ("/console/workflows", "Scheduled jobs"),
        ("/console/health", "Developer checks"),
        ("/console/inbox", "Notices about cases: new, sign-off needed, closed."),
        ("/console/decisions", "All gate decisions."),
        ("/console/search?q=payments", "payments"),
        ("/console/search?q=zzzzzz", 'No results for "zzzzzz"'),
    ],
)
def test_other_pages_render_with_new_text(ux: Console, url: str, text: str) -> None:
    r = ux.get(url)
    assert r.status_code == 200
    assert text in html.unescape(r.text)
    assert "ux5_g1.css" in r.text or "search" in url


def test_health_hides_env_flags_and_paths_from_non_admin(ux: Console) -> None:
    h = ux.get("/console/health", user="reviewer.an").text
    assert "CONSOLE_ONBOARD_ENABLED" not in h and "JUDGE_T1_MODEL" not in h
    assert "data_dir=" not in h and "Mock judges in use." in h


def test_workflows_plain_names_and_intervals(ux: Console) -> None:
    h = ux.get("/console/workflows").text
    assert "<code>case_intake</code>" not in h and "0 h 0 m" not in h
    assert "Scheduled jobs" in h and "Approvals and sinks" in h


def test_decisions_filters_collapse(ux: Console) -> None:
    h = ux.get("/console/decisions").text
    assert "More filters" in h and 'name="action"' not in h
    assert "u5-fold-row" in h  # a day header row


def test_inbox_rows_are_one_line(ux: Console) -> None:
    n = inbox_list.summarize(
        {
            "subject": "Governance event: gate_stop (high)",
            "body": "event: gate_stop\nseverity: high\nagent: payment-ops-copilot\nsystem: sys_1",
            "channel": "owner:payops-lead@example.invalid",
        }
    )
    assert n["kind"] == "gate stop" and n["severity"] == "high"
    assert n["agent"] == "payment-ops-copilot" and n["who"] == "payops-lead"
    other = inbox_list.summarize({"subject": "Hello", "body": "x", "channel": ""})
    assert other["kind"] == "" and other["who"] == ""
    assert top([1, 2, 3], 2) == [1, 2]


# ------------------------------------------------------------------ text
def test_new_keys_exist_in_both_languages_and_overrides_do_not_invent() -> None:
    base = i18n.table()
    for key, (en, vi) in i18n_ux5_g1.NEW.items():
        assert key in base and en.strip() and vi.strip(), key
    for key, (en, vi) in i18n_ux5_g1.UX5.items():
        assert key in base and key not in i18n_ux5_g1.NEW, key
        assert en.strip() and vi.strip(), key
    assert "supervisor.console.i18n_ux5_g1" in i18n_ux5.MODULES


def test_overrides_apply_en_and_vi() -> None:
    en = i18n.translator("en", ux5=True)
    vi = i18n.translator("vi", ux5=True)
    assert en("du_ov_line", avg=25, n=3, open=1) == "25%"
    assert en("ov4_why_overdue_high", arg="X") == "Overdue high-risk task: X."
    assert vi("ov4_assess") == "Tiến độ đánh giá"
    assert i18n.translator("en")("ov4_assess") == "Assessment completion"
