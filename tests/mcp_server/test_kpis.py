"""WP-G6 KPIs: one function for GET /v1/kpis, the MCP tool kpis and the Governance overview."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.config import REPO_ROOT
from supervisor.governance import kpis
from supervisor.governance.kpis import bp

from .conftest import Rig
from .test_tools_library_supervisor import _draft

ADMIN = {"X-Dev-User": "admin.chi"}


def person(user_id: str, *roles: str) -> AuthPrincipal:
    return AuthPrincipal(user_id, "user", "dev_header", frozenset(roles), user_id)


def make(rig: Rig, name: str, **over: Any) -> str:
    return str(
        rig.ctx.systems.register(
            {**_draft(), "owner_user": "reviewer.an", "name": name, **over}, "reviewer.an"
        )["system_id"]
    )


def floats(v: Any) -> list[Any]:
    if isinstance(v, float):
        return [v]
    if isinstance(v, dict):
        return [x for i in v.values() for x in floats(i)]
    if isinstance(v, list):
        return [x for i in v for x in floats(i)]
    return []


def test_bp_rounds_down_and_guards_zero() -> None:
    assert bp(1, 3) == 3333 and bp(3, 3) == 10000 and bp(0, 5) == 0
    assert bp(1, 0) is None


def test_an_empty_store_gives_zeros_and_none_with_reasons(rig: Rig) -> None:
    me = person("reviewer.an", "reviewer")
    k = kpis.compute(rig.ctx, me)
    assert k["coverage"]["systems_total"] == 0
    assert k["coverage"]["classification_rate_bp"] is None
    assert k["coverage"]["systems_by_risk"]["high"] == 0
    assert k["speed"]["avg_days_per_stage"] == {} and k["speed"]["automation"]["rule_runs"] == 0
    assert k["unavailable"]["implementation_per_policy_bp"] == "no_obligations"
    assert k["unavailable"]["risk_treatment_coverage_bp"] == "no_active_risks"
    assert not floats(k)


def test_the_figures_of_a_small_world(rig: Rig) -> None:
    a = make(rig, "Alpha", user_segment="customer", personal_data="identifiable")
    b = make(rig, "Beta")
    rig.ctx.state.update(
        "ai_system",
        {"system_id": a},
        {"decision33_class": "not_high_risk"},
        rig.ctx.state.get("ai_system", {"system_id": a})["row_version"],
    )
    rig.ctx.systems.link(a, "agent", "payments", "reviewer.an")
    rig.ctx.rules.run(a, "reviewer.an")
    me = person("reviewer.an", "reviewer")
    k = kpis.compute(rig.ctx, me)
    cov = k["coverage"]
    assert cov["systems_total"] == 2
    assert cov["classification_rate_bp"] == 5000  # one of two
    assert sum(cov["systems_by_stage"].values()) == 2 and cov["systems_by_stage"]["initiation"] == 2
    assert sum(cov["systems_by_risk"].values()) == 2
    assert cov["assets_by_kind"]["agent"] >= 1
    # Alpha has customer personal data: the rules assigned obligations to it, Beta has none
    assert cov["policy_coverage_bp"] == 5000
    assert k["quality"]["implementation_per_policy_bp"] is not None
    assert [r["system_id"] for r in k["quality"]["implementation_by_system"]] == [a]
    assert 0 <= k["quality"]["implementation_by_system"][0]["bp"] <= 10000
    assert k["speed"]["automation"]["rule_runs"] >= 1  # the run above, on the chain
    assert b != a and not floats(k)


def test_the_scope_is_the_scope_of_g0(rig: Rig) -> None:
    a = make(rig, "Alpha")
    make(rig, "Beta")
    rig.ctx.systems.add_member(a, "viewer.hoa", "technical_specialist", "reviewer.an")
    viewer = person("viewer.hoa", "viewer")
    assert kpis.compute(rig.ctx, viewer)["coverage"]["systems_total"] == 1
    nobody = person("nobody.xyz", "viewer")
    assert kpis.compute(rig.ctx, nobody)["coverage"]["systems_total"] == 0
    assert (
        kpis.compute(rig.ctx, person("auditor.dung", "auditor"))["coverage"]["systems_total"] == 2
    )


def test_speed_from_applied_stage_approvals(rig: Rig) -> None:
    a = make(rig, "Alpha")
    now = rig.ctx.clock.now()
    for n, days in enumerate((2, 4)):
        rig.ctx.state.insert(
            "stage_approval",
            {
                "approval_id": f"sa_{n}",
                "system_id": a,
                "from_stage": "initiation",
                "to_stage": "design",
                "requested_by": "reviewer.an",
                "status": "approved",
                "decided_by": "approver.em",
                "created_at": now - dt.timedelta(days=days + 1),
                "decided_at": now - dt.timedelta(days=1),
                "applied_at": now - dt.timedelta(days=1) + dt.timedelta(seconds=1),
            },
        )
    k = kpis.compute(rig.ctx, person("reviewer.an", "reviewer"))
    assert k["speed"]["avg_days_per_stage"] == {"initiation": 3}


def test_automation_counts_governance_events(rig: Rig) -> None:
    a = make(rig, "Alpha")
    now = rig.ctx.clock.now()
    for n, (status, actions) in enumerate(
        (("done", [{"action": "create_incident", "status": "done"}]),
         ("done", [{"action": "notify_owner", "status": "failed_final"},
                   {"action": "create_review", "status": "done"}]),
         ("started", [{"action": "x", "status": "attempting"}]))
    ):  # fmt: skip
        rig.ctx.state.insert(
            "governance_event",
            {
                "event_key": f"k{n}",
                "kind": "alert",
                "severity": "high",
                "agent_id": "payments",
                "system_id": a,
                "ref": "alert:x",
                "event_at": now,
                "status": status,
                "rules": [],
                "actions": actions,
                "started_at": now,
            },
        )
    auto = kpis.compute(rig.ctx, person("reviewer.an", "reviewer"))["speed"]["automation"]
    assert auto["events"] == 3 and auto["events_done"] == 2
    assert auto["actions_ok"] == 2 and auto["actions_failed"] == 1
    assert auto["action_success_bp"] == 6666


def test_quality_with_the_starter_risks_and_controls(rig: Rig) -> None:
    rig.ctx.risks.import_path(REPO_ROOT / "config" / "risks", "reviewer.an")
    rig.ctx.controls.import_path(REPO_ROOT / "config" / "controls", "reviewer.an")
    a = make(rig, "Alpha")
    rig.ctx.systems.link(a, "agent", "payments", "reviewer.an")
    k = kpis.compute(rig.ctx, person("reviewer.an", "reviewer"))
    q = k["quality"]
    assert q["risk_treatment_coverage_bp"] is not None
    assert 0 <= q["risk_treatment_coverage_bp"] <= 10000
    assert 0 <= q["acceptable_residual_bp"] <= 10000
    assert "risk_treatment_coverage_bp" not in k["unavailable"]
    assert isinstance(k["speed"]["overdue_tasks"], int)


def test_a_figure_that_cannot_be_computed_says_why(rig: Rig) -> None:
    make(rig, "Alpha")
    s = rig.ctx.settings
    s.risk_register_enabled = False
    s.controls_enabled = False
    k = kpis.compute(rig.ctx, person("reviewer.an", "reviewer"))
    assert k["quality"]["risk_treatment_coverage_bp"] is None
    assert k["unavailable"]["risk_treatment_coverage_bp"] == "risk_register_off"
    assert k["unavailable"]["control_readiness_bp"] == "controls_off"
    assert (
        k["speed"]["overdue_tasks"] is None and k["unavailable"]["overdue_tasks"] == "controls_off"
    )


# ------------------------------------------------------------------------ the endpoint


def test_the_endpoint_returns_the_same_figures(rig: Rig) -> None:
    make(rig, "Alpha")
    r = rig.console.client.get("/v1/kpis", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    me = rig.ctx.provider.users["admin.chi"]
    want = kpis.compute(rig.ctx, me)
    body.pop("generated_at"), want.pop("generated_at")
    assert body == want and body["coverage"]["systems_total"] == 1
    assert set(body) == {"coverage", "quality", "speed", "unavailable"}
    assert not floats(body)


def test_the_endpoint_is_scoped_and_open_to_every_role_with_console_view(rig: Rig) -> None:
    make(rig, "Alpha")
    viewer = rig.console.client.get("/v1/kpis", headers={"X-Dev-User": "viewer.hoa"})
    assert viewer.status_code == 200 and viewer.json()["coverage"]["systems_total"] == 0
    assert (
        rig.console.client.get("/v1/kpis", headers={"X-Dev-User": "ghost.user"}).status_code == 400
    )
    rig.ctx.settings.governance_enabled = False
    off = rig.console.client.get("/v1/kpis", headers=ADMIN)
    assert off.status_code == 400 and "GOVERNANCE_ENABLED" in off.json()["error"]


# ------------------------------------------------------------------------ the overview


def test_the_governance_overview_reads_the_same_function(rig: Rig) -> None:
    from supervisor.console import systems_overview

    make(rig, "Alpha")
    me = rig.ctx.provider.users["reviewer.an"]
    now = dt.datetime.now(dt.UTC)
    d = systems_overview.governance_overview(rig.ctx, me, "all", now)
    want = kpis.compute(rig.ctx, me, now)
    assert d["kpis"] == want


@pytest.mark.parametrize(
    ("lang", "title"), [("en", "Governance KPIs"), ("vi", "Chỉ số KPI quản trị")]
)
def test_the_overview_page_shows_the_block_in_both_languages(
    rig: Rig, lang: str, title: str
) -> None:
    s = rig.ctx.settings
    s.console_nav_v3 = True
    s.console_systems_enabled = True
    make(rig, "Alpha")
    r = rig.console.get(f"/console/governance?lang={lang}&scope=all", user="admin.chi")
    assert r.status_code == 200, r.text[:300]
    assert 'data-section="kpis"' in r.text and title in r.text
    for table in ("kpi-coverage", "kpi-quality", "kpi-speed"):
        assert f'data-table="{table}"' in r.text
    assert "g6_" not in r.text  # every key has a text


def test_the_overview_page_has_no_block_with_the_flag_off(rig: Rig) -> None:
    s = rig.ctx.settings
    s.console_nav_v3 = True
    s.mcp_server_enabled = False
    r = rig.console.get("/console/governance?lang=en&scope=all", user="admin.chi")
    assert r.status_code == 200 and 'data-section="kpis"' not in r.text


def test_every_i18n_key_of_g6_has_both_languages() -> None:
    from supervisor.console import i18n

    table = {k: v for k, v in i18n.table().items() if k.startswith("g6_")}
    assert len(table) >= 25
    for key, (en, vi) in table.items():
        assert en.strip() and vi.strip() and en != vi, key


def test_the_docs_name_the_flag_and_the_skills_exist() -> None:
    doc = (Path(__file__).resolve().parents[2] / "docs" / "mcp-server.md").read_text("utf-8")
    assert "MCP_SERVER_ENABLED" in doc and "GET /v1/kpis" in doc
