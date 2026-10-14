"""Each baseline rule with a positive and a negative case (real gate, real rules)."""

from __future__ import annotations

from supervisor.adapters.clock import FixedClock
from supervisor.gateway.engine import Gateway
from tests.gateway.helpers import call, matched_ids

C1 = "CUS-0001"
C2 = "CUS-0002"


def test_read_only_call_is_allowed(gateway: Gateway) -> None:
    r = call(gateway, "payments", "get_customer", customer_id=C1)
    assert r["allow"] is True and r["action"] == "allow" and r["rule_id"] is None
    assert isinstance(r["latency_ms"], int)


def test_pay07_allow_list(gateway: Gateway) -> None:
    r = call(gateway, "payments", "waive_fee", customer_id=C1, amount_minor=1000)
    assert r["allow"] is False and r["rule_id"] == "PAY-07" and r["action"] == "pause"
    assert gateway.states.get_state("payments") == "PAUSED"


def test_svc07_allow_list(gateway: Gateway) -> None:
    ok = call(gateway, "customer_service", "lookup_fee_schedule", product="card")
    assert ok["allow"] is True
    r = call(
        gateway,
        "customer_service",
        "ext_transfer_api",
        customer_id=C1,
        payee_id="P1",
        amount_minor=1000,
    )
    assert r["allow"] is False and r["rule_id"] == "SVC-07"


def test_crd07_allow_list(gateway: Gateway) -> None:
    assert call(gateway, "credit_prequal", "get_credit_score", customer_id=C1)["allow"]
    r = call(gateway, "credit_prequal", "internal_transfer", customer_id=C1, amount_minor=1)
    assert r["allow"] is False and r["rule_id"] == "CRD-07"


def test_pay01_amount_required(gateway: Gateway) -> None:
    r = call(gateway, "payments", "internal_transfer", customer_id=C1, payee_id="P1")
    assert r["allow"] is False and r["rule_id"] == "PAY-01"
    ok = call(
        gateway, "payments", "internal_transfer", customer_id=C1, payee_id="P1", amount_minor=10
    )
    assert ok["allow"] is True


def test_pay02_single_transfer_limit(gateway: Gateway) -> None:
    at_limit = call(
        gateway,
        "payments",
        "internal_transfer",
        customer_id=C1,
        payee_id="P1",
        amount_minor=100_000_000,
    )
    assert at_limit["allow"] is True
    over = call(
        gateway,
        "payments",
        "internal_transfer",
        customer_id=C2,
        payee_id="P1",
        amount_minor=100_000_001,
    )
    assert over["allow"] is False and over["rule_id"] == "PAY-02" and over["action"] == "block"
    assert gateway.states.get_state("payments") == "RUNNING"


def test_pay02_float_amount_fails_closed(gateway: Gateway) -> None:
    r = call(
        gateway, "payments", "internal_transfer", customer_id=C1, payee_id="P1", amount_minor=5.5
    )
    assert r["allow"] is False
    assert r["fail_mode"] == "closed" and "rule error" in r["reason"]


def test_pay04_new_payee_cooling_period(gateway: Gateway, clock: FixedClock) -> None:
    assert call(gateway, "payments", "add_payee", customer_id=C1, payee_id="P7")["allow"]
    clock.advance(600)
    r = call(
        gateway,
        "payments",
        "internal_transfer",
        customer_id=C1,
        payee_id="P7",
        amount_minor=1_000_000,
    )
    assert r["allow"] is False and r["rule_id"] == "PAY-04"
    other = call(
        gateway,
        "payments",
        "internal_transfer",
        customer_id=C1,
        payee_id="P8",
        amount_minor=1_000_000,
    )
    assert other["allow"] is True
    clock.advance(1201)
    later = call(
        gateway,
        "payments",
        "internal_transfer",
        customer_id=C1,
        payee_id="P7",
        amount_minor=1_000_000,
    )
    assert later["allow"] is True


def test_pay05_ext_transfer_needs_approved_payee(gateway: Gateway, clock: FixedClock) -> None:
    assert call(gateway, "payments", "add_payee", customer_id=C1, payee_id="P7")["allow"]
    clock.advance(1801)
    ok = call(
        gateway,
        "payments",
        "ext_transfer_api",
        customer_id=C1,
        payee_id="P7",
        amount_minor=2_000_000,
    )
    assert ok["allow"] is True
    other_customer = call(
        gateway,
        "payments",
        "ext_transfer_api",
        customer_id=C2,
        payee_id="P7",
        amount_minor=2_000_000,
    )
    assert other_customer["allow"] is False and other_customer["rule_id"] == "PAY-05"
    assert other_customer["action"] == "pause" and other_customer["agent_paused"] is True


def test_svc01_fee_waiver_limit(gateway: Gateway) -> None:
    ok = call(gateway, "customer_service", "waive_fee", customer_id=C1, amount_minor=500_000)
    assert ok["allow"] is True
    r = call(gateway, "customer_service", "waive_fee", customer_id=C2, amount_minor=500_001)
    assert r["allow"] is False and r["rule_id"] == "SVC-01"


def test_svc02_fee_waiver_count_per_customer(gateway: Gateway, clock: FixedClock) -> None:
    for _ in range(2):
        assert call(gateway, "customer_service", "waive_fee", customer_id=C1, amount_minor=50_000)[
            "allow"
        ]
    third = call(gateway, "customer_service", "waive_fee", customer_id=C1, amount_minor=50_000)
    assert third["allow"] is False and third["rule_id"] == "SVC-02"
    assert call(gateway, "customer_service", "waive_fee", customer_id=C2, amount_minor=50_000)[
        "allow"
    ]
    clock.advance(86_401)
    assert call(gateway, "customer_service", "waive_fee", customer_id=C1, amount_minor=50_000)[
        "allow"
    ]


def test_svc03_waiver_amount_required(gateway: Gateway) -> None:
    r = call(gateway, "customer_service", "waive_fee", customer_id=C1)
    assert r["allow"] is False and r["rule_id"] == "SVC-03"


def test_crd01_documents_before_decision(gateway: Gateway) -> None:
    r = call(
        gateway, "credit_prequal", "credit_decision", application_id="APP-1", decision="approve"
    )
    assert r["allow"] is False and r["rule_id"] == "CRD-01"
    assert call(gateway, "credit_prequal", "fetch_documents", application_id="APP-1")["allow"]
    ok = call(
        gateway, "credit_prequal", "credit_decision", application_id="APP-1", decision="approve"
    )
    assert ok["allow"] is True
    other = call(
        gateway, "credit_prequal", "credit_decision", application_id="APP-2", decision="approve"
    )
    assert other["allow"] is False


def test_pii01_export_denied_for_every_agent(gateway: Gateway) -> None:
    for agent in ("payments", "customer_service", "credit_prequal"):
        r = call(gateway, agent, "export_customer_data", customer_id=C1)
        assert r["allow"] is False
        assert "PII-01" in matched_ids(r)


def test_unknown_agent_and_unknown_tool_fail_closed(gateway: Gateway) -> None:
    r = call(gateway, "rogue_agent", "get_customer", customer_id=C1)
    assert r["allow"] is False and r["rule_id"] == "GATE-UNKNOWN-AGENT"
    r = call(gateway, "payments", "delete_ledger", customer_id=C1)
    assert r["allow"] is False and r["rule_id"] == "GATE-UNKNOWN-TOOL"


def test_every_decision_writes_verdict_event_and_evidence(
    gateway: Gateway, adapters, evidence
) -> None:
    r = call(
        gateway,
        "payments",
        "internal_transfer",
        customer_id=C1,
        payee_id="P1",
        amount_minor=200_000_000,
    )
    verdicts = adapters.tables.query("verdict", {"event_id": r["decision_id"]})
    assert verdicts and all(v["tier"] == 0 and not v["advisory"] for v in verdicts)
    assert {v["rule_id"] for v in verdicts} >= {"PAY-02"}
    assert all(v["policy_hash"] == r["policy_hash"] for v in verdicts)
    events = adapters.tables.query("agent_event", {"event_id": r["decision_id"]})
    assert len(events) == 1 and events[0]["status"] == "denied"
    assert events[0]["event_type"] == "gate_decision" and C1 not in events[0]["args_masked"]
    payloads = evidence.of_type("gate_decision")
    assert payloads[-1]["decision_id"] == r["decision_id"]
    assert isinstance(payloads[-1]["latency_us"], int)
    assert payloads[-1]["amount_minor"] == 200_000_000
    assert C1 not in str(payloads[-1])
