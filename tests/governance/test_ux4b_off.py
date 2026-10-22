"""WP-UX4b off path, first: with CONSOLE_NAV_V3 or console_systems_enabled off nothing changes, and
with GOVERNANCE_ENABLED off the two overviews keep the agent-based path of WP-UX4a."""

from __future__ import annotations

import re

import pytest

from .conftest import Console, draft

HX = {"HX-Request": "true"}
NEW_TABS = ("risks", "controls", "policies", "guardians", "reports")
OLD_TABS = ("overview", "components", "tasks", "reviews")


def _system(c: Console, name: str = "Off path system") -> str:
    out = c.ctx.systems.register(draft(name=name, owner_user="reviewer.an"), "reviewer.an")
    return str(out["system_id"])


def _tabs(html: str) -> list[str]:
    return sorted(set(re.findall(r'role="tab" data-tab="(\w+)"', html)))


# ------------------------------------------------------------------ v3 off (systems on)


def test_v3_off_system_page_keeps_the_four_tabs(on: Console) -> None:
    assert on.ctx.settings.console_nav_v3 is False
    sid = _system(on)
    html = on.get(f"/console/systems/{sid}?lang=en").text
    assert _tabs(html) == sorted(OLD_TABS)
    for tab in NEW_TABS:
        r = on.get(f"/console/systems/{sid}?tab={tab}")
        assert r.status_code == 400 and "unknown tab" in r.text, tab


def test_v3_off_wizard_answers_400_with_the_flag_name(on: Console) -> None:
    for method, url in [
        ("GET", "/console/systems/new"),
        ("POST", "/console/systems/new/checks"),
        ("POST", "/console/systems/new"),
    ]:
        r = on.get(url) if method == "GET" else on.post(url, {"name": "x"})
        assert r.status_code == 400 and "CONSOLE_NAV_V3=1" in r.text, (method, url)
    assert on.ctx.state.query("ai_system") == []


def test_v3_off_systems_page_has_no_wizard_link(on: Console) -> None:
    html = on.get("/console/systems?lang=en").text
    assert 'data-wizard="link"' not in html and "/console/systems/new" not in html
    assert 'id="register"' in html  # the old register form stays


def test_v3_off_agents_page_has_no_system_column(on: Console) -> None:
    for url in ("/console/agents", "/console/agents/rows"):
        html = on.get(f"{url}?lang=en").text
        assert 'data-col="system"' not in html and "ux4b_" not in html, url
        assert "Unlinked" not in html
    # the filter parameter is ignored while the column is off, as any unknown parameter was
    assert on.get("/console/agents?system=bogus").status_code == 200


def test_v3_off_overview_is_the_old_one(on: Console) -> None:
    html = on.get("/console/?lang=en").text
    assert 'id="numbers"' in html and 'data-unit="systems"' not in html


# ------------------------------------------------------------------ systems page flag off


def test_systems_page_flag_off_wizard_is_400(
    console: Console, mounted: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = console.ctx.settings
    monkeypatch.setattr(s, "console_nav_v3", True)
    monkeypatch.setattr(s, "governance_enabled", True)
    monkeypatch.setattr(s, "console_systems_enabled", False)
    r = console.get("/console/systems/new")
    assert r.status_code == 400 and "CONSOLE_SYSTEMS_ENABLED" in r.text
    monkeypatch.setattr(s, "console_systems_enabled", True)
    monkeypatch.setattr(s, "governance_enabled", False)
    r = console.get("/console/systems/new")
    assert r.status_code == 400 and "GOVERNANCE_ENABLED" in r.text


# ------------------------------------------------------------------ governance off (v3 on)


@pytest.fixture
def v3gov_off(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "console_nav_v3", True)
    assert console.ctx.settings.governance_enabled is False
    return console


def test_governance_off_my_overview_counts_agents(v3gov_off: Console) -> None:
    html = v3gov_off.get("/console/?scope=all&lang=en").text
    assert 'data-page="my-overview"' in html and 'data-unit="systems"' not in html
    assert 'data-num="agents"' in html and 'data-num="systems"' not in html
    assert "Health per agent" in html


def test_governance_off_governance_overview_counts_agents(v3gov_off: Console) -> None:
    html = v3gov_off.get("/console/governance?scope=all&lang=en").text
    assert 'data-num="agents"' in html and 'data-num="systems"' not in html
    assert 'data-unit="systems"' not in html and "By lifecycle stage" in html


def test_governance_off_agents_page_has_no_system_column(v3gov_off: Console) -> None:
    html = v3gov_off.get("/console/agents?lang=en").text
    assert 'data-col="system"' not in html


def test_governance_off_badge_is_the_agent_count(v3gov_off: Console) -> None:
    from supervisor.console import overview_v3

    html = v3gov_off.get("/console/?scope=all&lang=en").text
    tile = re.search(r'data-num="actions">\s*<h3>[^<]+</h3>\s*<div class="bignum"[^>]*>(\d+)', html)
    assert tile and int(tile.group(1)) == overview_v3.actions_count(v3gov_off.ctx, _me(v3gov_off))


def _me(c: Console):  # noqa: ANN202
    return c.ctx.provider.users["reviewer.an"]
