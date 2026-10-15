"""WP19: incident clock on cases: stored on open, tightened on severity raise, report sent."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.cases.incident_clock import load_holidays
from supervisor.cases.service import CaseError, CaseService, PermissionDenied
from supervisor.config import REPO_ROOT
from supervisor.judge.service import CaseRequest

from .conftest import ListSink


def _open(svc: CaseService, severity: str = "high") -> dict[str, Any]:
    return svc.open_case(
        agent_id="payments",
        severity=severity,
        summary="t",
        source_kind="monitor",
        source_ref=uuid.uuid4().hex,
    )


def test_open_stores_clock_and_keeps_deprecated_24h(svc: CaseService) -> None:
    c = _open(svc, "high")
    assert c["urgency_class"] == "urgent"
    assert c["incident_detected_at"] == c["opened_at"]
    assert c["prelim_report_due_at"] - c["opened_at"] == timedelta(hours=72)
    assert c["formal_report_due_at"] - c["prelim_report_due_at"] == timedelta(days=15)
    assert c["report_due_at"] - c["opened_at"] == timedelta(hours=24)  # deprecated, still filled
    s = svc.incident_status(c["case_id"])
    assert s["urgency"] == "urgent" and not s["prelim_overdue"]


def test_standard_uses_working_days(svc: CaseService) -> None:
    svc.holidays = load_holidays(REPO_ROOT / "config" / "vn_holidays.yaml")
    c = _open(svc, "medium")
    assert c["urgency_class"] == "standard"
    gap = c["prelim_report_due_at"] - c["opened_at"]
    assert timedelta(days=5) <= gap <= timedelta(days=11)


def test_severity_raise_tightens_never_relaxes(svc: CaseService) -> None:
    c = _open(svc, "medium")
    old = c["prelim_report_due_at"]
    svc.open_from_case_request(
        CaseRequest("raise_severity", "payments", "critical", "more", ("t",), ("v1",))
    )
    c2 = svc.get(c["case_id"])
    assert c2["severity"] == "critical" and c2["urgency_class"] == "urgent"
    assert c2["prelim_report_due_at"] <= old
    assert c2["prelim_report_due_at"] - c2["incident_detected_at"] == timedelta(hours=72)
    # a later, lower request never relaxes the clock
    svc.open_from_case_request(
        CaseRequest("raise_severity", "payments", "low", "x", ("t",), ("v2",))
    )
    c3 = svc.get(c["case_id"])
    assert c3["urgency_class"] == "urgent"
    assert c3["prelim_report_due_at"] == c2["prelim_report_due_at"]


def test_record_report_sent_paths(
    svc: CaseService, users: dict[str, AuthPrincipal], sink: ListSink
) -> None:
    rev = users["reviewer.an"]
    c = _open(svc)
    with pytest.raises(CaseError, match="preliminary report before"):
        svc.record_report_sent(c["case_id"], "formal", rev, c["row_version"])
    with pytest.raises(PermissionDenied):
        svc.record_report_sent(c["case_id"], "preliminary", users["auditor.dung"], c["row_version"])
    with pytest.raises(CaseError, match="kind"):
        svc.record_report_sent(c["case_id"], "other", rev, c["row_version"])
    sent = c["opened_at"] + timedelta(hours=5)
    c = svc.record_report_sent(c["case_id"], "preliminary", rev, c["row_version"], sent)
    assert c["prelim_report_sent_at"] == sent
    assert c["formal_report_due_at"] == sent + timedelta(days=15)
    with pytest.raises(CaseError, match="already"):
        svc.record_report_sent(c["case_id"], "preliminary", rev, c["row_version"])
    with pytest.raises(CaseError, match="changed since"):
        svc.record_report_sent(c["case_id"], "formal", rev, c["row_version"] - 1)
    c = svc.record_report_sent(c["case_id"], "formal", rev, c["row_version"])
    assert c["formal_report_sent_at"] is not None
    s = svc.incident_status(c["case_id"])
    assert not s["prelim_overdue"] and not s["formal_overdue"]
    actions = [p["action"] for p in sink.of("case_event")]
    assert actions[-2:] == ["report_sent:preliminary", "report_sent:formal"]


def test_overdue_flags(svc: CaseService) -> None:
    c = _open(svc, "critical")
    s = svc.incident_status(c["case_id"], now=c["opened_at"] + timedelta(hours=73))
    assert s["prelim_overdue"] and not s["formal_overdue"]
