"""WP30 on the reviewed WP29 evidence rules: only deterministic monitors count, shadow and
error verdict rows are not hits, packs have their own longer window, and a change to the map
of a control invalidates its status and the evidence of the risks that link it."""

from __future__ import annotations

import datetime as dt

from supervisor.controls.harness_env import CtlEnv


def _monitor(env: CtlEnv, name: str, status: str = "ok") -> None:
    env.adapters.state.insert(
        "oversight_metric",
        {
            "metric_date": (env.adapters.clock.now() - dt.timedelta(days=1)).date(),
            "agent_id": "pay",
            "computed_at": env.adapters.clock.now(),
            "monitor_status": {name: {"status": status, "code": "x", "reason": "x", "n": 1}},
        },
    )


def _first(env: CtlEnv) -> dict[str, object]:
    env.controls.run_status()
    return env.controls.agent_compliance("pay")["controls"][0]


def test_oversight_monitor_never_makes_a_control_work(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-M", evidence=[("monitor", "oversight")])
    _monitor(env, "oversight")
    assert _first(env)["status"] == "no_data"


def test_drift_monitor_ok_makes_a_control_work(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-D", evidence=[("monitor", "drift")])
    _monitor(env, "drift")
    assert _first(env)["status"] == "working"


def test_shadow_labelled_rows_are_not_rule_hits(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-A")
    env.adapters.tables.append(
        "verdict",
        [
            {
                "verdict_id": "vs1",
                "ts": env.window_time(),
                "agent_id": "pay",
                "tier": 0,
                "checker_id": "gate:tier0a",
                "is_mock": False,
                "advisory": False,
                "label": "shadow_would_block",
                "action": "log",
                "rule_id": "PAY-02",
            }
        ],
    )
    assert _first(env)["status"] == "no_data"


def test_pack_window_is_longer_than_the_rule_window(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-P", evidence=[("pack", "pack_a")])
    env.pack("pay", "pack_a", "ok", env.window_time() - dt.timedelta(days=20))
    assert _first(env)["status"] == "working"


def test_pack_older_than_the_pack_window_is_no_data(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-P", evidence=[("pack", "pack_a")])
    env.pack("pay", "pack_a", "ok", env.window_time() - dt.timedelta(days=45))
    assert _first(env)["status"] == "no_data"


def test_a_map_change_invalidates_the_status(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-A", evidence=[("rule", "PAY-02")])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    assert _first(env)["status"] == "working"
    env.controls.add_map("CTL-A", "pack", "pack_b", "u")
    c = env.controls.agent_compliance("pay")["controls"][0]
    assert (c["status"], c["reason"]) == ("no_data", "changed_since_evidence")
    assert env.controls.agent_compliance("pay")["compliance_bp"] == 0
    assert _first(env)["status"] == "working"  # a new pass in the same window


def test_a_map_change_invalidates_the_evidence_of_a_linked_risk(env: CtlEnv) -> None:
    env.agent("pay")
    rid = env.risk("r", "pay", [("matrix", "OB-1")])
    env.control("CTL-A", covers=[("matrix", "OB-1"), ("risk", rid)])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.svc.run_evidence()
    assert env.svc.get(rid)["evidence_state"] == "working"
    env.controls.add_map("CTL-A", "pack", "pack_b", "u")
    assert env.svc.get(rid)["evidence_reason"] == "changed_since_evidence"


def test_chain_payloads_carry_a_keyed_actor_ref_never_the_actor(env: CtlEnv, sink) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.controls.create(
        {
            "title": "T",
            "objective": "O",
            "control_type": "preventive",
            "implemented_by": "product",
            "owner": "ops",
            "status": "draft",
        },
        "alice@bank.example",
        control_id="C1",
    )
    from types import SimpleNamespace

    env.tasks.generate("pay", SimpleNamespace(user_id="bob@bank.example", roles=frozenset()))
    records = sink.of("control_change") + sink.of("task_change")
    assert records
    for p in records:
        assert "actor" not in p and p["actor_ref"].startswith("act_")
        assert "bank.example" not in str(p)
    # the readable id stays in the audited task_event row
    assert {e["actor"] for e in env.tasks.events("pay")} == {"bob@bank.example"}


def test_judge_scored_pack_and_status_less_monitor_are_references_in_the_starters() -> None:
    from supervisor.controls import harness as H
    from supervisor.controls.model import evidence_capable

    assert not evidence_capable("pack", "groundedness_monitor")
    assert not evidence_capable("monitor", "quality") and not evidence_capable(
        "monitor", "oversight"
    )
    assert evidence_capable("monitor", "drift") and evidence_capable("pack", "pii_canary")
    assert not evidence_capable("document", "x") and not evidence_capable("detector", "cccd")
    assert H.check_starters()["problems"] == []


def test_harness_starter_check_fails_a_product_control_with_only_references(tmp_path) -> None:
    from supervisor.controls import harness as H

    (tmp_path / "x.yaml").write_text(
        "version: 1\ncontrols:\n  - id: CTL-ONLY-REF\n    title: t\n    objective: o\n"
        "    type: preventive\n    implemented_by: product\n    owner: o\n    status: active\n"
        "    review_date: 2027-04-20\n    covers: {matrix: [INTL-SR117-2011-S5.2-01]}\n"
        "    evidence: {monitor: [oversight], pack: [groundedness_monitor]}\n",
        encoding="utf-8",
    )
    problems = H.check_starters(tmp_path)["problems"]
    assert any("only reference sources" in p for p in problems)
