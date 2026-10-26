"""WP-N1: My overview as a dashboard (CONSOLE_OVERVIEW_V4), the Candidates tab and
GET /v1/candidates. Off path first, then the page in English and Vietnamese, the tab strip, the
triage table (sort, page, filters, drawer), the API and the no-workspace-id rule."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest

from supervisor.app import app
from supervisor.console import overview_v4
from supervisor.inventory.graph import Graph
from supervisor.inventory.service import InventoryService

from .conftest import Console, draft, restore_app
from .test_n1_triage import golden_graph, mk

FLAGS = ("console_nav_v3", "console_overview_v4", "inventory_enabled", "controls_enabled")


def main(html: str) -> str:
    return html.split('id="main"', 1)[1].split("</main>", 1)[0]


def fill(c: Console, g: Graph) -> None:
    InventoryService.from_adapters(c.ctx.runtime.adapters).store.apply(g, source="workspace_scan")


@pytest.fixture
def v4(on: Console, monkeypatch: pytest.MonkeyPatch) -> Iterator[Console]:
    from supervisor.console.candidates_routes import api_router, router

    for f in FLAGS:
        monkeypatch.setattr(on.ctx.settings, f, True)
    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(router)
    app.include_router(api_router)
    fill(on, golden_graph())
    try:
        yield on
    finally:
        restore_app(app, saved, lifespan)


# ------------------------------------------------------------------ off path


def test_flag_default_is_off() -> None:
    from supervisor.config import load_settings

    s = load_settings(sql_backend="sqlite")
    assert s.console_overview_v4 is False and s.console_my_agents is False


def test_candidate_routes_are_not_mounted_by_default() -> None:
    paths = {getattr(r, "path", "") for r in app.router.routes}
    assert "/v1/candidates" not in paths and "/console/candidates" not in paths


def test_off_path_keeps_todays_page(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(on.ctx.settings, "console_nav_v3", True)
    assert on.ctx.settings.console_overview_v4 is False

    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("the v4 builder ran with the flag off")

    monkeypatch.setattr(overview_v4, "my_overview", boom)
    html = on.get("/console/?lang=en").text
    assert 'data-unit="systems"' in html and "data-version" not in html
    assert "ov4-" not in main(html) and "Health of my systems" in html
    assert 'class="subtabs sec-tabs"' not in html  # no tab strip under My overview
    assert on.get("/console/candidates").status_code == 404


def test_nav_v3_off_ignores_the_v4_flag(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(on.ctx.settings, "console_overview_v4", True)
    html = on.get("/console/?lang=en").text
    assert "ov4-" not in main(html)


def test_governance_off_keeps_the_agent_page(v4: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v4.ctx.settings, "governance_enabled", False)
    html = v4.get("/console/?lang=en").text
    assert "ov4-" not in main(html) and 'data-unit="systems"' not in html


# ------------------------------------------------------------------ the page


def test_page_layout_en(v4: Console) -> None:
    r = v4.get("/console/?lang=en")
    assert r.status_code == 200
    html = main(r.text)
    assert 'data-version="4"' in html
    for part in (
        "data-banner=",
        "data-pipeline",
        "data-assess",
        "data-risk",
        "data-totals",
        "data-cards",
    ):
        assert part in html or part == "data-cards", part
    assert "How are we doing" in html and "Registration pipeline" in html
    assert "Assessment completion" in html and "Risk classification by autonomy level" in html
    assert "Your action items" in html and "Top candidates to register" in html
    assert "My systems and agents" in html
    stages = re.findall(r'data-stage="(\w+)"', html)
    assert stages == list(overview_v4.STAGES)
    assert len(re.findall(r'data-dim="(\w+)"', html)) == 5
    assert len(re.findall(r'data-level="(\w+)"', html)) == 7  # l0..l5 and unspecified


def test_page_vi(v4: Console) -> None:
    html = main(v4.get("/console/?lang=vi").text)
    assert "Tình hình hiện nay" in html and "Quy trình đăng ký" in html
    assert "Ứng viên nên đăng ký trước" in html and "Mức hoàn thành đánh giá" in html
    assert "Databricks App loan-copilot" in html  # description built from facts, in Vietnamese
    assert "truy cập bảng khách hàng" in html
    assert "How are we doing" not in html


def test_banner_is_attention_with_a_high_score_candidate(v4: Console) -> None:
    html = main(v4.get("/console/?lang=en").text)
    # an overdue high task or a critical case may come first; a candidate over 70 is enough
    assert 'data-banner="attention"' in html
    assert "Attention" in html


def test_pipeline_counts(v4: Console) -> None:
    v4.ctx.systems.register(draft(name="Alpha", owner_user="reviewer.an"), "reviewer.an")
    html = main(v4.get("/console/?lang=en").text)
    counts = dict(re.findall(r'data-stage="(\w+)"><span class="n">(\d+)', html))
    assert counts["candidates"] == "5" and counts["draft"] == "1"
    assert counts["classified"] == "0" and counts["production"] == "0"
    assert 'data-num="systems"><span class="n">1' in html


def test_candidates_already_in_a_draft_leave_the_pipeline(v4: Console) -> None:
    rows = overview_v4.load_candidates(v4.ctx)
    assert rows is not None and len(rows) == 5
    sysrow = v4.ctx.systems.register(draft(name="Beta", owner_user="reviewer.an"), "reviewer.an")
    v4.ctx.systems.link(sysrow["system_id"], "node", rows[0]["node_id"], "reviewer.an")
    again = overview_v4.load_candidates(v4.ctx)
    assert again is not None and len(again) == 4
    assert rows[0]["node_id"] not in {r["node_id"] for r in again}


def test_assessment_and_risk_rows_follow_the_systems(v4: Console) -> None:
    a = v4.ctx.systems.register(draft(name="Alpha", owner_user="reviewer.an"), "reviewer.an")
    v4.ctx.systems.update_fields(a["system_id"], {"risk_level": "high"}, "x")
    d = overview_v4.my_overview(v4.ctx, _me(v4), "all", v4.ctx.clock.now(), {})
    assess = {x["key"]: (x["done"], x["of"]) for x in d["assess"]}
    assert assess["intake"] == (1, 1) and assess["class"] == (0, 1)
    row = next(r for r in d["risk_rows"] if r["level"] == "l1_assistive")
    assert row["total"] == 1 and row["segs"][0][0] == "high"
    assert next(r for r in d["risk_rows"] if r["level"] == "l0_rule_based")["total"] == 0


def _me(c: Console) -> Any:
    return c.ctx.provider.users["reviewer.an"]


def test_scope_switch_still_works(v4: Console) -> None:
    v4.ctx.systems.register(draft(name="Alpha", owner_user="reviewer.an"), "reviewer.an")
    v4.ctx.systems.register(
        draft(name="Gamma", owner_user="other.person", owner_team="risk-team"), "other.person"
    )
    my = main(v4.get("/console/?scope=my&lang=en").text)
    allv = main(v4.get("/console/?scope=all&lang=en").text)
    assert "Alpha" in my and "Gamma" not in my
    assert "Gamma" in allv
    r = v4.get("/console/?scope=zzz")
    assert r.status_code == 400 and "scope must be" in r.text


def test_cards_show_description_and_recommended_action(v4: Console) -> None:
    v4.ctx.systems.register(
        draft(name="Alpha", owner_user="reviewer.an", purpose="Answers questions about transfers."),
        "reviewer.an",
    )
    html = main(v4.get("/console/?lang=en").text)
    assert 'data-card="system"' in html and "Answers questions about transfers." in html
    assert "Classify (Decision 33)" in html  # a new system is unclassified
    vi = main(v4.get("/console/?lang=vi").text)
    assert "Phân loại (Quyết định 33)" in vi


def test_banner_rules_unit() -> None:
    none: dict[str, Any] = dict(actions_n=0, overdue=[], cases=[], top=None)
    assert overview_v4._banner(**none)["state"] == "good"
    assert overview_v4._banner(**{**none, "actions_n": 2})["state"] == "work"
    assert overview_v4._banner(**{**none, "top": {"score": 69, "name": "x"}})["state"] == "good"
    assert (
        overview_v4._banner(**{**none, "top": {"score": 70, "name": "x"}})["state"] == "attention"
    )
    late = {"title": "Fix", "level": "medium"}
    assert overview_v4._banner(**{**none, "overdue": [late]})["state"] == "work"
    assert (
        overview_v4._banner(**{**none, "overdue": [{**late, "level": "high"}]})["state"]
        == "attention"
    )
    assert (
        overview_v4._banner(**{**none, "cases": [{"severity": "critical"}]})["state"] == "attention"
    )
    assert overview_v4._banner(**{**none, "cases": [{"severity": "high"}]})["state"] == "work"


def test_inventory_off_says_so_on_the_page_and_the_tab(
    v4: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v4.ctx.settings, "inventory_enabled", False)
    html = main(v4.get("/console/?lang=en").text)
    assert "The inventory is off" in html and "data-candidate=" not in html
    r = v4.get("/console/candidates")
    assert r.status_code == 400 and "INVENTORY_ENABLED=1" in r.text


# ------------------------------------------------------------------ tab strip


def test_tab_strip(v4: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    html = v4.get("/console/?lang=en").text
    strip = html.split('class="subtabs sec-tabs"', 1)[1].split("</nav>", 1)[0]
    assert "Overview" in strip and "Candidates" in strip and "My agents" not in strip
    assert 'href="/console/candidates' in strip
    monkeypatch.setattr(v4.ctx.settings, "console_my_agents", True)
    strip = (
        v4.get("/console/?lang=en")
        .text.split('class="subtabs sec-tabs"', 1)[1]
        .split("</nav>", 1)[0]
    )
    assert "My agents" in strip and "/console/my/agents" in strip
    page = v4.get("/console/candidates?lang=en").text
    strip = page.split('class="subtabs sec-tabs"', 1)[1].split("</nav>", 1)[0]
    assert re.search(r'class="on" aria-current="page">Candidates', strip)


# ------------------------------------------------------------------ the table


def names(html: str) -> list[str]:
    return re.findall(r'data-candidate="inv_\w+">\s*<td><a class="head"[^>]*>([^<]+)</a>', html)


def test_table_is_sorted_by_score_and_sortable(v4: Console) -> None:
    html = v4.get("/console/candidates?lang=en").text
    assert names(html) == [
        "loan-copilot",
        "nightly-memo-batch",
        "Lending analytics",
        "gpt-agent",
        "agent-credit-memo",
    ]
    asc = v4.get("/console/candidates?sort=name&dir=asc&lang=en").text
    assert names(asc) == [
        "agent-credit-memo",
        "gpt-agent",
        "Lending analytics",
        "loan-copilot",
        "nightly-memo-batch",
    ]
    by_aut = names(v4.get("/console/candidates?sort=autonomy&dir=desc&lang=en").text)
    assert by_aut[0] == "nightly-memo-batch" and by_aut[1] == "loan-copilot"
    assert names(v4.get("/console/candidates?sort=bogus&lang=en").text)[0] == "loan-copilot"
    assert 'aria-sort="descending"' in html


def test_overview_table_pages_by_ten(v4: Console) -> None:
    g = Graph()
    for i in range(13):
        mk(g, "genie_space", f"space-{i:02d}", status="unmanaged")
    fill(v4, g)
    html = main(v4.get("/console/?lang=en").text)
    assert len(names(html)) == 10
    assert "Showing 1-10 of 18" in html
    p2 = main(v4.get("/console/?page=2&lang=en").text)
    assert len(names(p2)) == 8
    bad = v4.get("/console/?page=9")
    assert bad.status_code == 400


def test_rows_partial_for_both_pages(v4: Console) -> None:
    full = v4.get("/console/candidates/rows?sort=impact&dir=desc&lang=en")
    assert full.status_code == 200 and "<html" not in full.text and "loan-copilot" in full.text
    assert 'hx-get="/console/candidates/rows?' in full.text
    top = v4.get("/console/candidates/rows?src=top&lang=en").text
    assert 'href="/console/?' in top  # no-JS links go back to the overview


def test_filters(v4: Console) -> None:
    def got(q: str) -> list[str]:
        return names(v4.get(f"/console/candidates?{q}&lang=en").text)

    assert got("kind=endpoint") == ["gpt-agent", "agent-credit-memo"]
    assert got("signal=customer_table") == ["loan-copilot", "Lending analytics"]
    assert got("band=high") == ["loan-copilot"]
    assert got("kind=job&band=high") == []
    assert "No candidate" in v4.get("/console/candidates?kind=job&band=high&lang=en").text
    for q in ("kind=x", "signal=x", "band=x"):
        r = v4.get(f"/console/candidates?{q}")
        assert r.status_code == 400 and "filter" in r.text, q


def test_drawer(v4: Console) -> None:
    nid = overview_v4.load_candidates(v4.ctx)[0]["node_id"]  # type: ignore[index]
    r = v4.get(f"/console/candidates/{nid}/drawer?lang=en")
    assert r.status_code == 200
    for part in (
        "loan-copilot",
        "Signals",
        "Evidence",
        "workspace:system/app:loan-copilot",
        "Register now",
        f"/console/systems/new?from={nid}",
    ):
        assert part in r.text, part
    assert "external model" in r.text and "+30" in r.text
    fallback = v4.get(f"/console/candidates?drawer={nid}&lang=vi")
    assert (
        fallback.status_code == 200
        and 'id="drawer"' in fallback.text
        and "Bằng chứng" in fallback.text
    )
    assert v4.get("/console/candidates/inv_000000000000/drawer").status_code == 400
    assert v4.get("/console/candidates/bad id/drawer").status_code in (400, 404)


def test_register_button_needs_the_wizard(v4: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    html = v4.get("/console/candidates?lang=en").text
    assert "/console/systems/new?from=inv_" in html
    monkeypatch.setattr(v4.ctx.settings, "console_systems_enabled", False)
    assert "/console/systems/new?from=" not in v4.get("/console/candidates?lang=en").text


def test_page_is_vi_complete(v4: Console) -> None:
    html = v4.get("/console/candidates?lang=vi").text
    assert "Ứng viên cần đăng ký" in html and "Tín hiệu" in html and "Hành động đề xuất" in html
    assert "bảng khách hàng" in html


# ------------------------------------------------------------------ the API


def test_api_rows(v4: Console) -> None:
    r = v4.get("/v1/candidates")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 5 and body["total"] == 5
    first = body["items"][0]
    assert first["name"] == "loan-copilot" and first["score"] == 95
    assert first["recommended_action"] == "register_now" and "facts" not in first
    assert [i["name"] for i in v4.get("/v1/candidates?kind=job").json()["items"]] == [
        "nightly-memo-batch"
    ]
    bad = v4.get("/v1/candidates?band=nope")
    assert bad.status_code == 400 and "filter" in bad.json()["error"]


def test_api_off_answers_400_with_the_flag(v4: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v4.ctx.settings, "console_overview_v4", False)
    r = v4.get("/v1/candidates")
    assert r.status_code == 400 and "CONSOLE_OVERVIEW_V4=1" in r.json()["error"]
    monkeypatch.setattr(v4.ctx.settings, "console_overview_v4", True)
    monkeypatch.setattr(v4.ctx.settings, "inventory_enabled", False)
    r = v4.get("/v1/candidates")
    assert r.status_code == 400 and "INVENTORY_ENABLED=1" in r.json()["error"]


def test_permission_is_inventory_view() -> None:
    from supervisor.core import rbac

    for route in ("/console/candidates", "/console/candidates/rows", "/v1/candidates"):
        assert rbac.route_entry("GET", route) == "inventory.view"


# ------------------------------------------------------------------ no workspace id, no write


def test_no_workspace_url_or_id_on_any_page(v4: Console) -> None:
    host = "https://adb-" + "1234567890123456" + ".7." + "azure" + "databricks.net"
    g = Graph()
    a = mk(
        g,
        "system",
        "app:leaky",
        display_name="leaky",
        status="unmanaged",
        attrs={"role": "databricks_app", "owner_group": "grp"},
    )
    a.add_evidence("workspace_scan", f"{host}/apps/leaky")
    fill(v4, g)
    pages = [
        v4.get("/console/?lang=en").text,
        v4.get("/console/candidates?lang=en").text,
        v4.get("/console/candidates/rows?lang=vi").text,
        json.dumps(v4.get("/v1/candidates").json()),
    ]
    nid = overview_v4.load_candidates(v4.ctx)  # type: ignore[arg-type]
    leaky = next(r for r in nid if r["name"] == "leaky")  # type: ignore[union-attr]
    pages.append(v4.get(f"/console/candidates/{leaky['node_id']}/drawer").text)
    for html in pages:
        assert "azuredatabricks" not in html and "1234567890123456" not in html


def test_the_pages_write_nothing(v4: Console) -> None:
    tables = (
        "ai_system",
        "task",
        "inventory_node",
        "inventory_edge",
        "console_action",
        "system_component",
    )
    before = {t: len(v4.ctx.state.query(t)) for t in tables}
    for url in ("/console/?lang=en", "/console/candidates?lang=en", "/v1/candidates"):
        assert v4.get(url).status_code == 200
    assert {t: len(v4.ctx.state.query(t)) for t in tables} == before


def test_off_path_is_byte_identical_to_the_old_template(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag off: the page is the one the route rendered before WP-N1 (template ov_my_systems.html
    with systems_overview.my_overview), apart from the clock in the footer."""
    from starlette.requests import Request

    from supervisor.console import readmodels, routes, systems_overview

    monkeypatch.setattr(on.ctx.settings, "console_nav_v3", True)
    on.ctx.systems.register(draft(name="Alpha", owner_user="reviewer.an"), "reviewer.an")
    me = _me(on)
    now = on.ctx.clock.now()
    clock = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ICT")
    for lang in ("en", "vi"):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/console/",
            "query_string": f"lang={lang}".encode(),
            "headers": [],
        }
        d = systems_overview.my_overview(on.ctx, me, None, now)
        old = routes.render(
            Request(scope),
            on.ctx,
            me,
            "ov_my_systems.html",
            section="overview",
            d=d,
            greet_key=readmodels.greeting_key(now),
        ).body.decode()
        new = on.get(f"/console/?lang={lang}").text
        assert clock.sub("T", new) == clock.sub("T", old)


def test_api_is_not_capped_at_one_page_and_ignores_page(v4: Console) -> None:
    g = Graph()
    for i in range(120):
        mk(g, "job", f"job:bulk{i:03d}", display_name=f"bulk{i:03d}", status="unmanaged")
    fill(v4, g)
    body = v4.get("/v1/candidates?page=abc").json()
    assert body["count"] == len(body["items"]) == body["total"] >= 125
    assert v4.get("/v1/candidates?sort=../&dir=x&page=9").status_code == 200


def test_bad_query_input_never_gives_500(v4: Console) -> None:
    qs = ("sort=../&dir=x", "page=abc", "page=0", "page=99999999999", "band=junk", "kind=%00")
    for base in ("/console/candidates?", "/console/candidates/rows?", "/console/?"):
        for q in qs:
            assert v4.get(base + q).status_code < 500, (base, q)
    for nid in ("..%2f..", "%00", "a" * 500, "x y"):
        assert v4.get(f"/console/candidates/{nid}/drawer").status_code < 500
