"""WP-G0 off path: with both flags off nothing is mounted and the nav is unchanged."""

from __future__ import annotations

import re

import pytest

from supervisor.app import app
from supervisor.config import Settings, load_settings
from supervisor.console import nav

from .conftest import Console


def _sidebar(html: str) -> str:
    return html.split('<aside class="side"', 1)[1].split("</aside>", 1)[0]


def _paths() -> set[str]:
    from tests.console.test_rbac_matrix import app_routes

    return {p for _, p, _ in app_routes()}


def test_flags_are_off_by_default() -> None:
    assert Settings.model_fields["governance_enabled"].default is False
    assert Settings.model_fields["console_systems_enabled"].default is False
    s = load_settings(sql_backend="sqlite", llm_base_url="")
    assert s.governance_enabled is False and s.console_systems_enabled is False


def test_no_governance_route_is_mounted_with_the_flags_off() -> None:
    assert not [p for p in _paths() if p.startswith(("/v1/systems", "/console/systems"))]


@pytest.mark.parametrize(
    "url", ["/v1/systems", "/v1/systems/sys_x", "/console/systems", "/console/systems/rows"]
)
def test_urls_do_not_exist_with_the_flags_off(console: Console, url: str) -> None:
    assert console.get(url).status_code == 404
    assert app.openapi() and "/v1/systems" not in app.openapi()["paths"]


def test_nav_has_no_systems_item_with_the_flags_off(console: Console) -> None:
    side = _sidebar(console.get("/console/?lang=en").text)
    assert "systems" not in side.lower()
    heads = re.findall(r'<h2 class="side-h" id="sg-\d+">([^<]+)</h2>', side)
    assert heads == ["Watch", "Act", "Prove", "Onboard", "Analytics", "Settings"]
    # the item exists in the structure but is hidden without its page flag
    assert nav.PAGES["systems"] == "console_systems_enabled"
    for flag in (False, True):
        console.ctx.settings.console_nav_sections = flag
        assert "/console/systems" not in console.get("/console/?lang=en").text
    console.ctx.settings.console_nav_sections = False


def test_service_does_not_run_anything_by_itself(console: Console) -> None:
    # the tables exist (the schema is one file) and stay empty
    assert console.ctx.state.query("ai_system") == []
    assert console.ctx.state.query("system_team") == []
    assert console.ctx.state.query("system_component") == []
