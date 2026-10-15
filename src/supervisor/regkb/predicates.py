"""Evaluate an ``applies_to`` predicate against a product profile.

Rules: a key missing from the predicate is no condition. A fact the profile does not state
(None) never turns into applies or not_applicable by guessing. But when one known fact
already excludes the obligation, the answer is not_applicable whatever else is unknown.
"""

from __future__ import annotations

from collections.abc import Iterable

from supervisor.regkb.model import (
    Applicability,
    AppliesTo,
    KnowledgeBase,
    Obligation,
    ProductProfile,
)

APPLIES = "applies"
NOT_APPLICABLE = "not_applicable"
UNKNOWN = "unknown"


def _fmt(values: Iterable[str]) -> str:
    return "/".join(values)


def evaluate(applies_to: AppliesTo, profile: ProductProfile) -> Applicability:
    reasons: list[str] = []
    missing: list[str] = []
    failed = False

    def need_overlap(label: str, wanted: tuple[str, ...], have: tuple[str, ...] | None) -> None:
        nonlocal failed
        if have is None:
            missing.append(label)
            reasons.append(f"{label} unknown; needs one of {_fmt(wanted)}")
        elif set(wanted) & set(have):
            reasons.append(f"{label} {_fmt(have)} meets {_fmt(wanted)}")
        else:
            failed = True
            reasons.append(f"{label} {_fmt(have) or 'none'} has none of {_fmt(wanted)}")

    def need_member(label: str, wanted: tuple[str, ...], have: str | None) -> None:
        need_overlap(label, wanted, None if have is None else (have,))

    if applies_to.agent_class is not None:
        if "any" in applies_to.agent_class:
            reasons.append("agent_class any matches every product")
        else:
            need_overlap("agent_classes", applies_to.agent_class, profile.agent_classes)
    if applies_to.data_classes is not None:
        need_overlap("data_classes", applies_to.data_classes, profile.data_classes)
    if applies_to.autonomy is not None:
        need_member("autonomy", applies_to.autonomy, profile.autonomy)
    if applies_to.model_hosting is not None:
        need_member("model_hosting", applies_to.model_hosting, profile.model_hosting)
    if applies_to.role is not None:
        need_overlap("roles", applies_to.role, profile.roles)
    if applies_to.cross_border is not None:
        if profile.cross_border is None:
            missing.append("cross_border")
            reasons.append(f"cross_border unknown; needs {applies_to.cross_border}")
        elif profile.cross_border == applies_to.cross_border:
            reasons.append(f"cross_border is {profile.cross_border} as required")
        else:
            failed = True
            reasons.append(
                f"cross_border is {profile.cross_border}; needs {applies_to.cross_border}"
            )

    if failed:
        status = NOT_APPLICABLE
    elif missing:
        status = UNKNOWN
    else:
        status = APPLIES
    if not reasons:
        reasons.append("no condition in applies_to")
    return Applicability(status, tuple(reasons), tuple(missing))


def applicable(
    kb: KnowledgeBase, profile: ProductProfile, include_not_applicable: bool = True
) -> list[tuple[Obligation, Applicability]]:
    """Evaluate every obligation (sorted by id). Optionally drop the not_applicable ones."""
    out = [(o, evaluate(o.applies_to, profile)) for o in kb.obligations.values()]
    if not include_not_applicable:
        out = [(o, r) for o, r in out if r.status != NOT_APPLICABLE]
    return out
