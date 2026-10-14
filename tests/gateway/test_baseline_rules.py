"""Each baseline rule with a positive and a negative case (real gate, real rules).

Tool and argument names are the WP2 manifest names (src/supervisor_agents/*/manifest.yaml)."""

from __future__ import annotations

from supervisor.adapters.clock import FixedClock
from supervisor.gateway.engine import Gateway
from tests.gateway.helpers import call, matched_ids

C1 = "CUS-0001"
C2 = "CUS-0002"
A1 = "ACC-0000000001"
A2 = "ACC-0000000003"


def test_read_only_call_is_allowed(gateway: Gateway) -> None:
    r = call(gateway, "payments", "get_balance", account_id=A1)
    assert r["allow"] is True and r["action"] == "allow" and r["rule_id"] is None
    assert isinstance(r["latency_ms"], int)


def test_pay07_allow_list(gateway: Gateway) -> None:
    r = call(gateway, "payments", "waive_fee", account_id=A1, amount_minor=1000)
    assert r["allow"] is False and r["rule_id"] == "PAY-07" and r["action"] == "pause"
    assert gateway.states.get_state("payments") == "PAUSED"


def test_pay07_ext_transfer_api_not_approved_for_payments(gateway: Gateway) -> None:
    r = call(
        gateway,
        "payments",
        "ext_transfer_api",
        to_bank_swift="XYZBANKXX",
        to_account="0000123456789",
        amount_minor=1_000_000,
        currency="VND",
    )
    assert r["allow"] is False and r["rule_id"] == "PAY-07" and r["action"] == "pause"


def test_svc07_allow_list(gateway: Gateway) -> None:
    ok = call(gateway, "customer_service", "lookup_customer", customer_id=C1)
    assert ok["allow"] is True
    r = call(
        gateway,
        "customer_service",
        "transfer",
        from_account_id=A1,
        payee_id="P1",
        amount_minor=1000,
    )
    assert r["allow"] is False and r["rule_id"] == "SVC-07"


def test_crd07_allow_list(gateway: Gateway) -> None:
    assert call(gateway, "credit_prequal", "credit_score_lookup", customer_id=C1)["allow"]
    r = call(gateway, "credit_prequal", "transfer", from_account_id=A1, amount_minor=1)
    assert r["allow"] is False and r["rule_id"] == "CRD-07"


def test_pay01_amount_required(gateway: Gateway) -> None:
    r = call(gateway, "payments", "transfer", from_account_id=A1, payee_id="P1")
    assert r["allow"] is False and r["rule_id"] == "PAY-01"
    ok = call(gateway, "payments", "transfer", from_account_id=A1, payee_id="P1", amount_minor=10)
    assert ok["allow"] is True


def test_pay02_single_transfer_limit(gateway: Gateway) -> None:
    at_limit = call(
        gateway,
        "payments",
        "transfer",
        from_account_id=A1,
        payee_id="P1",
        amount_minor=100_000_000,
    )
    assert at_limit["allow"] is True
    over = call(
        gateway,
        "payments",
        "transfer",
        from_account_id=A2,
        payee_id="P2",
        amount_minor=100_000_001,
    )
    assert over["allow"] is False and over["rule_id"] == "PAY-02" and over["action"] == "block"
    assert gateway.states.get_state("payments") == "RUNNING"


def test_pay02_float_amount_fails_closed(gateway: Gateway) -> None:
    r = call(gateway, "payments", "transfer", from_account_id=A1, payee_id="P1", amount_minor=5.5)
    assert r["allow"] is False
    assert r["fail_mode"] == "closed" and "rule error" in r["reason"]


def test_pay03_missing_source_account_fails_closed(gateway: Gateway) -> None:
    r = call(gateway, "payments", "transfer", payee_id="P1", amount_minor=1_000)
    assert r["allow"] is False and r["fail_mode"] == "closed"


def test_pay09_new_payees_per_customer(gateway: Gateway, clock: FixedClock) -> None:
    for i in range(3):
        assert call(
            gateway,
            "payments",
            "add_payee",
            customer_id=C1,
            payee_name=f"N{i}",
            bank_code="970407",
            account_number="1234567890",
        )["allow"]
    fourth = call(
        gateway,
        "payments",
        "add_payee",
        customer_id=C1,
        payee_name="N4",
        bank_code="970407",
        account_number="1234567890",
    )
    assert fourth["allow"] is False and fourth["rule_id"] == "PAY-09"
    other = call(
        gateway,
        "payments",
        "add_payee",
        customer_id=C2,
        payee_name="N1",
        bank_code="970407",
        account_number="1234567890",
    )
    assert other["allow"] is True


def test_svc01_fee_waiver_limit(gateway: Gateway) -> None:
    ok = call(gateway, "customer_service", "waive_fee", account_id=A1, amount_minor=500_000)
    assert ok["allow"] is True
    r = call(gateway, "customer_service", "waive_fee", account_id=A2, amount_minor=500_001)
    assert r["allow"] is False and r["rule_id"] == "SVC-01"


def test_svc02_fee_waiver_count_per_account(gateway: Gateway, clock: FixedClock) -> None:
    for _ in range(2):
        assert call(gateway, "customer_service", "waive_fee", account_id=A1, amount_minor=50_000)[
            "allow"
        ]
    third = call(gateway, "customer_service", "waive_fee", account_id=A1, amount_minor=50_000)
    assert third["allow"] is False and third["rule_id"] == "SVC-02"
    assert call(gateway, "customer_service", "waive_fee", account_id=A2, amount_minor=50_000)[
        "allow"
    ]
    clock.advance(86_401)
    assert call(gateway, "customer_service", "waive_fee", account_id=A1, amount_minor=50_000)[
        "allow"
    ]


def test_svc03_waiver_amount_required(gateway: Gateway) -> None:
    r = call(gateway, "customer_service", "waive_fee", account_id=A1)
    assert r["allow"] is False and r["rule_id"] == "SVC-03"


def test_svc05_svc06_disputes(gateway: Gateway) -> None:
    r = call(gateway, "customer_service", "open_dispute", customer_id=C1, card_last4="1234")
    assert r["allow"] is False and r["rule_id"] == "SVC-05"
    r = call(
        gateway, "customer_service", "open_dispute", customer_id=C1, amount_minor=0, card_last4="1"
    )
    assert r["allow"] is False and r["rule_id"] == "SVC-05"
    for _ in range(2):
        assert call(
            gateway, "customer_service", "open_dispute", customer_id=C1, amount_minor=10_000
        )["allow"]
    third = call(gateway, "customer_service", "open_dispute", customer_id=C1, amount_minor=10_000)
    assert third["allow"] is False and third["rule_id"] == "SVC-06"


def test_crd02_application_read_before_decision(gateway: Gateway) -> None:
    r = call(gateway, "credit_prequal", "decide_prequal", application_id="APP-1", decision="refer")
    assert r["allow"] is False and r["rule_id"] == "CRD-02"
    assert call(gateway, "credit_prequal", "fetch_application", application_id="APP-1")["allow"]
    ok = call(gateway, "credit_prequal", "decide_prequal", application_id="APP-1", decision="refer")
    assert ok["allow"] is True
    other = call(
        gateway, "credit_prequal", "decide_prequal", application_id="APP-2", decision="refer"
    )
    assert other["allow"] is False


def test_crd03_prequal_amount_limit(gateway: Gateway) -> None:
    assert call(gateway, "credit_prequal", "fetch_application", application_id="APP-1")["allow"]
    r = call(
        gateway,
        "credit_prequal",
        "decide_prequal",
        application_id="APP-1",
        decision="refer",
        amount_minor=2_000_000_001,
    )
    assert r["allow"] is False and "CRD-03" in matched_ids(r)


def test_pii02_bulk_application_reads(gateway: Gateway) -> None:
    for i in range(200):
        assert call(gateway, "credit_prequal", "fetch_application", application_id=f"APP-{i}")[
            "allow"
        ]
    r = call(gateway, "credit_prequal", "fetch_application", application_id="APP-999")
    assert r["allow"] is False and r["rule_id"] == "PII-02"


def test_unknown_agent_and_unknown_tool_fail_closed(gateway: Gateway) -> None:
    r = call(gateway, "rogue_agent", "lookup_customer", customer_id=C1)
    assert r["allow"] is False and r["rule_id"] == "GATE-UNKNOWN-AGENT"
    r = call(gateway, "payments", "delete_ledger", customer_id=C1)
    assert r["allow"] is False and r["rule_id"] == "GATE-UNKNOWN-TOOL"
    r = call(gateway, "customer_service", "export_customer_data", customer_id=C1)
    assert r["allow"] is False and r["rule_id"] == "GATE-UNKNOWN-TOOL"


def test_every_decision_writes_verdict_event_and_evidence(
    gateway: Gateway, adapters, evidence
) -> None:
    r = call(
        gateway,
        "payments",
        "transfer",
        from_account_id=A1,
        payee_id="P1",
        amount_minor=200_000_000,
    )
    verdicts = adapters.tables.query("verdict", {"event_id": r["decision_id"]})
    assert verdicts and all(v["tier"] == 0 and not v["advisory"] for v in verdicts)
    assert {v["rule_id"] for v in verdicts} >= {"PAY-02"}
    assert all(v["policy_hash"] == r["policy_hash"] for v in verdicts)
    events = adapters.tables.query("agent_event", {"event_id": r["decision_id"]})
    assert len(events) == 1 and events[0]["status"] == "denied"
    assert events[0]["event_type"] == "gate_decision" and A1 not in events[0]["args_masked"]
    payloads = evidence.of_type("gate_decision")
    assert payloads[-1]["decision_id"] == r["decision_id"]
    assert isinstance(payloads[-1]["latency_us"], int)
    assert payloads[-1]["amount_minor"] == 200_000_000
    assert A1 not in str(payloads[-1])
