"""WP-B1 item 2: GATE-AUTONOMY-CAP. An accepted ``max_level`` (system tag ``autonomy_limits``)
and the money approval limit become a deterministic pause for approval; observe mode lifts it."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.gateway.autonomy_cap import (
    CapSource,
    Limits,
    check,
    make_source,
    merge,
    parse_limits,
)
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StorePolicyProvider, deploy_policy
from tests.gateway.conftest import MemoryEvidence
from tests.gateway.test_wp38_policy import OBSERVE, make, policy_text

L3 = "l3_tool_using_supervised"
NOW = dt.datetime(2026, 10, 29, 9, 0, tzinfo=dt.UTC)


class Stub:
    def __init__(self, limits: Limits) -> None:
        self.limits = limits

    def limits_for(self, agent_id: str) -> Limits:
        return self.limits


@pytest.fixture
def gw_cap(adapters: Adapters, evidence: MemoryEvidence) -> Iterator[Any]:
    made: list[Gateway] = []

    def build(text: str, limits: Limits | None) -> Gateway:
        deploy_policy(make(text), adapters.state, adapters.clock)
        gw = Gateway(
            StorePolicyProvider(adapters.state, refresh_s=0),
            adapters.tables,
            adapters.state,
            evidence,
            adapters.clock,
            state_cache_ttl_s=0,
        )
        gw.autonomy_cap = Stub(limits) if limits is not None else None
        made.append(gw)
        return gw

    yield build
    for gw in made:
        gw.close()


# the policy in policy_text has no rule for amounts below 100, so a pay of 50 is allowed by rules
def test_allow_when_the_tool_class_fits_the_cap(gw_cap: Any) -> None:
    gw = gw_cap(policy_text(), Limits(max_level="l4_autonomous_bounded"))
    assert gw.check("a1", "1", "pay", {"amount_minor": 50})["allow"] is True
    assert gw.check("a1", "1", "lookup", {"tag": "x"})["allow"] is True
    gw = gw_cap(policy_text(), Limits(max_level=L3))
    assert gw.check("a1", "1", "lookup", {"tag": "x"})["allow"] is True  # read_only needs L3


def test_money_tool_over_the_cap_is_paused_for_approval(gw_cap: Any) -> None:
    gw = gw_cap(policy_text(), Limits(max_level=L3))
    r = gw.check("a1", "1", "pay", {"amount_minor": 50})
    assert r["allow"] is False and r["action"] == "pause"
    assert r["rule_id"] == "GATE-AUTONOMY-CAP" and "l4" in r["reason"] and "l3" in r["reason"]
    assert r["agent_paused"] is True and gw.states.get_state("a1") == "PAUSED"


def test_a_lower_cap_pauses_a_read_only_tool(gw_cap: Any) -> None:
    gw = gw_cap(policy_text(), Limits(max_level="l2_workflow_step"))
    r = gw.check("a1", "1", "lookup", {"tag": "x"})
    assert r["allow"] is False and r["rule_id"] == "GATE-AUTONOMY-CAP"


def test_amount_above_the_approval_limit_pauses(gw_cap: Any) -> None:
    gw = gw_cap(policy_text(), Limits(max_level="l4_autonomous_bounded", approval_above_vnd=40))
    low = gw.check("a1", "1", "pay", {"amount_minor": 40})
    assert low["allow"] is True
    r = gw.check("a1", "1", "pay", {"amount_minor": 41})
    assert r["allow"] is False and r["rule_id"] == "GATE-AUTONOMY-CAP"
    assert "approval limit 40" in r["reason"]


def test_observe_lifts_the_cap_and_keeps_the_original(gw_cap: Any) -> None:
    gw = gw_cap(policy_text({"a1": ("RUNNING", OBSERVE)}), Limits(max_level=L3))
    r = gw.check("a1", "1", "pay", {"amount_minor": 50})
    assert r["allow"] is True and r["status"] == "report"
    assert r["observed_decision"]["action"] == "pause"
    assert r["observed_decision"]["rule_id"] == "GATE-AUTONOMY-CAP"
    assert r["agent_paused"] is False and gw.states.get_state("a1") == "RUNNING"


def test_off_path_nothing_changes(gw_cap: Any) -> None:
    gw = gw_cap(policy_text(), None)
    assert gw.check("a1", "1", "pay", {"amount_minor": 50})["allow"] is True
    assert gw.autonomy_cap is None


def test_dry_run_reports_would_pause(gw_cap: Any) -> None:
    gw = gw_cap(policy_text(), Limits(max_level=L3))
    out = gw.evaluate_only("a1", "1", "pay", {"amount_minor": 50}, {})
    assert out["allow"] is False and out["would_pause"] is True
    assert gw.states.get_state("a1") == "RUNNING"


def test_check_and_parse_helpers() -> None:
    assert check(Limits(), "money", {}) is None
    assert check(Limits(max_level=L3), None, {}) is None
    assert check(Limits(approval_above_vnd=10), "money", {"amount_minor": 11.5}) is None
    assert check(Limits(approval_above_vnd=10), "read_only", {"amount_minor": 99}) is None
    assert check(Limits(credit_approval_above_vnd=10), "credit", {"amount_minor": 11})
    assert parse_limits("not json").empty() and parse_limits('["x"]').empty()
    assert parse_limits('{"max_level": "nonsense", "approval_above_vnd": -1}').empty()
    assert parse_limits(json.dumps({"max_level": L3, "approval_above_vnd": 5})) == Limits(
        L3, 5, None
    )
    strict = merge(Limits("l4_autonomous_bounded", 10, None), Limits(L3, 5, 7))
    assert strict == Limits(L3, 5, 7)


def _system(adapters: Adapters, sid: str, tags: dict[str, str]) -> None:
    adapters.state.insert(
        "ai_system",
        {
            "system_id": sid,
            "name": sid,
            "owner_user": "u",
            "owner_team": "t",
            "purpose": "p",
            "system_type": "assistant",
            "org_role": "deployer",
            "user_segment": "internal",
            "personal_data": "none",
            "money_movement": True,
            "credit_decision": False,
            "human_control": "pre_approval",
            "lifecycle_stage": "operation",
            "risk_level": "medium",
            "risk_level_source": "manual",
            "decision33_class": "unclassified",
            "business_impact": "medium",
            "autonomy_level": "l4_autonomous_bounded",
            "status": "active",
            "tags": tags,
            "created_at": NOW,
            "created_by": "u",
        },
    )


def _link(adapters: Adapters, sid: str, agent: str) -> None:
    adapters.state.insert(
        "system_component",
        {
            "component_id": f"c-{sid}-{agent}",
            "system_id": sid,
            "ref_kind": "agent",
            "ref_id": agent,
            "role": "component_of",
            "source": "manual",
            "evidence_ref": "",
            "active": True,
            "first_seen": NOW,
            "last_seen": NOW,
        },
    )


def test_source_reads_the_tag_and_takes_the_strictest_system(adapters: Adapters) -> None:
    _system(
        adapters, "sys_a", {"autonomy_limits": json.dumps({"max_level": "l4_autonomous_bounded"})}
    )
    _system(
        adapters,
        "sys_b",
        {"autonomy_limits": json.dumps({"max_level": L3, "approval_above_vnd": 9})},
    )
    _system(adapters, "sys_c", {"other": "x"})
    for sid in ("sys_a", "sys_b", "sys_c"):
        _link(adapters, sid, "pay-agent")
    src = CapSource(adapters.state)
    assert src.limits_for("pay-agent") == Limits(L3, 9, None)
    assert src.limits_for("no-system").empty()


def test_make_source_needs_both_flags(adapters: Adapters) -> None:
    s = adapters.settings
    s.smart_guardian, s.governance_enabled = False, True
    assert make_source(s, adapters.state) is None
    s.smart_guardian, s.governance_enabled = True, False
    assert make_source(s, adapters.state) is None
    s.governance_enabled = True
    assert make_source(s, adapters.state) is not None
