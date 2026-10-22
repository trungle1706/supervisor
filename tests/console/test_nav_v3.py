"""WP-UX4a: merged sidebar (CONSOLE_NAV_V3) and the Supervisor-side pages. Off path first."""

from __future__ import annotations

import re

import pytest

from supervisor.console import i18n

from .conftest import Console

NEW_ROUTES = (
    "/console/governance",
    "/console/supervisor",
    "/console/activity",
    "/console/guardians",
    "/console/catalogues",
    "/console/risks-controls",
    "/console/workflows",
    "/console/systems",
)


def _sidebar(html: str) -> str:
    return html.split('<aside class="side"', 1)[1].split("</aside>", 1)[0]


def _main(html: str) -> str:
    return html.split('id="main"', 1)[1].split("</main>", 1)[0]


# ------------------------------------------------------------------ off path (first)


def test_flag_is_off_by_default(console: Console) -> None:
    assert console.ctx.settings.console_nav_v3 is False


def test_off_keeps_the_six_group_sidebar(console: Console) -> None:
    side = _sidebar(console.get("/console/?lang=en").text)
    heads = re.findall(r'<h2 class="side-h" id="sg-\d+">([^<]+)</h2>', side)
    assert heads == ["Watch", "Act", "Prove", "Onboard", "Analytics", "Settings"]
    assert "side-v3" not in side and "data-nav-v3" not in side and "nav-gear" not in side


def test_off_keeps_the_sections_sidebar(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_nav_sections", True)
    side = _sidebar(console.get("/console/?lang=en").text)
    assert side.count('<details class="side-sec" open>') == 2
    assert "side-v3" not in side


def test_off_overview_is_the_old_one(console: Console) -> None:
    html = console.get("/console/?lang=en").text
    assert 'id="numbers"' in html and 'data-page="my-overview"' not in html


@pytest.mark.parametrize("path", NEW_ROUTES)
def test_off_new_routes_answer_400_with_a_message(console: Console, path: str) -> None:
    r = console.get(path)
    assert r.status_code == 400 and "CONSOLE_NAV_V3=1" in r.text


@pytest.mark.parametrize(
    "path", ["/console/agents", "/console/cases", "/console/evidence", "/console/analytics"]
)
def test_off_pages_carry_no_tab_strip(console: Console, path: str) -> None:
    assert "sec-tabs" not in console.get(path).text


def test_off_old_urls_do_not_redirect(console: Console) -> None:
    for path in ("/console/inbox", "/console/signoff", "/console/evidence", "/console/agents"):
        assert console.get(path, follow_redirects=False).status_code == 200


def test_keys_exist_in_both_languages() -> None:
    table = i18n.table()
    for key in [k for k in table if k.startswith("nv3_")]:
        assert all(table[key]), key
