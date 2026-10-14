"""DoD: a case file renders from a real incident recorded in the chain, and the export verifies."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from supervisor.core.models import Case, CaseEvent, Signoff, Verdict
from supervisor.evidence.casefile import build_case_file, load_case_inputs, write_case_file
from supervisor.evidence.export import export_chain
from supervisor.evidence.verify import verify_export
from tests.evidence.conftest import T0, Env, make_writer


def test_incident_to_case_file_to_verified_export(env: Env) -> None:
    a = env.adapters
    w = make_writer(env)
    env.clock.advance(60)
    v = Verdict(
        verdict_id="v-block-1",
        ts=env.clock.now(),
        agent_id="payments",
        tier=0,
        checker_id="rule:limit",
        advisory=False,
        label="vuot_han_muc",
        action="block",
        rule_id="R-LIMIT-01",
        rationale_masked="Chuyen 600.000.000 VND den TK ****1234 vuot han muc",
    )
    a.tables.append("verdict", [v])
    w.record("verdict", "verdict:v-block-1", {"agent_id": "payments", "action": "block"})
    case = Case(
        case_id="C-0001",
        agent_id="payments",
        severity="high",
        opened_at=env.clock.now(),
        summary="Tac nhan thanh toan vuot han muc / payment agent over limit",
        regulation_refs=["QD-33/2026 Phu luc", "SBV draft AI circular"],
    )
    row = case.row()
    row.pop("row_version")
    row.pop("updated_at")
    a.state.insert("cases", row)
    w.record("case", "case:C-0001", {"agent_id": "payments", "case_id": "C-0001"})
    env.clock.advance(600)
    ev = CaseEvent(
        case_id="C-0001",
        seq=1,
        ts=env.clock.now(),
        actor="reviewer.nguyen",
        actor_kind="user",
        action="triage",
        comment_masked="Xac nhan chan giao dich",
    )
    a.tables.append("case_event", [ev])
    w.record("case_event", "case_event:C-0001:1", {"agent_id": "payments", "action": "triage"})
    so = Signoff(
        signoff_id="S-1",
        case_id="C-0001",
        reviewer_id="reviewer.nguyen",
        decision="confirm_block",
        reason="Giao dich vuot han muc ngay; giu nguyen chan.",
        ts=env.clock.now(),
        auth_method="dev_header",
    )
    a.tables.append("signoff", [so])
    w.record("signoff", "signoff:S-1", {"agent_id": "payments", "decision": "confirm_block"})

    inputs = load_case_inputs(a.tables, a.state, "C-0001", now=env.clock.now())
    cf = build_case_file(
        **inputs,
        decision33_text=a.settings.casefile_decision33_text,
        mask_version="caller-masked",
        generated_at=env.clock.now(),
    )
    assert cf.sbv.incident_detected_at == T0 + timedelta(seconds=60)
    assert cf.sbv.report_due_at == cf.sbv.incident_detected_at + timedelta(hours=24)
    assert cf.sbv.remediation_due_at == cf.sbv.incident_detected_at + timedelta(days=5)
    assert cf.chain is not None and cf.chain.lane == "agent:payments"
    assert cf.chain.seq_from == 0 and cf.chain.entry_count == 4
    assert cf.signoffs[0].reason == so.reason

    path, notice = write_case_file(cf, env.tmp / "casefiles", "html", sink=w)
    assert notice is None
    html = path.read_text(encoding="utf-8")
    assert "Hồ sơ sự cố" in html and "Case file" in html
    w.close()

    rows = a.tables.query("chain_entry", {"lane": "agent:payments", "record_type": "case_file"})
    assert len(rows) == 1
    payload = json.loads(
        a.tables.query("chain_payload", {"lane": "agent:payments", "seq": rows[0]["seq"]})[0][
            "payload"
        ]
    )
    assert payload["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()

    out = env.tmp / "export"
    export_chain(a.tables, out)
    report = verify_export(out, strict=True)
    assert report.failures == 0, "\n".join(report.lines)
