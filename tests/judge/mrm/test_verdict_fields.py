"""WP19: judge verdict rows carry prompt_hash and rubric_version (change control)."""

from __future__ import annotations

from supervisor.core.models import Verdict
from supervisor.judge.mrm.identity import rubric_version
from supervisor.judge.prompts import prompt_hash
from tests.judge.conftest import make_events
from tests.judge.test_service import BENIGN, RISKY, make_service


def test_judge_rows_and_payload_carry_fields(clock, tables, evidence) -> None:
    svc = make_service(clock, tables, evidence)
    out = svc.evaluate_trace(make_events(RISKY))
    rows = tables.tables["verdict"]
    assert rows and out.verdicts
    want = rubric_version(5000, 5000)
    for row in rows:
        assert row["rubric_version"] == want
        assert row["prompt_hash"] == row["policy_hash"]
        assert row["prompt_hash"] in (prompt_hash(1), prompt_hash(2))
        assert row["model_version"]
    for payload in evidence.of_type("judge_verdict"):
        assert payload["rubric_version"] == want and payload["prompt_hash"]


def test_thresholds_change_rubric(clock) -> None:
    a = make_service(clock, t1_threshold_bp=5000)
    b = make_service(clock, t1_threshold_bp=6000)
    assert a.rubric_version != b.rubric_version


def test_protocol_verdict_has_fields(clock, tables, evidence) -> None:
    svc = make_service(clock, tables, evidence, k_suspicious=1)
    svc.evaluate_trace(make_events(RISKY))
    proto = [r for r in tables.tables["verdict"] if r["role"] == "protocol"]
    assert proto
    assert proto[0]["prompt_hash"] and proto[0]["rubric_version"] == svc.rubric_version
    payloads = [p for p in evidence.of_type("judge_verdict") if p["role"] == "protocol"]
    assert payloads and payloads[0]["rubric_version"] == svc.rubric_version
    assert payloads[0]["prompt_hash"]


def test_tier0_rows_keep_fields_empty() -> None:
    v = Verdict(
        verdict_id="x",
        ts="2026-10-14T00:00:00Z",
        agent_id="a",
        tier=0,
        checker_id="gate",
        is_mock=False,
        advisory=False,
        label="l",
        action="allow",
    )
    assert v.prompt_hash is None and v.rubric_version is None


def test_benign_still_logs(clock, tables, evidence) -> None:
    svc = make_service(clock, tables, evidence)
    assert svc.evaluate_trace(make_events(BENIGN)).final_action == "log"
