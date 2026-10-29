"""WP-G3 in the gate: the off path, the shadow hook (log-only, same decision with and without it,
latency budget), and a live guardian acting through the detector slug gf:<id>@<version>."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.gateway.detector_gate import GUARDIAN_RULE, DetectorGate
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StorePolicyProvider, deploy_policy, load_policy_dir
from supervisor.guardian_factory import attach, caps
from supervisor.guardian_factory.attach import LiveGuardians
from supervisor.guardian_factory.definition import validate_definition
from supervisor.guardian_factory.shadow import ShadowRunner
from supervisor.jobs import bootstrap_schema
from supervisor.wiring import make_detector_gate
from tests.conftest import REPO_ROOT
from tests.gateway.conftest import T0, MemoryEvidence

from .conftest import FakeChat, regex_def

ACC = "0123456789012"
CALLS: list[tuple[str, str, dict[str, Any]]] = [
    ("customer_service", "read_ticket", {"ticket_id": "T1", "note": f"so tai khoan {ACC}"}),
    ("customer_service", "read_ticket", {"ticket_id": "T2", "note": "hello"}),
    ("payments", "add_payee", {"customer_id": "C-1", "payee_name": "Linh", "note": f"ref {ACC}"}),
    (
        "payments",
        "transfer",
        {
            "amount_minor": 1000,
            "from_account_id": "ACC-1",
            "payee_id": "P-1",
            "customer_id": "C-1",
            "memo": "rent",
        },
    ),
]
VOLATILE = (
    "decision_id",
    "request_id",
    "correlation_id",
    "latency_us",
    "detector_latency_us",
    "ts",
    "latency_ms",
    "total_us",
)


@dataclass
class World:
    adapters: Adapters
    gateway: Gateway
    gate: DetectorGate
    evidence: MemoryEvidence


def build_world(tmp_path: Path, name: str, **flags: Any) -> Iterator[World]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / name,
        llm_base_url="",
        detectors_enabled=True,
        **flags,
    )
    a = build_adapters(settings, clock=FixedClock(T0))
    bootstrap_schema.run(a.settings, a)
    policy = load_policy_dir(REPO_ROOT / "policies")
    deploy_policy(policy, a.state, a.clock)
    gate = make_detector_gate(settings, policy, a.state)
    ev = MemoryEvidence()
    gw = Gateway(
        StorePolicyProvider(a.state, refresh_s=0),
        a.tables,
        a.state,
        ev,
        a.clock,
        state_cache_ttl_s=0,
        detector_gate=gate,
    )
    try:
        yield World(a, gw, gate, ev)
    finally:
        gw.close()
        a.close()


@pytest.fixture
def off_world(tmp_path: Path) -> Iterator[World]:
    yield from build_world(tmp_path, "off")


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    yield from build_world(tmp_path, "on", guardian_factory=True, guardian_shadow=True)


@pytest.fixture
def world_b(tmp_path: Path) -> Iterator[World]:
    yield from build_world(tmp_path, "b", guardian_factory=True, guardian_shadow=True)


def add_def(w: World, state: str, **over: Any) -> dict[str, Any]:
    data = regex_def(owner_group="model_risk", **over)
    data["created_by"] = "reviewer.an"
    data["lifecycle"] = {"state": state, "version": 1}
    d = validate_definition(data)
    body = d.model_dump(mode="json")
    w.adapters.state.insert(
        "guardian_def",
        {
            "def_id": d.id,
            "version": d.lifecycle.version,
            "owner_group": d.owner_group,
            "type": d.type,
            "stage": d.stage,
            "definition_json": json.dumps(body, sort_keys=True),
            "state": state,
            "created_by": "reviewer.an",
        },
    )
    attach.bump()
    return body


def check(w: World, i: int) -> dict[str, Any]:
    agent, tool, args = CALLS[i]
    return w.gateway.check(agent, "1", tool, dict(args), {"trace_id": f"t-{i}"})


def core(r: dict[str, Any]) -> dict[str, Any]:
    drop = lambda v: (  # noqa: E731
        {k: drop(x) for k, x in v.items() if k not in VOLATILE} if isinstance(v, dict) else v
    )
    return drop(r)


# ============================================================ the off path


def test_off_the_gate_has_no_hook(off_world: World) -> None:
    assert off_world.gate.attach is None and off_world.gate.shadow is None
    assert check(off_world, 0)["allow"] is True


def test_factory_on_shadow_off_has_live_attach_but_no_shadow_hook(tmp_path: Path) -> None:
    for w in build_world(tmp_path, "half", guardian_factory=True):
        assert w.gate.attach is not None and w.gate.shadow is None


def test_shadow_flag_alone_does_nothing(tmp_path: Path) -> None:
    for w in build_world(tmp_path, "shonly", guardian_shadow=True):
        assert w.gate.attach is None and w.gate.shadow is None


# ============================================================ the shadow hook


def test_shadow_hook_records_findings_and_never_blocks(world: World) -> None:
    add_def(world, "shadow", action_on_fail="block")
    runner: ShadowRunner = world.gate.shadow
    runner.ttl_s = 0
    r = check(world, 0)
    assert r["allow"] is True and r["rule_id"] != GUARDIAN_RULE  # log-only: nothing is blocked
    assert not any(f["detector_slug"].startswith("gf:") for f in r["findings"])
    check(world, 1)
    runner.flush()
    rows = world.adapters.state.query("guardian_shadow_finding", {})
    assert len(rows) == 1
    f = dict(rows[0])
    assert (f["def_id"], f["version"], f["agent_id"], f["stage"]) == (
        "account-numbers",
        1,
        "customer_service",
        "input",
    )
    assert f["would_action"] == "block" and f["reviewed"] is None and f["count"] >= 1
    assert f["call_ref"] and len(f["value_hash"]) == 64
    assert ACC not in json.dumps(f, default=str)  # no value text
    day = world.adapters.state.query("guardian_shadow_day", {})
    assert [(d["calls_seen"], d["would_act"], d["findings_n"]) for d in day] == [(2, 1, 1)]


def test_decisions_are_identical_with_and_without_the_hook(tmp_path: Path) -> None:
    results: list[list[dict[str, Any]]] = []
    for name, shadow_on in (("plain", False), ("hooked", True)):
        flags = {"guardian_factory": True, "guardian_shadow": shadow_on}
        for w in build_world(tmp_path, name, **flags):
            add_def(w, "shadow", action_on_fail="block")
            if shadow_on:
                assert w.gate.shadow is not None
            else:
                assert w.gate.shadow is None
            results.append([core(check(w, i)) for i in range(len(CALLS))])
            if shadow_on:
                w.gate.shadow.flush()
                assert len(w.adapters.state.query("guardian_shadow_finding", {})) == 2
    assert results[0] == results[1]
    assert any(r["allow"] for r in results[0])


def test_latency_budget_skip_is_counted(world: World) -> None:
    add_def(world, "shadow", id="first-one")
    add_def(world, "shadow", id="second-one")
    ticks = iter(range(0, 10_000_000_000, 30_000_000))  # 30 ms per reading
    runner = ShadowRunner(
        world.adapters.state,
        world.adapters.settings,
        perf=lambda: next(ticks),
        ttl_s=0,
    )
    assert runner.budget_ns == 20_000_000
    view = {"args": {"note": ACC}, "meta": {"agent_id": "payments", "tool_name": "x"}}
    runner.observe(view, "input", "c1")
    runner.flush()
    days = {d["def_id"]: dict(d) for d in world.adapters.state.query("guardian_shadow_day", {})}
    # the first reading after t0 is already over the budget: both are in scope, both skipped
    assert sum(d["skipped_budget"] for d in days.values()) == 2
    assert sum(d["calls_seen"] for d in days.values()) == 2
    assert world.adapters.state.query("guardian_shadow_finding", {}) == []
    # a fast clock: nothing skipped, both find
    fast = iter(range(0, 10_000_000_000, 1_000))
    runner2 = ShadowRunner(
        world.adapters.state, world.adapters.settings, perf=lambda: next(fast), ttl_s=0
    )
    runner2.observe(view, "input", "c2")
    runner2.flush()
    assert len(world.adapters.state.query("guardian_shadow_finding", {})) == 2


def test_shadow_runner_ignores_other_states_stage_and_scope(world: World) -> None:
    add_def(world, "benchmarked", id="not-shadow")
    add_def(world, "shadow", id="out-stage", stage="output")
    add_def(world, "shadow", id="other-agent", scope={"agents": ["lending"], "tools": "*"})
    runner = ShadowRunner(world.adapters.state, world.adapters.settings, ttl_s=0)
    runner.observe(
        {"args": {"note": ACC}, "meta": {"agent_id": "payments", "tool_name": "x"}}, "input", "c"
    )
    runner.flush()
    assert world.adapters.state.query("guardian_shadow_finding", {}) == []
    assert world.adapters.state.query("guardian_shadow_day", {}) == []


def test_shadow_hook_never_raises(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    runner: ShadowRunner = world.gate.shadow

    def boom() -> Any:
        raise RuntimeError("store down")

    monkeypatch.setattr(runner, "active", boom)
    assert check(world, 0)["allow"] is True


def test_judge_shadow_runs_on_the_worker_and_never_gates(world: World) -> None:
    add_def(
        world,
        "shadow",
        id="judge-one",
        type="judge_prompt",
        action_on_fail="log",
        config={
            "prompt": "Is this an enquiry about accounts?",
            "verdict_labels": ["ok", "bad"],
            "fail_labels": ["bad"],
        },
    )
    chat = FakeChat({"label": "bad", "score_bp": 9000})
    runner = ShadowRunner(world.adapters.state, world.adapters.settings, chat=chat, ttl_s=0)
    runner.observe({"args": {"note": "x"}, "meta": {"agent_id": "payments"}}, "input", "cj")
    runner.join()
    runner.flush()
    rows = world.adapters.state.query("guardian_shadow_finding", {})
    assert len(rows) == 1 and rows[0]["finding_code"] == "guardian.judge-one.bad"
    # no model: the judge guardian is not run at all (nothing counted)
    r2 = ShadowRunner(world.adapters.state, world.adapters.settings, chat=None, ttl_s=0)
    r2.observe({"args": {"note": "x"}, "meta": {"agent_id": "payments"}}, "input", "cj2")
    r2.flush()
    assert len(world.adapters.state.query("guardian_shadow_finding", {})) == 1


# ============================================================ a live guardian acts


def test_live_regex_guardian_blocks_and_scope_limits_it(world: World) -> None:
    add_def(
        world, "live", action_on_fail="block", scope={"agents": ["customer_service"], "tools": "*"}
    )
    world.gate.attach.ttl_s = 0
    r = check(world, 0)  # customer_service, account number in the note
    assert r["allow"] is False and r["rule_id"] == GUARDIAN_RULE and r["status"] == "block"
    assert "gf:account-numbers@1" in [f["detector_slug"] for f in r["findings"]]
    assert check(world, 1)["allow"] is True  # no match
    assert check(world, 2)["allow"] is True  # payments: out of scope
    world.gateway.drain()
    blob = json.dumps([r, world.adapters.tables.query("finding", {})], default=str)
    assert ACC not in blob


def test_live_guardian_retired_stops_acting_and_rollback_target_acts_again(world: World) -> None:
    add_def(world, "live", action_on_fail="block")
    world.gate.attach.ttl_s = 0
    assert check(world, 0)["allow"] is False
    row = world.adapters.state.get("guardian_def", {"def_id": "account-numbers", "version": 1})
    world.adapters.state.update(
        "guardian_def",
        {"def_id": "account-numbers", "version": 1},
        {"state": "retired"},
        row["row_version"],
    )
    attach.bump()
    assert check(world, 0)["allow"] is True


def test_live_redact_guardian_transforms_without_blocking(world: World) -> None:
    add_def(world, "live", action_on_fail="redact")
    world.gate.attach.ttl_s = 0
    r = check(world, 0)
    assert r["allow"] is True and r["status"] == "transform"
    assert ACC not in json.dumps(r["transformed_payload"])


def test_live_judge_guardian_is_clamped_to_a_report(world: World) -> None:
    for action in ("log", "require_approval"):
        for w in build_world(
            world.adapters.settings.data_dir.parent, f"j-{action}", guardian_factory=True
        ):
            chat = FakeChat({"label": "bad", "score_bp": 9500})
            w.gate.attach = LiveGuardians(
                w.adapters.state, w.adapters.settings, w.gate.registry, chat=chat, ttl_s=0
            )
            add_def(
                w,
                "live",
                id="judge-live",
                type="judge_prompt",
                action_on_fail=action,
                config={
                    "prompt": "Is this a risky enquiry?",
                    "verdict_labels": ["ok", "bad"],
                    "fail_labels": ["bad"],
                },
            )
            r = check(w, 2)  # a pii_export tool
            assert r["allow"] is True and r["rule_id"] != GUARDIAN_RULE
            codes = [f["code"] for f in r["findings"]]
            assert "guardian.judge-live.bad" in codes
            hint = next(
                f["action_hint"] for f in r["findings"] if f["code"] == "guardian.judge-live.bad"
            )
            assert hint == ("report" if action == "log" else "pause")


def test_a_guardian_that_cannot_run_never_fails_a_risky_call_closed(world: World) -> None:
    add_def(
        world,
        "live",
        id="judge-dead",
        type="judge_prompt",
        action_on_fail="log",
        config={"prompt": "p", "verdict_labels": ["ok", "bad"], "fail_labels": ["bad"]},
    )
    world.gate.attach.ttl_s = 0  # no model configured: the judge reports not_executed
    r = check(world, 3)  # money tool
    assert r["allow"] is True and r["rule_id"] != "GATE-DETECTOR-FAILED"


def test_slug_scheme_and_registration(world: World) -> None:
    add_def(world, "live", action_on_fail="log")
    live: LiveGuardians = world.gate.attach
    live.ttl_s = 0
    assert live.slugs_for("payments/consumer-9") == ["gf:account-numbers@1"]
    assert "gf:account-numbers@1" in world.gate.registry
    assert attach.parse_slug("gf:account-numbers@1") == ("account-numbers", 1)
    assert attach.parse_slug("gf:Bad Id@1") is None and attach.parse_slug("dlp_vn") is None
    assert caps.GF_SLUG_RE.match("gf:a@12")
