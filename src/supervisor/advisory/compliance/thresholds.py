"""Circular 53 Art. 5(1)(g)(ii) cap on AI-executed payments (WP14).

Cap per customer per day: individual 100,000,000 VND, organisation 500,000,000 VND.
Each limit the product has is compared with the cap; then one "effective" finding says what
the product as a whole allows. Unknown facts (customer type, no limit known) become
questions, never a guess. Money is integer VND.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

from collections.abc import Iterable

from supervisor.advisory.compliance.model import (
    LimitFact,
    Pointer,
    ProductProfile,
    Question,
    ThresholdFinding,
)

OBLIGATION_ID = "VN-TT53-2026-A5.01G2-01"
_SHORT = "A5.01G2"
CAP_INDIVIDUAL_VND = 100_000_000
CAP_ORGANISATION_VND = 500_000_000
EFFECTIVE_SUFFIX = "-effective"

# Scopes whose daily total bounds the daily total of one customer: a per-agent total is an
# upper bound for every customer; per-account and unknown scopes are not.
_BOUNDING_SCOPES = ("per_customer", "per_agent")


def _fmt(n: int) -> str:
    return f"{n:,}"


def _verdict(limit: int, cap: int) -> str:
    if limit > cap:
        return "exceeds"
    return "at_cap" if limit == cap else "within"


def _customer_type(product: ProductProfile) -> str:
    """individual | organisation | unknown (never a guess)."""
    types = product.customer_types
    if not types:
        return "unknown"
    if "individual" in types:
        return "individual"  # strictest cap; covers every case when the set may be partial
    if product.customer_types_complete:
        return "organisation"
    return "unknown"


def _q_customer_types() -> Question:
    return Question(
        id="Q-customer_types",
        fact="customer_types",
        text_en="Does the product serve individual customers, organisations, or both?",
        text_vi="Sản phẩm phục vụ khách hàng cá nhân, tổ chức, hay cả hai?",
        obligation_ids=(OBLIGATION_ID,),
        why="Circular 53 Art. 5(1)(g)(ii): cap 100,000,000 VND per day for individuals, "
        "500,000,000 VND for organisations.",
    )


def _q_limits() -> Question:
    return Question(
        id="Q-max_daily_vnd",
        fact="max_daily_vnd",
        text_en="What is the largest total per customer per day the product may pay? "
        "No policy or manifest limit is known.",
        text_vi="Tổng giá trị tối đa mỗi khách hàng mỗi ngày mà sản phẩm được phép chi trả "
        "là bao nhiêu? "
        "Chưa biết hạn mức nào trong chính sách hoặc manifest.",
        obligation_ids=(OBLIGATION_ID,),
        why="Circular 53 Art. 5(1)(g)(ii) needs a daily per-customer limit.",
    )


def _applies_check(product: ProductProfile) -> bool:
    if product.executes_payments is False:
        return False
    classes = product.agent_classes or ()
    return "payment" in classes or product.executes_payments is True


def _limit_finding(lim: LimitFact, ctype: str) -> ThresholdFinding:
    ind, org = CAP_INDIVIDUAL_VND, CAP_ORGANISATION_VND
    what = "daily total per customer" if lim.period == "daily" else "single transaction"
    base = f"{lim.id} allows {_fmt(lim.value_vnd)} VND as {what}"
    if ctype == "individual":
        cap, verdict = ind, _verdict(lim.value_vnd, ind)
        reason = f"{base}; cap for individuals is {_fmt(ind)} VND per day"
    elif ctype == "organisation":
        cap, verdict = org, _verdict(lim.value_vnd, org)
        reason = f"{base}; cap for organisations is {_fmt(org)} VND per day"
    else:
        cap = ind
        if lim.value_vnd > org:
            verdict = "exceeds"
            reason = f"{base}; above both caps ({_fmt(ind)} individual, {_fmt(org)} organisation)"
        elif lim.value_vnd < ind:
            verdict = "within"
            reason = f"{base}; below both caps ({_fmt(ind)} individual, {_fmt(org)} organisation)"
        elif lim.value_vnd == ind:
            verdict = "at_cap"
            reason = (
                f"{base}; equals the individual cap ({_fmt(ind)}) and is below the organisation cap"
            )
        else:
            verdict = "needs_answer"
            reason = (
                f"{base}; exceeds the individual cap ({_fmt(ind)} VND) if the product serves "
                f"individuals; within the organisation cap ({_fmt(org)} VND)"
            )
    if lim.period == "per_transaction" and verdict == "at_cap":
        reason += "; one transaction may use the whole daily cap"
    return ThresholdFinding(
        id=f"TH-{_SHORT}-{lim.id}",
        obligation_id=OBLIGATION_ID,
        limit_id=lim.id,
        period=lim.period,
        customer_type=ctype,
        limit_vnd=lim.value_vnd,
        cap_vnd=cap,
        verdict=verdict,
        reason=reason,
        pointer=lim.pointer,
    )


def check_thresholds(product: ProductProfile) -> tuple[list[ThresholdFinding], list[Question]]:
    """Findings per limit plus one effective finding; questions for unknown facts."""
    if not _applies_check(product):
        return [], []
    ctype = _customer_type(product)
    findings: list[ThresholdFinding] = []
    questions: list[Question] = []
    payment_limits = [lim for lim in product.limits if lim.risk_class != "credit"]
    for lim in sorted(payment_limits, key=lambda x: (x.period, x.id)):
        findings.append(_limit_finding(lim, ctype))

    daily = [
        lim for lim in payment_limits if lim.period == "daily" and lim.scope in _BOUNDING_SCOPES
    ]
    eff_id = f"TH-{_SHORT}{EFFECTIVE_SUFFIX}"
    if daily:
        ceiling = min(daily, key=lambda x: (x.value_vnd, x.id))
        base = _limit_finding(ceiling, ctype)
        findings.append(
            ThresholdFinding(
                id=eff_id,
                obligation_id=OBLIGATION_ID,
                limit_id=ceiling.id,
                period="daily",
                customer_type=ctype,
                limit_vnd=ceiling.value_vnd,
                cap_vnd=base.cap_vnd,
                verdict=base.verdict,
                reason="effective daily ceiling is the smallest daily limit: " + base.reason,
                pointer=ceiling.pointer,
            )
        )
        if base.verdict == "needs_answer":
            questions.append(_q_customer_types())
    else:
        per_tx = [lim for lim in payment_limits if lim.period == "per_transaction"]
        ptr: Pointer | None = per_tx[0].pointer if per_tx else None
        if product.controls.known:
            findings.append(
                ThresholdFinding(
                    id=eff_id,
                    obligation_id=OBLIGATION_ID,
                    limit_id="none",
                    period="daily",
                    customer_type=ctype,
                    limit_vnd=None,
                    cap_vnd=CAP_ORGANISATION_VND if ctype == "organisation" else CAP_INDIVIDUAL_VND,
                    verdict="exceeds",
                    reason="no daily per-customer limit; the day total is unbounded"
                    + (
                        " (only per-transaction limits: "
                        + ", ".join(f"{x.id}" for x in per_tx)
                        + ")"
                        if per_tx
                        else ""
                    ),
                    pointer=ptr,
                )
            )
        else:
            findings.append(
                ThresholdFinding(
                    id=eff_id,
                    obligation_id=OBLIGATION_ID,
                    limit_id="none",
                    period="daily",
                    customer_type=ctype,
                    limit_vnd=None,
                    cap_vnd=CAP_ORGANISATION_VND if ctype == "organisation" else CAP_INDIVIDUAL_VND,
                    verdict="needs_answer",
                    reason="product controls and limits are unknown; cannot tell if a daily "
                    "per-customer limit exists",
                    pointer=ptr,
                )
            )
            questions.append(_q_limits())
    # An unknown customer type that changes the result is always one question.
    if ctype == "unknown" and any(f.verdict == "needs_answer" for f in findings):
        if all(q.id != "Q-customer_types" for q in questions):
            questions.append(_q_customer_types())
    return findings, questions


def tied_findings(
    findings: Iterable[ThresholdFinding], obligation_id: str
) -> list[ThresholdFinding]:
    """Findings that decide the row status: the effective finding of the obligation."""
    return [
        f for f in findings if f.obligation_id == obligation_id and f.id.endswith(EFFECTIVE_SUFFIX)
    ]
