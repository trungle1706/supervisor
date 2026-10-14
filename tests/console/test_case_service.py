"""WP8: case service: intake from gate / judge / monitor, state machine, two-person sign-off."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.adapters.factory import Adapters
from supervisor.adapters.notify import InboxNotifier
from supervisor.cases.service import CaseError, CaseService, PermissionDenied
from supervisor.judge.service import CaseRequest, JudgeService, TraceOutcome

from .conftest import ListSink


def _gate_verdict(
    a: Adapters, agent: str, rule: str, action: str = "block", event_id: str | None = None
) -> str:
    event_id = event_id or uuid.uuid4().hex
    a.tables.append(
        "verdict",
        [
            {
                "verdict_id": uuid.uuid4().hex,
                "ts": a.clock.now(),
                "trace_id": "t-" + event_id[:8],
                "event_id": event_id,
                "agent_id": agent,
                "tier": 0,
                "checker_id": "gate.tier0a",
                "is_mock": False,
                "advisory": False,
                "label": "matched",
                "action": action,
                "rule_id": rule,
                "rationale_masked": f"rule {rule} matched",
            }
        ],
    )
    return event_id


def _open(svc: CaseService, severity: str = "high") -> dict[str, Any]:
    return svc.open_case(
        agent_id="payments",
        severity=severity,
        summary="test case",
        source_kind="monitor",
        source_ref=uuid.uuid4().hex,
    )


def _to_contained(svc: CaseService, case: dict[str, Any], rev: AuthPrincipal) -> dict[str, Any]:
    case = svc.transition(
        case["case_id"], "triaged", rev, case["row_version"], assignee=rev.user_id
    )
    return svc.transition(
        case["case_id"], "contained", rev, case["row_version"], note="agent paused at the gate"
    )


def test_open_is_idempotent_and_recorded(
    svc: CaseService, sink: ListSink, inbox: InboxNotifier
) -> None:
    c1 = svc.open_case(
        agent_id="payments", severity="high", summary="s", source_kind="monitor", source_ref="m:1"
    )
    c2 = svc.open_case(
        agent_id="payments", severity="high", summary="s", source_kind="monitor", source_ref="m:1"
    )
    assert c1["case_id"] == c2["case_id"] and c1["status"] == "open"
    assert c1["report_due_at"] - c1["opened_at"] == timedelta(hours=24)
    assert [p["action"] for p in sink.of("case_event")] == ["open"]
    assert sink.of("case")[0]["opened_by"] == "supervisor-system"
    ev = svc.events(c1["case_id"])[0]
    assert ev["actor_kind"] == "system" and ev["auth_method"] == "local_system"
    assert inbox.list(channel="reviewers")
    assert svc.clocks(c1["case_id"]).report_due_at == c1["report_due_at"]


def test_state_machine_required_fields(svc: CaseService, users: dict[str, AuthPrincipal]) -> None:
    rev = users["reviewer.an"]
    c = _open(svc)
    with pytest.raises(CaseError, match="cannot move to contained"):
        svc.transition(c["case_id"], "contained", rev, c["row_version"], note="x")
    with pytest.raises(CaseError, match="assignee"):
        svc.transition(c["case_id"], "triaged", rev, c["row_version"])
    c = svc.transition(c["case_id"], "triaged", rev, c["row_version"], assignee="reviewer.an")
    assert c["status"] == "triaged" and c["assignee"] == "reviewer.an"
    with pytest.raises(CaseError, match="containment note"):
        svc.transition(c["case_id"], "contained", rev, c["row_version"])
    with pytest.raises(CaseError, match="only a false alarm"):
        svc.transition(
            c["case_id"], "closed", rev, c["row_version"], resolution="confirmed", note="x"
        )
    c = svc.transition(c["case_id"], "contained", rev, c["row_version"], note="paused")
    with pytest.raises(CaseError, match="resolution"):
        svc.transition(c["case_id"], "closed", rev, c["row_version"], note="done")


def test_roles_and_stale_version(svc: CaseService, users: dict[str, AuthPrincipal]) -> None:
    c = _open(svc)
    with pytest.raises(PermissionDenied):
        svc.assign(c["case_id"], "reviewer.an", users["auditor.dung"], c["row_version"])
    sp = AuthPrincipal("app-sp", "service_principal", "databricks_app_sp", frozenset({"reviewer"}))
    with pytest.raises(PermissionDenied, match="signed-in person"):
        svc.assign(c["case_id"], "reviewer.an", sp, c["row_version"])
    rev = users["reviewer.an"]
    svc.assign(c["case_id"], "reviewer.binh", rev, c["row_version"])
    with pytest.raises(CaseError, match="changed since you loaded it"):
        svc.comment(c["case_id"], "late", rev, c["row_version"])


def test_comment_is_masked(
    svc: CaseService, users: dict[str, AuthPrincipal], sink: ListSink
) -> None:
    c = _open(svc)
    svc.comment(
        c["case_id"],
        "Khach goi tu so 0912345678 hoi ve giao dich",
        users["reviewer.an"],
        c["row_version"],
    )
    ev = svc.events(c["case_id"])[-1]
    assert ev["action"] == "comment" and "0912345678" not in ev["comment_masked"]
    assert "0912345678" not in str(sink.records) and sink.of("case_event")[-1]["comment_sha256"]


def test_two_person_signoff_for_high(svc: CaseService, users: dict[str, AuthPrincipal]) -> None:
    an, binh, em = users["reviewer.an"], users["reviewer.binh"], users["approver.em"]
    admin = users["admin.chi"]
    c = _to_contained(svc, _open(svc, "high"), an)
    with pytest.raises(CaseError, match="two sign-offs"):
        svc.transition(
            c["case_id"], "closed", an, c["row_version"], resolution="confirmed", note="x"
        )
    c = svc.sign_off(c["case_id"], an, "approve", "Tôi đã xem xét.", c["row_version"])["case"]
    with pytest.raises(CaseError, match="different person"):
        svc.sign_off(c["case_id"], an, "approve", "again", c["row_version"])
    with pytest.raises(CaseError, match="approver"):
        svc.sign_off(c["case_id"], admin, "approve", "admin is not an approver", c["row_version"])
    with pytest.raises(PermissionDenied):
        svc.sign_off(c["case_id"], users["auditor.dung"], "approve", "x", c["row_version"])
    res = svc.sign_off(c["case_id"], em, "approve", "Đồng ý đóng.", c["row_version"])
    assert set(res["approvals"]) == {"reviewer.an", "approver.em"}
    c = svc.transition(
        c["case_id"], "closed", binh, res["case"]["row_version"], resolution="confirmed", note="ok"
    )
    assert c["status"] == "closed" and c["closed_at"] is not None
    reasons = [s["reason"] for s in svc.signoffs(c["case_id"])]
    assert reasons == ["Tôi đã xem xét.", "Đồng ý đóng."]  # verbatim
    with pytest.raises(CaseError, match="closed"):
        svc.comment(c["case_id"], "after close", an, c["row_version"])


def test_low_case_closes_with_one_person(svc: CaseService, users: dict[str, AuthPrincipal]) -> None:
    an = users["reviewer.an"]
    c = _open(svc, "low")
    c = svc.transition(c["case_id"], "triaged", an, c["row_version"], assignee="reviewer.an")
    c = svc.transition(
        c["case_id"], "closed", an, c["row_version"], resolution="false_alarm", note="benign"
    )
    assert c["status"] == "closed"
    assert svc.signoffs(c["case_id"])[0]["decision"] == "close:false_alarm"


def test_gate_intake_groups_by_rule_and_is_idempotent(svc: CaseService, adapters: Adapters) -> None:
    e1 = _gate_verdict(adapters, "payments", "PAY-07", "pause")
    e2 = _gate_verdict(adapters, "payments", "PAY-07", "pause")
    e3 = _gate_verdict(adapters, "payments", "PAY-08", "block")
    _gate_verdict(adapters, "payments", "PAY-01", "allow")
    touched = svc.sync_gate_cases()
    assert len(set(touched)) == 2
    assert svc.sync_gate_cases() == []
    c1 = svc.linked_case("gate", e1)
    assert c1 == svc.linked_case("gate", e2) != svc.linked_case("gate", e3)
    case = svc.get(c1)
    assert case["severity"] in ("high", "critical")  # a pause is at least high
    assert [e["action"] for e in svc.events(c1)] == ["open", "link_source"]
    assert len(svc.linked_verdicts(c1)) == 2


def test_judge_case_request_open_and_raise(svc: CaseService) -> None:
    r1 = CaseRequest(
        "open_case", "credit_prequal", "medium", "Tier 1 and 2 agree", ("t1",), ("v1",)
    )
    case = svc.open_from_case_request(r1)
    assert case["severity"] == "medium" and case["summary"].startswith("Judge (advisory)")
    r2 = CaseRequest("raise_severity", "credit_prequal", "critical", "K flags", ("t2",), ("v2",))
    raised = svc.open_from_case_request(r2)
    assert raised["case_id"] == case["case_id"] and raised["severity"] == "critical"
    assert "raise_severity" in [e["action"] for e in svc.events(case["case_id"])]


def test_judge_service_hands_case_requests_to_the_sink(adapters: Adapters) -> None:
    got: list[CaseRequest] = []
    judge = JudgeService.from_settings(
        adapters.settings, adapters.clock, force=True, case_sink=got.append
    )
    assert judge is not None
    out = TraceOutcome("t", "payments", t1=None)  # type: ignore[arg-type]
    out.case_requests.append(CaseRequest("open_case", "payments", "high", "r", ("t",), ("v",)))
    judge._deliver(out)
    assert got == out.case_requests

    def broken(_: CaseRequest) -> None:
        raise RuntimeError("store down")

    judge.case_sink = broken
    judge._deliver(out)  # logged, never raised
