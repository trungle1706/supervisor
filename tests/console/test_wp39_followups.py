"""WP39 follow-ups after the review (F13 to F17): export without JavaScript, no harness run in a
request, bounded not-evaluated subquery, Blocked vs Block, one window line."""

from __future__ import annotations

import json
import re
from datetime import UTC, timedelta
from typing import Any

import pytest

from supervisor.console import analytics, analytics_v2
from supervisor.jobs import decision_rollup
from supervisor.monitors.common import MonitorContext

from .conftest import Console
from .wp39_helpers import add_decision


def _mctx(c: Console) -> MonitorContext:
    return MonitorContext.from_adapters(c.runtime.adapters, c.runtime.chain)


def _plain_post(
    c: Console, data: dict[str, str], user: str = "auditor.dung", **headers: str
) -> Any:
    """A browser form post without JavaScript: no HX-Request header."""
    h = {"X-Dev-User": user, **headers}
    return c.client.post("/console/decisions/export", data=data, headers=h)


# --------------------------------------------------------------------------- F13


def test_the_export_form_posts_without_javascript(v2console: Console) -> None:
    page = v2console.get("/console/decisions", user="auditor.dung").text
    assert re.search(r'<form[^>]*action="/console/decisions/export"[^>]*method="post"', page)
    add_decision(v2console, consumer="app-nojs")
    r = _plain_post(v2console, {"consumer": "app-nojs"}, Origin="http://testserver")
    assert r.status_code == 200 and "<html" in r.text  # a whole page, not a partial
    m = re.search(r'href="(/console/decisions/exports/[^"]+)"', r.text)
    assert m and "exp=" in m.group(1) and "t=" in m.group(1)
    assert "/console/decisions?consumer=app-nojs" in r.text  # the way back keeps the filters
    got = v2console.get(m.group(1).replace("&amp;", "&"), user="auditor.dung")
    assert got.status_code == 200 and "text/csv" in got.headers["content-type"]
    assert v2console.get(m.group(1).replace("&amp;", "&"), user="auditor.dung").status_code == 400
    acts = v2console.ctx.tables.query("console_action", {"permission": "decisions.export"})
    assert sorted(a["outcome"] for a in acts) == ["attempted", "ok"]


def test_the_plain_post_keeps_the_permission_and_the_origin_check(v2console: Console) -> None:
    ok = {"Origin": "http://testserver"}
    assert _plain_post(v2console, {}, user="reviewer.an", **ok).status_code == 403
    assert _plain_post(v2console, {}, user="viewer.hoa", **ok).status_code == 403
    assert _plain_post(v2console, {}).status_code == 400  # no Origin, no Referer
    assert _plain_post(v2console, {}, Origin="http://evil.example").status_code == 400
    assert _plain_post(v2console, {}, Referer="http://evil.example/x").status_code == 400
    assert (
        _plain_post(v2console, {}, Referer="http://testserver/console/decisions").status_code == 200
    )
    assert _plain_post(v2console, {"status": "bogus"}, **ok).status_code == 400


# --------------------------------------------------------------------------- F14


def _write_report(c: Console) -> None:
    from tests._cache import cached_detector_report  # WP-T1: one harness run per process

    path = analytics_v2.report_path(c.ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cached_detector_report(commit="-", date="-")), encoding="utf-8")


def _lat_rows(c: Console) -> None:
    add_decision(c, status="report", codes=("pii.phone",))
    decision_rollup.run(_mctx(c), c.ctx.settings)


def test_detectors_tab_never_runs_the_harness_in_a_request(
    v2console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.detectors import harness

    def boom(*a: Any, **k: Any) -> None:
        raise AssertionError("the harness ran inside a request")

    monkeypatch.setattr(harness, "run", boom)
    _lat_rows(v2console)
    page = v2console.get("/console/analytics?tab=detectors").text
    assert 'id="det-not-run"' in page and "not run" in page
    assert "adversarial recall:" not in page and 'data-detector="dlp_vn"' in page


def test_detectors_tab_reads_the_recorded_report(v2console: Console) -> None:
    _lat_rows(v2console)
    _write_report(v2console)
    page = v2console.get("/console/analytics?tab=detectors").text
    assert "GO (indicative)" in page and 'id="det-not-run"' not in page


def test_a_bad_report_file_means_not_run(v2console: Console) -> None:
    _lat_rows(v2console)
    path = analytics_v2.report_path(v2console.ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    for text in ("{broken", "[]", '{"detectors": {"x": 1}}'):
        path.write_text(text, encoding="utf-8")
        page = v2console.get("/console/analytics?tab=detectors")
        assert page.status_code == 200 and 'id="det-not-run"' in page.text


# --------------------------------------------------------------------------- F15


def test_not_evaluated_subquery_has_the_date_bounds() -> None:
    sql = decision_rollup.not_evaluated_sql("e", "`f`")
    sub = sql[sql.index("SELECT event_id") :]
    assert ":r_from" in sub and ":r_to" in sub


def test_rollup_reads_no_old_finding_rows_into_a_recent_window(v2console: Console) -> None:
    old = add_decision(v2console, age_s=10 * 86400, not_executed=("timed_out",), agent="a-old")
    new = add_decision(v2console, age_s=60, not_executed=("timed_out",), agent="a-new")
    assert old != new
    ctx = _mctx(v2console)
    today = v2console.ctx.clock.now().astimezone(UTC).date()
    decision_rollup.rollup(ctx, today - timedelta(days=1), today)  # a recent window only
    rows = v2console.ctx.state.query("decision_daily", {"dimension": "agent"})
    assert {r["dim_key"] for r in rows} >= {"a-new"} and "a-old" not in {r["dim_key"] for r in rows}
    assert sum(r["not_evaluated"] for r in rows if r["dim_key"] == "a-new") == 1
    decision_rollup.rollup(ctx, today - timedelta(days=11), today)  # the window with the old row
    rows = v2console.ctx.state.query("decision_daily", {"dimension": "agent", "dim_key": "a-old"})
    assert sum(r["not_evaluated"] for r in rows) == 1 and sum(r["requests"] for r in rows) == 1


def test_a_finding_row_outside_the_window_does_not_mark_a_recent_decision(
    v2console: Console,
) -> None:
    """The bound is part of the statement: a detector row stamped before the window does not
    count for a decision inside it (rows of one decision share its time, so this only happens
    with a bad row)."""
    eid = add_decision(v2console, age_s=60, agent="a-edge")
    old = add_decision(v2console, age_s=20 * 86400, not_executed=("timed_out",), agent="a-edge2")
    row = v2console.ctx.tables.query("finding", {"event_id": old})[0]
    v2console.ctx.tables.append(
        "finding",
        [{**row, "finding_id": "z" * 32, "event_id": eid}],  # old time, recent decision
    )
    decision_rollup.rollup(_mctx(v2console), v2console.ctx.clock.now().date() - timedelta(days=1),
                           v2console.ctx.clock.now().date())  # fmt: skip
    rows = v2console.ctx.state.query("decision_daily", {"dimension": "agent", "dim_key": "a-edge"})
    assert sum(r["requests"] for r in rows) == 1 and sum(r["not_evaluated"] for r in rows) == 0


# --------------------------------------------------------------------------- F16


def _v1_stops(c: Console) -> tuple[int, int]:
    t = analytics.gate_data(c.ctx, None, "")["gate_total"]
    return t["blocked"], t["paused"]


def _v2_stops(c: Console) -> tuple[int, int]:
    rows = c.ctx.state.query("decision_daily", {"dimension": "total"})
    return sum(r["blocks"] for r in rows), sum(r["pauses"] for r in rows)


def test_blocked_and_block_agree_on_the_demo_store(v2console: Console) -> None:
    for _ in range(3):
        add_decision(v2console, status="block", agent="payments")
    for _ in range(2):
        add_decision(v2console, status="pause", agent="payments")
    decision_rollup.run(_mctx(v2console), v2console.ctx.settings)
    assert _v1_stops(v2console) == _v2_stops(v2console)
    assert _v1_stops(v2console)[0] >= 3  # the three added blocks plus the demo ones


def test_a_call_that_matched_block_and_pause_is_counted_by_the_label(v2console: Console) -> None:
    eid = add_decision(v2console, status="block", agent="payments")
    v2console.ctx.tables.append(
        "verdict",
        [
            {
                "verdict_id": "p" * 32,
                "ts": v2console.ctx.clock.now(),
                "trace_id": "t",
                "event_id": eid,
                "agent_id": "payments",
                "tier": 0,
                "checker_id": "gate.tier0a",
                "is_mock": False,
                "advisory": False,
                "label": "matched",
                "action": "pause",
                "rule_id": "PAY-P",
                "rationale_masked": "x",
            }
        ],
    )
    b1, p1 = _v1_stops(v2console)
    decision_rollup.run(_mctx(v2console), v2console.ctx.settings)
    b2, p2 = _v2_stops(v2console)
    # the stopping rule says pause (pause first), the verdict status says block (block first)
    assert (b2 - b1, p1 - p2) == (1, 1) and b1 + p1 == b2 + p2
    page = v2console.get("/console/analytics?tab=gate").text
    assert 'id="dd-series-note"' in page and "block before pause" in page
    # UX5-BUG: the rollup tables say they are a different source from the tiles
    assert 'id="dd-rollup-note"' in page and "daily rollup" in page


# --------------------------------------------------------------------------- F17


def test_detectors_tab_shows_the_window_once(v2console: Console) -> None:
    _lat_rows(v2console)
    page = v2console.get("/console/analytics?tab=detectors").text
    assert len(re.findall(r"\d{4}-\d{2}-\d{2} \.\. \d{4}-\d{2}-\d{2}", page)) == 1
