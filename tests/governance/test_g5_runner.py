"""WP-G5: the action runner. Every action kind, never-lower, dedupe across runs, a raising action,
resume of a started event, dry run, incidents closed by a person only, clean chain payloads."""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.governance import actions as actions_mod
from supervisor.governance import event_sources as src
from supervisor.governance.actions import ACTOR
from supervisor.governance.incidents import IncidentError
from supervisor.governance.model import SystemsError

from .g5_support import NOW, Rig, ago, only, rule

PACK_ONLY = {"pack_no_go": src.pack_no_go}
ALL_ACTIONS = [
    "create_incident",
    "notify_owner",
    "raise_risk_level",
    "move_to_re_evaluation",
    "create_review",
    "fire_webhook",
    "reopen_control",
]


def deployed_system(rig: Rig, name: str = "Alpha", **over: Any) -> str:
    s = rig.system(name, **over)
    sid = str(s["system_id"])
    rig.team(sid, "rev.lan", "reviewer")
    rig.stage(sid, "deployment")
    return sid


def marker(rig: Rig) -> list[dict[str, Any]]:
    return [dict(r) for r in rig.a.state.query("governance_event")]


def statuses(rig: Rig) -> dict[str, str]:
    (m,) = marker(rig)
    return {a["action"]: a["status"] for a in m["actions"]}


# ------------------------------------------------------------------------------ every action


def test_every_action_kind_runs_for_one_event(rig: Rig) -> None:
    sid = deployed_system(rig)
    rig.control("CTL-PII", "pack", "counterfactual_vi")
    rig.eval_result("counterfactual_vi", "fail", "required")
    runner = rig.runner(only([rule("pack_no_go", ALL_ACTIONS, rid="ALL")]), sources=PACK_ONLY)
    res = runner.run()
    assert res.handled == 1 and res.failed == 0 and res.refused == 0, res
    assert statuses(rig) == dict.fromkeys(ALL_ACTIONS, "done")

    (inc,) = rig.a.state.query("incident")
    assert inc["status"] == "open" and inc["system_id"] == sid and inc["agent_id"] == "agent-a"
    assert inc["kind"] == "pack_no_go" and inc["severity"] == "high"
    assert inc["title"] == "A required assurance pack gave a NO-GO"
    assert inc["closed_at"] is None and inc["closed_by"] is None

    (notice,) = rig.a.state.query("notice")
    assert notice["channel"] == "owner:owner.lan" and "pack_no_go" in notice["subject"]

    system = rig.a.state.get("ai_system", {"system_id": sid})
    assert system["risk_level"] == "medium" and system["risk_level_source"] == "event"
    assert system["lifecycle_stage"] == "re_evaluation"
    (change,) = [p for p in rig.sink.of("system_change") if p["action"] == "risk_raise"]
    assert (change["from_level"], change["to_level"]) == ("unspecified", "medium")
    assert [p["to_stage"] for p in rig.sink.of("stage_change") if p["action"] == "move"] == [
        "re_evaluation"
    ]

    (review,) = rig.a.state.query("review")
    assert review["kind"] == "internal" and review["reviewer_user"] == "rev.lan"
    assert review["scope"] == [{"kind": "event", "id": inc["event_ref"]}]

    (out,) = rig.a.state.query("outbound_event", {"kind": "governance_action"})
    assert out["kind"] == "governance_action" and out["system_id"] == sid
    assert set(out["payload"]) == {"event_key", "event_kind", "rule_id", "severity", "system_id"}

    (row,) = rig.a.tables.query("control_status", {"control_id": "CTL-PII"})
    assert row["status"] == "failing" and row["reason"] == "reopened_by_event"
    assert row["agent_id"] == "agent-a" and row["chain_hash"]
    assert len(rig.sink.of("control_reopen")) == 1
    (g,) = rig.sink.of("governance_action")
    assert g["rules"] == ["ALL"] and g["done_n"] == 7 and g["failed_n"] == 0


def test_a_reopened_control_reads_failing_until_a_newer_pass(rig: Rig) -> None:
    rig.system()
    rig.control("CTL-PII", "pack", "counterfactual_vi")
    rig.eval_result("counterfactual_vi", "fail")
    rig.runner(only([rule("pack_no_go", ["reopen_control"])]), sources=PACK_ONLY).run()
    comp = rig.controls.agent_compliance("agent-a")
    (item,) = comp["controls"]
    assert (item["status"], item["reason"]) == ("failing", "reopened_by_event")
    assert comp["failing"] == 1 and comp["working"] == 0
    assert rig.controls.status_summary()["CTL-PII"]["failing"] == 1
    # the control, its map and its scope are untouched
    assert rig.a.state.get("control", {"control_id": "CTL-PII"})["status"] == "active"
    # a repeat for the same event writes nothing
    again = rig.controls.reopen("CTL-PII", "agent-a", next(iter(marker(rig)))["event_key"], ACTOR)
    assert again["written"] is False
    assert len(rig.a.tables.query("control_status")) == 1


def test_reopen_control_follows_the_evidence_and_the_rule_controls(rig: Rig) -> None:
    rig.system()
    rig.control("CTL-A", "pack", "counterfactual_vi")
    rig.control("CTL-B", "pack", "other_pack")
    rig.control("CTL-C", "pack", "counterfactual_vi", status="retired")
    rig.control("CTL-D", "monitor", "drift")
    rig.eval_result("counterfactual_vi", "fail")
    r = only([rule("pack_no_go", ["reopen_control"], controls=["CTL-D", "CTL-NONE"])])
    rig.runner(r, sources=PACK_ONLY).run()
    reopened = sorted(x["control_id"] for x in rig.a.tables.query("control_status"))
    assert reopened == ["CTL-A", "CTL-D"]  # mapped by the event, named by the rule; not B, not C
    (m,) = marker(rig)
    assert m["actions"][0]["ref"] == "CTL-A,CTL-D"


def test_actions_that_cannot_run_are_skipped_or_refused_with_a_code(rig: Rig) -> None:
    s = rig.system()
    sid = str(s["system_id"])  # initiation stage, no reviewer on the team, no control
    rig.eval_result("counterfactual_vi", "fail")
    r = only([rule("pack_no_go", ["move_to_re_evaluation", "create_review", "reopen_control"])])
    rig.runner(r, sources=PACK_ONLY).run()
    assert statuses(rig) == {
        "move_to_re_evaluation": "skipped",
        "create_review": "skipped",
        "reopen_control": "skipped",
    }
    (m,) = marker(rig)
    assert {a["ref"] for a in m["actions"]} == {"not_deployed", "no_reviewer", "no_control"}
    assert rig.a.state.get("ai_system", {"system_id": sid})["lifecycle_stage"] == "initiation"
    assert rig.a.state.query("review") == []


def test_a_stage_that_needs_approval_refuses_the_move(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = deployed_system(rig)
    rig.eval_result("counterfactual_vi", "fail")
    monkeypatch.setattr(rig.lifecycle, "_policy", {"re_evaluation": True})
    rig.runner(only([rule("pack_no_go", ["move_to_re_evaluation"])]), sources=PACK_ONLY).run()
    assert statuses(rig) == {"move_to_re_evaluation": "refused"}
    assert rig.a.state.get("ai_system", {"system_id": sid})["lifecycle_stage"] == "deployment"


def test_system_less_event_gets_an_incident_and_no_system_actions(rig: Rig) -> None:
    rig.chain_verify(False)
    r = only([rule("chain_break", ALL_ACTIONS, rid="CHAIN", min_severity="critical")])
    rig.runner(r, sources={"chain_breaks": src.chain_breaks}).run()
    assert statuses(rig) == {
        "create_incident": "done",
        "notify_owner": "skipped",  # no agent, no system: no owner
        "reopen_control": "skipped",
    }
    (inc,) = rig.a.state.query("incident")
    assert inc["system_id"] is None and inc["agent_id"] == "-" and inc["kind"] == "chain_break"


# ------------------------------------------------------------------------------ never lower


def test_raise_risk_level_never_lowers_and_stops_at_high(rig: Rig) -> None:
    sid = str(rig.system(risk_level="unspecified")["system_id"])
    steps = [rig.systems.raise_risk_from_event(sid, ACTOR, f"k{i}") for i in range(2)]
    assert [(s["from_level"], s["to_level"]) for s in steps] == [
        ("unspecified", "medium"),
        ("medium", "high"),
    ]
    with pytest.raises(SystemsError, match="already high"):
        rig.systems.raise_risk_from_event(sid, ACTOR, "k3")
    assert rig.a.state.get("ai_system", {"system_id": sid})["risk_level"] == "high"


def test_a_higher_manual_or_inherited_level_is_never_lowered(rig: Rig) -> None:
    high = str(rig.system("High one", agent=None, risk_level="high")["system_id"])
    prohibited = str(rig.system("Banned one", agent=None, risk_level="prohibited")["system_id"])
    for sid, level in ((high, "high"), (prohibited, "prohibited")):
        with pytest.raises(SystemsError):
            rig.systems.raise_risk_from_event(sid, ACTOR, "k")
        assert rig.a.state.get("ai_system", {"system_id": sid})["risk_level"] == level
    # inherited high: the manual level is low, the effective level is high: nothing to raise
    inh = rig.system("Inherits", agent="agent-hi", risk_level="low")
    rig.a.state.update("agent", {"agent_id": "agent-hi"}, {"risk_tier": "high"}, 1)
    with pytest.raises(SystemsError):
        rig.systems.raise_risk_from_event(str(inh["system_id"]), ACTOR, "k")
    row = rig.a.state.get("ai_system", {"system_id": inh["system_id"]})
    assert row["risk_level"] == "low" and row["risk_level_source"] != "event"


def test_a_run_never_lowers_the_level_when_an_event_repeats(rig: Rig) -> None:
    sid = deployed_system(rig, risk_level="medium")
    rig.a.state.update("agent", {"agent_id": "agent-a"}, {"risk_tier": "low"}, 1)
    rig.eval_result("counterfactual_vi", "fail", run_id="r1")
    rig.eval_result("counterfactual_vi", "fail", run_id="r2")  # a second, different event
    rig.runner(only([rule("pack_no_go", ["raise_risk_level"])]), sources=PACK_ONLY).run()
    levels = [p["to_level"] for p in rig.sink.of("system_change") if p["action"] == "risk_raise"]
    assert levels == ["high"]  # the second event finds the effective level at high: no change
    assert rig.a.state.get("ai_system", {"system_id": sid})["risk_level"] == "high"


# ------------------------------------------------------------------------------ dedupe


def test_an_event_is_processed_once_across_runs(rig: Rig) -> None:
    rig.system()
    rig.alert("al_1")
    r = only([rule("alert", ["create_incident", "notify_owner", "fire_webhook"])])
    runner = rig.runner(r, sources={"alerts": src.alerts})
    first = runner.run()
    assert first.handled == 1
    for _ in range(3):
        again = rig.runner(r, sources={"alerts": src.alerts}).run()  # a new runner: no memory
        assert again.handled == 0 and again.already == 1
    assert len(rig.a.state.query("incident")) == 1
    assert len(rig.a.state.query("notice")) == 1
    assert len(rig.a.state.query("outbound_event", {"kind": "governance_action"})) == 1
    assert len(rig.sink.of("incident_change")) == 1
    assert len(rig.sink.of("governance_action")) == 1


def test_a_new_event_after_a_run_is_handled_alone(rig: Rig) -> None:
    rig.alert("al_1")
    r = only([rule("alert", ["create_incident"])])
    runner = rig.runner(r, sources={"alerts": src.alerts})
    assert runner.run().handled == 1
    rig.alert("al_2", ts=ago(10))
    res = runner.run()
    assert res.handled == 1 and res.already == 1
    assert len(rig.a.state.query("incident")) == 2


def test_the_same_source_row_for_two_systems_is_two_events(rig: Rig) -> None:
    rig.system("Alpha")
    rig.system("Beta", agent="agent-a")
    rig.alert("al_1")
    rig.runner(only([rule("alert", ["create_incident"])]), sources={"alerts": src.alerts}).run()
    assert len(rig.a.state.query("incident")) == 2
    assert len(marker(rig)) == 2


def test_events_without_a_matching_rule_leave_no_marker(rig: Rig) -> None:
    rig.alert("al_1", severity="low")
    res = rig.runner(
        only([rule("alert", ["create_incident"], min_severity="high")]),
        sources={"alerts": src.alerts},
    ).run()
    assert res.unmatched == 1 and res.handled == 0
    assert marker(rig) == [] and rig.a.state.query("incident") == []


def test_the_budget_defers_the_rest_and_the_cursor_waits(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(actions_mod, "MAX_NEW_PER_RUN", 2)
    for i in range(5):
        rig.alert(f"al_{i}", ts=ago(100 - i))
    runner = rig.runner(only([rule("alert", ["create_incident"])]), sources={"alerts": src.alerts})
    handled = [runner.run().handled for _ in range(4)]
    assert handled == [2, 2, 1, 0]
    assert len(rig.a.state.query("incident")) == 5


# ------------------------------------------------------------------------------ failures


def test_a_raising_action_does_not_stop_the_others(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployed_system(rig)
    rig.eval_result("counterfactual_vi", "fail")

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("the review store is down")

    monkeypatch.setattr(rig.reviews, "create", boom)
    monkeypatch.setattr(rig.systems, "raise_risk_from_event", boom)
    runner = rig.runner(only([rule("pack_no_go", ALL_ACTIONS)]), sources=PACK_ONLY)
    res = runner.run()
    got = statuses(rig)
    assert got["create_review"] == "failed" and got["raise_risk_level"] == "failed"
    assert got["create_incident"] == "done" and got["notify_owner"] == "done"
    assert got["fire_webhook"] == "done" and got["move_to_re_evaluation"] == "done"
    assert res.failed == 2 and res.handled == 1
    (m,) = marker(rig)
    assert m["status"] == "done"
    assert {a["ref"] for a in m["actions"] if a["status"] == "failed"} == {"RuntimeError"}
    again = runner.run()  # a failed action is recorded, not retried by itself
    assert again.handled == 0 and len(rig.a.state.query("incident")) == 1


def test_a_failing_source_does_not_stop_the_others(rig: Rig) -> None:
    rig.alert("al_1")

    def broken(*a: Any, **k: Any) -> Any:
        raise RuntimeError("table missing")

    runner = rig.runner(
        only([rule("alert", ["create_incident"])]),
        sources={"alerts": src.alerts, "x_broken": broken},
    )
    res = runner.run()
    assert res.source_errors == 1 and res.handled == 1
    assert (
        rig.a.state.get(
            "monitor_state", {"monitor": "governance_actions", "state_key": "cursor:x_broken"}
        )
        is None
    )
    assert rig.a.state.get(
        "monitor_state", {"monitor": "governance_actions", "state_key": "cursor:alerts"}
    )


def test_a_started_event_is_resumed_without_repeating_what_was_done(rig: Rig) -> None:
    rig.system()
    rig.alert("al_1")
    r = only([rule("alert", ["create_incident", "notify_owner"])])
    runner = rig.runner(r, sources={"alerts": src.alerts})
    (event,) = src.attach_systems(src.alerts(rig.ctx, ago(3600), NOW), src.systems_of(rig.a.state))
    row, _ = rig.incidents.open_from_event(event, ACTOR)  # the crash happened after this
    rig.a.state.insert(
        "governance_event",
        {
            "event_key": event.key,
            "kind": event.kind,
            "severity": event.severity,
            "agent_id": event.agent_id,
            "system_id": event.system_id,
            "ref": event.ref,
            "event_at": event.at,
            "status": "started",
            "rules": ["T-1"],
            "actions": [{"action": "create_incident", "status": "done", "ref": row["incident_id"]}],
            "started_at": NOW,
        },
    )
    res = runner.run()
    assert res.handled == 1
    assert statuses(rig) == {"create_incident": "done", "notify_owner": "done"}
    assert len(rig.a.state.query("incident")) == 1 and len(rig.a.state.query("notice")) == 1
    assert marker(rig)[0]["status"] == "done"


# ------------------------------------------------------------------------------ dry run


def test_a_dry_run_writes_nothing_and_matches_the_real_run(rig: Rig) -> None:
    deployed_system(rig)
    rig.eval_result("counterfactual_vi", "fail")
    rig.control("CTL-PII", "pack", "counterfactual_vi")
    r = only([rule("pack_no_go", ALL_ACTIONS)])
    runner = rig.runner(r, sources=PACK_ONLY)
    before = {
        t: len(rig.a.state.query(t))
        for t in (
            "incident",
            "governance_event",
            "notice",
            "review",
            "outbound_event",
            "monitor_state",
        )
    }
    n_chain = len(rig.sink.records)
    dry = runner.run(dry_run=True)
    assert len(dry.planned) == 1 and dry.handled == 0
    assert dry.planned[0]["actions"] == ALL_ACTIONS
    assert before == {t: len(rig.a.state.query(t)) for t in before}
    assert len(rig.sink.records) == n_chain and rig.a.tables.query("control_status") == []
    assert runner.run(dry_run=True).planned == dry.planned  # same input, same plan
    runner.run()
    (m,) = marker(rig)
    assert [a["action"] for a in m["actions"]] == dry.planned[0]["actions"]
    after = runner.run(dry_run=True)
    assert after.planned == []  # the event is done: nothing would fire


# ------------------------------------------------------------------------------ incidents


def person(user: str, *roles: str, kind: str = "user") -> AuthPrincipal:
    return AuthPrincipal(user, kind, "dev_header", frozenset(roles), user)


def test_incidents_are_made_by_the_job_and_closed_only_by_a_person(rig: Rig) -> None:
    rig.system()
    rig.alert("al_1")
    rig.runner(only([rule("alert", ["create_incident"])]), sources={"alerts": src.alerts}).run()
    (inc,) = rig.a.state.query("incident")
    iid = inc["incident_id"]
    assert inc["status"] == "open" and inc["closed_by"] is None  # nothing automatic closes it
    for who in (person("svc", "admin", kind="service_principal"), person("sys", kind="system")):
        with pytest.raises(IncidentError, match="signed-in person"):
            rig.incidents.transition(iid, "closed", who)
    me = person("reviewer.an", "reviewer")
    out = rig.incidents.transition(iid, "investigating", me, root_cause="Key leaked in a prompt")
    assert out["status"] == "investigating" and out["root_cause"] == "Key leaked in a prompt"
    with pytest.raises(IncidentError, match="can become"):
        rig.incidents.transition(iid, "open", me)
    out = rig.incidents.transition(iid, "closed", me, affected_scope="one agent")
    assert out["status"] == "closed" and out["closed_by"] == "reviewer.an" and out["closed_at"]
    with pytest.raises(IncidentError, match="closed"):
        rig.incidents.transition(iid, "investigating", me)
    # no service method makes an incident from a person's input; only open_from_event exists
    assert not [n for n in dir(rig.incidents) if n.startswith(("create", "add", "new"))]


def test_a_repeat_of_the_event_finds_the_same_incident(rig: Rig) -> None:
    rig.alert("al_1")
    (event,) = src.alerts(rig.ctx, ago(3600), NOW)
    a, made = rig.incidents.open_from_event(event)
    b, again = rig.incidents.open_from_event(event)
    assert made is True and again is False and a["incident_id"] == b["incident_id"]
    assert len(rig.sink.of("incident_change")) == 1


def test_the_title_comes_from_a_template(rig: Rig) -> None:
    rig.alert("al_1", rule_id="AL-QUARANTINE")
    (event,) = src.alerts(rig.ctx, ago(3600), NOW)
    row, _ = rig.incidents.open_from_event(event)
    assert row["title"] == "Alert AL-QUARANTINE raised"
    from supervisor.governance.incidents import title_for

    assert title_for("alert", "x y <script>") == "Alert (unknown) raised"


# ------------------------------------------------------------------------------ the chain

SAFE = re.compile(r"^[A-Za-z0-9_.:\-+,]*$")


def walk(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [x for v in value.values() for x in walk(v)]
    if isinstance(value, (list, tuple)):
        return [x for v in value for x in walk(v)]
    return [value]


def test_chain_payloads_hold_ids_enums_integers_and_hashes_only(rig: Rig) -> None:
    sid = deployed_system(rig)
    rig.control("CTL-PII", "pack", "counterfactual_vi")
    rig.eval_result("counterfactual_vi", "fail")
    rig.runner(only([rule("pack_no_go", ALL_ACTIONS)]), sources=PACK_ONLY).run()
    me = person("reviewer.an@bank.example", "reviewer")
    (inc,) = rig.a.state.query("incident")
    rig.incidents.transition(
        inc["incident_id"], "closed", me, root_cause="Typed by me, with spaces"
    )
    wanted = {"incident_change", "governance_action", "control_reopen", "system_change"}
    seen = set()
    for rtype, ref, payload in rig.sink.records:
        if rtype not in wanted:
            continue
        seen.add(rtype)
        assert "agent_id" not in payload or rtype == "control_reopen", (rtype, payload)
        for v in walk(payload):
            assert not isinstance(v, float), (rtype, payload)
            if isinstance(v, str):
                assert SAFE.match(v), (rtype, v)
        assert "reviewer.an" not in repr(payload) and "Typed by me" not in repr(payload)
        assert sid not in ref or ref.startswith("system:")
    assert seen == wanted
    closing = [p for p in rig.sink.of("incident_change") if p["action"] == "transition"][0]
    assert closing["status"] == "closed" and closing["actor_ref"].startswith("act_")
    assert len(closing["root_cause_hash"]) == 64
