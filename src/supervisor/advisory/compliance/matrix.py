"""Build the obligations matrix: one row per RegKB obligation (WP14).

Every status traces to control ids and product facts. Unknown facts become questions.
The narrative (if any) is added last and changes nothing.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from datetime import UTC, date, datetime

from supervisor.advisory.compliance.applicability import assess, fact_questions
from supervisor.advisory.compliance.deadlines import deadline_for, needs_operation_date
from supervisor.advisory.compliance.decision33 import suggest_decision33
from supervisor.advisory.compliance.model import (
    APPLIES,
    STATUSES,
    MatrixHeader,
    MatrixRow,
    ObligationMatrix,
    Pointer,
    ProductProfile,
    Question,
)
from supervisor.advisory.compliance.narrative import build_narrative
from supervisor.advisory.compliance.status import check_controls, counts_as_present, derive_status
from supervisor.advisory.compliance.thresholds import check_thresholds, tied_findings
from supervisor.core.ports import ChatModel
from supervisor.regkb import DISCLAIMER
from supervisor.regkb.model import KnowledgeBase

ADVISORY_NOTE = (
    "Advisory only. This matrix is a working aid built from RegKB and the product facts "
    "listed in it. It does not decide compliance. Unknown facts are open questions."
)


def _q_in_operation() -> Question:
    return Question(
        id="Q-in_operation_since",
        fact="in_operation_since",
        text_en="Since what date has the product been in official operation? "
        "Circular 53 Art. 24 and AI Law Art. 35 give different transition dates.",
        text_vi="Sản phẩm đã chính thức vận hành từ ngày nào? "
        "Thông tư 53 Điều 24 và Luật AI Điều 35 có ngày chuyển tiếp khác nhau.",
        why="The transition date that applies depends on this date.",
    )


def _merge_questions(groups: list[list[Question]]) -> list[Question]:
    merged: dict[str, Question] = {}
    for group in groups:
        for q in group:
            old = merged.get(q.id)
            if old is None:
                merged[q.id] = q
            else:
                ids = tuple(sorted(set(old.obligation_ids) | set(q.obligation_ids)))
                merged[q.id] = dataclasses.replace(old, obligation_ids=ids)
    return [
        dataclasses.replace(q, obligation_ids=tuple(sorted(set(q.obligation_ids))))
        for _, q in sorted(merged.items())
    ]


def _packs_by_duty() -> dict[str, list[str]]:
    """duty id -> assurance pack ids (src/supervisor/assurance/packs). Empty if unreadable."""
    try:
        from supervisor.assurance.loader import load_packs

        packs = load_packs()
    except Exception:  # noqa: BLE001 - optional evidence hint, never fatal
        return {}
    out: dict[str, list[str]] = {}
    for p in packs:
        for duty in p.maps_to.regkb_duties:
            out.setdefault(duty, []).append(p.id)
    return out


def build_matrix(
    kb: KnowledgeBase,
    product: ProductProfile,
    *,
    as_of: str | None = None,
    generated_at: str | None = None,
    chat: ChatModel | None = None,
) -> ObligationMatrix:
    assessed = assess(kb, product)
    findings, th_questions = check_thresholds(product)
    d33, d33_questions = suggest_decision33(product)

    # first pass: statuses and the obligations that need the operation date
    op_ids: list[str] = []
    partial: dict[str, dict] = {}
    for oid, ob in sorted(kb.obligations.items()):
        app = assessed[oid]
        applies = app.applies if app.applies in APPLIES else "needs_answer"
        checks = check_controls(ob, product.controls) if applies != "no" else ()
        tied = tied_findings(findings, oid) if applies != "no" else []
        status, reason = derive_status(applies, checks, tied)
        if applies == "yes" or applies == "needs_answer":
            if any(f.verdict == "needs_answer" for f in tied):
                reason += "; threshold check needs an answer (see open questions)"
        if applies != "no" and product.in_operation_since is None and needs_operation_date(ob):
            op_ids.append(oid)
        partial[oid] = {
            "applies": applies,
            "checks": checks,
            "tied": tied,
            "status": status,
            "reason": reason,
        }

    q_op = [dataclasses.replace(_q_in_operation(), obligation_ids=tuple(op_ids))] if op_ids else []
    questions = _merge_questions(
        [list(fact_questions(product, assessed)), th_questions, list(d33_questions), q_op]
    )
    by_obligation: dict[str, list[str]] = {}
    for q in questions:
        for oid in q.obligation_ids:
            by_obligation.setdefault(oid, []).append(q.id)

    packs = _packs_by_duty()
    rows: list[MatrixRow] = []
    for oid, ob in sorted(kb.obligations.items()):
        p = partial[oid]
        app = assessed[oid]
        pointers: list[Pointer] = []
        for c in p["checks"]:
            if counts_as_present(c) and c.pointer is not None and c.pointer not in pointers:
                pointers.append(c.pointer)
        for f in p["tied"]:
            if f.pointer is not None and f.pointer not in pointers:
                pointers.append(f.pointer)
        rows.append(
            MatrixRow(
                obligation_id=oid,
                instrument_id=ob.instrument_id,
                instrument_number=ob.number,
                jurisdiction=ob.jurisdiction,
                binding=ob.binding,
                instrument_status=ob.status,
                article_ref=ob.article_ref,
                summary_en=ob.summary_en,
                duties=tuple(ob.duties),
                applies=p["applies"],
                applies_reasons=tuple(app.reasons),
                missing_facts=tuple(app.missing_facts),
                status=p["status"],
                status_reason=p["reason"],
                controls=p["checks"],
                evidence_needed=tuple(ob.evidence_needed),
                evidence_pointers=tuple(pointers),
                deadline=deadline_for(ob, kb),
                question_ids=tuple(sorted(by_obligation.get(oid, []))),
                threshold_ids=tuple(sorted(f.id for f in findings if f.obligation_id == oid)),
                assurance_packs=()
                if p["applies"] == "no"
                else tuple(sorted({pid for d in ob.duties for pid in packs.get(d, [])})),
            )
        )

    yes_rows = [r for r in rows if r.applies == "yes"]
    by_status = {s: 0 for s in STATUSES}
    by_status.update(Counter(r.status for r in yes_rows))
    by_applies = {a: 0 for a in APPLIES}
    by_applies.update(Counter(r.applies for r in rows))
    by_instrument: dict[str, dict[str, int]] = {}
    for r in rows:
        d = by_instrument.setdefault(
            r.instrument_id, {"total": 0, "yes": 0, "needs_answer": 0, "no": 0}
        )
        d["total"] += 1
        d[r.applies] += 1
        if r.applies == "yes":
            d[r.status] = d.get(r.status, 0) + 1
    summary = {
        "by_status": by_status,
        "by_applies": by_applies,
        "needs_answer": by_applies["needs_answer"],
        "questions": len(questions),
        # decisive findings (the effective ceiling per obligation) that exceed a cap
        "threshold_gaps": sum(
            1 for f in findings if f.id.endswith("-effective") and f.verdict == "exceeds"
        ),
        # every single limit that is above its cap, including limits a stricter limit overrides
        "threshold_exceeds": sum(1 for f in findings if f.verdict == "exceeds"),
        "by_instrument": dict(sorted(by_instrument.items())),
    }
    internal = tuple(sorted(i.id for i in kb.instruments if i.kind == "internal"))
    header = MatrixHeader(
        product_id=product.product_id,
        product_name=product.name,
        product_source=product.source,
        regkb_version=kb.version,
        instruments=len(kb.instruments),
        obligations=len(kb.obligations),
        internal_rules=bool(internal),
        internal_instruments=internal,
        as_of=as_of or date.today().isoformat(),
        generated_at=generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        disclaimer=DISCLAIMER,
        advisory_note=ADVISORY_NOTE,
    )
    matrix = ObligationMatrix(
        header=header,
        product=product,
        rows=tuple(rows),
        questions=tuple(questions),
        thresholds=tuple(sorted(findings, key=lambda f: f.id)),
        decision33=d33,
        summary=summary,
        narrative=None,
    )
    if chat is not None:
        matrix = dataclasses.replace(matrix, narrative=build_narrative(matrix, chat))
    return matrix
