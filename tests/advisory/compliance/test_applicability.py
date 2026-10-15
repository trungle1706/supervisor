"""Applicability: reuse of regkb.evaluate, incomplete-set rule, one question per fact."""

from __future__ import annotations

from supervisor.advisory.compliance.applicability import assess, fact_questions, regkb_profile
from supervisor.advisory.compliance.demo import demo_product
from supervisor.advisory.compliance.facts import from_questionnaire
from supervisor.advisory.compliance.model import ProductProfile
from supervisor.regkb import KnowledgeBase

PAY = "VN-QD33-2026-PL4.1-01"  # agent_class payment; role deployer or provider
CREDIT = "VN-QD33-2026-PL4.2-01"  # agent_class credit_decision


def _p(**kw: object) -> ProductProfile:
    base: dict[str, object] = {
        "product_id": "t",
        "name": "T",
        "source": "questionnaire",
        "roles": ("deployer",),
        "roles_complete": True,
    }
    return ProductProfile(**{**base, **kw})  # type: ignore[arg-type]


def test_every_obligation_is_assessed(kb: KnowledgeBase) -> None:
    out = assess(kb, demo_product("payments"))
    assert set(out) == set(kb.obligations)
    assert all(r.applies in ("yes", "no", "needs_answer") for r in out.values())
    assert all(r.reasons for r in out.values())


def test_applies_no_and_needs_answer(kb: KnowledgeBase) -> None:
    yes = assess(kb, _p(agent_classes=("payment",), agent_classes_complete=True))
    assert yes[PAY].applies == "yes"
    assert yes[CREDIT].applies == "no"  # complete set without credit_decision: a real "no"
    unknown = assess(kb, _p())
    assert unknown[PAY].applies == "needs_answer"
    assert "agent_classes" in unknown[PAY].missing_facts


def test_incomplete_set_found_payment_vs_credit(kb: KnowledgeBase) -> None:
    found = ("payment",)
    incomplete = assess(kb, _p(agent_classes=found, agent_classes_complete=False))
    assert incomplete[CREDIT].applies == "needs_answer"  # code may have missed the credit tool
    assert incomplete[PAY].applies == "yes"  # positive evidence is enough
    assert any("lower bound" in r for r in incomplete[CREDIT].reasons)
    complete = assess(kb, _p(agent_classes=found, agent_classes_complete=True))
    assert complete[CREDIT].applies == "no"
    assert complete[PAY].applies == "yes"


def test_empty_incomplete_set_is_not_a_no(kb: KnowledgeBase) -> None:
    out = assess(kb, _p(agent_classes=(), agent_classes_complete=False))
    assert out[PAY].applies == "needs_answer"
    assert assess(kb, _p(agent_classes=(), agent_classes_complete=True))[PAY].applies == "no"


def test_customer_facing_flag(kb: KnowledgeBase) -> None:
    p = _p(agent_classes=("payment",), agent_classes_complete=True, customer_facing=True)
    assert "customer_facing" in (regkb_profile(p).agent_classes or ())
    p2 = _p(
        agent_classes=("payment", "customer_facing"),
        agent_classes_complete=True,
        customer_facing=False,
    )
    assert regkb_profile(p2).agent_classes == ("payment",)
    # False on an incomplete set cannot remove a class the code may not have found
    p3 = _p(agent_classes=("customer_facing",), agent_classes_complete=False, customer_facing=False)
    assert regkb_profile(p3).agent_classes == ("customer_facing",)


def test_one_question_per_missing_fact(kb: KnowledgeBase) -> None:
    product = _p(roles=None, roles_complete=False)  # nothing known
    out = assess(kb, product)
    qs = fact_questions(product, out)
    facts = [q.fact for q in qs]
    assert len(facts) == len(set(facts))
    missing = {f for r in out.values() if r.applies == "needs_answer" for f in r.missing_facts}
    assert set(facts) == missing and facts
    for q in qs:
        assert q.id == f"Q-{q.fact}"
        assert q.text_en and q.text_vi
        assert q.obligation_ids
        assert list(q.obligation_ids) == sorted(q.obligation_ids)
        for oid in q.obligation_ids:
            assert out[oid].applies == "needs_answer" and q.fact in out[oid].missing_facts
    # every needs_answer row is covered by at least one question
    covered = {oid for q in qs for oid in q.obligation_ids}
    assert covered == {o for o, r in out.items() if r.applies == "needs_answer"}


def test_questionnaire_with_every_fact_has_no_needs_answer(kb: KnowledgeBase) -> None:
    product = from_questionnaire(
        {
            "product_id": "full",
            "name": "Full",
            "agent_classes": ["payment", "customer_facing"],
            "data_classes": ["personal", "financial"],
            "autonomy": "acts_with_approval",
            "cross_border": False,
            "model_hosting": "on_prem",
            "roles": ["deployer"],
        }
    )
    out = assess(kb, product)
    assert [o for o, r in out.items() if r.applies == "needs_answer"] == []
    assert fact_questions(product, out) == []
    assert {r.applies for r in out.values()} == {"yes", "no"}


def test_demo_payments_applies_payment_rows(kb: KnowledgeBase) -> None:
    out = assess(kb, demo_product("payments"))
    assert out["VN-TT53-2026-A4.02A-01"].applies == "yes"
    assert out["VN-TT53-2026-A5.01G2-01"].applies == "yes"
    assert out["VN-TT53-2026-A4.02B-01"].applies == "needs_answer"  # credit tool may be missed
