"""Shared facts about gate decisions under verdict v2 (WP39).

Pure helpers, no I/O. The rollup job, the Decisions page, the Analytics tabs, the CSV export and
the alert signal loader all read decisions through these functions, so "status", "not evaluated"
and "finding class" mean one thing everywhere.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

STATUSES = ("allow", "report", "transform", "pause", "block", "skip")
DIRECTIONS = ("input", "output")

# Coverage reasons that mean a part of the call was not inspected. "not_applicable_for_direction"
# and "not_provided" are not gaps: there was nothing to inspect.
COVERAGE_GAP_REASONS = (
    "content_uninspectable",
    "payload_too_large",
    "skipped_by_policy",
    "execution_failed",
    "gate_failed",
)
# not_executed reasons of a detector that mean "it could not look" (all but the direction one).
DETECTOR_GAP_REASONS = (
    "execution_failed",
    "invalid_config",
    "payload_too_large",
    "content_uninspectable",
    "timed_out",
    "budget_exhausted",  # WP-D4
)
# The two that an on-call person treats as a detector outage.
DETECTOR_FAILED_REASONS = ("execution_failed", "timed_out")

CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")


_ID_CHECK: Any = None  # the masker used only to FIND personal data in an id (never to mask it)


def looks_personal(value: Any) -> bool:
    """True when an id-shaped value given by a caller (correlation id, request id, consumer id)
    holds personal data: an e-mail, a phone number, an ID number, an account number (R2). The
    plain-id pattern allows ``@``, ``.`` and digits, so ``thu.nguyen@example.com`` or
    ``0912345678`` pass it; the Vietnamese regex masker decides. Deterministic, no key used."""
    global _ID_CHECK
    if not isinstance(value, str) or not value:
        return False
    if _ID_CHECK is None:
        from supervisor.adapters.masking.vn_regex import VnRegexMasker

        _ID_CHECK = VnRegexMasker(b"id-check-only", "id-check")
    try:
        return bool(_ID_CHECK.find(value))
    except Exception:  # noqa: BLE001 - a check that fails treats the value as personal
        return True


def safe_id(value: Any) -> str | None:
    """``value`` when it is a plain id with no personal data in it, else None (R2)."""
    if isinstance(value, str) and ID_RE.fullmatch(value) and not looks_personal(value):
        return value
    return None


def shown_id(value: Any) -> Any:
    """An id for a page or an export: as stored when it is safe, else a fixed marker (personal
    data, or not a plain id). Rows written before the gate checked ids, or by another writer,
    can still hold personal data."""
    if value is None or value == "":
        return value
    return value if safe_id(str(value)) is not None else "<id-hidden>"


def loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, dict | list):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def status_of(event: Mapping[str, Any]) -> str:
    """Verdict v2 status of a decision row; rows written without detectors fall back to the old
    columns (pause / block / allow)."""
    s = event.get("verdict_status")
    if s in STATUSES:
        return str(s)
    if event.get("classification") == "pause":
        return "pause"
    return "block" if event.get("status") == "denied" else "allow"


def direction_of(event: Mapping[str, Any]) -> str:
    cov = loads(event.get("coverage_json"), {})
    d = cov.get("direction") if isinstance(cov, dict) else None
    return str(d) if d in DIRECTIONS else "input"


def coverage_gaps(event: Mapping[str, Any]) -> list[str]:
    """Reasons from the coverage record (sorted, unique), gaps only."""
    cov = loads(event.get("coverage_json"), {})
    out = set()
    for n in cov.get("not_inspected", []) if isinstance(cov, dict) else []:
        r = n.get("reason") if isinstance(n, dict) else None
        if r in COVERAGE_GAP_REASONS:
            out.add(str(r))
    return sorted(out)


def not_evaluated(event: Mapping[str, Any], findings: Iterable[Mapping[str, Any]]) -> list[str]:
    """Why part of the call was not inspected: coverage gaps plus detector rows that did not
    run. Empty list = fully evaluated."""
    reasons = set(coverage_gaps(event))
    for f in findings:
        r = f.get("not_executed_reason")
        if r in DETECTOR_GAP_REASONS:
            reasons.add(str(r))
    return sorted(reasons)


def finding_class(code: str) -> str:
    """Coarse class of a finding code, by its prefix. An unknown prefix is ``other``: it is
    shown and counted, never dropped."""
    head = str(code).split(".", 1)[0].lower()
    if head in ("secret", "secrets"):
        return "secret"
    if head in ("pii", "injection", "judge"):
        return head
    return "other"
