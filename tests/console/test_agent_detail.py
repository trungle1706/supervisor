"""WP-UX2: agent detail page, eight tabs (htmx partial + no-JS ?tab=), flag rules, controls."""

from __future__ import annotations

import re

import pytest

from supervisor.console import agent_detail

from .conftest import Console

FLAGS = (
    "console_tools_enabled",
    "tool_analytics_enabled",
    "inventory_enabled",
    "console_assurance_enabled",
    "console_compliance_enabled",
)
DEMO_AGENTS = ("payments", "credit_prequal", "customer_service")
HX = {"HX-Request": "true"}


def _all_on(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in FLAGS:
        monkeypatch.setattr(console.ctx.settings, flag, True)


def _tab_hrefs(html: str) -> list[str]:
    return re.findall(r'role="tab" data-tab="([a-z]+)"', html)


def _body(html: str) -> str:
    """The inside of #tab-body of a full page."""
    return html.split('id="tab-body" class="tabpanel" role="tabpanel">', 1)[1].split(
        "</main>", 1
    )[0]


def test_every_tab_renders_for_every_demo_agent(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    _all_on(console, monkeypatch)
    for agent in DEMO_AGENTS:
        page = console.get(f"/console/agents/{agent}")
        assert page.status_code == 200, (agent, page.text[:300])
        assert _tab_hrefs(page.text) == list(agent_detail.TABS)
        assert 'aria-current="page"' in page.text.split('<aside class="side"', 1)[1]
        for tab in agent_detail.TABS:
            part = console.get(f"/console/agents/{agent}/tab/{tab}", headers=HX)
            assert part.status_code == 200, (agent, tab, part.text[:300])
            assert "<html" not in part.text and part.text.strip()
            full = console.get(f"/console/agents/{agent}?tab={tab}")
            assert full.status_code == 200, (agent, tab)
            # the no-JS page holds exactly the htmx partial body
            assert part.text.strip() in _body(full.text), (agent, tab)
            assert f'data-tab="{tab}" class="on"' in full.text
        for lang in ("en", "vi"):
            assert console.get(f"/console/agents/{agent}?lang={lang}").status_code == 200


def test_overview_has_card_controls_gate_lane_and_cases(console: Console) -> None:
    r = console.get("/console/agents/payments")
    assert r.status_code == 200
    assert 'data-agent="payments"' in r.text and "/console/agents/payments/pause" in r.text
    assert 'data-section="gate24"' in r.text and 'data-section="lane"' in r.text
    assert 'id="agent-pills"' in r.text and "RUNNING" in r.text
    checked = int(re.search(r'data-num="checked">(\d+)<', r.text).group(1))  # type: ignore[union-attr]
    events = console.ctx.tables.query("agent_event", {"agent_id": "payments"})
    assert 0 < checked <= len(events)
    assert "agent:payments" in r.text
    # breadcrumb back to the list; the list row drawer links here
    assert "/console/agents?lang=en" in r.text
    d = console.get("/console/agents/payments/drawer?tab=overview", headers=HX)
    assert "/console/agents/payments?lang=en" in d.text


def test_lifecycle_controls_moved_here_with_their_rbac(console: Console) -> None:
    assert 'data-agent="' not in console.get("/console/agents").text  # not on the list any more
    p = console.post("/console/agents/payments/pause", {"reason": "x"})
    assert p.status_code == 200 and 'data-state="PAUSED"' in p.text
    page = console.get("/console/agents/payments")
    assert "PAUSED" in page.text and "/console/agents/payments/resume" in page.text
    # a viewer may read the page but the action stays a 403
    assert console.get("/console/agents/payments", user="viewer.hoa").status_code == 200
    r = console.post("/console/agents/payments/resume", {"reason": "x"}, user="viewer.hoa")
    assert r.status_code == 403
    # two audit rows per action, as before
    rows = [
        x for x in console.ctx.tables.query("console_action") if x["permission"] == "agent.pause"
    ]
    assert [x["outcome"] for x in rows] == ["attempted", "ok"]


def test_policy_tab_lists_rules_and_allow_list(console: Console) -> None:
    r = console.get("/console/agents/payments/tab/policy", headers=HX)
    assert r.status_code == 200
    assert 'data-rule="PAY-07"' in r.text and 'data-section="allow-list"' in r.text
    assert "Read only" in r.text
    n = console.get("/console/agents/payments").text
    assert re.search(r'data-tab="policy"[^>]*>Policy <span class="k">\d+</span>', n)


def test_flagged_tabs_hidden_when_off_and_400_with_the_flag_name(console: Console) -> None:
    page = console.get("/console/agents/payments")
    assert _tab_hrefs(page.text) == ["overview", "policy", "traces", "cases"]
    for tab, flag in (
        ("tools", "CONSOLE_TOOLS_ENABLED"),
        ("inventory", "INVENTORY_ENABLED"),
        ("assurance", "CONSOLE_ASSURANCE_ENABLED"),
        ("compliance", "CONSOLE_COMPLIANCE_ENABLED"),
    ):
        for url in (
            f"/console/agents/payments/tab/{tab}",
            f"/console/agents/payments?tab={tab}",
        ):
            r = console.get(url, headers=HX)
            assert r.status_code == 400 and flag in r.text, (url, r.status_code)


def test_flags_show_their_tabs(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    _all_on(console, monkeypatch)
    page = console.get("/console/agents/payments")
    assert _tab_hrefs(page.text) == list(agent_detail.TABS)
    # compliance summary from the advisor read API, assurance and inventory empty states
    comp = console.get("/console/agents/payments/tab/compliance", headers=HX).text
    assert 'data-section="counts"' in comp and "Advisory only" in comp
    assert "/console/compliance/payments" in comp
    inv = console.get("/console/agents/payments/tab/inventory", headers=HX).text
    assert "not in the inventory" in inv
    assert "No assurance result" in console.get(
        "/console/agents/payments/tab/assurance", headers=HX
    ).text
    tools = console.get("/console/agents/payments/tab/tools", headers=HX).text
    assert 'data-tools="1"' in tools


def test_assurance_tab_shows_results_of_this_agent(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    _all_on(console, monkeypatch)
    ctx = console.ctx
    ctx.tables.append(
        "eval_result",
        [
            {
                "run_id": "run-1",
                "ts": ctx.clock.now(),
                "pack_id": "pii_canary",
                "pack_version": 1,
                "manifest_sha256": "a" * 64,
                "dimension": "privacy",
                "target_kind": "agent",
                "target_id": "payments",
                "status": "ok",
                "metrics": {"leak_bp": 0},
                "metric_status": {"leak_bp": "ok"},
                "thresholds": {},
                "reasons": "",
                "n_items": 5,
                "data_mode": "synthetic",
                "dataset_id": "d1",
                "dataset_sha256": "b" * 64,
                "is_mock": True,
                "launch_gate": "required",
                "judge_gate": False,
                "details": {},
            }
        ],
    )
    r = console.get("/console/agents/payments/tab/assurance", headers=HX)
    assert r.status_code == 200 and "pii_canary" in r.text and "/console/assurance/run-1" in r.text
    other = console.get("/console/agents/credit_prequal/tab/assurance", headers=HX)
    assert "pii_canary" not in other.text


def test_traces_tab_links_case_transcript_then_traces_page(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = console.get("/console/agents/payments/tab/traces", headers=HX)
    assert r.status_code == 200 and 'id="agent-traces"' in r.text
    rows = agent_detail.trace_rows(console.ctx, "payments")
    assert rows and len(rows) <= agent_detail.TRACE_LIMIT
    with_case = [x for x in rows if x["case_id"]]
    assert with_case, "the demo pause is linked to a case"
    assert f"/console/cases/{with_case[0]['case_id']}?tab=transcript" in r.text
    assert "/console/traces/" not in r.text  # WP-UX3 page not built here
    monkeypatch.setattr(agent_detail, "traces_page_exists", lambda: True)
    r = console.get("/console/agents/payments/tab/traces", headers=HX)
    assert f"/console/traces/{rows[0]['trace_id']}" in r.text


def test_cases_tab_lists_all_cases_of_the_agent(console: Console) -> None:
    r = console.get("/console/agents/payments/tab/cases", headers=HX)
    assert r.status_code == 200
    ids = re.findall(r'data-case="(CASE-[0-9A-F]+)"', r.text)
    own = [c["case_id"] for c in console.ctx.cases.list_cases(agent_id="payments")]
    assert ids == own and ids


def test_bad_input_is_400_never_500(console: Console) -> None:
    for url, needle in (
        ("/console/agents/ghost", "not registered"),
        ("/console/agents/ghost/tab/policy", "not registered"),
        ("/console/agents/payments?tab=nope", "unknown agent tab"),
        ("/console/agents/payments/tab/nope", "unknown agent tab"),
        ("/console/agents/bad%20id", "invalid agent id"),
        ("/console/agents/payments/tab/%3Cscript%3E", "unknown agent tab"),
    ):
        r = console.get(url, headers=HX)
        assert r.status_code == 400 and needle in r.text, (url, r.status_code, r.text[:200])


def test_pages_have_no_inline_script_or_external_url(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    _all_on(console, monkeypatch)
    for tab in agent_detail.TABS:
        html = console.get(f"/console/agents/payments?tab={tab}").text
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), tab
        assert not re.search(r"\son[a-z]+=\"", html), tab
        assert not re.search(r"https?://", html, re.I), tab


def test_service_principal_sees_read_only_tabs(console: Console) -> None:
    class SP:
        kind = "service_principal"
        roles: tuple[str, ...] = ()

    sp = SP()
    assert agent_detail.can(sp, "tools.view") and not agent_detail.can(sp, "tools.download")
    assert not agent_detail.can(sp, "agent.pause")
