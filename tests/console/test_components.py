"""WP-UX1: component macros render, paging math, sort allow-list, no external URL in templates."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from supervisor.console import i18n, listing
from supervisor.console.listing import ListingError, paginate, parse_sort, sort_rows

TEMPLATES = Path(i18n.__file__).parent / "templates"


def _render(src: str, lang: str = "en", **ctx: object) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["hhmm"] = str
    return env.from_string(src).render(t=i18n.translator(lang), lang=lang, **ctx)


UI = '{% import "_ui.html" as ui with context %}'
TB = '{% import "_c_table.html" as tb with context %}'


# ---- paging and sorting


def test_paginate_first_last_empty_and_out_of_range() -> None:
    rows = list(range(23))
    p1 = paginate(rows, 1, 10)
    assert (p1.first, p1.last, p1.pages, p1.prev, p1.next) == (1, 10, 3, None, 2)
    p3 = paginate(rows, 3, 10)
    assert (p3.first, p3.last, p3.items, p3.next) == (21, 23, [20, 21, 22], None)
    empty = paginate([], 1, 10)
    assert (empty.first, empty.last, empty.pages, empty.total, empty.items) == (0, 0, 1, 0, [])
    for bad in (0, 4, -1):
        with pytest.raises(ListingError):
            paginate(rows, bad, 10)
    with pytest.raises(ListingError):
        paginate([], 2, 10)
    with pytest.raises(ListingError):
        paginate(rows, 1, 0)
    with pytest.raises(ListingError):
        paginate(rows, 1, listing.MAX_SIZE + 1)


def test_parse_int_rejects_junk() -> None:
    assert listing.parse_int(None, "page", 1) == 1 and listing.parse_int("7", "page", 1) == 7
    for bad in ("abc", "-1", "1.5", "0", "99999999", " 1"):
        with pytest.raises(ListingError):
            listing.parse_int(bad, "page", 1)


def test_sort_column_allow_list_and_stable_order() -> None:
    allowed = ("a", "b")
    assert parse_sort("b", "desc", allowed, "a") == ("b", "desc")
    assert parse_sort("__class__", "desc", allowed, "a") == ("a", "asc")  # unknown column
    assert parse_sort("b", "sideways", allowed, "a", "desc") == ("b", "desc")  # unknown direction
    rows = [{"a": 2, "n": 1}, {"a": 1, "n": 2}, {"a": None, "n": 3}, {"a": 2, "n": 4}]
    asc = [r["n"] for r in sort_rows(rows, "a", "asc")]
    desc = [r["n"] for r in sort_rows(rows, "a", "desc")]
    assert asc == [2, 1, 4, 3] and desc == [1, 4, 2, 3]  # None last, ties keep input order
    assert listing.query_string({"q": "x", "state": ""}, page=2, q=None) == "page=2"


# ---- macros


def test_pagehead_crumbs_stat_empty_kv_render() -> None:
    html = _render(
        UI
        + "{{ ui.crumbs([('A', '/a'), ('B', None)]) }}"
        + "{% call ui.pagehead('Title', ui.pill('x', 'ok')) %}<a>go</a>{% endcall %}"
        + "{{ ui.pagehead('Plain') }}"
        + "{{ ui.stat('Calls', 12, 'sub', 'calls', '/c') }}"
        + "{{ ui.empty('Nothing', 'Because.', '/x', 'Go') }}"
        + "{{ ui.kv([('Id', 'abc', True), ('Name', None)]) }}"
        + "{{ ui.barcell(5, 10) }}{{ ui.barcell(0, 0) }}{{ ui.action_pill('block') }}"
        + "{{ ui.toast('Saved') }}"
        + "{{ ui.timeline([{'t': '10:00', 'text': 'Opened', 'tone': 'red', 'who': 'an'}]) }}"
    )
    assert 'aria-current="page">B' in html and '<a href="/a">A</a>' in html
    assert '<div class="actions"><a>go</a></div>' in html
    assert html.count('class="pagehead"') == 2
    assert 'data-num="calls"' in html and 'href="/c"' in html
    assert "Nothing" in html and 'class="mono wrap">abc' in html and "<dd>-</dd>" in html
    assert "width:50%" in html and "width:0%" in html
    assert "block" in html and 'role="status"' in html and 'class="dot red"' in html


def test_tabs_filterbar_tiles_render_both_languages() -> None:
    for lang, word in (("en", "Reset"), ("vi", "Đặt lại")):
        html = _render(
            UI
            + "{{ ui.tabs(['a','b'], 'b', {'a': 'A', 'b': 'B'}, '/p?tab={tab}', '/h?tab={tab}', counts={'a': 3}) }}"  # noqa: E501
            + "{{ ui.filterbar('/p', '/p/rows', [{'name':'q','label':'Find','kind':'search','value':'x'},"  # noqa: E501
            + "{'name':'s','label':'State','kind':'select','value':'a','options':[('a','low')]}], '/p') }}"  # noqa: E501
            + "{{ ui.tiles([{'label':'all','n':4,'on':True,'qs':''}], '/p', '/p/rows') }}",
            lang=lang,
        )
        assert word in html
        assert 'role="tablist"' in html and html.count('role="tab"') == 2
        assert 'aria-selected="true"' in html and 'href="/p?tab=a"' in html
        assert 'hx-get="/h?tab=b"' in html and '<span class="k">3</span>' in html
        assert 'role="search"' in html and "selected" in html and 'maxlength="64"' in html
        assert 'aria-current="true"' in html and 'hx-get="/p/rows?lang=' in html


def test_table_header_and_pager_render() -> None:
    page = paginate(list(range(30)), 2, 10)
    html = _render(
        TB
        + "<table><tr>{{ tb.th('c', 'Col', 'c', 'asc', '/p', '/p/rows', 'q=1') }}"
        + "{{ tb.th('d', 'Other', 'c', 'asc', '/p', '/p/rows', '') }}</tr></table>"
        + "{{ tb.pager(page, '/p', '/p/rows', 'q=1&sort=c&dir=asc') }}",
        page=page,
    )
    assert 'aria-sort="ascending"' in html and "dir=desc" in html  # toggles direction
    assert html.count("aria-sort") == 1
    assert "Showing 11-20 of 30" in html and "page 2 of 3" in html
    assert 'rel="prev"' in html and 'rel="next"' in html and "page=3" in html
    first = _render(TB + "{{ tb.pager(page, '/p', '/p/rows', '') }}", page=paginate([], 1, 10))
    assert "Showing 0-0 of 0" in first and 'aria-disabled="true"' in first
    assert 'rel="prev"' not in first and 'rel="next"' not in first
    vi = _render(TB + "{{ tb.pager(page, '/p', '/p/rows', '') }}", "vi", page=page)
    assert "Hiển thị 11-20 trên 30" in vi


def test_drawer_macro_has_close_copy_and_title() -> None:
    html = _render(
        '{% import "_c_drawer.html" as dr with context %}'
        "{% call dr.drawer('payments', 'PILLS', 'TABS', '{\"a\": 1}', '/p', '/h', None, None) %}BODY{% endcall %}"  # noqa: E501
    )
    assert (
        'id="drawer-title"' in html
        and "data-drawer-close" in html
        and 'data-copy="#drawer-json"' in html
    )
    assert "BODY" in html and "&#34;a&#34;" in html and "hidden>" in html
    assert 'aria-label="Previous row"' in html and "Next row" not in html


# ---- templates and styles stay offline


def test_no_external_url_in_any_template_or_style() -> None:
    root = Path(i18n.__file__).parent
    files = [p for p in (root / "templates").rglob("*") if p.is_file()]
    files += [p for p in (root / "static").iterdir() if p.suffix in (".css", ".js")]
    assert any(p.name == "_c_sidebar.html" for p in files)
    for p in files:
        assert not re.search(r"https?://|//cdn\.|@import", p.read_text(encoding="utf-8")), p.name


def test_new_labels_exist_in_both_languages() -> None:
    table = i18n.table()
    for key in (
        "nav_g_watch",
        "nav_audit",
        "pager_showing",
        "copy_json",
        "soon_line",
        "search_none",
    ):
        en, vi = table[key]
        assert en and vi and en != vi, key


def test_every_wp_ux1_key_has_both_languages() -> None:
    """Every key of the WP-UX1 block in i18n.py has a non-empty EN and VI text, and every label
    key the sidebar uses exists."""
    from supervisor.console import nav

    src = Path(i18n.__file__).read_text(encoding="utf-8")
    block = src.split("# --- WP-UX1", 1)[1].split("\n}\n", 1)[0]
    keys = re.findall(r'^    "([a-z0-9_A-Z]+)": \(', block, re.M)
    assert len(keys) >= 60
    table = i18n.table()
    for key in keys:
        en, vi = table[key]
        assert en.strip() and vi.strip(), key
    for _, items in nav.GROUPS:
        for it in items:
            assert all(table[it.label]), it.label
    for g, _ in nav.GROUPS:
        assert g is None or all(table[g]), g


def test_tabs_point_at_their_panel() -> None:
    html = _render(
        UI
        + "{{ ui.tabs(['a'], 'a', {'a': 'A'}, '/p?tab={tab}', '/h?tab={tab}', panel='tab-body') }}"
    )  # noqa: E501
    assert 'aria-controls="tab-body"' in html
    d = _render(
        '{% import "_c_drawer.html" as dr with context %}'
        "{% call dr.drawer('x', '', 'TABS', '{}') %}B{% endcall %}"
    )
    assert 'id="tab-body" role="tabpanel"' in d


# ---- span tree


def _ev(span: str, parent: str | None, ts: str, **kw: object) -> dict[str, object]:
    return {
        "event_id": f"e-{span}-{ts}",
        "span_id": span,
        "parent_span_id": parent,
        "ts": ts,
        "event_type": "tool_call",
        **kw,
    }


def test_span_tree_nests_orphans_and_cuts_cycles() -> None:
    from supervisor.console.readmodels import span_tree

    events = [
        _ev("root", None, "01"),
        _ev("child", "root", "02", tool_name="pay/send", latency_ms=12),
        _ev("child", "root", "03", event_type="gate_decision", latency_ms=30),
        _ev("orphan", "missing", "04"),
        _ev("a", "b", "05"),  # a <-> b: a parent loop
        _ev("b", "a", "06"),
        _ev("self", "self", "07"),  # its own parent: a root
    ]
    tree = span_tree(events)
    assert [n["span_id"] for n in tree["roots"]] == ["root", "self"]
    child = tree["roots"][0]["children"][0]
    assert child["span_id"] == "child" and len(child["events"]) == 2
    assert child["latency_ms"] == 30 and child["tool_name"] == "pay/send"
    under = [n["span_id"] for n in tree["unparented"]]
    assert under[0] == "orphan" and "a" in under
    cut = next(n for n in tree["unparented"] if n["span_id"] == "a")
    assert cut["cut"] and [c["span_id"] for c in cut["children"]] == ["b"]

    def ids(nodes: list[dict[str, object]]) -> list[str]:
        out: list[str] = []
        for n in nodes:
            out.append(str(n["span_id"]))
            out += ids(n["children"])  # type: ignore[arg-type]
        return out

    every = ids(tree["roots"]) + ids(tree["unparented"])
    assert sorted(every) == sorted({e["span_id"] for e in events})  # each span exactly once
    assert tree["n"] == 6 and not tree["truncated"]


def test_span_tree_cap_and_depth_and_render() -> None:
    from supervisor.console import readmodels

    chain = [_ev(f"s{i:04d}", f"s{i - 1:04d}" if i else None, f"{i:06d}") for i in range(600)]
    tree = readmodels.span_tree(chain)
    assert tree["n"] == readmodels.SPAN_CAP and tree["truncated"]
    depth, node = 1, tree["roots"][0]
    while node["children"]:
        depth, node = depth + 1, node["children"][0]
    assert depth <= readmodels.SPAN_DEPTH  # deep chains re-hang, no deep recursion in Jinja
    for lang, word in (("en", "Showing the first 500"), ("vi", "Chỉ hiển thị 500")):
        html = _render(
            '{% import "_c_spantree.html" as st with context %}{{ st.spantree(tree) }}',
            lang,
            tree=tree,
        )
        assert word in html and html.count("<li data-span=") == 500
        assert "<details open>" in html and 'role="tree"' not in html
    small = readmodels.span_tree(
        [_ev("r", None, "1"), _ev("o", "gone", "2"), _ev("x<y", None, "3", tool_name="<b>")]
    )
    html = _render(
        '{% import "_c_spantree.html" as st with context %}{{ st.spantree(tree) }}', tree=small
    )
    assert "Spans without a parent" in html and "&lt;b&gt;" in html and "<b>" not in html
    empty = _render(
        '{% import "_c_spantree.html" as st with context %}{{ st.spantree(tree) }}',
        tree=readmodels.span_tree([]),
    )
    assert "No span in this trace" in empty
