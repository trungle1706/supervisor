"""Snapshot tests of the compliance matrix for four products (WP14).

``UPDATE_SNAPSHOTS=1`` rewrites the snapshot files. Not legal advice.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from supervisor.advisory.compliance import corpus_product, demo_product
from supervisor.advisory.compliance.matrix import build_matrix
from supervisor.advisory.compliance.render import to_json, to_markdown

SNAP_DIR = Path(__file__).parent / "snapshots"
AS_OF = "2026-10-15"
GEN = "2026-10-15T00:00:00Z"
NAMES = ("payments", "credit_prequal", "customer_service", "fastapi_toolserver_remit")


def _product(name: str):
    return corpus_product(name) if name == "fastapi_toolserver_remit" else demo_product(name)


def _build(kb, name: str):
    return build_matrix(kb, _product(name), as_of=AS_OF, generated_at=GEN, chat=None)


def project(m) -> dict:
    d33 = m.decision33
    return {
        "header": {name: getattr(m.header, name) for name in m.header.__dataclass_fields__},
        "summary": {
            k: m.summary[k]
            for k in (
                "by_status",
                "by_applies",
                "needs_answer",
                "questions",
                "threshold_gaps",
                "threshold_exceeds",
            )
        },
        "decision33": {
            "classification": d33.classification,
            "entries": [
                {"entry": e.entry, "triggered": e.triggered, "lines": list(e.lines)}
                for e in d33.entries
            ],
        },
        "thresholds": [
            {
                "id": t.id,
                "limit_id": t.limit_id,
                "limit_vnd": t.limit_vnd,
                "cap_vnd": t.cap_vnd,
                "verdict": t.verdict,
            }
            for t in m.thresholds
        ],
        "questions": [{"id": q.id, "obligations": len(q.obligation_ids)} for q in m.questions],
        "rows": [
            [r.obligation_id, r.applies, r.status, sorted(c.id for c in r.controls if c.present)]
            for r in m.rows
        ],
    }


def _dump(data: dict) -> str:
    return json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("name", NAMES)
def test_snapshot(kb, name):
    text = _dump(project(_build(kb, name)))
    path = SNAP_DIR / f"{name}.json"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.is_file(), "run with UPDATE_SNAPSHOTS=1 to create the snapshot"
    assert text == path.read_text(encoding="utf-8")


def test_payments_threshold_gap(kb):
    m = _build(kb, "payments")
    row = next(r for r in m.rows if r.obligation_id == "VN-TT53-2026-A5.01G2-01")
    assert row.status == "gap"
    assert "PAY-03" in row.status_reason


@pytest.mark.parametrize("name", ["payments", "credit_prequal"])
def test_high_risk(kb, name):
    assert _build(kb, name).decision33.classification == "high_risk"


def test_remit_value_unknown_is_a_question(kb):
    """No payment value limit in the remit policy: Decision 33 asks for the largest value,
    it does not assume "unbounded" (the Art. 5 daily-cap check still reports the missing
    daily limit as a gap, by its own rule)."""
    m = _build(kb, "fastapi_toolserver_remit")
    assert m.decision33.classification == "needs_answer"
    assert {"Q-max_transaction_vnd", "Q-max_daily_vnd"} <= set(m.decision33.question_ids)


@pytest.mark.parametrize("name", NAMES)
def test_rows_cite_known_obligations(kb, name):
    m = _build(kb, name)
    assert {r.obligation_id for r in m.rows} == set(kb.obligations)
    assert m.header.regkb_version == kb.version


def test_json_is_byte_identical(kb):
    assert to_json(_build(kb, "payments")) == to_json(_build(kb, "payments"))


def test_assurance_packs_are_evidence_hints_only(kb) -> None:
    """WP17 packs that map to a row's duties are listed; they never change a status."""
    from supervisor.assurance.loader import load_packs

    m = build_matrix(kb, demo_product("credit_prequal"), as_of="2026-10-15", generated_at="x")
    duty_packs = {p.id: set(p.maps_to.regkb_duties) for p in load_packs()}
    hinted = [r for r in m.rows if r.assurance_packs]
    assert hinted, "some rows should name an assurance pack"
    for r in hinted:
        for pid in r.assurance_packs:
            assert duty_packs[pid] & set(r.duties)
    assert any("fairness_metrics" in r.assurance_packs for r in m.rows)
    assert "eval_result pack" in to_markdown(m)


def test_wp19_evidence_hints_follow_duties(kb) -> None:
    """Incident-clock and judge-MRM hints appear on rows with matching duties, nowhere else."""
    from supervisor.advisory.compliance.matrix import EVIDENCE_HINTS

    m = build_matrix(kb, demo_product("payments"), as_of="2026-10-15", generated_at="x")
    incident = [r for r in m.rows if "incident_report_72h" in r.duties and r.applies != "no"]
    assert incident and all(any("incident clock" in h for h in r.evidence_hints) for r in incident)
    for r in m.rows:
        assert set(r.evidence_hints) <= {h for d in r.duties for h in EVIDENCE_HINTS.get(d, ())}
    plain = build_matrix(kb, demo_product("payments"), as_of="2026-10-15", generated_at="x")
    assert [r.status for r in plain.rows] == [r.status for r in m.rows]
