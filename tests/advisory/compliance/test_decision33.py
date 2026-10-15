"""Decision 33 suggestion: onboard mapping + Circular 53 Art. 4(2) lines."""

from __future__ import annotations

from typing import Any

from supervisor.advisory.compliance.decision33 import suggest_decision33
from supervisor.advisory.compliance.demo import demo_product
from supervisor.advisory.compliance.facts import from_questionnaire
from supervisor.onboard.models import DECISION33_CAVEAT


def _tx(**kw: Any):
    data = {
        "product_id": "t",
        "name": "T",
        "executes_payments": True,
        "human_approval_before_execution": False,
        "credit_decisions": False,
        **kw,
    }
    return suggest_decision33(from_questionnaire(data))


def _entry(sug, name: str):
    return next(e for e in sug.entries if e.entry == name)


def test_payments_demo_is_high_risk() -> None:
    sug, qs = suggest_decision33(demo_product("payments"))
    assert sug.classification == "high_risk" and qs == []
    text = "\n".join(sug.lines)
    for oid in ("VN-QD33-2026-PL4.1-01", "VN-QD33-2026-PL4.1-02", "VN-QD33-2026-PL4.1-03"):
        assert oid in text
    assert "VN-TT53-2026-A4.02A-01" in text
    assert _entry(sug, "transactions").triggered is True
    assert _entry(sug, "credit").triggered is False
    assert sug.caveat == DECISION33_CAVEAT
    assert "src/supervisor_agents/payments" in text  # fact pointers are cited


def test_credit_demo_is_high_risk_via_credit_entry() -> None:
    sug, _ = suggest_decision33(demo_product("credit_prequal"))
    assert sug.classification == "high_risk"
    credit = _entry(sug, "credit")
    assert credit.triggered is True
    text = "\n".join(credit.lines)
    assert "2,000,000,000" in text and "VN-QD33-2026-PL4.2-03" in text
    assert "VN-TT53-2026-A4.02B-01" in text
    assert _entry(sug, "transactions").triggered is False


def test_customer_service_follows_onboard_mapping() -> None:
    p = demo_product("customer_service")
    sug, qs = suggest_decision33(p)
    assert p.onboard_decision33 is not None
    assert sug.classification == p.onboard_decision33["classification"] == "not_high_risk"
    assert qs == []


def test_in_between_value_with_unknown_customer_types_asks() -> None:
    sug, qs = _tx(max_transaction_vnd=15_000_000, max_daily_vnd=15_000_000)
    assert sug.classification == "needs_answer"
    assert [q.id for q in qs] == ["Q-customer_types"]
    assert sug.question_ids == ("Q-customer_types",)
    assert _entry(sug, "transactions").triggered is None
    assert "VN-QD33-2026-PL4.1-02" in qs[0].obligation_ids


def test_in_between_value_with_known_types() -> None:
    assert (
        _tx(
            max_transaction_vnd=15_000_000, max_daily_vnd=15_000_000, customer_types=["individual"]
        )[0].classification
        == "high_risk"
    )
    sug, qs = _tx(
        max_transaction_vnd=15_000_000, max_daily_vnd=15_000_000, customer_types=["organisation"]
    )
    assert sug.classification == "not_high_risk" and qs == []


def test_value_under_10m_is_not_triggered() -> None:
    sug, qs = _tx(max_transaction_vnd=5_000_000, max_daily_vnd=5_000_000)
    assert sug.classification == "not_high_risk" and qs == []
    assert _entry(sug, "transactions").triggered is False


def test_above_organisation_line_needs_no_customer_types() -> None:
    sug, qs = _tx(max_transaction_vnd=60_000_000)
    assert sug.classification == "high_risk" and qs == []


def test_exact_line_is_not_over() -> None:
    sug, _ = _tx(max_transaction_vnd=10_000_000, max_daily_vnd=20_000_000)
    assert sug.classification == "not_high_risk"  # the law says "over"


def test_unknown_max_asks_for_it() -> None:
    sug, qs = _tx()
    assert sug.classification == "needs_answer"
    assert {q.id for q in qs} == {"Q-customer_types", "Q-max_transaction_vnd", "Q-max_daily_vnd"}


def test_known_small_tx_but_unknown_daily_asks_daily_only() -> None:
    sug, qs = _tx(max_transaction_vnd=5_000_000, customer_types=["individual"])
    assert sug.classification == "needs_answer"
    assert [q.id for q in qs] == ["Q-max_daily_vnd"]


def test_human_approval_makes_entry_false() -> None:
    sug, qs = _tx(human_approval_before_execution=True, max_transaction_vnd=900_000_000)
    assert sug.classification == "not_high_risk" and qs == []


def test_unknown_approval_asks() -> None:
    sug, qs = suggest_decision33(
        from_questionnaire(
            {
                "product_id": "t",
                "name": "T",
                "executes_payments": True,
                "max_transaction_vnd": 900_000_000,
                "credit_decisions": False,
            }
        )
    )
    assert sug.classification == "needs_answer"
    assert [q.id for q in qs] == ["Q-human_approval_before_execution"]


def test_credit_lines() -> None:
    def credit(**kw: Any):
        return suggest_decision33(
            from_questionnaire(
                {
                    "product_id": "c",
                    "name": "C",
                    "executes_payments": False,
                    "credit_decisions": True,
                    "independent_credit_approval": False,
                    **kw,
                }
            )
        )

    assert credit(max_credit_vnd=50_000_000)[0].classification == "high_risk"
    assert credit(max_credit_vnd=49_999_999)[0].classification == "not_high_risk"
    assert (
        credit(independent_credit_approval=True, max_credit_vnd=10**9)[0].classification
        == "not_high_risk"
    )
    sug, qs = credit()
    assert sug.classification == "needs_answer" and [q.id for q in qs] == ["Q-max_credit_vnd"]


def test_complete_agent_classes_without_payment_means_no_payment() -> None:
    sug, qs = suggest_decision33(
        from_questionnaire({"product_id": "n", "name": "N", "agent_classes": ["internal_tool"]})
    )
    assert sug.classification == "not_high_risk" and qs == []


def test_nothing_known_is_needs_answer() -> None:
    sug, qs = suggest_decision33(from_questionnaire({"product_id": "n", "name": "N"}))
    assert sug.classification == "needs_answer"
    ids = {q.id for q in qs}
    assert {"Q-executes_payments", "Q-credit_decisions"} <= ids
