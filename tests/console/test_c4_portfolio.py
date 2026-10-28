# ruff: noqa: F811
"""WP-C4: portfolio blocks on My overview (OVERVIEW_PORTFOLIO) and GET /v1/portfolio.

Off path first (My overview unchanged, the route answers 400 overview_portfolio_off), then the
numbers (equal to the two summary services and APIs on a seeded store), the integer percents, the
50-row cap of the grid, the click links, the outcome filter of the systems list, the page without
script, and the RBAC row."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from typing import Any

import pytest

from supervisor.app import app
from supervisor.console import portfolio
from supervisor.core import rbac
from supervisor.governance import risk_dimensions as rd
from tests.governance.conftest import draft, mounted, on, restore_app  # noqa: F401  (fixtures)

from .conftest import Console

CREATOR = "reviewer.an"
FLAGS = ("console_nav_v3", "console_overview_v4", "overview_portfolio")
NOW = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)


def main(html: str) -> str:
    return html.split('id="main"', 1)[1].split("</main>", 1)[0]


@pytest.fixture
def pf(on: Console, monkeypatch: pytest.MonkeyPatch) -> Iterator[Console]:  # noqa: F811
    from supervisor.console.portfolio_routes import api_router

    for f in FLAGS:
        monkeypatch.setattr(on.ctx.settings, f, True)
    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(api_router)
    try:
        yield on
    finally:
        restore_app(app, saved, lifespan)


@pytest.fixture
def pfall(pf: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(pf.ctx.settings, "classification_v2", True)
    monkeypatch.setattr(pf.ctx.settings, "risk_dimensions", True)
    return pf


def _system(c: Console, name: str) -> str:
    s = c.ctx.systems.register(draft(name=name), CREATOR)
    return str(s["system_id"])


def _classify(c: Console, sid: str, outcome: str, *, approved: bool = True, n: int = 1) -> None:
    c.ctx.state.insert(
        "classification_v2",
        {
            "classification_id": f"{sid}-c{n}",
            "system_id": sid,
            "outcome": outcome,
            "path_json": [],
            "tree_sha256": "0" * 64,
            "path_hash": "0" * 64,
            "decided_by": "reviewer.an",
            "approved_by": "approver.em" if approved else None,
            "approved_at": NOW if approved else None,
            "inherited_from_provider": False,
            "valid_until": NOW + dt.timedelta(days=365),
            "created_at": NOW + dt.timedelta(seconds=n),
        },
    )


def _rows(c: Console, sid: str) -> None:
    rd.ensure_rows(rd.Env.from_console(c.ctx), c.ctx.systems.get(sid))


def _set(c: Console, sid: str, dim: str, status: str, valid_until: str | None = None) -> None:
    key = {"status_id": rd.status_id(sid, dim)}
    row = c.ctx.state.get("risk_dimension_status", key)
    c.ctx.state.update(
        "risk_dimension_status",
        key,
        {"status": status, "valid_until": valid_until},
        int(row["row_version"]),
    )


@pytest.fixture
def seeded_pf(pfall: Console) -> Console:
    """Seven systems: every outcome once, one unapproved record, one without a record."""
    c = pfall
    ids = {o: _system(c, f"Sys {o}") for o in ("prohibited", "high_certify", "high_self", "medium")}
    ids["low"] = _system(c, "Sys low")
    ids["waiting"] = _system(c, "Sys waiting")
    ids["bare"] = _system(c, "Sys bare")
    for o in ("prohibited", "high_certify", "high_self", "medium", "low"):
        _classify(c, ids[o], o)
    _classify(c, ids["waiting"], "low", approved=False)
    for sid in ids.values():
        _rows(c, sid)
    _set(c, ids["prohibited"], "model", "fail")
    _set(c, ids["prohibited"], "ethics", "fail")
    _set(c, ids["high_certify"], "model", "pass")
    _set(c, ids["high_self"], "model", "in_progress")
    _set(c, ids["medium"], "ethics", "waived")
    _set(c, ids["low"], "reputation", "not_applicable")
    _set(c, ids["low"], "model", "pass", valid_until="2026-01-01")  # past valid_until
    _set(c, ids["medium"], "model", "pass", valid_until="2026-02-01")  # past valid_until
    c.ids = ids  # type: ignore[attr-defined]
    return c


# ------------------------------------------------------------------ off path


def test_flag_default_is_off() -> None:
    from supervisor.config import load_settings

    assert load_settings(sql_backend="sqlite").overview_portfolio is False


def test_route_is_400_while_off(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from supervisor.console.portfolio_routes import api_router

    monkeypatch.setattr(on.ctx.settings, "console_overview_v4", True)
    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(api_router)
    try:
        assert on.ctx.settings.overview_portfolio is False
        r = on.get("/v1/portfolio")
        assert r.status_code == 400 and "overview_portfolio_off" in r.text
    finally:
        restore_app(app, saved, lifespan)


def test_route_is_not_mounted_without_overview_v4() -> None:
    assert "/v1/portfolio" not in {getattr(r, "path", "") for r in app.router.routes}


def test_my_overview_unchanged_while_off(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    for f in ("console_nav_v3", "console_overview_v4"):
        monkeypatch.setattr(on.ctx.settings, f, True)
    monkeypatch.setattr(on.ctx.settings, "classification_v2", True)
    monkeypatch.setattr(on.ctx.settings, "risk_dimensions", True)

    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("a portfolio builder ran with the flag off")

    monkeypatch.setattr(portfolio, "block_data", boom)
    html = on.get("/console/?scope=all&lang=en").text
    assert 'data-version="4"' in html
    assert "pf-wrap" not in html and "data-portfolio" not in html


def test_flag_needs_overview_v4_and_governance(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    s = on.ctx.settings
    monkeypatch.setattr(s, "overview_portfolio", True)
    assert portfolio.enabled(s) is False  # CONSOLE_OVERVIEW_V4 is off
    monkeypatch.setattr(s, "console_overview_v4", True)
    assert portfolio.enabled(s) is True
    monkeypatch.setattr(s, "governance_enabled", False)
    assert portfolio.enabled(s) is False


# ------------------------------------------------------------------ the blocks say "turn on"


def test_blocks_show_a_turn_on_note_without_their_flags(pf: Console) -> None:
    _system(pf, "Only one")
    html = main(pf.get("/console/?scope=all&lang=en").text)
    assert 'data-off="classification"' in html and "CLASSIFICATION_V2" in html
    assert 'data-off="risk"' in html and "RISK_DIMENSIONS" in html
    body = pf.get("/v1/portfolio").json()
    assert body == {"classification": {"on": False}, "risk": {"on": False}}


# ------------------------------------------------------------------ numbers


def test_classification_counts_equal_the_summary_api(seeded_pf: Console) -> None:
    c = seeded_pf
    api = c.get("/v1/classification/summary").json()
    block = c.get("/v1/portfolio").json()["classification"]
    assert block["systems_n"] == api["systems_n"] == 7
    got = {b["outcome"]: b["count"] for b in block["bars"]}
    assert {k: v for k, v in got.items() if k != "none"} == api["counts"]
    assert got["none"] == api["systems_n"] - api["approved_n"] == 2  # waiting + no record
    assert sum(got.values()) == api["systems_n"]
    assert block["waiting_for_approval_n"] == api["waiting_for_approval_n"] == 1
    assert block["review_due_n"] == api["review_due_n"]
    assert got["prohibited"] == got["high_certify"] == got["high_self"] == got["medium"] == 1
    assert [b["outcome"] for b in block["bars"]][:5] == [
        "prohibited", "high_certify", "high_self", "medium", "low"
    ]  # fmt: skip


def test_percents_are_integers_and_add_up(seeded_pf: Console) -> None:
    bars = seeded_pf.get("/v1/portfolio").json()["classification"]["bars"]
    assert all(isinstance(b["pct"], int) for b in bars)
    assert sum(b["pct"] for b in bars) == 100
    assert {b["pct"] for b in bars} <= {0, 14, 15, 28, 29}  # 1/7 and 2/7 by largest remainder


@pytest.mark.parametrize(
    ("counts", "total", "want"),
    [
        ([1, 1, 1], 3, [34, 33, 33]),
        ([0, 0], 0, [0, 0]),
        ([5], 5, [100]),
        ([2, 1], 3, [67, 33]),
        ([1, 0, 0], 1, [100, 0, 0]),
    ],
)
def test_percents_unit(counts: list[int], total: int, want: list[int]) -> None:
    got = portfolio.percents(counts, total)
    assert got == want and all(isinstance(x, int) for x in got)


def test_risk_totals_equal_the_summary_api(seeded_pf: Console) -> None:
    c = seeded_pf
    api = c.get("/v1/risk-dimensions/summary").json()
    block = c.get("/v1/portfolio").json()["risk"]
    assert block["systems_n"] == api["systems"] == 7
    by_dim = {d["dimension_id"]: d for d in block["dimensions"]}
    assert list(by_dim) == [d["dimension_id"] for d in api["dimensions"]] == block["dimension_ids"]
    assert len(by_dim) == 8
    for d in api["dimensions"]:
        got = by_dim[d["dimension_id"]]
        assert got["pass"] == d["pass"] and got["fail"] == d["fail"]
        assert got["waived"] == d["waived"] and got["not_applicable"] == d["not_applicable"]
        assert got["open"] == d["not_started"] + d["in_progress"]
        assert sum(got[k] for k in ("pass", "open", "fail", "waived", "not_applicable")) == 7
    assert by_dim["model"]["fail"] == 1 and by_dim["model"]["pass"] == 3
    assert by_dim["model"]["open"] == 3
    assert block["past_valid_until_n"] == 2


def test_grid_cells_and_order(seeded_pf: Console) -> None:
    c = seeded_pf
    rows = c.get("/v1/portfolio").json()["risk"]["rows"]
    assert len(rows) == 7
    first = rows[0]  # two failed types: first
    assert first["system_id"] == c.ids["prohibited"] and first["fail_n"] == 2  # type: ignore[attr-defined]
    assert first["cells"]["model"] == "fail" and first["cells"]["ethics"] == "fail"
    assert first["cells"]["cybersecurity"] == "not_started"
    assert all(len(r["cells"]) == 8 for r in rows)


def test_grid_is_capped_at_50_rows(pfall: Console) -> None:
    c = pfall
    for i in range(55):
        _system(c, f"Bulk {i:02d}")
    risk = c.get("/v1/portfolio").json()["risk"]
    assert risk["systems_n"] == 55 and risk["rows_total"] == 55
    assert len(risk["rows"]) == portfolio.GRID_ROWS == 50 and risk["more_n"] == 5
    assert all(sum(d[k] for k in ("pass", "open", "fail", "waived", "not_applicable")) == 55
               for d in risk["dimensions"])  # fmt: skip
    html = main(c.get("/console/?scope=all&lang=en").text)
    assert html.count("data-system=") == 50
    assert 'data-more="5"' in html and "Showing 50 of 55" in html


def test_page_blocks_equal_the_api_for_scope_all(seeded_pf: Console) -> None:
    c = seeded_pf
    html = main(c.get("/console/?scope=all&lang=en").text)
    api = c.get("/v1/portfolio").json()
    for b in api["classification"]["bars"]:
        assert re.search(
            rf'data-outcome="{b["outcome"]}" data-count="{b["count"]}" data-pct="{b["pct"]}"', html
        ), b
    assert f'data-past="{api["risk"]["past_valid_until_n"]}"' in html
    for d in api["risk"]["dimensions"]:
        for key in ("pass", "open", "fail", "waived", "not_applicable"):
            tot = re.search(rf'<tr data-total="{key}">(.*?)</tr>', html, re.S)
            assert tot and f'data-dim="{d["dimension_id"]}">{d[key]}<' in tot.group(1)


def test_scope_narrows_both_blocks(seeded_pf: Console) -> None:
    c = seeded_pf
    other = c.ctx.systems.register(
        draft(name="Other owner", owner_user="someone.else"), "admin.chi"
    )
    _classify(c, str(other["system_id"]), "low")
    mine = main(c.get("/console/?scope=my&lang=en").text)
    allp = main(c.get("/console/?scope=all&lang=en").text)
    assert mine.count("data-system=") <= allp.count("data-system=") == 8


# ------------------------------------------------------------------ click links


def test_bars_and_cells_link_to_the_pages(seeded_pf: Console) -> None:
    c = seeded_pf
    html = main(c.get("/console/?scope=all&lang=en").text)
    for o in ("prohibited", "high_certify", "high_self", "medium", "low", "not_system", "none"):
        assert f'href="/console/systems?outcome={o}&amp;lang=en"' in html, o
    sid = c.ids["prohibited"]  # type: ignore[attr-defined]
    assert f'href="/console/systems/{sid}?tab=riskdim&amp;lang=en"' in html
    assert f'href="/console/systems/{sid}?lang=en"' in html
    tab = c.get(f"/console/systems/{sid}?tab=riskdim&lang=en")
    assert tab.status_code == 200


def test_systems_list_filters_by_outcome(seeded_pf: Console) -> None:
    c = seeded_pf
    ids = c.ids  # type: ignore[attr-defined]

    def shown(outcome: str) -> set[str]:
        r = c.get(f"/console/systems?outcome={outcome}&lang=en")
        assert r.status_code == 200, outcome
        return {sid for sid in ids.values() if f"/console/systems/{sid}" in main(r.text)}

    assert shown("prohibited") == {ids["prohibited"]}
    assert shown("high_certify") == {ids["high_certify"]}
    assert shown("none") == {ids["waiting"], ids["bare"]}  # no approved record
    assert shown("low") == {ids["low"]}  # the unapproved "low" record does not count
    page = c.get("/console/systems?outcome=prohibited&lang=en").text
    assert 'data-outcome-filter="prohibited"' in page
    rows = c.get("/console/systems/rows?outcome=medium&lang=en")
    assert rows.status_code == 200 and ids["medium"] in rows.text and ids["low"] not in rows.text


def test_systems_list_outcome_filter_errors_are_400(
    pf: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    _system(pf, "One")
    off = pf.get("/console/systems?outcome=low&lang=en")  # CLASSIFICATION_V2 is off
    assert off.status_code == 400 and "classification_v2_off" in off.text
    monkeypatch.setattr(pf.ctx.settings, "classification_v2", True)
    bad = pf.get("/console/systems?outcome=bogus&lang=en")
    assert bad.status_code == 400 and "outcome must be one of" in bad.text
    assert pf.get("/console/systems?outcome=bad%20%3Cx%3E&lang=en").status_code == 400
    assert pf.get("/console/systems?lang=en").status_code == 200  # no filter: as before


# ------------------------------------------------------------------ page quality


def test_blocks_have_no_script_and_both_languages(seeded_pf: Console) -> None:
    c = seeded_pf
    en = main(c.get("/console/?scope=all&lang=en").text)
    block = en.split("data-portfolio", 1)[1].split('<div class="ov4-mid">', 1)[0]
    assert "<script" not in block and " onclick=" not in block and "javascript:" not in block
    assert "Classification" in block and "Risk assessment" in block and "Not classified" in block
    vi = main(c.get("/console/?scope=all&lang=vi").text)
    assert "Chưa phân loại" in vi and "Đánh giá rủi ro" in vi and "pf_" not in vi


def test_keys_exist_in_both_languages() -> None:
    from supervisor.console import i18n
    from supervisor.console.i18n_portfolio import PF

    for key, (en, vi) in PF.items():
        assert en and vi and i18n._T[key] == (en, vi), key  # noqa: SLF001


def test_numbers_are_integers_in_the_api(seeded_pf: Console) -> None:
    body = seeded_pf.get("/v1/portfolio").json()

    def walk(x: Any) -> Iterator[Any]:
        if isinstance(x, dict):
            for v in x.values():
                yield from walk(v)
        elif isinstance(x, list):
            for v in x:
                yield from walk(v)
        else:
            yield x

    assert not [v for v in walk(body) if isinstance(v, float)]


# ------------------------------------------------------------------ RBAC


def test_rbac_row_and_roles(seeded_pf: Console) -> None:
    assert rbac.ROUTES[("GET", "/v1/portfolio")] == "systems.view"
    for user in ("viewer.hoa", "reviewer.an", "admin.chi"):
        assert seeded_pf.get("/v1/portfolio", user=user).status_code == 200, user
