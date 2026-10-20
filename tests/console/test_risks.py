"""WP29: /v1/risks routes (RBAC, audit, errors), the Risks page, the drawer and the Agent tab.

Both flags are off by default (HTTP 400 with the flag name, no nav entry). Viewer reads;
reviewer, owner and admin edit; every POST writes two console_action rows and a risk_change
chain record."""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.inventory.service import InventoryService
from supervisor.risk.service import RiskService
from tests.conftest import REPO_ROOT

from .conftest import Console

STARTERS = REPO_ROOT / "config" / "risks"
HX = {"HX-Request": "true"}
NEW = {
    "title": "API created risk",
    "category": "pii",
    "agent_id": "payments",
    "inherent_likelihood": 3,
    "inherent_impact": 4,
    "residual_likelihood": 2,
    "residual_impact": 3,
    "treatment": "mitigate",
    "owner": "Payments Ops",
    "review_date": "2027-04-20",
    "status": "active",
    "links": [{"kind": "rule", "target": "PAY-02"}],
}


@pytest.fixture
def risks_on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    s = console.ctx.settings
    for flag in ("risk_register_enabled", "console_risks_enabled", "inventory_enabled"):
        monkeypatch.setattr(s, flag, True)
    InventoryService.from_adapters(console.runtime.adapters).fill_manifests()
    return console


@pytest.fixture
def seeded_risks(risks_on: Console) -> Console:
    res = risks_on.ctx.risks.import_path(STARTERS, "test", source="starter")
    assert res.errors == []
    return risks_on


def _post(c: Console, url: str, body: Any, user: str = "reviewer.an") -> Any:
    return c.client.post(url, json=body, headers={"X-Dev-User": user})


def _outcome_rows(c: Console) -> list[dict[str, Any]]:
    return [
        r
        for r in c.ctx.tables.query("console_action", order_by=("ts",))
        if r["permission"].startswith("risks.")
    ]


# ---- off by default -------------------------------------------------------------------------


def test_off_by_default(console: Console) -> None:
    s = console.ctx.settings
    assert s.risk_register_enabled is False and s.console_risks_enabled is False
    for url in ("/v1/risks", "/v1/risks/RSK-X", "/v1/risks/agents/payments"):
        r = console.get(url)
        assert r.status_code == 400 and "RISK_REGISTER_ENABLED" in r.json()["error"], url
    r = console.get("/console/risks")
    assert r.status_code == 400 and "CONSOLE_RISKS_ENABLED" in r.text
    assert "/console/risks" not in console.get("/console/").text  # no nav entry
    assert console.get("/console/agents/payments/tab/risks", headers=HX).status_code == 400


def test_page_needs_both_flags(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_risks_enabled", True)
    r = console.get("/console/risks")
    assert r.status_code == 400 and "RISK_REGISTER_ENABLED" in r.text


# ---- routes ---------------------------------------------------------------------------------


def test_list_get_filters_and_scores(seeded_risks: Console) -> None:
    c = seeded_risks
    body = c.get("/v1/risks", user="viewer.hoa").json()
    assert body["count"] == 19 and body["illustrative_bands"] is True
    one = c.get("/v1/risks/RSK-PAY-001", user="viewer.hoa").json()
    assert (one["inherent_score"], one["inherent_band"]) == (20, "critical")
    assert one["links"] and one["agents"] == ["payments"] and one["evidence"] == []
    sub = c.get("/v1/risks?agent=credit_prequal&band=critical", user="viewer.hoa").json()
    assert all("credit_prequal" in r["agents"] for r in sub["risks"])
    shared = c.get("/v1/risks/RSK-SHR-001").json()
    assert shared["agents"] == ["credit_prequal", "customer_service", "payments"]
    s = c.get("/v1/risks/agents/payments").json()
    assert s["residual_level"] == "critical" and len(s["risks"]) == 8


def test_unknown_risk_is_404_and_bad_input_is_400(seeded_risks: Console) -> None:
    c = seeded_risks
    assert c.get("/v1/risks/RSK-NOPE").status_code == 404
    assert c.get("/v1/risks/RSK-NOPE/evidence").status_code == 404
    assert c.get("/v1/risks/bad%20id%3Cscript%3E").status_code == 400
    assert c.get("/v1/risks?band=purple").status_code == 400
    assert c.get("/v1/risks?nope=1").status_code == 400
    r = _post(c, "/v1/risks", {"title": "x"})
    assert r.status_code == 400 and "error" in r.json()
    assert _post(c, "/v1/risks/RSK-PAY-001", {"inherent_likelihood": 9}).status_code == 400
    assert _post(c, "/v1/risks/RSK-NOPE", {"owner": "x"}).status_code == 404
    assert (
        _post(c, "/v1/risks/RSK-PAY-001/links", {"kind": "rule", "target": "PAY-777"}).status_code
        == 400
    )
    assert _post(c, "/v1/risks/RSK-PAY-001/links", {"action": "drop"}).status_code == 400
    raw = c.client.post(
        "/v1/risks",
        content=b"[1,2]",
        headers={"X-Dev-User": "reviewer.an", "content-type": "application/json"},
    )
    assert raw.status_code == 400
    raw = c.client.post("/v1/risks", content=b"{not json", headers={"X-Dev-User": "reviewer.an"})
    assert raw.status_code == 400


@pytest.mark.parametrize(
    ("user", "may_edit"),
    [
        ("viewer.hoa", False),
        ("auditor.dung", False),
        ("operator.khanh", False),
        ("approver.em", False),
        ("reviewer.an", True),
        ("payops-lead@example.invalid", True),
        ("admin.chi", True),
    ],
)
def test_roles(seeded_risks: Console, user: str, may_edit: bool) -> None:
    c = seeded_risks
    assert c.get("/v1/risks", user=user).status_code == 200  # every role reads
    r = _post(c, "/v1/risks", NEW, user)
    assert (r.status_code == 201) is may_edit, (user, r.status_code, r.text[:200])
    if not may_edit:
        assert (
            r.status_code == 403
            and "risks.edit" not in r.text
            and "needs role" in r.json()["error"]
        )


def test_unknown_user_is_refused(seeded_risks: Console) -> None:
    assert seeded_risks.get("/v1/risks", user="nobody.at.all").status_code in (400, 403)


def test_create_update_link_write_two_audit_rows_and_a_chain_record(seeded_risks: Console) -> None:
    c = seeded_risks
    before = len(_outcome_rows(c))
    r = _post(c, "/v1/risks", NEW)
    assert r.status_code == 201, r.text
    rid = r.json()["risk_id"]
    rows = _outcome_rows(c)[before:]
    assert [x["outcome"] for x in rows] == ["attempted", "ok"]
    assert all(x["permission"] == "risks.edit" and x["actor"] == "reviewer.an" for x in rows)
    assert rows[1]["detail"] == f"create:{rid}"

    cur = c.get(f"/v1/risks/{rid}").json()
    up = _post(c, f"/v1/risks/{rid}", {"owner": "Someone Else", "row_version": 1})
    assert up.status_code == 200 and up.json()["owner"] == "Someone Else"
    rows = _outcome_rows(c)[before + 2 :]
    assert [x["outcome"] for x in rows] == ["attempted", "ok"]
    assert rows[0]["target_kind"] == "risk" and rows[0]["target_id"] == rid
    assert (
        rows[1]["before_hash"]
        and rows[1]["after_hash"]
        and rows[1]["before_hash"] != rows[1]["after_hash"]
    )
    assert cur["owner"] == "Payments Ops"

    stale = _post(c, f"/v1/risks/{rid}", {"owner": "Third", "row_version": 1})
    assert stale.status_code == 400 and "changed by someone else" in stale.json()["error"]

    ln = _post(
        c, f"/v1/risks/{rid}/links", {"action": "add", "kind": "monitor", "target": "oversight"}
    )
    assert ln.status_code == 200 and ln.json()["added"] is True
    assert {"kind": "monitor", "target": "oversight"} in c.get(f"/v1/risks/{rid}").json()["links"]
    rm = _post(
        c, f"/v1/risks/{rid}/links", {"action": "remove", "kind": "monitor", "target": "oversight"}
    )
    assert rm.json()["removed"] is True

    chained = [e for e in c.ctx.tables.query("chain_entry", {"record_type": "risk_change"})]
    assert (
        len(chained) >= 4
    )  # 19 imported + create, update, link, unlink (the import is chained too)
    assert any(e["record_ref"] == f"risk:{rid}" for e in chained)


def test_denied_post_is_audited_and_changes_nothing(seeded_risks: Console) -> None:
    c = seeded_risks
    n = len(c.ctx.risks.list_risks())
    r = _post(c, "/v1/risks", NEW, "viewer.hoa")
    assert r.status_code == 403
    denied = [x for x in _outcome_rows(c) if x["outcome"] == "denied"]
    assert denied and denied[-1]["actor"] == "viewer.hoa"
    assert len(c.ctx.risks.list_risks()) == n


def test_evidence_route_after_a_pass(seeded_risks: Console) -> None:
    c = seeded_risks
    out = c.ctx.risks.run_evidence()
    assert out["written"] == 19
    ev = c.get("/v1/risks/RSK-PAY-001/evidence").json()["evidence"]
    assert len(ev) == 1 and ev[0]["state"] in ("working", "no_evidence", "failing")
    assert isinstance(ev[0]["rule_hits"], int)


# ---- console --------------------------------------------------------------------------------


def test_page_lists_filters_and_shows_nav(seeded_risks: Console) -> None:
    c = seeded_risks
    r = c.get("/console/risks")
    assert r.status_code == 200, r.text[:300]
    t = r.text
    assert "RSK-PAY-001" in t and "ILLUSTRATIVE" in t and 'data-row="RSK-CRD-001"' in t
    assert "/console/risks" in c.get("/console/").text  # nav entry
    only = c.get("/console/risks?agent=credit_prequal&category=credit_decision").text
    assert "RSK-CRD-001" in only and "RSK-PAY-001" not in only
    rows = c.get("/console/risks/rows?band=critical", headers=HX)
    assert rows.status_code == 200 and "<html" not in rows.text and "RSK-PAY-001" in rows.text
    assert "RSK-SVC-001" not in rows.text
    assert c.get("/console/risks?owner=Payments%20Ops").status_code == 200


def test_page_input_errors_are_400(seeded_risks: Console) -> None:
    c = seeded_risks
    for q in ("band=purple", "category=x", "agent=a%20b", "status=zzz", "page=99", "page=abc"):
        assert c.get(f"/console/risks?{q}").status_code == 400, q
    assert c.get("/console/risks/NOPE/drawer").status_code == 400
    assert c.get("/console/risks/RSK-PAY-001/drawer?tab=zzz").status_code == 400


def test_sort_and_pager(seeded_risks: Console) -> None:
    c = seeded_risks
    html = c.get("/console/risks?sort=risk_id&dir=asc").text
    ids = re.findall(r'data-row="(RSK-[A-Z]+-\d+)"', html)
    assert ids == sorted(ids) and len(ids) == 19
    assert c.get("/console/risks?sort=nope").status_code == 200  # unknown column: default order


@pytest.mark.parametrize("tab", ["details", "links", "evidence"])
def test_drawer_tabs(seeded_risks: Console, tab: str) -> None:
    c = seeded_risks
    c.ctx.risks.run_evidence()
    r = c.get(f"/console/risks/RSK-PAY-001/drawer?tab={tab}", headers=HX)
    assert r.status_code == 200 and "<html" not in r.text and "RSK-PAY-001" in r.text
    if tab == "links":
        assert "PAY-02" in r.text and "VN-QD33-2026-PL4.1-02" in r.text
    if tab == "evidence":
        assert "<table" in r.text
    full = c.get(f"/console/risks?drawer=RSK-PAY-001&dtab={tab}")  # no-JS fallback
    assert full.status_code == 200 and 'id="drawer-title"' in full.text


def test_drawer_in_vietnamese(seeded_risks: Console) -> None:
    r = seeded_risks.get("/console/risks?lang=vi&drawer=RSK-PAY-001")
    assert r.status_code == 200 and "Rủi ro" in r.text


def test_agent_tab(seeded_risks: Console) -> None:
    c = seeded_risks
    page = c.get("/console/agents/payments")
    assert 'data-tab="risks"' in page.text
    tab = c.get("/console/agents/payments/tab/risks", headers=HX)
    assert tab.status_code == 200 and "<html" not in tab.text
    assert "RSK-PAY-001" in tab.text and "RSK-SHR-001" in tab.text  # own and inherited
    assert "RSK-CRD-001" not in tab.text
    assert (
        tab.text.strip()
        in page.text.split('id="tab-body"', 1)[0] + c.get("/console/agents/payments?tab=risks").text
    )


def test_agent_tab_hidden_when_the_page_flag_is_off(
    risks_on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(risks_on.ctx.settings, "console_risks_enabled", False)
    assert 'data-tab="risks"' not in risks_on.get("/console/agents/payments").text
    assert risks_on.get("/console/agents/payments/tab/risks", headers=HX).status_code == 400


def test_agent_tab_with_the_register_off(
    risks_on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(risks_on.ctx.settings, "risk_register_enabled", False)
    tab = risks_on.get("/console/agents/payments/tab/risks", headers=HX)
    assert tab.status_code == 200 and "RISK_REGISTER_ENABLED" in tab.text


def test_workspace_fixture_unmanaged_items_do_not_break_the_page(
    seeded_risks: Console, tmp_path: Any
) -> None:
    allow = tmp_path / "allow.yaml"
    allow.write_text("apps:\n  - bi-portal\n", encoding="utf-8")
    seeded_risks.ctx.settings.inventory_allowlist_file = allow
    InventoryService.from_adapters(seeded_risks.runtime.adapters).refresh_workspace(
        FixtureWorkspaceReader.from_file(
            REPO_ROOT / "tests" / "fixtures" / "inventory" / "workspace_7.json"
        )
    )
    assert seeded_risks.get("/console/risks").status_code == 200
    assert isinstance(seeded_risks.ctx.risks, RiskService)


# ---- review (WP29): more bad calls, viewer writes, no lowering through the route ------------


@pytest.mark.parametrize(
    ("url", "body"),
    [
        ("/v1/risks", {**NEW, "links": "PAY-02"}),
        ("/v1/risks", {**NEW, "links": [{"kind": "rule"}]}),
        ("/v1/risks", {**NEW, "links": [{"kind": "rule", "target": 7}]}),
        ("/v1/risks", {**NEW, "links": [{"kind": "zzz", "target": "PAY-02"}]}),
        ("/v1/risks", {**NEW, "risk_id": 12}),
        ("/v1/risks", {**NEW, "risk_id": "bad id"}),
        ("/v1/risks", {**NEW, "inherent_likelihood": True}),
        ("/v1/risks", {**NEW, "inherent_likelihood": 3.0}),
        ("/v1/risks", {**NEW, "review_date": "tomorrow"}),
        ("/v1/risks", {**NEW, "agent_id": "a b"}),
        ("/v1/risks", {**NEW, "title": "x" * 5000}),
        ("/v1/risks/RSK-PAY-001", {"row_version": "1"}),
        ("/v1/risks/RSK-PAY-001", {"risk_id": "RSK-OTHER"}),
        ("/v1/risks/RSK-PAY-001", {"source": "starter"}),
        ("/v1/risks/RSK-PAY-001", {"residual_likelihood": 5, "residual_impact": 5}),
        ("/v1/risks/RSK-PAY-001", {"status": "gone"}),
        ("/v1/risks/RSK-PAY-001/links", {"kind": "rule", "target": None}),
        ("/v1/risks/RSK-PAY-001/links", {"kind": ["rule"], "target": "PAY-02"}),
        ("/v1/risks/RSK-PAY-001/links", {"action": None, "kind": "rule", "target": "PAY-02"}),
        ("/v1/risks/bad%20id/links", {"kind": "rule", "target": "PAY-02"}),
    ],
)
def test_bad_bodies_are_400(seeded_risks: Console, url: str, body: Any) -> None:
    r = _post(seeded_risks, url, body)
    assert r.status_code == 400, (url, body, r.status_code, r.text[:200])
    assert "error" in r.json()


def test_oversized_body_is_refused_not_500(seeded_risks: Console) -> None:
    big = {**NEW, "description": "x" * 70_000}
    r = _post(seeded_risks, "/v1/risks", big)
    assert r.status_code in (400, 413), r.status_code


def test_bad_agent_id_on_the_agent_route_is_400(seeded_risks: Console) -> None:
    assert seeded_risks.get("/v1/risks/agents/a%20b").status_code == 400
    assert seeded_risks.get("/v1/risks/agents/nobody").status_code == 200  # no risks, no error


@pytest.mark.parametrize(
    ("url", "body"),
    [
        ("/v1/risks/RSK-PAY-001", {"owner": "viewer"}),
        ("/v1/risks/RSK-PAY-001/links", {"action": "remove", "kind": "rule", "target": "PAY-02"}),
    ],
)
def test_viewer_cannot_write_through_any_route(seeded_risks: Console, url: str, body: Any) -> None:
    c = seeded_risks
    before = c.get("/v1/risks/RSK-PAY-001").json()
    r = _post(c, url, body, "viewer.hoa")
    assert r.status_code == 403
    denied = [x for x in _outcome_rows(c) if x["outcome"] == "denied"]
    assert denied and denied[-1]["actor"] == "viewer.hoa"
    after = c.get("/v1/risks/RSK-PAY-001").json()
    assert (after["owner"], after["links"], after["row_version"]) == (
        before["owner"],
        before["links"],
        before["row_version"],
    )


def test_link_route_audits_before_and_after_hashes(seeded_risks: Console) -> None:
    c = seeded_risks
    n = len(_outcome_rows(c))
    r = _post(
        c, "/v1/risks/RSK-PAY-001/links", {"action": "add", "kind": "monitor", "target": "drift"}
    )
    assert r.status_code == 200
    att, out = _outcome_rows(c)[n:]
    assert (att["outcome"], out["outcome"]) == ("attempted", "ok")
    assert out["before_hash"] and out["after_hash"] and out["before_hash"] != out["after_hash"]


def test_update_route_cannot_lower_the_residual_without_evidence(seeded_risks: Console) -> None:
    c = seeded_risks
    r = _post(c, "/v1/risks/RSK-PAY-001", {"residual_likelihood": 1, "residual_impact": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["declared_residual_score"] == 1
    assert body["residual_score"] == body["inherent_score"] == 20
