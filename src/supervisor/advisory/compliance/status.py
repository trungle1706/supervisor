"""Control presence and the status derivation table (WP14).

``check_controls`` joins an obligation's control_mapping with the controls the product has.
``derive_status`` applies the one table:

1. applies == no                                   -> not_applicable
2. a threshold finding "exceeds" tied to the row   -> gap
3. mapping has no Supervisor control (process only)-> bank_process
4. Supervisor controls mapped, none present        -> gap
5. a present control has coverage full             -> met
6. otherwise                                       -> partial

``applies == needs_answer`` gets the status of rules 2-6 (what it would be if it applies).
A present control with coverage none does not count as present for rules 4-6.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

from collections.abc import Iterable

from supervisor.advisory.compliance.model import (
    ControlCheck,
    Pointer,
    ProductControls,
    ThresholdFinding,
)
from supervisor.regkb.model import Obligation


def _presence(kind: str, cid: str, controls: ProductControls) -> bool | None:
    if kind == "process":
        return None
    if not controls.known:
        return False
    if kind == "catalogue":
        return cid in controls.catalogue_on
    if kind == "rule":
        return any(r.id == cid for r in controls.rules)
    if kind == "monitor":
        return cid in controls.monitors
    if kind == "evidence":
        return cid in controls.evidence
    if kind == "console":
        return cid in controls.console
    return False


def check_controls(obligation: Obligation, controls: ProductControls) -> tuple[ControlCheck, ...]:
    """One ControlCheck per control_mapping entry. process controls: present None."""
    checks: list[ControlCheck] = []
    for ctl in obligation.control_mapping:
        present = _presence(ctl.kind, ctl.id, controls)
        pointer: Pointer | None = None
        if present:
            pointer = controls.pointers.get(f"{ctl.kind}:{ctl.id}")
        note = ctl.note or ""
        if present is False and not controls.known:
            note = (note + " " if note else "") + "(product controls unknown)"
        checks.append(
            ControlCheck(
                kind=ctl.kind,
                id=ctl.id,
                coverage=ctl.coverage,
                present=present,
                pointer=pointer,
                note=note,
            )
        )
    return tuple(checks)


def counts_as_present(check: ControlCheck) -> bool:
    """A Supervisor control counts only if present and its coverage is not none."""
    return check.present is True and check.coverage != "none"


def _ptr(check: ControlCheck) -> str:
    if check.pointer is None:
        return check.id
    return f"{check.id} ({check.pointer.ref})"


def derive_status(
    applies: str,
    checks: Iterable[ControlCheck],
    threshold_findings: Iterable[ThresholdFinding] = (),
) -> tuple[str, str]:
    """Return (status, status_reason). The reason names control ids and product facts.

    ``threshold_findings`` are the findings tied to this obligation.
    """
    checks = tuple(checks)
    if applies == "no":
        return "not_applicable", "applies_to predicate is not met by the product facts"
    tail = (
        " (if the obligation applies; product facts are incomplete)"
        if applies == "needs_answer"
        else ""
    )

    exceeding = [f for f in threshold_findings if f.verdict == "exceeds"]
    if exceeding:
        parts = [
            f"{f.limit_id} {f.limit_vnd if f.limit_vnd is not None else 'none'} VND "
            f"vs cap {f.cap_vnd} VND ({f.customer_type}): {f.reason}"
            for f in exceeding
        ]
        return "gap", "threshold exceeded: " + "; ".join(parts) + tail

    supervisor = [c for c in checks if c.kind != "process"]
    process = [c for c in checks if c.kind == "process"]
    if not supervisor:
        if process:
            ids = ", ".join(c.id for c in process)
            return "bank_process", f"bank process, no Supervisor control; process ids: {ids}" + tail
        return "bank_process", "bank process, no control mapped in RegKB" + tail

    present = [c for c in supervisor if counts_as_present(c)]
    missing = [c for c in supervisor if not counts_as_present(c)]

    def missing_text(c: ControlCheck) -> str:
        if c.present is True:
            return f"{c.id} (present but coverage none)"
        return f"{c.id} ({c.kind} not on)"

    present_txt = ", ".join(_ptr(c) for c in present) or "none"
    missing_txt = ", ".join(missing_text(c) for c in missing) or "none"
    reason = f"present: {present_txt}; missing: {missing_txt}"
    if not present:
        return "gap", reason + tail
    if any(c.coverage == "full" for c in present):
        return "met", reason + tail
    return "partial", reason + tail
