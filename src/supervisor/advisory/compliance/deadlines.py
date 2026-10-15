"""Dates of an obligation: effective, compliance deadline, transitions, article date (WP14).

Only data from RegKB is shown. Nothing is invented.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import re

from supervisor.advisory.compliance.model import DateItem, Deadline
from supervisor.regkb.model import DatedFact, KnowledgeBase, Obligation

# Rows whose transition date depends on "in official operation before ..." (Circular 53
# Art. 24, AI Law Art. 35): the product fact in_operation_since decides which date applies.
_OPERATION_DATE_PREFIXES = ("VN-TT53-", "VN-AI-2025")

_ART = re.compile(r"^Art\. \d+[a-z]?(?:\([^)]*\))*")


def _item(fact: DatedFact, label: str) -> DateItem:
    return DateItem(
        label=label,
        date=fact.date,
        source=fact.source,
        verification=fact.verification,
        note=fact.note or "",
    )


def _article_matches(label: str, article_ref: str) -> bool:
    m = _ART.match(label)
    if not m:
        return False
    token = m.group(0)
    if not article_ref.startswith(token):
        return False
    rest = article_ref[len(token) :]
    return rest == "" or not rest[0].isalnum()


def needs_operation_date(obligation: Obligation) -> bool:
    """True when the row's transition date depends on in_operation_since."""
    return obligation.instrument_id.startswith(_OPERATION_DATE_PREFIXES)


def deadline_for(obligation: Obligation, kb: KnowledgeBase | None = None) -> Deadline:
    """Dates for one obligation. ``kb`` is accepted for API symmetry (dates are merged already)."""
    dates = obligation.dates
    inst_dates = None
    if kb is not None:
        try:
            inst_dates = kb.instrument(obligation.instrument_id).dates
        except Exception:  # unknown instrument id: use the obligation's own dates only
            inst_dates = None
    # The obligation's own dates override the instrument's, field by field.
    eff_fact = dates.effective or (inst_dates.effective if inst_dates else None)
    dl_fact = dates.compliance_deadline or (inst_dates.compliance_deadline if inst_dates else None)
    milestones = dates.milestones or (inst_dates.milestones if inst_dates else None) or ()
    effective = _item(eff_fact, "effective") if eff_fact else None
    deadline = _item(dl_fact, "compliance_deadline") if dl_fact else None
    article: DateItem | None = None
    transitions: list[DateItem] = []
    for ms in milestones:
        label = ms.label or "milestone"
        item = _item(ms, label)
        if article is None and _article_matches(label, obligation.article_ref):
            article = item
        else:
            transitions.append(item)
    if (
        article is None
        and dates.effective is not None
        and inst_dates is not None
        and inst_dates.effective is not None
        and dates.effective.date != inst_dates.effective.date
    ):
        # The obligation carries its own, later effective date (for example Art. 14).
        article = _item(dates.effective, f"{obligation.article_ref} takes effect")
    return Deadline(
        effective=effective,
        compliance_deadline=deadline,
        transitions=tuple(transitions),
        article_effective=article,
    )
