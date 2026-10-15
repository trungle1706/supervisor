"""Decision 33 high-risk suggestion (WP14).

Reuses the onboard mapping (``ProductProfile.executes_payments`` etc. come from the onboard
Decision 33 entries) and adds the Circular 53 Art. 4(2) money lines. A condition that is not
known stays ``None`` and becomes a question; nothing is guessed.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

from supervisor.advisory.compliance.model import (
    D33Entry,
    Decision33Suggestion,
    ProductProfile,
    Question,
)
from supervisor.advisory.compliance.questionnaire import make_question
from supervisor.onboard.models import DECISION33_CAVEAT

__all__ = ["suggest_decision33"]

# Circular 53/2026/TT-NHNN Art. 4(2): (per transaction, per day) lines in VND, "over" the line.
LINES = {"individual": (10_000_000, 20_000_000), "organisation": (50_000_000, 100_000_000)}
CREDIT_LINE = 50_000_000  # Art. 4(2)(b): credit of 50 million VND or more

TX_IDS = (
    "VN-QD33-2026-PL4.1-01",
    "VN-QD33-2026-PL4.1-02",
    "VN-QD33-2026-PL4.1-03",
    "VN-TT53-2026-A4.02A-01",
)
CREDIT_IDS = (
    "VN-QD33-2026-PL4.2-01",
    "VN-QD33-2026-PL4.2-02",
    "VN-QD33-2026-PL4.2-03",
    "VN-TT53-2026-A4.02B-01",
)


def _yn(value: bool | None) -> str:
    return "unknown" if value is None else ("yes" if value else "no")


def _vnd(value: int | None) -> str:
    return "unknown" if value is None else f"{value:,} VND"


def _src(product: ProductProfile, name: str) -> str:
    refs = [p.ref for p in product.provenance.get(name, ())][:3]
    return f" (source: {', '.join(refs)})" if refs else ""


def _over(tx: int | None, day: int | None, kind: str) -> bool | None:
    """Tri-state: is the product above the Art. 4(2)(a) lines for one customer type?"""
    line_tx, line_day = LINES[kind]
    if (tx is not None and tx > line_tx) or (day is not None and day > line_day):
        return True
    if tx is not None and day is not None:
        return False
    return None


def _high_value(product: ProductProfile) -> tuple[bool | None, str]:
    tx, day = product.max_transaction_vnd, product.max_daily_vnd
    types = product.customer_types
    complete = product.customer_types_complete and types is not None
    if complete:
        verdicts = [_over(tx, day, t) for t in types or ()]
        if any(v is True for v in verdicts):
            value: bool | None = True
        elif verdicts and all(v is False for v in verdicts):
            value = False
        else:
            value = None
        who = "/".join(types or ()) or "no customers"
        return value, f"customer types {who}"
    ind, org = _over(tx, day, "individual"), _over(tx, day, "organisation")
    if org is True:
        return True, "above the organisation line, so above both lines"
    if ind is False:
        return False, "at or below the individual line, so below both lines"
    return None, "customer types unknown"


def _d33_transactions(product: ProductProfile, qs: dict[str, Question]) -> D33Entry:
    lines: list[str] = []
    ex = product.executes_payments
    if ex is None and product.agent_classes_complete and product.agent_classes is not None:
        if "payment" not in product.agent_classes:
            ex = False
    lines.append(
        f"[VN-QD33-2026-PL4.1-01] Executes payments by itself: {_yn(ex)}"
        f"{_src(product, 'executes_payments')}."
    )
    hv, why = _high_value(product)
    lines.append(
        f"[VN-QD33-2026-PL4.1-02, VN-TT53-2026-A4.02A-01] High value (over 10,000,000 VND per "
        f"transaction or 20,000,000 per day for an individual; over 50,000,000 or 100,000,000 "
        f"for an organisation): {_yn(hv)} ({why}; largest payment "
        f"{_vnd(product.max_transaction_vnd)}{_src(product, 'max_transaction_vnd')}; largest "
        f"day total {_vnd(product.max_daily_vnd)}{_src(product, 'max_daily_vnd')})."
    )
    approval = product.human_approval_before_execution
    no_human = None if approval is None else not approval
    lines.append(
        f"[VN-QD33-2026-PL4.1-03] No human inspection or approval before execution: "
        f"{_yn(no_human)}{_src(product, 'human_approval_before_execution')}."
    )
    conds = (ex, hv, no_human)
    triggered: bool | None
    if any(c is False for c in conds):
        triggered = False
    elif all(c is True for c in conds):
        triggered = True
    else:
        triggered = None
        _ask(
            product,
            qs,
            TX_IDS,
            ex is None and "executes_payments",
            approval is None and "human_approval_before_execution",
        )
        if hv is None:
            if product.customer_types is None:
                _ask(product, qs, TX_IDS, "customer_types")
            if product.max_transaction_vnd is None:
                _ask(product, qs, TX_IDS, "max_transaction_vnd")
            if product.max_daily_vnd is None:
                _ask(product, qs, TX_IDS, "max_daily_vnd")
    return D33Entry("transactions", triggered, tuple(lines), TX_IDS)


def _d33_credit(product: ProductProfile, qs: dict[str, Question]) -> D33Entry:
    cd = product.credit_decisions
    if cd is None and product.agent_classes_complete and product.agent_classes is not None:
        if "credit_decision" not in product.agent_classes:
            cd = False
    lines = [
        f"[VN-QD33-2026-PL4.2-01] Decides credit by itself: {_yn(cd)}"
        f"{_src(product, 'credit_decisions')}."
    ]
    indep = product.independent_credit_approval
    no_indep = None if indep is None else not indep
    lines.append(
        f"[VN-QD33-2026-PL4.2-02] No independent approval by a credit officer: "
        f"{_yn(no_indep)}{_src(product, 'independent_credit_approval')}."
    )
    amount = product.max_credit_vnd
    big = None if amount is None else amount >= CREDIT_LINE
    lines.append(
        f"[VN-QD33-2026-PL4.2-03, VN-TT53-2026-A4.02B-01] Credit of 50,000,000 VND or more: "
        f"{_yn(big)} (largest credit {_vnd(amount)}{_src(product, 'max_credit_vnd')})."
    )
    conds = (cd, no_indep, big)
    triggered: bool | None
    if any(c is False for c in conds):
        triggered = False
    elif all(c is True for c in conds):
        triggered = True
    else:
        triggered = None
        _ask(
            product,
            qs,
            CREDIT_IDS,
            cd is None and "credit_decisions",
            indep is None and "independent_credit_approval",
            amount is None and "max_credit_vnd",
        )
    return D33Entry("credit", triggered, tuple(lines), CREDIT_IDS)


def _ask(
    product: ProductProfile,
    qs: dict[str, Question],
    ids: tuple[str, ...],
    *facts: str | bool,
) -> None:
    for fact in facts:
        if isinstance(fact, str) and fact not in qs:
            qs[fact] = make_question(fact, ids, "Decision 33 suggestion needs this fact.")
        elif isinstance(fact, str):
            q = qs[fact]
            qs[fact] = make_question(fact, (*q.obligation_ids, *ids), q.why)


def suggest_decision33(product: ProductProfile) -> tuple[Decision33Suggestion, list[Question]]:
    """high_risk if any entry is triggered; not_high_risk if every entry is False; else
    needs_answer (with one question per unknown fact)."""
    qs: dict[str, Question] = {}
    entries = (_d33_transactions(product, qs), _d33_credit(product, qs))
    triggered = [e.triggered for e in entries]
    if any(t is True for t in triggered):
        cls = "high_risk"
    elif all(t is False for t in triggered):
        cls = "not_high_risk"
    else:
        cls = "needs_answer"
    # Questions only matter when the class is not settled by a triggered entry.
    questions = [] if cls == "high_risk" else [qs[k] for k in sorted(qs)]
    headline = {
        "high_risk": (
            "Suggested: HIGH RISK under Decision 33 Appendix IV (an entry has all its conditions)."
        ),
        "not_high_risk": (
            "Suggested: not high risk under Decision 33 Appendix IV "
            "(no entry has all its conditions)."
        ),
        "needs_answer": "Cannot tell yet: answer the open questions.",
    }[cls]
    lines = [headline]
    for e in entries:
        state = {True: "triggered", False: "not triggered", None: "needs an answer"}[e.triggered]
        lines.append(f"Entry {e.entry}: {state}.")
        lines.extend(e.lines)
    return (
        Decision33Suggestion(
            classification=cls,
            entries=entries,
            lines=tuple(lines),
            caveat=DECISION33_CAVEAT,
            question_ids=tuple(q.id for q in questions),
        ),
        questions,
    )
