"""Plan picks capabilities by risk class; the generated policy validates with the gateway
loader; the gateway with that policy stops each agent's planted demo incident."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.demo import replay as R
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import Policy, StaticPolicyProvider, parse_policy_text
from supervisor.jobs import bootstrap_schema
from supervisor.onboard.discover import Discovery
from supervisor.onboard.instrument import render_policy, validate_policy
from supervisor.onboard.models import AgentProfile, MonitoringPlan
from supervisor.onboard.plan import APPROVER_PLACEHOLDERS, plan
from supervisor_agents.common.world import BankWorld
from tests.gateway.conftest import T0, MemoryEvidence, assert_no_floats
from tests.onboard.conftest import AGENT_IDS


@pytest.fixture(scope="module")
def plans(
    discoveries: dict[str, Discovery], profiles: dict[str, AgentProfile]
) -> dict[str, MonitoringPlan]:
    return {a: plan(discoveries[a].inventory, profiles[a])[0] for a in AGENT_IDS}


def test_capabilities_by_risk_class(plans: dict[str, MonitoringPlan]) -> None:
    pay, credit, svc = (set(plans[a].on_ids) for a in AGENT_IDS)
    always = {"approved_tools", "pii_masking", "injection_prefilter", "evidence_chain"}
    for s in (pay, credit, svc):
        assert always | {"case_files"} <= s
        assert "proxy_log" not in s  # in-process gate hook plug point
    assert {"split_payment", "single_limit", "daily_aggregate", "amount_valid"} <= pay
    assert "fairness_slices" not in pay and "system_of_record" not in pay
    assert {"fairness_slices", "system_of_record", "prior_read", "pii_bulk_read"} <= credit
    assert "split_payment" not in credit and "amount_valid" not in credit
    assert "split_payment" not in svc and "fairness_slices" not in svc
    assert "groundedness" in svc  # free-text replies
    off = {c.id: c.reason for c in plans["customer_service"].capabilities if c.status == "off"}
    assert "risk class" in (off["fairness_slices"] or "")


def test_plan_numbers_are_integers(plans: dict[str, MonitoringPlan]) -> None:
    for mp in plans.values():
        assert_no_floats(json.loads(mp.model_dump_json()))
        assert all(type(v) is int for v in mp.thresholds.values())
        assert mp.cost.llm_tokens_per_day > 0
        assert mp.slices == (
            ["segment", "province", "language"] if mp.agent_id == "credit_prequal" else []
        )
        for j in mp.judges:
            assert j.family_must_differ_from == "qwen"
    assert plans["payments"].thresholds["limit.transfer_max_minor"] == 100_000_000


def test_rules_need_two_approvers(plans: dict[str, MonitoringPlan]) -> None:
    for mp in plans.values():
        assert mp.rules
        for r in mp.rules:
            if r.spec["action"] in ("block", "pause"):
                assert r.spec["approvals"] == APPROVER_PLACEHOLDERS
            assert r.spec["agent_scope"] == [mp.agent_id]


def test_coverage_rows_cover_the_catalogue(plans: dict[str, MonitoringPlan]) -> None:
    for mp in plans.values():
        statuses = {r["capability_id"]: r["status"] for r in mp.coverage}
        assert set(statuses.values()) <= {"planned", "off"}
        assert {c.id for c in mp.capabilities} == set(statuses)


def _policy(
    agent: str,
    discoveries: dict[str, Discovery],
    profiles: dict[str, AgentProfile],
    plans: dict[str, MonitoringPlan],
) -> str:
    return render_policy(discoveries[agent].inventory, profiles[agent], plans[agent])


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_generated_policy_validates(
    agent: str,
    discoveries: dict[str, Discovery],
    profiles: dict[str, AgentProfile],
    plans: dict[str, MonitoringPlan],
) -> None:
    text = _policy(agent, discoveries, profiles, plans)
    doc = parse_policy_text(text)
    pol = validate_policy(text)
    assert isinstance(pol, Policy)
    assert doc.agents[agent].initial_state == "SHADOW"
    assert set(doc.tools) == {t.name for t in discoveries[agent].inventory.tools}
    assert len(pol.rules_for(agent)) == len(plans[agent].rules)
    assert "FILL-ME-approver" in text


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    a = build_adapters(settings, clock=FixedClock(T0))
    bootstrap_schema.run(settings, a)
    try:
        yield a
    finally:
        a.close()


PLANTED = {
    "payments": [("DEMO-1", "approved_tools", "pause"), ("DEMO-4", "split_payment", "block")],
    "customer_service": [("DEMO-2", "daily_aggregate", "block")],
    "credit_prequal": [("DEMO-3", "system_of_record", "block")],
}


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_gateway_blocks_planted_incident(
    agent: str,
    tmp_path: Path,
    discoveries: dict[str, Discovery],
    profiles: dict[str, AgentProfile],
    plans: dict[str, MonitoringPlan],
) -> None:
    text = _policy(agent, discoveries, profiles, plans)
    enforced = text.replace("initial_state: SHADOW", "initial_state: RUNNING")
    policy = validate_policy(enforced)
    cap_of = {r.rule_id: r.capability_id for r in plans[agent].rules}
    for incident, capability, action in PLANTED[agent]:
        # Fresh store per incident: a pause from one incident must not leak into the next.
        settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / incident)
        adapters = build_adapters(settings, clock=FixedClock(T0))
        bootstrap_schema.run(settings, adapters)
        world = BankWorld.build()
        evidence = MemoryEvidence()
        gw = Gateway(
            StaticPolicyProvider(policy),
            adapters.tables,
            adapters.state,
            evidence,
            adapters.clock,
            facts=R.world_facts(world),
            state_cache_ttl_s=0,
        )
        try:
            (res,) = R.replay([incident], gate=gw, world=world)
        finally:
            gw.close()
            adapters.close()
        assert res.attack_stopped, incident
        rule_id, got = res.first_stop or ("", "")
        assert cap_of.get(rule_id) == capability, (incident, rule_id)
        assert got == action
        assert res.stop_fail_mode is None  # a real rule match, not a fail-closed error
        assert res.harmful_effects_recorded == 0 or incident in ("DEMO-2", "DEMO-4")
        assert any(t == "gate_decision" for t, _, _ in evidence.entries)


def test_shadow_mode_records_but_does_not_stop(
    adapters: Adapters,
    discoveries: dict[str, Discovery],
    profiles: dict[str, AgentProfile],
    plans: dict[str, MonitoringPlan],
) -> None:
    policy = validate_policy(_policy("payments", discoveries, profiles, plans))
    world = BankWorld.build()
    gw = Gateway(
        StaticPolicyProvider(policy),
        adapters.tables,
        adapters.state,
        MemoryEvidence(),
        adapters.clock,
        state_cache_ttl_s=0,
    )
    try:
        (res,) = R.replay(["DEMO-1"], gate=gw, world=world)
    finally:
        gw.close()
    pay_calls = [c for s in res.steps if s.agent == "payments" for c in s.run.tool_calls]
    assert pay_calls and pay_calls[0].decision["action"] == "log"
    assert pay_calls[0].decision["reason"].startswith("shadow: would pause")
