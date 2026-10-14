"""Oversight metrics: daily integer rows per agent; chain walk; eval report placeholders."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from supervisor.adapters.clock import FixedClock
from supervisor.config import load_settings
from supervisor.core.models import CaseEvent
from supervisor.evidence.chain import ChainWriter
from supervisor.evidence.signer import build_signer
from supervisor.monitors.common import MonitorContext, open_case
from supervisor.monitors.oversight import OversightMetrics, check_lane, load_eval_report
from supervisor.monitors.seed import _event, as_rows
from tests.judge.conftest import assert_no_floats
from tests.monitors.conftest import T0

INT_COLUMNS = (
    "events_seen",
    "events_gated",
    "coverage_bp",
    "ttd_ms",
    "tth_s",
    "judge_verdicts",
    "judge_disagree_bp",
    "groundedness_bp",
    "cases_opened",
    "blocks",
    "llm_calls",
    "judge_latency_ms",
)


def _verdict(eid: str, ts, *, tier=0, action="log", role=None, label="x", score_bp=None,
             checker="gate:tier0a", latency=None):  # noqa: ANN001, ANN202  # fmt: skip
    return {
        "verdict_id": f"v-{eid}-{checker}-{tier}-{role}",
        "ts": ts,
        "event_id": eid,
        "agent_id": "payments",
        "tier": tier,
        "checker_id": checker,
        "is_mock": tier > 0,
        "advisory": tier > 0,
        "label": label,
        "action": action,
        "role": role,
        "score_bp": score_bp,
        "latency_ms": latency,
    }


def test_daily_row_values(adapters, clock: FixedClock, evidence, tmp_path: Path) -> None:
    ctx = MonitorContext.from_adapters(adapters, evidence)
    t = T0 + timedelta(hours=9)
    evs = [
        _event(t, "payments", "1.0.0", "tool_call", tool="transfer", latency_ms=10),
        _event(t, "payments", "1.0.0", "tool_call", tool="get_balance", latency_ms=10),
        _event(t, "payments", "1.0.0", "tool_call", tool="reply", latency_ms=10),
        _event(t, "payments", "1.0.0", "tool_call", tool="list_payees", latency_ms=10),
        _event(t, "payments", "1.0.0", "gate_decision", tool="transfer", status="denied"),
        _event(t, "payments", "1.0.0", "gate_decision", tool="get_balance"),
        _event(t, "payments", "1.0.0", "gate_decision", tool="list_payees"),
        _event(t, "payments", "1.0.0", "llm_call", latency_ms=500),
    ]
    adapters.tables.append("agent_event", as_rows(evs))
    blocked = evs[4].event_id
    adapters.tables.append(
        "verdict",
        [
            _verdict(blocked, t, action="block"),
            _verdict(
                evs[0].event_id,
                t + timedelta(seconds=4),
                tier=2,
                action="alert",
                role="primary",
                label="tiers_disagree",
                latency=40,
                checker="judge.t2.primary",
            ),
            _verdict(
                evs[1].event_id,
                t + timedelta(seconds=2),
                tier=2,
                action="log",
                role="primary",
                label="benign",
                latency=60,
                checker="judge.t2.primary",
            ),
            _verdict(
                evs[2].event_id,
                t,
                tier=1,
                role="quality",
                score_bp=7000,
                checker="quality.groundedness",
            ),
        ],  # fmt: skip
    )
    clock.advance(10 * 3600)
    case_id = open_case(ctx, agent_id="payments", severity="medium", case_type="drift",
                        summary="s", actor="monitor:test", evidence_payload={})  # fmt: skip
    adapters.tables.append(
        "case_event",
        [
            CaseEvent(
                case_id=case_id,
                seq=1,
                ts=clock.now() + timedelta(seconds=90),
                actor="reviewer.an",
                actor_kind="user",
                action="triage",
            )
        ],  # fmt: skip
    )
    report = tmp_path / "eval.json"
    report.write_text(json.dumps({"metrics": {"dev": {"catch_rate_bp": 9167,
                                                      "false_alarm_bp": 435}}}))  # fmt: skip
    rows = OversightMetrics(ctx, eval_report=report).run(days=[T0.date()])
    assert rows == 1
    m = adapters.state.get("oversight_metric", {"metric_date": T0.date(), "agent_id": "payments"})
    assert m["events_seen"] == 4 and m["events_gated"] == 3 and m["coverage_bp"] == 7500
    assert m["blocks"] == 1 and m["llm_calls"] == 1
    assert m["ttd_ms"] == 0  # nearest-rank median of [0 (rule block), 4000 (judge alert)]
    assert m["tth_s"] == 90 and m["cases_opened"] == 1
    assert m["judge_verdicts"] == 2 and m["judge_disagree_bp"] == 5000
    assert m["judge_latency_ms"] == 100 and m["groundedness_bp"] == 7000
    assert (m["catch_rate_bp"], m["false_alarm_bp"]) == (9167, 435)
    assert m["chain_ok"] is True  # no chain lane yet: nothing to contradict
    assert m["coverage"] == 0.75  # legacy float column
    for col in INT_COLUMNS:
        assert m[col] is None or isinstance(m[col], int), col
    recorded = evidence.of_type("oversight_metric")
    assert len(recorded) == 1
    assert_no_floats(recorded[0])
    # Unchanged values are not recorded again.
    OversightMetrics(ctx, eval_report=report).run(days=[T0.date()])
    assert len(evidence.of_type("oversight_metric")) == 1


def test_eval_report_missing_or_committed() -> None:
    assert load_eval_report(None) == {"catch_rate_bp": None, "false_alarm_bp": None}
    from supervisor.jobs.metrics import EVAL_REPORT

    got = load_eval_report(EVAL_REPORT)
    assert isinstance(got["catch_rate_bp"], int)


def test_chain_walk_ok_then_detects_tamper(adapters, clock) -> None:
    settings = load_settings()
    writer = ChainWriter(adapters.tables, clock, build_signer(settings))
    try:
        for i in range(5):
            writer.record("note", f"n{i}", {"agent_id": "payments", "i": i})
    finally:
        writer.close()
    from tests.judge.conftest import MemoryEvidence

    ctx = MonitorContext.from_adapters(adapters, MemoryEvidence())
    first = check_lane(ctx, "agent:payments")
    assert first.ok and first.checked == 5 and first.last_seq == 4
    assert check_lane(ctx, "agent:payments").checked == 0  # incremental
    # A forged entry appended out of chain (wrong prev_hash) is caught.
    row = adapters.tables.query("chain_entry", {"lane": "agent:payments", "seq": 4})[0]
    adapters.tables.append("chain_entry", [{**row, "seq": 5, "entry_hash": "f" * 64}])
    bad = check_lane(ctx, "agent:payments")
    assert not bad.ok and "prev_hash" in (bad.problem or "")
    assert not check_lane(ctx, "agent:payments").ok  # stays broken
