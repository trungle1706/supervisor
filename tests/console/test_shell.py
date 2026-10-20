"""WP-UX1: the sidebar shell, the CONSOLE_NAV=top rollback, search, placeholders, agents list."""

from __future__ import annotations

import re

import pytest

from supervisor.console import nav, readmodels

from .conftest import Console

PAGES = {
    "overview": "/console/",
    "agents": "/console/agents",
    "cases": "/console/cases",
    "evidence": "/console/evidence",
    "onboard": "/console/onboard",
    "health": "/console/health",
    "metrics": "/console/metrics",
    "inbox": "/console/inbox",
}


def _sidebar(html: str) -> str:
    return html.split('<aside class="side"', 1)[1].split("</aside>", 1)[0]


def _hrefs(html: str) -> list[str]:
    return re.findall(r'<a href="([^"]+)" class="[^"]*"', _sidebar(html))


@pytest.mark.parametrize("lang", ["en", "vi"])
def test_every_page_renders_with_sidebar_and_marks_the_active_item(
    console: Console, lang: str
) -> None:
    for section, path in PAGES.items():
        r = console.get(f"{path}?lang={lang}")
        assert r.status_code == 200, (path, r.text[:300])
        assert '<body class="nav-side">' in r.text
        side = _sidebar(r.text)
        current = re.findall(r'<a href="[^"]+" class="active"[^>]*aria-current="page"', side)
        assert len(current) == 1, (section, current)
        assert 'class="skip" href="#main"' in r.text and 'id="main"' in r.text
        assert '<header class="top">' not in r.text  # the pill header is gone
        assert 'id="drawer"' in r.text and "gsearch" in r.text
    t = nav  # keep the import used: the six groups
    assert [g[0] for g in t.GROUPS] == [
        None, "nav_g_watch", "nav_g_act", "nav_g_prove", "nav_g_onboard", "nav_g_analytics",
        "nav_g_settings",
    ]  # fmt: skip


def test_sidebar_language_and_labels(console: Console) -> None:
    en = _sidebar(console.get("/console/?lang=en").text)
    vi = _sidebar(console.get("/console/?lang=vi").text)
    for word in ("Watch", "Act", "Prove", "Onboard", "Analytics", "Settings", "Agents", "Health"):
        assert f">{word}<" in en or word in en, word
    for word in ("Giám sát", "Xử lý", "Chứng minh", "Tiếp nhận", "Phân tích", "Cài đặt", "Tác tử"):
        assert word in vi, word
    assert all("lang=vi" in h for h in _hrefs(console.get("/console/?lang=vi").text))


def test_sidebar_counts_match_shell(console: Console) -> None:
    r = console.get("/console/agents")
    sh = readmodels.shell(console.ctx, _principal(console))
    side = _sidebar(r.text)
    assert re.search(rf"Agents <span class=\"k \">{sh['agents_n']}</span>", side)
    assert re.search(rf"Cases <span class=\"k hot\">{sh['cases_n']}</span>", side)  # critical case
    assert sh["critical_n"] >= 1
    assert re.search(rf"Sign-off <span class=\"k[^\"]*\">{sh['signoff_n']}</span>", side)
    assert re.search(rf"Alerts <span class=\"k[^\"]*\">{sh['alerts_n']}</span>", side)


def _principal(console: Console):  # type: ignore[no-untyped-def]
    from supervisor.adapters.auth.dev_header import DevHeaderPrincipal
    from supervisor.config import REPO_ROOT

    return DevHeaderPrincipal.from_file(REPO_ROOT / "config" / "users.yaml").users["reviewer.an"]


FLAGS = {
    "console_compliance_enabled": "/console/compliance",
    "console_integration_enabled": "/console/integration",
    "console_assurance_enabled": "/console/assurance",
    "console_tools_enabled": "/console/tools",
    "inventory_enabled": "/console/inventory",
}


def test_flagged_items_hidden_when_off_and_present_when_on(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    off = _hrefs(console.get("/console/").text)
    for path in FLAGS.values():
        assert not any(h.startswith(path) for h in off), path
    assert not any(h.startswith("/console/soon/") for h in off)
    for flag, path in FLAGS.items():
        monkeypatch.setattr(console.ctx.settings, flag, True)
        assert any(h.startswith(path) for h in _hrefs(console.get("/console/").text)), flag


def test_placeholder_items_follow_their_flag(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    for page in nav.PLACEHOLDERS:
        r = console.get(f"/console/soon/{page}")
        assert r.status_code == 400 and "not built yet" in r.text  # flag off: message, no 500
    monkeypatch.setattr(console.ctx.settings, "console_nav_placeholders", True)
    hrefs = _hrefs(console.get("/console/").text)
    for page in nav.PLACEHOLDERS:
        assert any(h.startswith(f"/console/soon/{page}") for h in hrefs), page
        r = console.get(f"/console/soon/{page}?lang=en")
        assert r.status_code == 200 and "coming in WP-UX3" in r.text
        assert 'aria-current="page"' in _sidebar(r.text)
    vi = console.get("/console/soon/audit?lang=vi")
    assert "WP-UX3" in vi.text and "Nhật ký kiểm toán" in vi.text
    assert console.get("/console/soon/nope").status_code == 400


def test_top_nav_is_the_rollback(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_nav", "top")
    for lang in ("en", "vi"):
        for path in PAGES.values():
            r = console.get(f"{path}?lang={lang}")
            assert r.status_code == 200, path
            assert '<body class="nav-top">' in r.text
            assert '<header class="top">' in r.text and '<aside class="side"' not in r.text
            assert '<nav class="nav"' in r.text
    r = console.get("/console/?lang=en")
    assert re.search(r"Cases <span class=\"k[^\"]*\">\d+</span>", r.text)
    assert 'id="switch"' not in r.text and "dev-user" in r.text  # Switch user stays


def test_user_menu_keeps_switch_user_in_dev_header_mode(console: Console) -> None:
    r = console.get("/console/")
    assert "Switch user" in r.text and 'hx-post="/console/dev/user"' in r.text
    assert 'name="q"' in r.text and "inboxlink" in r.text and "EN · vi" in r.text


def test_setting_default_and_values() -> None:
    from supervisor.config import load_settings

    s = load_settings()
    assert s.console_nav == "sidebar" and s.console_nav_placeholders is False
    assert load_settings(console_nav="top").console_nav == "top"
    with pytest.raises(Exception):  # noqa: B017,PT011 - pydantic ValidationError
        load_settings(console_nav="left")


def test_search_returns_agents_cases_traces(console: Console) -> None:
    r = console.get("/console/search?q=pay", headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<html" not in r.text
    assert "payments" in r.text and "/console/agents?q=payments" in r.text
    case = console.ctx.cases.list_cases()[0]
    c = console.get(f"/console/search?q={case['case_id'][:9]}", headers={"HX-Request": "true"})
    assert f"/console/cases/{case['case_id']}" in c.text
    ev = console.ctx.tables.query("agent_event", {"event_type": "gate_decision"}, limit=1)[0]
    tr = console.get(f"/console/search?q={ev['trace_id']}", headers={"HX-Request": "true"})
    assert ev["trace_id"] in tr.text and ev["agent_id"] in tr.text
    page = console.get("/console/search?q=pay")  # no htmx: a full page
    assert "<html" in page.text and 'class="side"' in page.text


def test_search_edge_cases_are_4xx_or_empty_never_500(console: Console) -> None:
    hx = {"HX-Request": "true"}
    assert "at least 2" in console.get("/console/search?q=a", headers=hx).text
    assert "No match" in console.get("/console/search?q=zzzzzz", headers=hx).text
    assert console.get("/console/search?q=" + "x" * 80, headers=hx).status_code == 400
    assert console.get("/console/search?q=%3Cscript%3E", headers=hx).status_code == 400
    assert console.get("/console/search", headers=hx).status_code == 200


def test_search_escapes_html(console: Console) -> None:
    r = console.get("/console/search?q=a%27b", headers={"HX-Request": "true"})
    assert r.status_code == 400  # quote is not in the allowed set


def test_agents_list_filters_sorts_pages_and_drawer(console: Console) -> None:
    r = console.get("/console/agents")
    assert 'data-row="payments"' in r.text and 'class="tiles"' in r.text
    assert 'aria-sort="ascending"' in r.text  # default sort column marked
    assert (
        console.post("/console/agents/customer_service/pause", {"reason": "x"}).status_code == 200
    )
    paused = console.get("/console/agents/rows?state=PAUSED")
    assert 'data-row="customer_service"' in paused.text
    assert 'data-row="credit_prequal"' not in paused.text
    assert "<html" not in paused.text
    q = console.get("/console/agents/rows?q=credit")
    assert 'data-row="credit_prequal"' in q.text and 'data-row="payments"' not in q.text
    desc = console.get("/console/agents/rows?sort=agent_id&dir=desc").text
    ids = re.findall(r'data-row="([^"]+)"', desc)
    assert ids == sorted(ids, reverse=True) and len(ids) >= 2
    odd = console.get("/console/agents/rows?sort=__class__&dir=sideways")
    assert odd.status_code == 200  # unknown column and direction fall back
    assert console.get("/console/agents/rows?page=99").status_code == 400
    assert console.get("/console/agents/rows?page=abc").status_code == 400
    assert console.get("/console/agents/rows?state=NOPE").status_code == 400
    assert console.get("/console/agents/rows?q=%3C").status_code == 400
    d = console.get("/console/agents/payments/drawer?tab=overview")
    assert d.status_code == 200 and 'id="drawer-title"' in d.text and "<html" not in d.text
    assert 'role="tablist"' in d.text and d.text.count('role="tab"') == 3
    assert "Copy JSON" in d.text and 'id="drawer-json"' in d.text
    pol = console.get("/console/agents/payments/drawer?tab=policy")
    assert "PAY-07" in pol.text
    cases = console.get("/console/agents/payments/drawer?tab=cases")
    assert "/console/cases/CASE-" in cases.text or "no open case" in cases.text
    assert console.get("/console/agents/payments/drawer?tab=nope").status_code == 400
    assert console.get("/console/agents/ghost/drawer").status_code == 400
    fallback = console.get("/console/agents?drawer=payments&dtab=policy")  # no JS
    assert fallback.status_code == 200 and "PAY-07" in fallback.text.split('id="drawer"', 1)[1]
    assert "hidden>" not in fallback.text.split('id="drawer"', 1)[1].split(">", 1)[0] + ">"


def test_agent_action_still_works_and_refreshes_the_list(console: Console) -> None:
    p = console.post("/console/agents/credit_prequal/pause", {"reason": "x"})
    assert p.status_code == 200
    assert 'id="list" hx-swap-oob="innerHTML"' in p.text
    assert 'data-state="PAUSED"' in p.text


def test_overview_uses_the_stat_component(console: Console) -> None:
    r = console.get("/console/")
    assert r.text.count('class="card stat"') == 4 and 'data-num="chain"' in r.text


def test_no_inline_script_and_no_external_url_in_rendered_pages(console: Console) -> None:
    for path in [*PAGES.values(), "/console/agents?drawer=payments"]:
        html = console.get(path).text
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), path
        assert not re.search(r"\son[a-z]+=\"", html), path  # no inline event handler
        assert not re.search(r"https?://", html, re.I), path
