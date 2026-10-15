"""WP19: judge-vs-human agreement, the daily metric and the drop case."""

from __future__ import annotations

from datetime import timedelta

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import build_adapters
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from supervisor.judge.mrm.agreement import agree_bp, agreement_pairs, agreement_summary
from supervisor.monitors.common import MonitorContext
from supervisor.monitors.oversight import OversightMetrics
from supervisor.monitors.seed import _event, as_rows
from tests.judge.conftest import T0, MemoryEvidence, MemoryTables
from tests.monitors.conftest import T0 as DAY0


@pytest.fixture
def adapters():
    settings = load_settings()
    a = build_adapters(settings, clock=FixedClock(DAY0))
    bootstrap_schema.run(settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def evidence() -> MemoryEvidence:
    return MemoryEvidence()


def add_pair(t, n: int, resolution: str, agent="a1", ts=T0, kind="judge") -> None:
    t.append(
        "case_link",
        [{"source_kind": kind, "source_ref": f"v{n}", "case_id": f"c{n}",
          "agent_id": agent, "ts": ts}],
    )  # fmt: skip
    t.append(
        "signoff",
        [{"signoff_id": f"s{n}", "case_id": f"c{n}", "reviewer_id": "r",
          "decision": f"close:{resolution}", "reason": "", "ts": ts, "auth_method": "sso"}],
    )  # fmt: skip


def test_math_rounding() -> None:
    assert agree_bp(0, 0) is None
    assert agree_bp(1, 3) == 3333 and agree_bp(2, 3) == 6667 and agree_bp(3, 3) == 10000
    assert agree_bp(1, 8) == 1250 and agree_bp(1, 16) == 625


def test_no_pairs() -> None:
    s = agreement_summary(MemoryTables())
    assert s["status"] == "no_pairs" and s["pairs"] == 0 and s["agree_bp"] is None


def test_mixed_and_by_agent() -> None:
    t = MemoryTables()
    add_pair(t, 1, "confirmed")
    add_pair(t, 2, "false_alarm")
    add_pair(t, 3, "confirmed", agent="a2")
    t.append(
        "signoff",
        [{"signoff_id": "x", "case_id": "c1", "decision": "approve:reviewer",
          "ts": T0, "reviewer_id": "r"}],
    )  # fmt: skip
    # a closed case with no judge link is not a pair
    t.append(
        "signoff",
        [{"signoff_id": "y", "case_id": "cz", "decision": "close:confirmed",
          "ts": T0, "reviewer_id": "r"}],
    )  # fmt: skip
    s = agreement_summary(t, min_pairs=3)
    assert (s["status"], s["pairs"], s["agree"], s["agree_bp"]) == ("ok", 3, 2, 6667)
    assert s["by_agent"]["a1"] == {"pairs": 2, "agree": 1, "agree_bp": 5000}
    assert agreement_summary(t)["status"] == "insufficient_pairs"  # default min 5
    p = agreement_pairs(t)[0]
    assert p["judge_label"] == "suspicious" and p["verdict_ids"] == ["v1"]


def test_all_agree_and_time_filter() -> None:
    t = MemoryTables()
    for i in range(5):
        add_pair(t, i, "confirmed", ts=T0 + timedelta(days=i))
    assert agreement_summary(t)["agree_bp"] == 10000
    s = agreement_summary(t, since=T0 + timedelta(days=1), until=T0 + timedelta(days=3))
    assert s["pairs"] == 2


def test_gate_link_counts_only_tier_1_2_verdicts() -> None:
    t = MemoryTables()
    t.append(
        "verdict",
        [{"verdict_id": "g0", "event_id": "ev0", "tier": 0},
         {"verdict_id": "g2", "event_id": "ev1", "tier": 2}],
    )  # fmt: skip
    add_pair(t, 1, "confirmed", kind="gate")
    t.tables["case_link"][0]["source_ref"] = "ev0"
    assert agreement_pairs(t) == []
    t.tables["case_link"][0]["source_ref"] = "ev1"
    assert agreement_pairs(t)[0]["verdict_ids"] == ["g2"]


# ---- daily metric and drop case (SQLite adapters)


def setup(adapters, evidence, resolutions: list[str]):
    day = DAY0 + timedelta(hours=9)
    ev = _event(day, "payments", "1.0.0", "tool_call", tool="transfer")
    adapters.tables.append("agent_event", as_rows([ev]))
    for i, res in enumerate(resolutions):
        add_pair(adapters.tables, i, res, agent="payments", ts=day + timedelta(minutes=i))
    ctx = MonitorContext.from_adapters(adapters, evidence)
    return OversightMetrics(ctx, min_agreement_bp=8000, min_agreement_pairs=5)


def snapshot(adapters):
    return (
        adapters.state.query("agent"),
        adapters.tables.query("gate_control"),
        [v for v in adapters.tables.query("verdict") if v["action"] in ("block", "pause")],
    )


def run(m: OversightMetrics, adapters):
    m.run(now=DAY0 + timedelta(hours=20), days=[DAY0.date()])
    key = {"metric_date": DAY0.date(), "agent_id": "payments"}
    return adapters.state.get("oversight_metric", key)


def judge_cases(adapters):
    # Opened through CaseService.open_from_monitor (monitor id judge_human_agreement).
    return [
        c
        for c in adapters.state.query("cases")
        if str(c["summary"]).startswith("Monitor judge_human_agreement:")
    ]


def test_daily_values_and_drop_case_once(adapters, evidence) -> None:
    before = snapshot(adapters)
    m = setup(
        adapters, evidence, ["confirmed", "false_alarm", "false_alarm", "confirmed", "false_alarm"]
    )
    row = run(m, adapters)
    assert row["judge_human_pairs"] == 5 and row["judge_human_agree_bp"] == 4000
    (case,) = judge_cases(adapters)
    assert case["severity"] == "medium" and "4000 bp" in case["summary"]
    assert "python -m supervisor.judge.mrm triggers" in case["summary"]
    assert case["urgency_class"] == "standard" and case["prelim_report_due_at"] is not None
    run(m, adapters)  # idempotent
    assert len(judge_cases(adapters)) == 1
    assert snapshot(adapters) == before  # never through the gate


def test_above_threshold_no_case(adapters, evidence) -> None:
    m = setup(adapters, evidence, ["confirmed"] * 5)
    assert run(m, adapters)["judge_human_agree_bp"] == 10000
    assert judge_cases(adapters) == []


def test_below_min_pairs_no_case(adapters, evidence) -> None:
    m = setup(adapters, evidence, ["false_alarm"] * 4)
    row = run(m, adapters)
    assert row["judge_human_pairs"] == 4 and row["judge_human_agree_bp"] == 0
    assert judge_cases(adapters) == []


def test_no_pairs_row(adapters, evidence) -> None:
    m = setup(adapters, evidence, [])
    row = run(m, adapters)
    assert row["judge_human_pairs"] == 0 and row["judge_human_agree_bp"] is None
