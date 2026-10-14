"""The baseline policy and the WP2 agent manifests name the same tools and agents."""

from __future__ import annotations

from collections import Counter

import pytest

from supervisor.gateway.policy import Policy
from supervisor_agents.common.manifest import PACKAGE_DIR, AgentManifest, load_manifest

AGENT_IDS = sorted(p.parent.name for p in PACKAGE_DIR.glob("*/manifest.yaml"))


@pytest.fixture(scope="module")
def manifests() -> dict[str, AgentManifest]:
    return {a: load_manifest(a) for a in AGENT_IDS}


def _rule_tools(policy: Policy) -> set[str]:
    names: set[str] = set()
    for r in policy.rules:
        if r.when.tool is not None:
            names.update(r.when.tool.names())
        if r.aggregate is not None:
            names.update(r.aggregate.tools or [])
        if r.prior is not None:
            names.add(r.prior.tool)
    return names


def _covering_tools(policy: Policy) -> set[str]:
    """Tools a rule actually applies to (eq / in matches, not allow-list exclusions)."""
    out: set[str] = set()
    for r in policy.rules:
        if r.when.tool is not None and r.when.tool.op in ("eq", "in"):
            out.update(r.when.tool.names())
    return out


def test_three_manifests_found(manifests: dict[str, AgentManifest]) -> None:
    assert AGENT_IDS == ["credit_prequal", "customer_service", "payments"]


def test_every_policy_tool_is_in_exactly_one_manifest(
    baseline: Policy, manifests: dict[str, AgentManifest]
) -> None:
    owners = Counter(t.name for m in manifests.values() for t in m.tools)
    named = set(baseline.doc.tools) | _rule_tools(baseline)
    bad = {t: owners.get(t, 0) for t in sorted(named) if owners.get(t, 0) != 1}
    assert bad == {}, f"tools not in exactly one manifest: {bad}"


def test_policy_risk_classes_match_manifests(
    baseline: Policy, manifests: dict[str, AgentManifest]
) -> None:
    for m in manifests.values():
        for t in m.tools:
            assert baseline.doc.tools.get(t.name) == t.risk_class, f"{m.id}.{t.name}"


def test_every_non_read_only_manifest_tool_is_covered_by_a_rule(
    baseline: Policy, manifests: dict[str, AgentManifest]
) -> None:
    covered = _covering_tools(baseline)
    missing = [
        f"{m.id}.{t.name}"
        for m in manifests.values()
        for t in m.tools
        if t.risk_class != "read_only" and t.name not in covered
    ]
    assert missing == []


def test_policy_agents_match_manifests(
    baseline: Policy, manifests: dict[str, AgentManifest]
) -> None:
    assert sorted(baseline.doc.agents) == AGENT_IDS
    for agent_id, m in manifests.items():
        a = baseline.doc.agents[agent_id]
        assert (a.name, a.owner_user, a.owner_team, a.risk_tier, a.model_family) == (
            m.name,
            m.owner_user,
            m.owner,
            m.risk_tier,
            m.model_family,
        )
        assert (a.host_type, a.plug_point) == (m.host_type, m.plug_point)


def test_each_agent_allow_list_is_its_manifest_minus_unapproved_tools(
    baseline: Policy, manifests: dict[str, AgentManifest]
) -> None:
    unapproved = {"ext_transfer_api"}  # registered for payments, approved for ops staff only
    allow_lists = {
        r.agent_scope[0]: set(r.when.tool.names())
        for r in baseline.rules
        if r.id.endswith("-07") and r.when.tool is not None and r.agent_scope != "*"
    }
    for agent_id, m in manifests.items():
        assert allow_lists[agent_id] == set(m.tool_names) - unapproved, agent_id
