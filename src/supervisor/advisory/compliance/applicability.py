"""Which obligations apply to a product (WP14). Reuses ``supervisor.regkb.evaluate``.

Incomplete sets (found in code = a lower bound): when a set is not complete and the found
values do not overlap the values an obligation wants, the set is passed as unknown (None), so
the answer is ``needs_answer`` and never a false ``no``. Positive evidence is enough: if the
found values overlap, they are passed as they are.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from supervisor import regkb
from supervisor.advisory.compliance.model import ProductProfile, Question
from supervisor.advisory.compliance.questionnaire import make_question
from supervisor.regkb import AppliesTo, KnowledgeBase

__all__ = ["RowApplicability", "assess", "fact_questions", "regkb_profile"]

_YES, _NO, _ASK = "yes", "no", "needs_answer"
_STATUS = {regkb.predicates.APPLIES: _YES, regkb.predicates.NOT_APPLICABLE: _NO}


@dataclass(frozen=True)
class RowApplicability:
    obligation_id: str
    applies: str  # yes | no | needs_answer
    reasons: tuple[str, ...] = ()
    missing_facts: tuple[str, ...] = ()


def _agent_classes(product: ProductProfile) -> tuple[tuple[str, ...] | None, bool]:
    """Found agent classes after the ``customer_facing`` flag, and whether the set is complete."""
    base, complete = product.agent_classes, product.agent_classes_complete
    cf = product.customer_facing
    if cf is True:
        return tuple(
            dict.fromkeys([*(base or ()), "customer_facing"])
        ), complete and base is not None
    if cf is False and base is not None and complete:
        return tuple(c for c in base if c != "customer_facing"), True
    return base, complete and base is not None


def _pick(
    found: tuple[str, ...] | None, complete: bool, wanted: tuple[str, ...] | None
) -> tuple[str, ...] | None:
    if wanted is None or found is None or complete or "any" in wanted:
        return found
    return found if set(found) & set(wanted) else None


def _profile_for(product: ProductProfile, wanted: AppliesTo) -> regkb.ProductProfile:
    classes, classes_complete = _agent_classes(product)
    return regkb.ProductProfile(
        agent_classes=_pick(classes, classes_complete, wanted.agent_class),
        data_classes=_pick(
            product.data_classes, product.data_classes_complete, wanted.data_classes
        ),
        autonomy=product.autonomy,
        cross_border=product.cross_border,
        model_hosting=product.model_hosting,
        roles=_pick(product.roles, product.roles_complete, wanted.role),
    )


def regkb_profile(product: ProductProfile) -> regkb.ProductProfile:
    """The found values as a RegKB profile (sets as found, ``customer_facing`` applied). Use
    ``assess`` for the per-obligation answer; it treats incomplete sets with care."""
    classes, _ = _agent_classes(product)
    return regkb.ProductProfile(
        agent_classes=classes,
        data_classes=product.data_classes,
        autonomy=product.autonomy,
        cross_border=product.cross_border,
        model_hosting=product.model_hosting,
        roles=product.roles,
    )


def assess(kb: KnowledgeBase, product: ProductProfile) -> dict[str, RowApplicability]:
    """Applicability of every obligation in the KB (sorted by obligation id)."""
    out: dict[str, RowApplicability] = {}
    for oid in sorted(kb.obligations):
        ob = kb.obligations[oid]
        res = regkb.evaluate(ob.applies_to, _profile_for(product, ob.applies_to))
        reasons = res.reasons
        if res.missing_facts:
            lower = [
                f
                for f, incomplete in (
                    ("agent_classes", not _agent_classes(product)[1]),
                    ("data_classes", not product.data_classes_complete),
                    ("roles", not product.roles_complete),
                )
                if f in res.missing_facts and incomplete and _known(product, f)
            ]
            if lower:
                reasons = (
                    *reasons,
                    "found so far (lower bound, the set may be incomplete): "
                    + "; ".join(f"{f} {'/'.join(_found(product, f)) or 'none'}" for f in lower),
                )
        out[oid] = RowApplicability(oid, _STATUS.get(res.status, _ASK), reasons, res.missing_facts)
    return out


def _known(product: ProductProfile, fact: str) -> bool:
    return _found(product, fact) is not None


def _found(product: ProductProfile, fact: str) -> tuple[str, ...] | None:
    if fact == "agent_classes":
        return _agent_classes(product)[0]
    return getattr(product, fact)


_WHY = {
    "agent_classes": (
        "Code shows only some agent classes, or none; the missing ones decide these rows."
    ),
    "data_classes": (
        "Code shows only some data classes; legal classes such as sensitive_personal "
        "are never read from code."
    ),
    "roles": (
        "The scan assumes the bank is the deployer; whether it is also the provider is not in code."
    ),
    "autonomy": "Autonomy is not known.",
    "cross_border": "Code cannot prove whether data leaves Vietnam.",
    "model_hosting": "Code cannot prove where the model is hosted.",
}


def fact_questions(
    product: ProductProfile, assessed: Mapping[str, RowApplicability]
) -> list[Question]:
    """One Question per missing fact (id ``Q-<fact>``) with the obligation ids it would decide."""
    by_fact: dict[str, list[str]] = {}
    for oid in sorted(assessed):
        row = assessed[oid]
        if row.applies != _ASK:
            continue
        for fact in row.missing_facts:
            by_fact.setdefault(fact, []).append(oid)
    questions: list[Question] = []
    for fact in sorted(by_fact):
        why = _WHY.get(fact, "")
        found = (
            _found(product, fact) if fact in ("agent_classes", "data_classes", "roles") else None
        )
        if found:
            why += f" Found so far: {', '.join(found)}."
        questions.append(make_question(fact, tuple(by_fact[fact]), why.strip()))
    return questions
