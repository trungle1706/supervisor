"""WP8 review fixes: policy vs console roles, masked close notes, high false alarm from
triaged, non-ASCII user ids in the audit pack, evidence failure after a gate action."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.cases.service import CaseService

from .conftest import Console


def test_console_role_without_policy_membership_gets_clear_400(console: Console) -> None:
    assert console.post("/console/agents/payments/pause", {"reason": "x"}).status_code == 200
    # cc-lead has the console owner role but owns another agent and is no policy reviewer
    r = console.post(
        "/console/agents/payments/resume", {"reason": "x"}, user="cc-lead@example.invalid"
    )
    assert r.status_code == 400 and "console roles alone are not enough" in r.text


def test_admin_release_and_non_admin_refused(console: Console) -> None:
    q = console.post("/console/agents/payments/quarantine", {"reason": "q"}, user="admin.chi")
    assert q.status_code == 200 and 'data-state="QUARANTINED"' in q.text
    r = console.post("/console/agents/payments/release", {"reason": "r"}, user="reviewer.binh")
    assert r.status_code == 403 and "needs role admin" in r.text
    ok = console.post("/console/agents/payments/release", {"reason": "r"}, user="admin.chi")
    assert ok.status_code == 200 and 'data-state="PAUSED"' in ok.text


def test_close_note_is_masked_in_signoff(svc: CaseService, users: dict[str, AuthPrincipal]) -> None:
    an = users["reviewer.an"]
    c = svc.open_case(
        agent_id="payments", severity="low", summary="s", source_kind="monitor", source_ref="m:9"
    )
    c = svc.transition(c["case_id"], "triaged", an, c["row_version"], assignee="reviewer.an")
    svc.transition(
        c["case_id"],
        "closed",
        an,
        c["row_version"],
        resolution="false_alarm",
        note="khach hang goi 0912345678",
    )
    assert "0912345678" not in svc.signoffs(c["case_id"])[0]["reason"]


def test_high_false_alarm_closes_from_triaged_with_two_signoffs(
    svc: CaseService, users: dict[str, AuthPrincipal]
) -> None:
    an, em = users["reviewer.an"], users["approver.em"]
    c = svc.open_case(
        agent_id="payments", severity="high", summary="s", source_kind="monitor", source_ref="m:8"
    )
    c = svc.transition(c["case_id"], "triaged", an, c["row_version"], assignee="reviewer.an")
    c = svc.sign_off(c["case_id"], an, "approve", "false alarm", c["row_version"])["case"]
    c = svc.sign_off(c["case_id"], em, "approve", "agree", c["row_version"])["case"]
    c = svc.transition(
        c["case_id"], "closed", an, c["row_version"], resolution="false_alarm", note="benign"
    )
    assert c["status"] == "closed"


def test_audit_pack_with_non_ascii_user(console: Console) -> None:
    from supervisor.console.auditpack import build_audit_pack

    who = AuthPrincipal("kiểm.toán@bank.example", "user", "databricks_sso", frozenset({"auditor"}))
    pack = build_audit_pack(console.ctx, who)
    assert pack.verify_ok and pack.path.is_file()


def test_gate_action_evidence_failure_is_a_warning(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.console import routes

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("chain down")

    monkeypatch.setattr(routes, "_record_gate_action", boom)
    r = console.post("/console/agents/payments/pause", {"reason": "x"})
    assert r.status_code == 200 and "WARNING" in r.text and 'data-state="PAUSED"' in r.text
