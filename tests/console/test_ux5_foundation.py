"""UX5-F: the console_ux5 flag, text overrides, list helpers and the _ux5.html macros."""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from supervisor.config import Settings
from supervisor.console import i18n, i18n_ux5, ux5

from .conftest import Console

TEMPLATES = Path(i18n.__file__).parent / "templates"


# ---------------------------------------------------------------- flag and translator
def test_flag_defaults_off() -> None:
    assert Settings(_env_file=None).console_ux5 is False  # type: ignore[call-arg]


def test_translator_off_path_unchanged() -> None:
    base = i18n.table()
    for lang, idx in (("en", 0), ("vi", 1)):
        t = i18n.translator(lang)
        assert t("dev_banner") == base["dev_banner"][idx]
        assert t("dev_banner") == i18n.translator(lang, ux5=False)("dev_banner")
    assert i18n.translator("en")("no_such_key") == "no_such_key"


def test_translator_on_applies_override_en_and_vi() -> None:
    over = i18n_ux5.load()
    assert over, "the base module overrides at least one key"
    key = "dev_banner"
    assert i18n.translator("en", ux5=True)(key) == over[key][0] != i18n.table()[key][0]
    assert i18n.translator("vi", ux5=True)(key) == over[key][1]
    # a key without override falls back to the normal table
    assert i18n.translator("en", ux5=True)("inbox") == i18n.table()["inbox"][0]


def test_every_override_key_exists_and_has_text() -> None:
    base = i18n.table()
    for key, (en, vi) in i18n_ux5.load().items():
        assert key in base, f"override invents a key: {key}"
        if key not in i18n_ux5.REMOVED:
            assert en.strip() and vi.strip(), key


def test_override_placeholders_match_base() -> None:
    import re

    base = i18n.table()
    for key, (en, vi) in i18n_ux5.load().items():
        want = set(re.findall(r"{(\w+)}", base[key][0]))
        assert set(re.findall(r"{(\w+)}", en)) == set(re.findall(r"{(\w+)}", vi)), key
        assert set(re.findall(r"{(\w+)}", en)) <= want | set(), key


# ---------------------------------------------------------------- helpers
def test_top() -> None:
    assert ux5.top(list(range(9)), 5) == [0, 1, 2, 3, 4]
    assert ux5.top([1], 5) == [1] and ux5.top([1, 2], -3) == []


def test_page_slice_clamps() -> None:
    rows = list(range(60))
    assert ux5.page_slice(rows, 1) == (rows[:25], 1, 3)
    assert ux5.page_slice(rows, "3")[0] == rows[50:]
    assert ux5.page_slice(rows, 99)[1] == 3
    assert ux5.page_slice(rows, "junk")[1] == 1 and ux5.page_slice(rows, -4)[1] == 1
    assert ux5.page_slice([], 5) == ([], 1, 1)
    assert ux5.page_slice(rows, 2, size=50) == (rows[50:], 2, 2)


def test_fold_identical() -> None:
    rows = [("a", 1), ("a", 1), ("a", 1), ("b", 2), ("a", 1), ("c", 3), ("c", 3)]
    out = ux5.fold_identical(rows, key=lambda r: r[0])
    assert out[0] == ("fold", (3, ("a", 1)))
    assert [k for k, _ in out] == ["fold", "row", "row", "row", "row"]
    assert ux5.fold_identical([], key=str) == []


# ---------------------------------------------------------------- macros
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


def _render(src: str, lang: str = "en") -> str:
    env = _env()
    tpl = env.from_string('{% import "_ux5.html" as u5 with context %}' + src)
    return tpl.render(t=i18n.translator(lang, ux5=True))


def test_macro_page_head_with_about_and_actions() -> None:
    html = _render(
        "{% set a %}<a class='btn' href='#'>Go</a>{% endset %}"
        "{{ u5.page_head('Duties', 'What we owe.', about='Long text here.', actions=a) }}"
    )
    assert "<h1>Duties</h1>" in html and "What we owe." in html
    assert 'class="u5-info"' in html and "Long text here." in html
    assert "About this page" in html and "<a class='btn'" in html
    plain = _render("{{ u5.page_head('X', 'Y') }}")
    assert "u5-info" not in plain and "u5-about" not in plain


def test_macro_disclaimer_and_chip() -> None:
    html = _render("{{ u5.disclaimer('Advisory only. Not legal advice.') }}")
    assert 'title="Advisory only. Not legal advice."' in html and "u5-chip" in html
    chip = _render("{{ u5.status_chip('ok', 'Met') }}")
    assert "u5-chip ok" in chip and "u5-dot" in chip and "Met" in chip


def test_macro_tick_strip_and_legend() -> None:
    html = _render("{{ u5.tick_strip([('gap', 2), ('partial', 1), ('closed', 3)]) }}")
    assert html.count("<i ") == 6 and 'class="gap"' in html
    assert 'aria-label="2 gap, 1 partial, 3 met"' in html and "more" not in html
    big = _render("{{ u5.tick_strip([('gap', 40), ('closed', 50)]) }}")
    assert big.count("<i ") == 60 and "+30 more" in big
    assert big.count('class="gap"') == 40  # the worst statuses are kept when capped
    leg = _render("{{ u5.tick_legend(['gap', 'partial', 'bank', 'closed']) }}")
    assert leg.count("<i ") == 4 and "Bank process" in leg
    vi = _render("{{ u5.tick_legend(['gap']) }}", lang="vi")
    assert "Thiếu" in vi


def test_macro_view_all_pager_fold_technical() -> None:
    assert "5 of 21 shown" in _render("{{ u5.view_all(5, 21, '/console/x') }}")
    assert 'href="/console/x"' in _render("{{ u5.view_all(5, 21, '/console/x') }}")
    assert "View all" not in _render("{{ u5.view_all(5, 5, '/console/x') }}")
    p = _render("{{ u5.pager(2, 3, '/console/x?lang=en') }}")
    assert "Page 2 of 3" in p and "page=1" in p and "page=3" in p
    p1 = _render("{{ u5.pager(1, 1, '/console/x') }}")
    assert "href" not in p1
    assert "<b>153</b> agents: no findings" in _render("{{ u5.fold(153, 'agents: no findings') }}")
    assert "<tr" in _render("{{ u5.fold(3, 'same', cols=4) }}")
    tech = _render("{{ u5.technical([('Flag', 'CONSOLE_UX5'), ('Path', '/data/x')]) }}")
    assert "Technical details" in tech and "CONSOLE_UX5" in tech
    assert _render("{{ u5.technical([]) }}").strip() == ""


# ---------------------------------------------------------------- base.html on / off
def test_off_path_page_has_no_ux5_markup(console: Console) -> None:
    html = console.get("/console/cases").text
    assert "ux5" not in html and "u5-" not in html
    assert '<html lang="en">' in html
    assert '/console/static/console.css">\n<script src="/console/static/console.js">' in html
    assert "Dev identity (users file, X-Dev-User)" in html


def test_on_path_page_links_css_and_class(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_ux5", True)
    html = console.get("/console/cases").text
    assert '<html lang="en" class="ux5">' in html
    css = html.index("/console/static/console.css")
    assert css < html.index("/console/static/ux5.css") < html.index("console.js")
    assert "u5-chip" in html and "Dev identity (X-Dev-User)" in html  # chip + overridden tooltip
    vi = console.get("/console/cases?lang=vi").text
    assert "Danh tính dev (X-Dev-User)" in vi
    assert console.get("/console/static/ux5.css").status_code == 200


def test_on_path_v3_sidebar_renders(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_ux5", True)
    monkeypatch.setattr(console.ctx.settings, "console_nav_v3", True)
    r = console.get("/console/")
    assert r.status_code == 200 and "side-v3" in r.text and 'class="ux5"' in r.text
