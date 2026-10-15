from __future__ import annotations

import pytest

from supervisor.advisory.compliance.deadlines import deadline_for, needs_operation_date
from supervisor.regkb import load_kb


@pytest.fixture(scope="module")
def kb():
    return load_kb()


def _ob(kb, instrument_id, article_prefix):
    for o in kb.obligations.values():
        if o.instrument_id == instrument_id and o.article_ref.startswith(article_prefix):
            return o
    raise AssertionError(f"no obligation {instrument_id} {article_prefix}")


def _first(kb, instrument_id):
    return next(o for o in kb.obligations.values() if o.instrument_id == instrument_id)


def test_art14_gets_article_effective(kb):
    d = deadline_for(_ob(kb, "VN-TT53-2026", "Art. 14"), kb)
    assert d.article_effective is not None
    assert d.article_effective.date == "2027-01-01"


def test_art6_1b_gets_article_effective(kb):
    d = deadline_for(_ob(kb, "VN-TT53-2026", "Art. 6(1)(b)"), kb)
    assert d.article_effective is not None
    assert d.article_effective.date == "2027-09-01"


def test_other_article_gets_no_article_effective(kb):
    d = deadline_for(_ob(kb, "VN-TT53-2026", "Art. 5(1)(g)(ii)"), kb)
    assert d.article_effective is None


def test_tt53_compliance_deadline(kb):
    d = deadline_for(_ob(kb, "VN-TT53-2026", "Art. 5(1)(g)(ii)"), kb)
    assert d.compliance_deadline is not None and d.compliance_deadline.date == "2027-03-01"
    assert d.effective is not None and d.effective.date == "2026-11-15"
    assert any(t.date == "2027-03-01" for t in d.transitions)


def test_ai_law_row_shows_art35_milestones(kb):
    d = deadline_for(_first(kb, "VN-AI-2025"), kb)
    labels = " ".join(t.label for t in d.transitions)
    assert "Art. 35(1)(a)" in labels and "Art. 35(1)(b)" in labels
    assert {"2027-03-01", "2027-09-01"} <= {t.date for t in d.transitions}


def test_operation_date_rows(kb):
    assert needs_operation_date(_ob(kb, "VN-TT53-2026", "Art. 14"))
    assert needs_operation_date(_first(kb, "VN-AI-2025"))
    assert not needs_operation_date(_first(kb, "VN-PDPL-2025"))
