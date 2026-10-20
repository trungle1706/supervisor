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
)
# The two that an on-call person treats as a detector outage.
DETECTOR_FAILED_REASONS = ("execution_failed", "timed_out")

CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")


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
