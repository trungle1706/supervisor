"""Two-section sidebar (CONSOLE_NAV_SECTIONS) and the Catalog page (CONSOLE_CATALOG_ENABLED):
both off by default, the off path is the six-group sidebar as before."""

from __future__ import annotations

import re

import pytest

from supervisor.console import catalog_view, i18n, nav

from .conftest import Console


def _sidebar(html: str) -> str:
    return html.split('<aside class="side"', 1)[1].split("</aside>", 1)[0]


@pytest.fixture
def sections(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "console_nav_sections", True)
    monkeypatch.setattr(console.ctx.settings, "console_catalog_enabled", True)
    return console


# ------------------------------------------------------------------ off path


def test_flags_are_off_by_default(console: Console) -> None:
    assert console.ctx.settings.console_nav_sections is False
    assert console.ctx.settings.console_catalog_enabled is False


def test_off_keeps_the_six_group_sidebar(console: Console) -> None:
    side = _sidebar(console.get("/console/?lang=en").text)
    assert 'class="side-sec"' not in side
    heads = re.findall(r'<h2 class="side-h" id="sg-\d+">([^<]+)</h2>', side)
    assert heads == ["Watch", "Act", "Prove", "Onboard", "Analytics", "Settings"]
    assert "/console/catalog" not in side


def test_catalog_off_is_400(console: Console) -> None:
    r = console.get("/console/catalog")
    assert r.status_code == 400 and "CONSOLE_CATALOG_ENABLED=1" in r.text


# ------------------------------------------------------------------ sections


def test_every_item_sits_in_exactly_one_section_group() -> None:
    placed = [k for _, _, gs in nav.SECTIONS for _, keys in gs for k in keys]
    rest = [it.key for _, items in nav.GROUPS[1:] for it in items]
    assert sorted(placed) == sorted(rest)
    assert len(placed) == len(set(placed))
    table = i18n.table()
    for key, kicker, gs in nav.SECTIONS:
        assert all(table[key]) and all(table[kicker])
        for label, _ in gs:
            assert all(table[label]), label


@pytest.mark.parametrize(
    ("lang", "gov", "guard"),
    [
        ("en", "AI Management and Governance", "AI Guardian and Supervisor"),
        ("vi", "Quản lý và quản trị AI", "Bảo vệ và giám sát AI"),
    ],
)
def test_sections_render_in_order(sections: Console, lang: str, gov: str, guard: str) -> None:
    side = _sidebar(sections.get(f"/console/agents?lang={lang}").text)
    titles = re.findall(r'<span class="side-t">([^<]+)<', side)
    assert titles == [gov, guard]
    assert side.count('<details class="side-sec" open>') == 2
    current = re.findall(r'class="active"[^>]*aria-current="page"', side)
    assert len(current) == 1
    # Agents sits in the guardian section, Evidence in the governance one
    gov_html, guard_html = side.split('<details class="side-sec"')[1:3]
    assert "/console/evidence?" in gov_html and "/console/agents?" in guard_html
    assert "/console/catalog?" in guard_html
    assert all(f"lang={lang}" in h for h in re.findall(r'<a href="([^"]+)" class=', side))


def test_sections_keep_flags_and_counts(sections: Console) -> None:
    side = _sidebar(sections.get("/console/").text)
    assert re.search(r'Agents <span class="k ">\d+</span>', side)
    assert "/console/decisions" not in side  # page flag still off, no placeholder
    assert "/console/overview" not in side and 'href="/console/?lang=en"' in side


# ------------------------------------------------------------------ catalog page


@pytest.mark.parametrize("lang", ["en", "vi"])
def test_catalog_renders_every_entry(sections: Console, lang: str) -> None:
    r = sections.get(f"/console/catalog?lang={lang}")
    assert r.status_code == 200
    assert r.text.count('<li class="cat-card') == len(catalog_view.ENTRIES)
    t = i18n.translator(lang)
    for e in catalog_view.ENTRIES:
        assert t(f"cat_{e.key}") in r.text
    assert "<form" not in r.text.split('id="main"', 1)[1].split("</main>", 1)[0]  # read-only


def test_active_tab_shows_only_what_is_on(
    sections: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sections.ctx.settings, "drift_enabled", True)
    monkeypatch.setattr(sections.ctx.settings, "detectors_enabled", False)
    html = sections.get("/console/catalog?tab=active").text
    assert "Drift monitor" in html and "Fairness monitor" not in html
    assert "Prompt injection patterns" not in html  # detectors off
    assert "Hash-chained evidence" in html  # always on
    all_html = sections.get("/console/catalog?tab=catalog").text
    assert "FAIRNESS_ENABLED=1" in all_html


def test_detector_status_follows_the_detector_file(
    sections: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sections.ctx.settings, "detectors_enabled", True)
    html = sections.get("/console/catalog?tab=active").text
    assert "Prompt injection patterns" in html  # enabled: true in config/detectors.yaml
    assert "Indirect prompt injection" not in html  # enabled: false there


def test_judges_on_without_a_model_are_labelled_mock(
    sections: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sections.ctx.settings, "judge_enabled", True)
    monkeypatch.setattr(sections.ctx.settings, "judge_t1_model", "")
    html = sections.get("/console/catalog?tab=active").text
    assert "On · mock" in html


def test_bad_tab_is_400(sections: Console) -> None:
    assert sections.get("/console/catalog?tab=nope").status_code == 400


def test_catalog_works_in_the_old_sidebar_too(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_catalog_enabled", True)
    r = console.get("/console/catalog")
    assert r.status_code == 200
    side = _sidebar(r.text)
    assert re.search(r'href="/console/catalog\?lang=en" class="active"', side)
