"""Regression tests for defects found in the WP3 review."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters
from supervisor.gateway import wiring
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import PolicyError, StaticPolicyProvider, load_policy_texts
from supervisor.gateway.routes import router
from supervisor.gateway.state import TransitionError
from tests.gateway.conftest import MemoryEvidence
from tests.gateway.helpers import call


def _down(*_a: object, **_k: object) -> None:
    raise RuntimeError("store unavailable")


def test_negative_and_zero_amounts_are_blocked(gateway: Gateway) -> None:
    for amount in (-900_000_000, 0):
        r = call(
            gateway,
            "payments",
            "internal_transfer",
            customer_id="C1",
            payee_id="P1",
            amount_minor=amount,
        )
        assert r["allow"] is False and "PAY-06" in [m["rule_id"] for m in r["matched_rules"]]
        w = call(gateway, "customer_service", "waive_fee", customer_id="C1", amount_minor=amount)
        assert w["allow"] is False and w["rule_id"] == "SVC-04"
    # a negative amount never lowers the daily aggregate
    for _ in range(1):
        assert call(
            gateway,
            "payments",
            "internal_transfer",
            customer_id="C1",
            payee_id="P1",
            amount_minor=100_000_000,
        )["allow"]
    r = call(
        gateway,
        "payments",
        "internal_transfer",
        customer_id="C1",
        payee_id="P1",
        amount_minor=100_000_000,
    )
    assert r["allow"] is False and r["rule_id"] == "PAY-03"


def test_quarantine_and_release_void_pending_resume(gateway: Gateway) -> None:
    gateway.states.pause("payments", "reviewer.an")
    assert gateway.states.resume("payments", "owner.payments")["status"] == "pending"
    gateway.states.quarantine("payments", "reviewer.an", "confirmed")
    gateway.states.release_quarantine("payments", "admin.chi", "fixed")
    r = gateway.states.resume("payments", "reviewer.binh")
    assert r["status"] == "pending" and gateway.states.get_state("payments") == "PAUSED"


def test_resume_fails_closed_without_reviewer_list(
    adapters: Adapters, evidence: MemoryEvidence
) -> None:
    text = """
policy_version: 1
tools: {read: read_only}
agents:
  a1: {name: A1, owner_user: o1, owner_team: t1, initial_state: RUNNING}
"""
    g = Gateway(
        StaticPolicyProvider(load_policy_texts([("p.yaml", text)])),
        adapters.tables,
        adapters.state,
        evidence,
        adapters.clock,
    )
    g.states.pause("a1", "someone")
    with pytest.raises(TransitionError, match="may not approve"):
        g.states.resume("a1", "anyone.else")
    g.close()


def test_prior_rule_cannot_be_dodged_by_missing_or_retyped_ids(gateway: Gateway) -> None:
    r = call(gateway, "payments", "internal_transfer", customer_id="C1", amount_minor=10)
    assert r["allow"] is False and r["rule_id"] == "PAY-04"  # no payee_id: unlinkable
    assert call(gateway, "payments", "add_payee", customer_id="C1", payee_id=123)["allow"]
    r = call(
        gateway,
        "payments",
        "internal_transfer",
        customer_id=" c1 ",
        payee_id="123",
        amount_minor=10,
    )
    assert r["allow"] is False and r["rule_id"] == "PAY-04"


def test_quarantined_agent_stays_denied_during_store_outage(
    gateway: Gateway, adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway.states.quarantine("payments", "reviewer.an", "incident")
    assert call(gateway, "payments", "get_customer", customer_id="C1")["allow"] is False
    monkeypatch.setattr(adapters.state, "get", _down)
    r = call(gateway, "payments", "get_customer", customer_id="C1")
    assert r["allow"] is False and r["fail_mode"] == "closed"


def test_redos_patterns_rejected() -> None:
    text = """
policy_version: 1
tools: {read: read_only}
agents:
  a1: {name: A1, owner_user: o1, owner_team: t1}
rules:
  - id: R-1
    version: 1
    description: bad regex
    agent_scope: [a1]
    when:
      all: [{arg: x, op: matches, value: "(a+)+$"}]
    action: alert
    severity: low
    risk_class: read_only
    owner: t
"""
    with pytest.raises(PolicyError, match="nested quantifiers"):
        load_policy_texts([("p.yaml", text)])


def test_windows_rewarm_when_policy_changes(
    adapters: Adapters, evidence: MemoryEvidence, clock: FixedClock
) -> None:
    base = """
policy_version: 1
tools: {pay: money}
agents:
  a1: {name: A1, owner_user: o1, owner_team: t1, initial_state: RUNNING}
rules: []
"""
    limit = base.replace(
        "rules: []",
        """rules:
  - id: L-1
    version: 1
    description: per customer limit
    agent_scope: [a1]
    when: {tool: pay}
    aggregate: {fn: sum, field: amount_minor, window_s: 3600, group_by: customer, limit: 100}
    action: block
    severity: high
    risk_class: money
    owner: t
    approvals: [x, y]
""",
    )
    provider = StaticPolicyProvider(load_policy_texts([("p.yaml", base)]))
    g = Gateway(provider, adapters.tables, adapters.state, evidence, clock)
    assert call(g, "a1", "pay", customer_id="C1", amount_minor=90)["allow"]
    provider.policy = load_policy_texts([("p.yaml", limit)])
    r = call(g, "a1", "pay", customer_id="C1", amount_minor=20)
    assert r["allow"] is False and r["rule_id"] == "L-1"
    g.close()


def test_body_principal_rejected_when_not_trusted(gateway: Gateway) -> None:
    app = FastAPI()
    app.include_router(router)
    wiring.set_gateway(gateway)
    try:
        client = TestClient(app)
        gateway.trust_body_principal = False
        r = client.post("/gate/pause", json={"agent_id": "payments", "principal": "reviewer.an"})
        assert r.status_code == 400 and "principal" in r.json()["error"]
        r = client.post(
            "/gate/pause",
            json={"agent_id": "payments"},
            headers={"X-Forwarded-User": "reviewer.an"},
        )
        assert r.status_code == 200 and r.json()["state"] == "PAUSED"
        bad = client.post(
            "/gate/check",
            json={"agent_id": "x" * 500, "agent_version": "1", "tool_name": "t", "args": {}},
        )
        assert bad.status_code == 400
    finally:
        wiring.set_gateway(None)
