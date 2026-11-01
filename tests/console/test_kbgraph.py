"""Regulation graph (KBGRAPH_ENABLED): the pure builder, the 300-system showcase portfolio, the
routes (off path, on path, permission, scope), the i18n keys and the nav tab."""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.adapters.factory import build_adapters
from supervisor.console import i18n, kbgraph, nav_v3
from supervisor.console import systems_duties as sd
from supervisor.console.kbgraph import KbGraphError, Params, build_graph, parse_params
from supervisor.core import rbac
from supervisor.demo import showcase_portfolio as sp
from supervisor.demo.session import demo_settings
from supervisor.governance.systems import ALL
from supervisor.jobs import bootstrap_schema

from .conftest import Console
from .test_nav_v3 import v3, v3all  # noqa: F401, F811  (fixtures)
from .test_rbac_matrix import app_routes

ADMIN = "admin.chi"
VIEWER = "viewer.hoa"  # a scoped role: sees only the systems of its team
PAGE = "/console/regkb/graph"
API = "/v1/regkb/graph"

# ------------------------------------------------------------------------------ a small fixture

CAT = {
    "instruments": {
        "I-A": {"number": "Circular A", "title_en": "Title A", "title_vi": "Tieu de A"},
        "I-B": {"number": "Decision B", "title_en": "Title B", "title_vi": ""},
    },
    "obligations": {
        "I-A-1": {
            "article": "Art. 1",
            "summary_en": "Do one",
            "summary_vi": "Lam mot",
            "controls": [],
        },
        "I-A-2": {"article": "Art. 2", "summary_en": "Do two", "summary_vi": "", "controls": []},
        "I-B-1": {"article": "Art. 9", "summary_en": "Do nine", "summary_vi": "", "controls": []},
    },
}


def sysrow(sid: str, name: str, risk: str = "medium", status: str = "active") -> dict[str, Any]:
    return {
        "system_id": sid,
        "name": name,
        "risk_level": risk,
        "status": status,
        "owner_team": "team-x",
        "lifecycle_stage": "operation",
    }


def row(sid: str, oid: str, inst: str, coverage: str, status: str = "open", applies: str = "yes"):
    return {
        "system_id": sid,
        "obligation_id": oid,
        "instrument_id": inst,
        "coverage": coverage,
        "status": status,
        "applies": applies,
    }


SYSTEMS = [
    sysrow("s1", "Alpha", "high"),
    sysrow("s2", "Beta", "low"),
    sysrow("s3", "Gamma", "high"),
    sysrow("s4", "Archived one", "high", "archived"),
]
ROWS = [
    row("s1", "I-A-1", "I-A", "none"),
    row("s1", "I-A-2", "I-A", "partial"),
    row("s1", "I-B-1", "I-B", "full"),
    row("s2", "I-A-1", "I-A", "none", "closed"),
    row("s2", "I-A-2", "I-A", "partial"),
    row("s3", "I-A-1", "I-A", "none"),
    row("s3", "I-A-2", "I-A", "none", "waived"),  # not a link
    row("s3", "I-B-1", "I-B", "unknown", applies="needs_answer"),  # not a link
    row("s4", "I-A-1", "I-A", "none"),  # archived system: left out
    row("gone", "I-A-1", "I-A", "none"),  # a system the caller cannot see: left out
]


def graph(**q: str) -> dict[str, Any]:
    return build_graph(ROWS, SYSTEMS, CAT, parse_params(q))


def ids(g: dict[str, Any], kind: str) -> list[str]:
    return [n["key"] for n in g["nodes"] if n["kind"] == kind]


def test_the_mark_of_a_link_is_the_tick_of_the_duties_tab() -> None:
    for status in ("open", "closed", "waived"):
        for applies in ("yes", "no", "needs_answer"):
            for cov in ("full", "partial", "none", "unknown"):
                r = row("s", "o", "i", cov, status, applies)
                assert kbgraph.tick_of(r) == sd._tick_of(r)
    assert kbgraph.tick_of(row("s", "o", "i", "full")) == "bank"
    assert kbgraph.tick_of(row("s", "o", "i", "none")) == "gap"
    assert kbgraph.tick_of(row("s", "o", "i", "partial", "closed")) == "closed"


def test_the_default_view_picks_the_instrument_with_most_gaps() -> None:
    g = graph()
    assert g["focus"] == {
        "instrument": "I-A",
        "label": "Circular A",
        "auto": True,
        "all": False,
        "n": 20,
    }
    assert ids(g, "instrument") == ["I-A"]
    assert set(ids(g, "obligation")) == {"I-A-1", "I-A-2"}
    # archived and unknown systems, waived rows and rows that need an answer are no links
    assert set(ids(g, "system")) == {"s1", "s2", "s3"}
    states = sorted(r["state"] for r in g["rows"])
    assert states == ["closed", "gap", "gap", "partial", "partial"]
    c = g["counts"]
    assert c["systems_in_scope"] == 3 and c["links"] == 6 and c["instruments"] == 2
    assert c["by_state"] == {"gap": 2, "partial": 2, "bank": 1, "closed": 1}
    assert c["shown"]["links"] == 5 and c["hidden_systems"] == 0


def test_systems_come_in_rank_order_gap_first() -> None:
    g = graph(instrument="I-A")
    order = ids(g, "system")
    assert order == ["s1", "s3", "s2"]  # s1: 1 gap 1 partial, s3: 1 gap, s2: no gap
    ys = [n["y"] for n in g["nodes"] if n["kind"] == "system"]
    assert ys == sorted(ys)


def test_filters_instrument_risk_coverage_n() -> None:
    assert sorted(ids(graph(instrument="all"), "instrument")) == ["I-A", "I-B"]
    assert ids(graph(instrument="I-B"), "system") == ["s1"]
    assert ids(graph(instrument="all", risk="low"), "system") == ["s2"]
    g = graph(instrument="all", coverage="gap")
    assert {r["state"] for r in g["rows"]} == {"gap"} and len(g["rows"]) == 2 + 0
    assert ids(g, "system") == ["s1", "s3"]
    assert graph(instrument="all", coverage="bank")["rows"][0]["system_id"] == "s1"
    g = graph(instrument="I-A", n="10")
    assert g["focus"]["n"] == 10
    assert graph(risk="prohibited")["empty"] is True


def test_search_by_system_obligation_instrument() -> None:
    g = graph(q="alp")  # a system name: all its obligations, in every instrument
    assert ids(g, "system") == ["s1"] and g["focus"]["all"] is True
    assert set(ids(g, "obligation")) == {"I-A-1", "I-A-2", "I-B-1"}
    g = graph(q="i-b-1")  # an obligation id: that obligation and the systems it binds
    assert ids(g, "obligation") == ["I-B-1"] and ids(g, "system") == ["s1"]
    g = graph(q="art. 2")  # an article
    assert ids(g, "obligation") == ["I-A-2"]
    g = graph(q="decision b")  # an instrument number
    assert ids(g, "instrument") == ["I-B"]
    assert graph(q="nothing like this")["empty"] is True
    assert ids(graph(q="alp", instrument="I-B"), "obligation") == ["I-B-1"]  # explicit wins


def test_bad_parameters_raise_the_400_error() -> None:
    bad = [
        {"risk": "extreme"},
        {"coverage": "met"},
        {"n": "5"},
        {"n": "x"},
        {"view": "pie"},
        {"instrument": "a b"},
        {"instrument": "x" * 70},
        {"q": "x" * 81},
        {"q": "a\x01b"},
        {"sel": "evil:1"},
    ]
    for q in bad:
        with pytest.raises(KbGraphError):
            parse_params(q)
    assert parse_params({}) == Params()


def test_layout_is_deterministic_and_inside_the_canvas() -> None:
    a, b = graph(instrument="all"), graph(instrument="all")
    assert a == b
    w, h = a["layout"]["width"], a["layout"]["height"]
    for n in a["nodes"]:
        assert 0 <= n["x"] and n["x"] + n["w"] <= w and 0 <= n["y"] and n["y"] + n["h"] <= h
    # an obligation sits under its instrument: no instrument edge crosses another one
    by = {n["id"]: n for n in a["nodes"]}
    spans = []
    for e in a["edges"]:
        if e["kind"] == "structure":
            spans.append((by[e["a"]]["y"], by[e["b"]]["y"]))
    assert len(spans) == len(ids(a, "obligation"))
    assert all(e["d"].startswith("M") for e in a["edges"])


def test_neighbours_totals_and_detail_data() -> None:
    g = graph(instrument="I-A")
    by = {n["id"]: n for n in g["nodes"]}
    s1 = by["sys:s1"]
    assert {x["id"] for x in s1["links"]} == {"obl:I-A-1", "obl:I-A-2"}
    assert s1["states"]["gap"] == 1 and s1["totals"]["partial"] == 1
    o1 = by["obl:I-A-1"]
    assert {x["id"] for x in o1["links"]} == {"sys:s1", "sys:s2", "sys:s3"}
    assert o1["article"] == "Art. 1" and o1["title"] == "Do one" and o1["badge"] == 3
    assert by["ins:I-A"]["title"] == "Title A"
    vi = build_graph(ROWS, SYSTEMS, CAT, Params(instrument="I-A"), lang="vi")
    assert {n["key"]: n["title"] for n in vi["nodes"] if n["kind"] == "obligation"}[
        "I-A-1"
    ] == "Lam mot"
    # a missing vi text falls back to English
    assert {n["key"]: n["title"] for n in vi["nodes"] if n["kind"] == "obligation"}[
        "I-A-2"
    ] == "Do two"
    assert graph(instrument="I-A", sel="sys:s1")["selected"] == "sys:s1"
    assert graph(instrument="I-A", sel="sys:nope")["selected"] == ""


def test_an_unknown_instrument_or_obligation_is_still_listed() -> None:
    rows = [row("s1", "X-1", "X", "none")]
    g = build_graph(rows, SYSTEMS, {"instruments": {}, "obligations": {}}, Params())
    assert ids(g, "instrument") == ["X"] and ids(g, "obligation") == ["X-1"]


def test_no_rows_is_an_empty_graph() -> None:
    g = build_graph([], SYSTEMS, CAT, Params())
    assert g["empty"] and g["nodes"] == [] and g["counts"]["links"] == 0


def test_the_graph_is_bounded() -> None:
    many_s = [sysrow(f"s{i:03d}", f"System {i:03d}") for i in range(200)]
    many_r = [
        row(f"s{i:03d}", f"I-A-{j}", "I-A", "none" if (i + j) % 3 else "partial")
        for i in range(200)
        for j in range(60)
    ]
    g = build_graph(many_r, many_s, {}, Params(instrument="I-A", n=60))
    assert len(ids(g, "system")) <= 60
    assert len(ids(g, "obligation")) <= kbgraph.MAX_OBLIGATIONS
    assert len(g["rows"]) <= kbgraph.MAX_EDGES
    assert g["counts"]["hidden_systems"] >= 140 and g["counts"]["hidden_obligations"] == 20
    assert g["counts"]["hidden_links"] > 0


# ------------------------------------------------------------------------------ 300 systems

NOW = dt.datetime(2026, 10, 29, 9, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def big(tmp_path_factory: pytest.TempPathFactory) -> Any:
    s = demo_settings(
        tmp_path_factory.mktemp("kbgraph300"),
        governance_enabled=True,
        classification_v2=True,
        risk_dimensions=True,
        overview_portfolio=True,
        console_overview_v4=True,
        console_nav_v3=True,
        inventory_enabled=True,
        kbgraph_enabled=True,
    )
    a = build_adapters(s)
    bootstrap_schema.run(s, a)
    a.close()
    rep = sp.run(
        s, systems=300, seed=1, env={"SHOWCASE_ENABLED": "1"}, now=NOW, echo=lambda _l: None
    )
    assert rep.ok
    a = build_adapters(s)
    yield s, a
    a.close()


class CountingState:
    """The state store of the page, counting the statements it is asked for."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.tables: list[str] = []

    def query(self, table: str, *a: Any, **kw: Any) -> list[dict[str, Any]]:
        self.tables.append(table)
        return self.inner.query(table, *a, **kw)


def test_300_systems_default_and_all_views_stay_readable_and_fast(big: Any) -> None:
    s, a = big
    state = CountingState(a.state)
    ctx = SimpleNamespace(
        settings=s, state=state, systems=SimpleNamespace(scope_for=lambda me: ALL)
    )
    me = AuthPrincipal(
        user_id="admin.chi", kind="user", auth_method="dev_header", roles=frozenset({"admin"})
    )
    t0 = time.perf_counter()
    g = kbgraph.load(ctx, me, {})
    elapsed = time.perf_counter() - t0
    assert state.tables == ["obligation_status", "ai_system"]  # one query per table, not per node
    assert g["counts"]["systems_in_scope"] == 300 - 0 or g["counts"]["systems_in_scope"] > 290
    assert g["counts"]["links"] > 3000
    shown = g["counts"]["shown"]
    assert shown["instruments"] == 1 and shown["systems"] == 20
    assert shown["obligations"] <= kbgraph.MAX_OBLIGATIONS and shown["links"] <= 150
    assert g["counts"]["hidden_systems"] > 200
    assert elapsed < 5.0
    # every instrument, every risk level, every coverage: bounded and fast
    for q in (
        {"instrument": "all"},
        {"instrument": "all", "n": "60"},
        {"risk": "high"},
        {"coverage": "closed"},
        {"coverage": "partial", "instrument": "all", "n": "40"},
        {"q": "Card Fraud"},
        {"q": "A12"},
    ):
        t0 = time.perf_counter()
        g = kbgraph.load(ctx, me, q)
        assert time.perf_counter() - t0 < 5.0, q
        sh = g["counts"]["shown"]
        assert sh["links"] <= kbgraph.MAX_EDGES and sh["obligations"] <= kbgraph.MAX_OBLIGATIONS, q
        assert sh["systems"] <= 60, q
    assert state.tables.count("obligation_status") == 1 + 7


def test_300_systems_search_finds_a_system_and_an_obligation(big: Any) -> None:
    s, a = big
    systems = a.state.query("ai_system")
    rows = a.state.query("obligation_status", {"applies": "yes"})
    from supervisor.console.compliance_view import kb_for

    kb = kb_for(s)
    cat = kbgraph.catalogue_of(
        kb, {r["instrument_id"] for r in rows}, {r["obligation_id"] for r in rows}
    )
    name = systems[7]["name"]
    g = build_graph(rows, systems, cat, parse_params({"q": name}))
    assert systems[7]["system_id"] in ids(g, "system") or g["empty"]
    oid = rows[3]["obligation_id"]
    g = build_graph(rows, systems, cat, parse_params({"q": oid.lower()}))
    assert oid in ids(g, "obligation")
    assert all(
        n["article"] for n in g["nodes"] if n["kind"] == "obligation"
    )  # the catalogue joined


# ------------------------------------------------------------------------------ the routes


def _put_system(
    c: Console, sid: str, name: str, risk: str = "high", owner: str = "someone"
) -> None:
    c.ctx.state.insert(
        "ai_system",
        {
            "system_id": sid,
            "name": name,
            "owner_user": owner,
            "owner_team": "team-x",
            "purpose": "x",
            "system_type": "assistant",
            "org_role": "deployer",
            "user_segment": "internal",
            "personal_data": "none",
            "money_movement": False,
            "credit_decision": False,
            "human_control": "post_review",
            "lifecycle_stage": "operation",
            "risk_level": risk,
            "risk_level_source": "manual",
            "decision33_class": "unclassified",
            "business_impact": "low",
            "autonomy_level": "unspecified",
            "status": "active",
            "tags": "{}",
            "created_at": NOW,
            "created_by": "tester",
        },
    )


def _put_duty(c: Console, sid: str, oid: str, inst: str, cov: str, status: str = "open") -> None:
    c.ctx.state.insert(
        "obligation_status",
        {
            "status_id": f"{sid}|{oid}",
            "system_id": sid,
            "obligation_id": oid,
            "instrument_id": inst,
            "applies": "yes",
            "coverage": cov,
            "status": status,
            "owner_user": "someone",
            "created_at": NOW,
        },
    )


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in ("kbgraph_enabled", "governance_enabled", "console_systems_enabled"):
        monkeypatch.setattr(console.ctx.settings, flag, True)
    kb = kbgraph.catalogue_of
    assert kb  # the module imports
    from supervisor.console.compliance_view import kb_for

    obls = list(kb_for(console.ctx.settings).obligations.values())[:4]
    inst = obls[0].instrument_id
    same = [
        o for o in kb_for(console.ctx.settings).obligations.values() if o.instrument_id == inst
    ][:3]
    _put_system(console, "kg_s1", "Graph System One", "high")
    _put_system(console, "kg_s2", "Graph System Two", "low")
    for i, o in enumerate(same):
        _put_duty(console, "kg_s1", o.id, inst, ("none", "partial", "full")[i % 3])
        _put_duty(console, "kg_s2", o.id, inst, "none", "closed" if i == 0 else "open")
    console.inst, console.oids = inst, [o.id for o in same]  # type: ignore[attr-defined]
    return console


def test_off_by_default_every_route_answers_400_with_the_code(console: Console) -> None:
    assert console.ctx.settings.kbgraph_enabled is False
    for u in (PAGE, API, PAGE + "?view=list", PAGE + "?risk=bad"):
        r = console.get(u, user=ADMIN)
        assert r.status_code == 400 and "kbgraph_off" in r.text, u


def test_the_flag_alone_is_not_enough(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "kbgraph_enabled", True)
    monkeypatch.setattr(console.ctx.settings, "governance_enabled", False)
    r = console.get(PAGE, user=ADMIN)
    assert r.status_code == 400 and "GOVERNANCE_ENABLED" in r.text


def test_page_graph_view(on: Console) -> None:
    r = on.get(PAGE, user=ADMIN)
    assert r.status_code == 200, r.text[:400]
    t = r.text
    assert 'id="kbgraph"' in t and 'data-kg="svg"' in t and "<svg" in t
    assert "Graph System One" in t and "Graph System Two" in t
    for o in on.oids:
        assert f'data-id="obl:{o}"' in t
    assert 'data-id="sys:kg_s1"' in t and "/console/static/kbgraph.js" in t
    assert 'class="kg-e duty gap' in t and "kg-e duty bank" in t and "kg-e duty closed" in t
    assert 'data-kg="panel"' in t and "kbgraph.css" in t
    assert "Regulation graph" in t  # the tab of the section strip
    assert "No link matches" not in t


def test_page_selected_node_and_list_view(on: Console) -> None:
    t = on.get(f"{PAGE}?sel=sys:kg_s1", user=ADMIN).text
    assert 'data-selected="sys:kg_s1"' in t and "has-sel" in t and 'class="kg-n system sel' in t
    assert "/console/systems/kg_s1" in t  # the link to the system page
    oid = on.oids[0]
    t = on.get(f"{PAGE}?sel=obl:{oid}", user=ADMIN).text
    assert 'data-selected="obl:' in t and "Graph System Two" in t
    lst = on.get(f"{PAGE}?view=list", user=ADMIN).text
    assert 'data-table="kbgraph-list"' in lst and 'data-kg="svg"' not in lst
    assert lst.count("<tr data-state") == len(on.get(f"{API}", user=ADMIN).json()["rows"])
    assert 'data-state="gap"' in lst and "Graph System One" in lst


def test_empty_state_and_filters(on: Console) -> None:
    t = on.get(f"{PAGE}?q=zzzzzz", user=ADMIN).text
    assert 'data-empty="regkb-graph"' in t and "No link matches" in t
    t = on.get(f"{PAGE}?risk=low&instrument=all", user=ADMIN).text
    assert "Graph System Two" in t and "Graph System One" not in t
    t = on.get(f"{PAGE}?lang=vi", user=ADMIN).text
    assert "Đồ thị quy định" in t and "Hệ thống AI" in t


def test_bad_input_is_400_never_500(on: Console) -> None:
    for q in (
        "risk=x",
        "coverage=x",
        "n=7",
        "view=x",
        "sel=bad",
        "q=" + "a" * 90,
        "instrument=%3Cb%3E",
    ):
        for base in (PAGE, API):
            r = on.get(f"{base}?{q}", user=ADMIN)
            assert r.status_code == 400, (base, q, r.status_code)
    assert on.get(f"{PAGE}?instrument=NO-SUCH-ONE", user=ADMIN).status_code == 200  # an empty graph


def test_json_api(on: Console) -> None:
    j = on.get(API, user=ADMIN).json()
    assert j["banner"].startswith("Not legal advice")
    assert j["counts"]["shown"]["systems"] == 2 and j["counts"]["by_state"]["gap"] >= 1
    assert {n["kind"] for n in j["nodes"]} == {"instrument", "obligation", "system"}
    assert j["focus"]["instrument"] == on.inst
    j2 = on.get(f"{API}?coverage=bank", user=ADMIN).json()
    assert {r["state"] for r in j2["rows"]} == {"bank"}


def test_permission_and_scope(on: Console) -> None:
    assert rbac.ROUTES[("GET", PAGE)] == "regkb.view" and rbac.ROUTES[("GET", API)] == "regkb.view"
    for role in ("viewer", "reviewer", "auditor", "operator", "owner", "approver", "admin"):
        assert rbac.allowed([role], "regkb.view")
    # a scoped role sees only the systems of its team: here none, so the graph is empty
    r = on.get(PAGE, user=VIEWER)
    assert r.status_code == 200 and "Graph System One" not in r.text
    assert on.get(API, user=VIEWER).json()["counts"]["systems_in_scope"] == 0
    assert on.get(API, user="reviewer.an").json()["counts"]["systems_in_scope"] == 2


def test_the_graph_is_read_only(on: Console) -> None:
    before = len(on.ctx.state.query("console_action"))
    on.get(PAGE, user=ADMIN)
    assert len(on.ctx.state.query("console_action")) == before
    assert on.client.post(PAGE, headers={"X-Dev-User": ADMIN}).status_code in (404, 405)


def test_rbac_rows_and_every_route_is_in_the_table() -> None:
    mounted = {(m, p) for m, p, _ in app_routes() if "/regkb/graph" in p}
    assert mounted == {("GET", PAGE), ("GET", API)}
    for key in mounted:
        assert key in rbac.ROUTES


# ------------------------------------------------------------------------------ nav and i18n


def test_nav_tab_only_with_the_flag(
    v3all: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = 'href="/console/regkb/graph?lang=en"'
    off = v3all.get("/console/risks?lang=en", user=ADMIN)
    assert off.status_code == 200 and link not in off.text
    monkeypatch.setattr(v3all.ctx.settings, "kbgraph_enabled", True)
    page = v3all.get("/console/risks?lang=en", user=ADMIN).text
    assert link in page and "Regulation graph" in page
    vi = v3all.get("/console/risks?lang=vi", user=ADMIN).text
    assert 'href="/console/regkb/graph?lang=vi"' in vi and "Đồ thị quy định" in vi
    # the page marks its tab active
    r = v3all.get("/console/regkb/graph?lang=en", user=ADMIN)
    assert (
        r.status_code == 200
        and 'href="/console/regkb/graph?lang=en" class="on" aria-current="page"' in r.text
    )
    assert 'data-kg="json"' in r.text and 'href="/v1/regkb/graph" class="kg-json"' in r.text


def test_nav_tab_follows_the_regkb_view_permission() -> None:
    sh = {"regkb_graph": True}
    for role in ("viewer", "admin"):
        keys = [
            t.key
            for t in nav_v3.visible_tabs(
                "risks_controls", sh, [role], compliance=True, integration=True
            )
        ]
        assert "regkb_graph" in keys


def test_keys_exist_in_english_and_vietnamese() -> None:
    from supervisor.console.i18n_kbgraph import KG

    table = i18n.table()
    for key, (en, vi) in KG.items():
        assert key.startswith("kg_") and key in table
        assert en.strip() and vi.strip() and en != vi, key
    # every key the template and the builder use
    tpl = (Path(i18n.__file__).parent / "templates" / "regkb_graph.html").read_text(
        encoding="utf-8"
    )
    import re

    used = set(re.findall(r"\bt\('(kg_[a-z0-9_]+)'\s*[,)]", tpl))
    dynamic = (
        [f"kg_s_{s}" for s in kbgraph.STATES]
        + [f"kg_s_{s}_d" for s in kbgraph.STATES]
        + [f"kg_risk_{r}" for r in kbgraph.RISKS]
        + [f"kg_d_{k}" for k in ("instrument", "obligation", "system")]
        + ["kg_d_open_duties", "kg_d_open_system"]
    )
    assert not (used | set(dynamic)) - set(KG)
    for key, (en, vi) in KG.items():
        import string

        fields = lambda s: {f for _, f, _, _ in string.Formatter().parse(s) if f}  # noqa: E731
        assert fields(en) == fields(vi), key
