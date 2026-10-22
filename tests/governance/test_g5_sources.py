"""WP-G5: the event sources read existing tables and give normalised events."""

from __future__ import annotations

from datetime import timedelta

from supervisor.governance import event_sources as src
from supervisor.governance.actions_model import GovernanceEvent

from .g5_support import NOW, Rig, ago

LO = NOW - timedelta(hours=1)
CLASSES = {"transfer": "money", "lookup": "read_only", "export": "pii_export"}


def kinds(events: list[GovernanceEvent]) -> list[str]:
    return [e.kind for e in events]


def test_alert_rows_become_events(rig: Rig) -> None:
    rig.alert("al_1", "AL-QUARANTINE", "critical", "agent-a", case_id="CASE-1")
    rig.alert("al_2", "AL-JOB-FAILURE", "medium", None)
    rig.alert("al_old", "AL-QUARANTINE", "critical", "agent-a", ts=ago(7200))
    events = src.alerts(rig.ctx, LO, NOW)
    assert [(e.ref, e.severity, e.agent_id, e.rule_id, e.case_id) for e in events] == [
        ("alert:al_1", "critical", "agent-a", "AL-QUARANTINE", "CASE-1"),
        ("alert:al_2", "medium", "-", "AL-JOB-FAILURE", None),
    ]


def test_gate_stops_only_on_risky_tools(rig: Rig) -> None:
    rig.event_row("e1", "transfer")
    rig.event_row("e2", "lookup")
    rig.event_row("e3", "export")
    rig.event_row("e4", "transfer")
    rig.verdict("v1", "e1", "block", rule_id="R-LIMIT")
    rig.verdict("v2", "e2", "block")  # read_only tool: not an event
    rig.verdict("v3", "e3", "pause", rule_id="R-PAYEE")
    rig.verdict("v4", "e4", "block", label="shadow_block")  # SHADOW would-block: not a hit
    rig.verdict("v5", None, "block")  # no decision to read the tool from
    rig.verdict("v6", "e1", "allow")
    events = src.gate_stops(rig.ctx, LO, NOW, classes=CLASSES)
    assert [(e.ref, e.severity, e.rule_id, e.evidence) for e in events] == [
        ("verdict:v1", "high", "R-LIMIT", ("rule", "R-LIMIT")),
        ("verdict:v3", "medium", "R-PAYEE", ("rule", "R-PAYEE")),
    ]


def test_detector_failures_are_grouped_per_agent_detector_and_hour(rig: Rig) -> None:
    rig.finding("f1", "timed_out")
    rig.finding("f2", "timed_out")
    rig.finding("f3", "execution_failed")
    rig.finding("f4", "not_applicable")  # a detector that did not need to run
    rig.finding("f5", None)  # a fired finding
    events = src.detector_failures(rig.ctx, LO, NOW)
    assert len(events) == 1
    assert events[0].kind == "detector_failed" and events[0].severity == "medium"
    assert events[0].ref == "finding:agent-a:pii:20261022" + "11"


def test_monitor_failures_come_from_breach_cases_and_low_quality(rig: Rig) -> None:
    rig.case("CASE-drift-1", "drift", "medium")
    rig.case("CASE-fair-1", "fairness", "high")
    rig.case("CASE-manual", "manual", "high")
    events = src.monitor_failures(rig.ctx, LO, NOW)
    assert sorted((e.ref, e.severity, e.evidence) for e in events) == [
        ("case:CASE-drift-1", "medium", ("monitor", "drift")),
        ("case:CASE-fair-1", "high", ("monitor", "fairness")),
    ]
    rig.verdict("q1", None, "log", tier=1, checker_id="quality.groundedness", label="low")
    rig.verdict("q2", None, "log", tier=1, checker_id="quality.groundedness", label="pass")
    quality = [e for e in src.monitor_failures(rig.ctx, LO, NOW) if e.rule_id == "quality"]
    assert [(e.severity, e.evidence) for e in quality] == [("low", ("monitor", "quality"))]


def test_pack_no_go_needs_a_required_real_failed_result(rig: Rig) -> None:
    rig.eval_result("counterfactual_vi", "fail", "required")
    rig.eval_result("bbq_vi", "fail", "advisory")  # advisory: never a NO-GO
    rig.eval_result("fairness_metrics", "ok", "required")
    rig.eval_result("four_fifths_rule", "error", "required", is_mock=True)  # mock never counts
    rig.eval_result("garak_probe_families", "error", "required", target_id="agent-b")
    events = src.pack_no_go(rig.ctx, LO, NOW)
    assert sorted((e.agent_id, e.rule_id, e.evidence) for e in events) == [
        ("agent-a", "counterfactual_vi", ("pack", "counterfactual_vi")),
        ("agent-b", "garak_probe_families", ("pack", "garak_probe_families")),
    ]
    assert {e.severity for e in events} == {"high"}


def test_chain_break_reads_failed_verifies_only(rig: Rig) -> None:
    rig.chain_verify(True, seq=1)
    rig.chain_verify(False, seq=2)
    events = src.chain_breaks(rig.ctx, LO, NOW)
    assert [(e.kind, e.severity, e.agent_id, e.ref) for e in events] == [
        ("chain_break", "critical", "-", "chain:root:2")
    ]


def test_model_version_change_needs_a_different_model(rig: Rig) -> None:
    rig.version("agent-a", "v1", "ep-1", "qwen", NOW - timedelta(days=3))
    rig.version("agent-a", "v2", "ep-1", "qwen", ago(120))  # prompt change only
    rig.version("agent-a", "v3", "ep-2", "qwen", ago(90))  # new endpoint
    rig.version("agent-b", "v1", "ep-1", "qwen", ago(80))  # first version
    events = src.model_changes(rig.ctx, LO, NOW)
    assert [(e.ref, e.severity) for e in events] == [("agent_version:agent-a:v3", "medium")]


def test_judge_escalation_is_a_judge_case(rig: Rig) -> None:
    rig.case("CASE-judge-1", "judge", "high")
    rig.case("CASE-rule-1", "rule", "high")
    events = src.judge_escalations(rig.ctx, LO, NOW)
    assert [(e.ref, e.severity, e.case_id) for e in events] == [
        ("case:CASE-judge-1", "high", "CASE-judge-1")
    ]


def test_attach_systems_fans_out_per_linked_system_and_skips_archived(rig: Rig) -> None:
    s1 = rig.system("Alpha")
    s2 = rig.system("Beta", agent="agent-a")
    s3 = rig.system("Gamma", agent="agent-a")
    rig.systems.archive(s3["system_id"], "owner.lan")
    rig.alert("al_1", agent_id="agent-a")
    rig.alert("al_2", agent_id="agent-z")
    rig.alert("al_3", agent_id=None)
    events = src.attach_systems(src.alerts(rig.ctx, LO, NOW), src.systems_of(rig.a.state))
    got = sorted((e.ref, e.system_id) for e in events)
    assert got == sorted(
        [
            ("alert:al_1", s1["system_id"]),
            ("alert:al_1", s2["system_id"]),
            ("alert:al_2", None),
            ("alert:al_3", None),
        ]
    )
    keys = {e.key for e in events}
    assert len(keys) == len(events)  # one dedupe key per source row and system
