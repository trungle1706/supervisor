"""WP-UX2: Analytics page - tabs Gate / Tools / Oversight metrics / Latency, one toolbar."""

from __future__ import annotations

import datetime as dt
import re

import pytest

from supervisor.console import analytics

from .conftest import Console

HX = {"HX-Request": "true"}
TABS = ("gate", "tools", "metrics", "latency")


def _on(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_tools_enabled", True)
    monkeypatch.setattr(console.ctx.settings, "tool_analytics_enabled", True)


def _tabs(html: str) -> list[str]:
    return re.findall(r'role="tab" data-tab="([a-z]+)"', html)


def test_tabs_follow_the_tools_flag(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    r = console.get("/console/analytics")
    assert r.status_code == 200 and _tabs(r.text) == ["gate", "metrics", "latency"]
    off = console.get("/console/analytics?tab=tools", headers=HX)
    assert off.status_code == 400 and "CONSOLE_TOOLS_ENABLED" in off.text
    assert console.get("/console/analytics/tab/tools", headers=HX).status_code == 400
    _on(console, monkeypatch)
    r = console.get("/console/analytics")
    assert _tabs(r.text) == list(TABS)


def test_each_tab_renders_and_the_no_js_page_equals_the_partial(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    _on(console, monkeypatch)
    for tab in TABS:
        part = console.get(f"/console/analytics/tab/{tab}", headers=HX)
        assert part.status_code == 200 and "<html" not in part.text, tab
        full = console.get(f"/console/analytics?tab={tab}")
        assert full.status_code == 200
        body = full.text.split('role="tabpanel">', 1)[1].split("</main>", 1)[0]
        assert part.text.strip() in body, tab
        assert f'data-tab="{tab}" class="on"' in full.text
        assert console.get(f"/console/analytics?tab={tab}&lang=vi").status_code == 200


def test_gate_tab_counts_the_demo_decisions(console: Console) -> None:
    r = console.get("/console/analytics?tab=gate&days=90")
    assert r.status_code == 200 and 'id="gate-totals"' in r.text
    n = int(
        re.search(
            r'data-num="checked">\s*<h3>[^<]*</h3>\s*<div class="bignum">(\d+)', r.text
        ).group(1)
    )  # type: ignore[union-attr]
    events = console.ctx.tables.query("agent_event", {"event_type": "gate_decision"})
    assert 0 < n <= len(events)
    blocked = int(
        re.search(
            r'data-num="blocked">\s*<h3>[^<]*</h3>\s*<div class="bignum">(\d+)', r.text
        ).group(1)
    )  # type: ignore[union-attr]
    assert blocked >= 1  # the demo has gate blocks
    assert 'id="gate-table"' in r.text and "/console/agents/payments?lang=en" in r.text
    only = console.get("/console/analytics/tab/gate?agent=payments&days=90", headers=HX)
    assert 'data-agent="payments"' in only.text and 'data-agent="credit_prequal"' not in only.text


def test_toolbar_range_and_agent_apply_to_the_metrics_tab(console: Console) -> None:
    ctx = console.ctx
    today = ctx.clock.now().date()
    for agent, days_ago in (("aa_old", 40), ("aa_new", 1)):
        ctx.state.insert(
            "oversight_metric",
            {
                "metric_date": today - dt.timedelta(days=days_ago),
                "agent_id": agent,
                "computed_at": ctx.clock.now(),
            },
        )
    allrows = console.get("/console/analytics/tab/metrics", headers=HX).text
    assert 'data-agent="aa_old"' in allrows and 'data-agent="aa_new"' in allrows  # default: all
    week = console.get("/console/analytics/tab/metrics?days=7", headers=HX).text
    assert 'data-agent="aa_new"' in week and 'data-agent="aa_old"' not in week
    one = console.get("/console/analytics/tab/metrics?agent_id=aa_new", headers=HX).text
    assert 'data-agent="aa_old"' not in one  # legacy agent_id still accepted


def test_toolbar_markup_and_selection(console: Console) -> None:
    r = console.get("/console/analytics?tab=gate&days=30&agent=payments")
    assert 'name="days"' in r.text and 'name="agent"' in r.text and 'name="tab"' in r.text
    assert re.search(r'<option value="30" selected>', r.text)
    assert re.search(r'<option value="payments" selected>', r.text)
    assert "agent=payments" in r.text.split('role="tablist"', 1)[1].split("</div>", 1)[0]
    assert "<noscript>" in r.text  # works without JS: a submit button


def test_bad_toolbar_input_is_400(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    _on(console, monkeypatch)
    for q in ("days=abc", "days=0", "days=999", "agent=bad%24id", "agent=ghost"):
        for url in (f"/console/analytics?{q}", f"/console/analytics/tab/gate?{q}"):
            r = console.get(url, headers=HX)
            assert r.status_code == 400, (url, r.status_code)
    for url in (
        "/console/analytics?tab=nope",
        "/console/analytics/tab/nope",
        "/console/analytics?tab=tools&sort=nope",
        "/console/analytics/tab/tools?sort=nope",
    ):
        assert console.get(url, headers=HX).status_code == 400, url


def test_latency_tab_has_the_gateway_counters(console: Console) -> None:
    r = console.get("/console/analytics/tab/latency", headers=HX)
    assert r.status_code == 200 and 'id="latency-table"' in r.text


def test_metrics_tab_keeps_chain_status_and_verify(console: Console) -> None:
    r = console.get("/console/analytics?tab=metrics")
    assert "Chain status" in r.text and "/console/chain/verify" in r.text
    assert 'id="monitor-status"' in r.text


def test_tools_tab_is_the_old_tools_page(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.analytics.test_console_api import _seed

    _on(console, monkeypatch)
    _seed(console)
    r = console.get("/console/analytics?tab=tools&sort=calls&dir=desc&days=30")
    assert r.status_code == 200 and 'id="tools-totals"' in r.text and 'data-tools="1"' in r.text
    assert 'aria-sort="descending"' in r.text and 'data-tool="add_payee"' in r.text
    assert "/console/analytics?tab=tools" in r.text  # sort links stay on this page
    calls = int(
        re.search(r'data-num="calls">\s*<h3>[^<]*</h3>\s*<div class="bignum">(\d+)', r.text).group(
            1
        )
    )  # type: ignore[union-attr]
    assert calls > 0
    agent = console.get("/console/analytics/tab/tools?agent=payments&days=30", headers=HX).text
    assert 'data-agent="payments"' in agent and 'data-agent="credit_prequal"' not in agent


def test_helpers() -> None:
    assert analytics.RANGES == (7, 30, 90)


def test_range_options_include_a_custom_value(console: Console) -> None:
    opts = analytics.toolbar_options(console.ctx, 45)["range_opts"]
    assert opts == [7, 30, 45, 90]


def test_no_inline_script_or_external_url(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    _on(console, monkeypatch)
    for tab in TABS:
        html = console.get(f"/console/analytics?tab={tab}").text
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), tab
        assert not re.search(r"\son[a-z]+=\"", html), tab
        assert not re.search(r"https?://", html, re.I), tab


def test_toolbar_always_names_the_effective_window(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review fix: a blank range keeps each tab's own window, and the toolbar says which."""
    _on(console, monkeypatch)
    kinds = {"gate": "days", "tools": "days", "metrics": "stored", "latency": "live"}
    for tab, kind in kinds.items():
        r = console.get(f"/console/analytics?tab={tab}")
        m = re.search(r'id="an-window" data-window="(\w+)">([^<]+)<', r.text)
        assert m and m.group(1) == kind, (tab, m)
        assert "Window:" in m.group(2), tab
        if kind == "days":
            assert re.search(r"\d{4}-\d\d-\d\d \.\. \d{4}-\d\d-\d\d", m.group(2))
            assert "(default)" in m.group(2), tab
    r = console.get("/console/analytics?tab=metrics&days=30")
    m = re.search(r'id="an-window" data-window="(\w+)">([^<]+)<', r.text)
    assert m and m.group(1) == "days" and "30 days" in m.group(2) and "default" not in m.group(2)
    vi = console.get("/console/analytics?tab=gate&lang=vi").text
    assert "Khoảng:" in vi and "ngày, UTC" in vi


def test_tab_click_swaps_main_so_the_toolbar_follows_the_tab(console: Console) -> None:
    """Review fix: the toolbar form holds the tab in a hidden field; a tab click that swapped
    only #tab-body left it on the first tab, so a range change jumped back. Tabs now swap
    #main from the full page."""
    r = console.get("/console/analytics")
    tabs = re.findall(r'<a role="tab"[^>]*>', r.text)
    assert tabs and all('hx-select="#main"' in a and 'hx-target="#main"' in a for a in tabs)
    assert all('hx-get="/console/analytics?tab=' in a for a in tabs)
    assert 'aria-labelledby="tab-body-tab-gate"' in r.text and 'id="tab-body-tab-gate"' in r.text
