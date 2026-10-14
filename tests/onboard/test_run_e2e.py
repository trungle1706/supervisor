"""End to end: onboarding ``payments`` from a clean checkout produces every artefact, a
branch in a clone (never merged), and the Onboarding Agent's own events appear in
``agent_event`` and on the evidence chain. Also: the agent's own gate blocks it."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from supervisor import sandbox
from supervisor.adapters.clock import SystemClock
from supervisor.adapters.factory import build_adapters
from supervisor.adapters.llm.mock import MockChat
from supervisor.config import Settings
from supervisor.evidence.export import export_chain
from supervisor.evidence.verify import verify_export
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StaticPolicyProvider, load_policy_texts
from supervisor.jobs import bootstrap_schema
from supervisor.onboard import __main__ as cli
from supervisor.onboard.agent import AGENT_ID, SELF_POLICY, OnboardBlocked, OnboardingAgent
from supervisor.onboard.instrument import validate_policy
from supervisor.onboard.run import ARTEFACTS, run_onboarding
from supervisor_agents.common.tracing import AgentEventExporter, make_tracer_provider
from tests.conftest import REPO_ROOT
from tests.gateway.conftest import MemoryEvidence, assert_no_floats


def _g(args: list[str], cwd: Path) -> str:
    res = sandbox.git(args, cwd=cwd)
    assert res.ok, res.stderr
    return res.stdout.strip()


@pytest.fixture(scope="module")
def checkout(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A clean checkout (git clone) of this repository at HEAD."""
    base = tmp_path_factory.mktemp("checkout")
    dest = base / "supervisor"
    _g(["clone", "--quiet", "--no-hardlinks", str(REPO_ROOT), str(dest)], base)
    return dest


def test_end_to_end_payments(
    checkout: Path, tmp_path: Path, sqlite_settings: Callable[[], Settings]
) -> None:
    settings = sqlite_settings()
    target = checkout / "src" / "supervisor_agents" / "payments"
    head = _g(["rev-parse", "HEAD"], checkout)
    branches = _g(["branch", "--list"], checkout)
    out = tmp_path / "out"
    res = run_onboarding(
        target, out, settings=settings, chat=MockChat(model_id="mock-onboarding-v1")
    )
    # every artefact exists and parses
    for name in ARTEFACTS:
        p = out / name
        assert p.is_file() and p.stat().st_size > 0, name
        if name.endswith(".json"):
            assert_no_floats(json.loads(p.read_text(encoding="utf-8")))
    assert set(res.artefacts) == set(ARTEFACTS)
    policy = validate_policy((out / "policy.yaml").read_text(encoding="utf-8"))
    assert policy.policy_hash == res.instrument.policy_hash
    profile = json.loads((out / "profile.json").read_text(encoding="utf-8"))
    assert profile["decision33"]["classification"] == "high_risk"
    report = json.loads((out / "launch_report.json").read_text(encoding="utf-8"))
    assert report["go"] is True and report["catch_rate_bp"] >= 9000
    pr = (out / "pr_description.md").read_text(encoding="utf-8")
    assert "supervisor/onboard-payments" in pr and "Never auto-merged" in pr
    handover = json.loads((out / "handover.json").read_text(encoding="utf-8"))
    assert handover["gate_state_after_merge"] == "SHADOW"
    assert set(handover["artefacts"]) == set(ARTEFACTS) - {"handover.json"}
    # the checkout is untouched; the branch is in the work clone, never merged
    assert _g(["rev-parse", "HEAD"], checkout) == head
    assert _g(["branch", "--list"], checkout) == branches
    assert _g(["status", "--porcelain"], checkout) == ""
    clone = Path(res.instrument.work_repo)
    assert clone.is_relative_to(out / "_work")
    assert _g(["rev-parse", "--abbrev-ref", "HEAD"], clone) == "supervisor/onboard-payments"
    assert _g(["rev-parse", res.instrument.base_ref], clone) == head
    assert res.instrument.merged is False
    # CLI lines are ASCII
    assert all(line.isascii() for line in res.lines)

    # the Onboarding Agent ran under Watch: registry, agent_event and the chain
    a = build_adapters(settings, clock=SystemClock())
    try:
        assert a.state.get("agent", {"agent_id": AGENT_ID}) is not None
        events = a.tables.query("agent_event", {"agent_id": AGENT_ID})
        kinds = {e["event_type"] for e in events}
        assert {"tool_call", "gate_decision", "message"} <= kinds
        tools = {e["tool_name"] for e in events if e["event_type"] == "tool_call"}
        assert {
            "list_repo_tree",
            "read_file",
            "write_artifact",
            "git_branch_commit",
            "run_redteam_sandbox",
        } <= tools
        lane = a.tables.query("chain_entry", {"lane": f"agent:{AGENT_ID}"})
        types = {e["record_type"] for e in lane}
        assert {"agent_registered", "gate_decision", "onboard_artifact", "onboard_stage"} <= types
        assert "onboard_run" in types
        n_artifacts = sum(1 for e in lane if e["record_type"] == "onboard_artifact")
        assert n_artifacts == len(ARTEFACTS)
        cov = a.state.query("coverage", {"agent_id": "payments"})
        assert {r["status"] for r in cov} == {"planned", "off"}
        # the chain verifies offline
        export_dir = tmp_path / "export"
        export_chain(a.tables, export_dir)
        assert verify_export(export_dir).ok
    finally:
        a.close()


def test_cli_runs_and_prints_ascii(
    checkout: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = checkout / "src" / "supervisor_agents" / "customer_service"
    rc = cli.main(["--target", str(target), "--out", str(tmp_path / "o"), "--mock-llm"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert out.isascii()
    assert "[OK] discover:" in out and "[OK] launch report:" in out
    assert (tmp_path / "o" / "launch_report.md").is_file()


def test_cli_reports_failure_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--target", str(tmp_path / "missing"), "--out", str(tmp_path / "o")])
    out = capsys.readouterr().out
    assert rc == 1 and out.startswith("[FAIL]") and out.isascii()


@pytest.fixture
def watched(tmp_path: Path, sqlite_settings: Callable[[], Settings]):  # type: ignore[no-untyped-def]
    settings = sqlite_settings()
    a = build_adapters(settings)
    bootstrap_schema.run(settings, a)
    policy = load_policy_texts([(SELF_POLICY.name, SELF_POLICY.read_text(encoding="utf-8"))])
    evidence = MemoryEvidence()
    gw = Gateway(
        StaticPolicyProvider(policy), a.tables, a.state, evidence, a.clock, state_cache_ttl_s=0
    )
    provider = make_tracer_provider(AgentEventExporter(a.tables))
    agent = OnboardingAgent(gw, evidence, provider, a.clock, run_id="r1", target_agent_id="x")
    try:
        yield agent, evidence, a
    finally:
        gw.close()
        provider.shutdown()
        a.close()


def test_own_gate_blocks_unsafe_calls(watched, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    agent, evidence, a = watched
    ran: list[str] = []
    # a path in an artefact name (escape from the output folder)
    with pytest.raises(OnboardBlocked) as exc:
        agent.write_artifact(tmp_path, "../escape.md", "x", "test")
    assert exc.value.decision["rule_id"] == "OB-SELF-04"
    assert not (tmp_path.parent / "escape.md").exists()
    # an LLM call on text that was not scrubbed
    with pytest.raises(OnboardBlocked) as exc:
        agent.call("call_llm", {"scrubbed": False}, lambda: ran.append("llm"))
    assert exc.value.decision["rule_id"] == "OB-SELF-02"
    # a branch outside supervisor/onboard-*, or a merge request
    for args in ({"branch": "main"}, {"branch": "supervisor/onboard-x", "merge": True}):
        with pytest.raises(OnboardBlocked) as exc:
            agent.call("git_branch_commit", args, lambda: ran.append("git"))
        assert exc.value.decision["rule_id"] == "OB-SELF-03"
    # a tool outside the allow-list pauses the Onboarding Agent
    with pytest.raises(OnboardBlocked) as exc:
        agent.call("shell", {"cmd": "x"}, lambda: ran.append("shell"))
    assert exc.value.decision["action"] in ("pause", "block")
    assert ran == []
    # allowed calls run
    agent.call("call_llm", {"scrubbed": True, "chars": 10}, lambda: ran.append("llm"))
    agent.write_artifact(tmp_path, "ok.md", "fine", "test")
    assert ran == ["llm"] and (tmp_path / "ok.md").read_text() == "fine"
    rows = a.tables.query("agent_event", {"agent_id": AGENT_ID, "event_type": "tool_call"})
    assert len(rows) == 7
    assert [p["name"] for t, _, p in evidence.entries if t == "onboard_artifact"] == ["ok.md"]
