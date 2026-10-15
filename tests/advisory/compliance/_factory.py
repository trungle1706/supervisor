"""Small builders for W2 tests (no dependency on the facts / applicability modules)."""

from __future__ import annotations

from supervisor.advisory.compliance.model import (
    ControlCheck,
    D33Entry,
    Deadline,
    Decision33Suggestion,
    LimitFact,
    MatrixHeader,
    MatrixRow,
    Narrative,
    ObligationMatrix,
    Pointer,
    ProductControls,
    ProductProfile,
    Question,
    RuleFact,
    ThresholdFinding,
)
from supervisor.regkb import DISCLAIMER


def payments_product(
    *,
    customer_types: tuple[str, ...] | None = ("individual",),
    complete: bool = True,
    known: bool = True,
    daily: bool = True,
) -> ProductProfile:
    limits = [
        LimitFact(
            "PAY-02",
            "rule",
            "per_transaction",
            "per_customer",
            100_000_000,
            ("transfer",),
            Pointer("rule", "policies/baseline.yaml:139"),
        ),
        LimitFact(
            "daily_transfer_max_minor",
            "manifest",
            "daily",
            "per_agent",
            300_000_000,
            (),
            Pointer("manifest", "daily_transfer_max_minor"),
        ),
    ]
    if daily:
        limits.append(
            LimitFact(
                "PAY-03",
                "rule",
                "daily",
                "per_customer",
                150_000_000,
                ("transfer",),
                Pointer("rule", "policies/baseline.yaml:154"),
            )
        )
    controls = ProductControls(
        known=known,
        basis="planned",
        supervised=True,
        catalogue_on=("single_limit",),
        rules=(
            RuleFact("PAY-02", "single transfer", Pointer("rule", "policies/baseline.yaml:139")),
        ),
        pointers={"catalogue:single_limit": Pointer("plan", "single_limit")},
    )
    return ProductProfile(
        product_id="payments",
        name="Payments agent",
        source="onboard",
        agent_classes=("payment",),
        executes_payments=True,
        customer_types=customer_types,
        customer_types_complete=complete,
        limits=tuple(limits),
        controls=controls,
    )


def tiny_matrix(*, narrative: Narrative | None = None, evil: str = "") -> ObligationMatrix:
    """A hand-built matrix with three rows (yes/gap, needs_answer/partial, no)."""
    dl = Deadline()
    rows = (
        MatrixRow(
            "OB-1",
            "INST-1",
            "1/2026",
            "VN",
            True,
            "in_force",
            "Art. 1",
            evil or "Duty one.",
            ("d1",),
            "yes",
            ("agent_class matches",),
            (),
            "gap",
            "present: none; missing: x (catalogue not on)",
            (ControlCheck("catalogue", "x", "full", False),),
            ("log",),
            (),
            dl,
        ),
        MatrixRow(
            "OB-2",
            "INST-1",
            "1/2026",
            "VN",
            True,
            "in_force",
            "Art. 2",
            "Duty two.",
            (),
            "needs_answer",
            (),
            ("cross_border",),
            "partial",
            "present: y; missing: none",
            (ControlCheck("monitor", "y", "partial", True, Pointer("plan", "y")),),
            (),
            (Pointer("plan", "y"),),
            dl,
            ("Q-cross_border",),
        ),
        MatrixRow(
            "OB-3",
            "INST-1",
            "1/2026",
            "VN",
            True,
            "in_force",
            "Art. 3",
            "Duty three.",
            (),
            "no",
            (),
            (),
            "not_applicable",
            "not applicable",
            (),
            (),
            (),
            dl,
        ),
    )
    header = MatrixHeader(
        "p1",
        "Product <One>",
        "questionnaire",
        "kbversion0123456789",
        1,
        3,
        False,
        (),
        "2026-10-15",
        "2026-10-15T00:00:00Z",
        DISCLAIMER,
        "Advisory only. test",
    )
    d33 = Decision33Suggestion(
        "needs_answer",
        (D33Entry("transactions", None, ("line one VN-QD33-2026-PL4.1-01",)),),
        ("overall line",),
        "caveat text",
    )
    return ObligationMatrix(
        header=header,
        product=ProductProfile("p1", "Product <One>", "questionnaire"),
        rows=rows,
        questions=(
            Question(
                "Q-cross_border", "cross_border", "Cross border?", "Xuyên biên giới?", ("OB-2",)
            ),
        ),
        thresholds=(
            ThresholdFinding(
                "TH-x-effective", "OB-1", "L1", "daily", "individual", 5, 3, "exceeds", "why"
            ),
        ),
        decision33=d33,
        summary={
            "by_status": {"met": 0, "partial": 0, "gap": 1, "bank_process": 0, "not_applicable": 0},
            "by_applies": {"yes": 1, "no": 1, "needs_answer": 1},
            "needs_answer": 1,
            "questions": 1,
            "threshold_gaps": 1,
        },
        narrative=narrative,
    )
