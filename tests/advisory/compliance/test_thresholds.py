from __future__ import annotations

import dataclasses

from supervisor.advisory.compliance.thresholds import (
    OBLIGATION_ID,
    check_thresholds,
    tied_findings,
)

from ._factory import payments_product


def _by_limit(findings):
    return {f.limit_id: f for f in findings}


def _effective(findings):
    (eff,) = [f for f in findings if f.id.endswith("-effective")]
    return eff


def test_payments_individual_exceeds():
    findings, questions = check_thresholds(payments_product())
    by = _by_limit([f for f in findings if not f.id.endswith("-effective")])
    assert by["PAY-03"].verdict == "exceeds"
    assert by["PAY-03"].limit_vnd == 150_000_000 and by["PAY-03"].cap_vnd == 100_000_000
    assert by["PAY-02"].verdict == "at_cap"
    assert "whole daily cap" in by["PAY-02"].reason
    assert by["daily_transfer_max_minor"].verdict == "exceeds"
    eff = _effective(findings)
    assert eff.verdict == "exceeds" and eff.limit_id == "PAY-03"
    assert eff.obligation_id == OBLIGATION_ID == "VN-TT53-2026-A5.01G2-01"
    assert questions == []
    assert tied_findings(findings, OBLIGATION_ID) == [eff]


def test_organisation_only_is_within():
    findings, questions = check_thresholds(payments_product(customer_types=("organisation",)))
    assert _effective(findings).verdict == "within"
    assert _effective(findings).cap_vnd == 500_000_000
    assert questions == []


def test_unknown_customer_type_at_150m_needs_answer():
    findings, questions = check_thresholds(payments_product(customer_types=None, complete=False))
    eff = _effective(findings)
    assert eff.verdict == "needs_answer" and eff.customer_type == "unknown"
    assert "individuals" in eff.reason
    assert [q.id for q in questions] == ["Q-customer_types"]
    assert OBLIGATION_ID in questions[0].obligation_ids


def test_incomplete_organisation_set_is_unknown():
    findings, questions = check_thresholds(
        payments_product(customer_types=("organisation",), complete=False)
    )
    assert _effective(findings).verdict == "needs_answer"
    assert questions


def test_unknown_type_over_both_caps_still_exceeds():
    p = payments_product(customer_types=None, complete=False)
    limits = tuple(
        dataclasses.replace(x, value_vnd=600_000_000) if x.period == "daily" else x
        for x in p.limits
    )
    findings, _ = check_thresholds(dataclasses.replace(p, limits=limits))
    assert _effective(findings).verdict == "exceeds"


def test_no_daily_limit_known_controls_exceeds():
    p = payments_product(daily=False)
    p = dataclasses.replace(p, limits=tuple(x for x in p.limits if x.period != "daily"))
    findings, questions = check_thresholds(p)
    eff = _effective(findings)
    assert eff.verdict == "exceeds" and eff.limit_id == "none" and eff.limit_vnd is None
    assert "unbounded" in eff.reason
    assert questions == []


def test_controls_unknown_needs_answer():
    p = payments_product(daily=False, known=False)
    p = dataclasses.replace(p, limits=())
    findings, questions = check_thresholds(p)
    assert _effective(findings).verdict == "needs_answer"
    assert "Q-max_daily_vnd" in [q.id for q in questions]


def test_not_a_payment_product_has_no_findings():
    p = dataclasses.replace(
        payments_product(), agent_classes=("customer_facing",), executes_payments=False
    )
    assert check_thresholds(p) == ([], [])
    p = dataclasses.replace(payments_product(), executes_payments=None, agent_classes=None)
    assert check_thresholds(p) == ([], [])


def test_money_is_integer():
    findings, _ = check_thresholds(payments_product())
    for f in findings:
        assert isinstance(f.cap_vnd, int)
        assert f.limit_vnd is None or isinstance(f.limit_vnd, int)
