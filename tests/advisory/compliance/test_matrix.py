from __future__ import annotations

import dataclasses

import pytest

from supervisor.adapters.llm.mock import MockChat
from supervisor.advisory.compliance.matrix import build_matrix
from supervisor.advisory.compliance.model import APPLIES, STATUSES
from supervisor.regkb import DISCLAIMER, load_kb

from ._factory import payments_product

AS_OF = "2026-10-15"
GEN = "2026-10-15T00:00:00Z"
TH_ROW = "VN-TT53-2026-A5.01G2-01"


@pytest.fixture(scope="module")
def kbase():
    return load_kb()


def _product(**over):
    p = payments_product()
    return dataclasses.replace(
        p,
        roles=("deployer",),
        roles_complete=True,
        agent_classes_complete=True,
        data_classes=("personal", "financial"),
        data_classes_complete=True,
        **over,
    )


@pytest.fixture(scope="module")
def matrix(kbase):
    return build_matrix(kbase, _product(), as_of=AS_OF, generated_at=GEN)


def test_rows_cover_every_obligation_sorted(matrix, kbase):
    ids = [r.obligation_id for r in matrix.rows]
    assert ids == sorted(ids)
    assert set(ids) == set(kbase.obligations)
    assert len(ids) == len(kbase.obligations)
    for r in matrix.rows:
        assert r.obligation_id in kbase.obligations
        assert r.summary_en == kbase.obligations[r.obligation_id].summary_en


def test_header(matrix, kbase):
    h = matrix.header
    assert h.regkb_version == kbase.version
    assert h.obligations == len(kbase.obligations) and h.instruments == len(kbase.instruments)
    assert h.disclaimer == DISCLAIMER
    assert h.as_of == AS_OF and h.generated_at == GEN
    assert h.internal_rules is False and h.internal_instruments == ()
    assert h.advisory_note.startswith("Advisory only.")


def test_summary_counts_add_up(matrix):
    s = matrix.summary
    yes = sum(1 for r in matrix.rows if r.applies == "yes")
    assert sum(s["by_status"].values()) == yes == s["by_applies"]["yes"]
    assert set(s["by_status"]) == set(STATUSES)
    assert sum(s["by_applies"].values()) == len(matrix.rows)
    assert set(s["by_applies"]) == set(APPLIES)
    assert s["needs_answer"] == s["by_applies"]["needs_answer"]
    assert s["questions"] == len(matrix.questions)
    assert sum(v["total"] for v in s["by_instrument"].values()) == len(matrix.rows)


def test_questions_sorted_unique_and_point_at_real_rows(matrix, kbase):
    ids = [q.id for q in matrix.questions]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
    for q in matrix.questions:
        assert q.text_en and q.text_vi
        assert all(o in kbase.obligations for o in q.obligation_ids)
    by_row = {r.obligation_id: r for r in matrix.rows}
    for q in matrix.questions:
        for oid in q.obligation_ids:
            assert q.id in by_row[oid].question_ids


def test_threshold_row_is_gap(matrix):
    row = next(r for r in matrix.rows if r.obligation_id == TH_ROW)
    assert row.applies == "yes"
    assert row.status == "gap"
    assert "PAY-03" in row.status_reason
    assert row.threshold_ids
    assert any(p.ref == "policies/baseline.yaml:154" for p in row.evidence_pointers)
    assert matrix.summary["threshold_gaps"] >= 1


def test_not_applicable_rows_have_no_controls(matrix):
    for r in matrix.rows:
        if r.applies == "no":
            assert r.status == "not_applicable" and r.controls == ()


def test_status_traces_to_controls_or_threshold(matrix):
    for r in matrix.rows:
        if r.applies == "no":
            continue
        assert r.status_reason
        if r.status == "bank_process":
            mapped = [c.id for c in r.controls] or ["no control"]
            assert any(m in r.status_reason for m in mapped)
        elif r.status in ("met", "partial", "gap") and r.threshold_ids == ():
            assert r.controls, r.obligation_id
            assert any(c.id in r.status_reason for c in r.controls)


def test_needs_answer_rows_keep_applies_and_have_status(matrix):
    na = [r for r in matrix.rows if r.applies == "needs_answer"]
    for r in na:
        assert r.status in ("met", "partial", "gap", "bank_process")
        assert "if the obligation applies" in r.status_reason
        assert r.missing_facts


def test_unknown_operation_date_raises_question_for_tt53_and_ai_law(kbase):
    m = build_matrix(kbase, _product(), as_of=AS_OF, generated_at=GEN)
    q = next(q for q in m.questions if q.id == "Q-in_operation_since")
    assert all(o.startswith(("VN-TT53-", "VN-AI-2025")) for o in q.obligation_ids)
    assert TH_ROW in q.obligation_ids


def test_deterministic(kbase, matrix):
    again = build_matrix(kbase, _product(), as_of=AS_OF, generated_at=GEN)
    assert again == matrix


def test_narrative_only_when_chat_given_and_changes_nothing(kbase, matrix):
    assert matrix.narrative is None
    with_n = build_matrix(kbase, _product(), as_of=AS_OF, generated_at=GEN, chat=MockChat())
    assert with_n.narrative is not None and with_n.narrative.is_mock is True
    assert with_n.rows == matrix.rows and with_n.summary == matrix.summary
    assert with_n.questions == matrix.questions


def test_unknown_controls_never_produce_met(kbase):
    p = _product()
    p = dataclasses.replace(p, controls=dataclasses.replace(p.controls, known=False))
    m = build_matrix(kbase, p, as_of=AS_OF, generated_at=GEN)
    assert m.summary["by_status"]["met"] == 0
    assert m.summary["by_status"]["partial"] == 0
