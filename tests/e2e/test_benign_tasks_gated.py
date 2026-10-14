"""False-alarm check: the 20 scripted tasks of each agent behind the real gateway with the
baseline policy (same runtime as the M1 replay).

Four WP2 tasks ask for more than the manifest limits allow and expect the TOOL to refuse
(status ``error``). Behind the gateway a rule stops them first; that is the intended
control, so they are listed here with the rule. Every other task must pass unchanged."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from supervisor.adapters.llm.mock import MockChat
from supervisor.config import load_settings
from supervisor.demo.replay import AGENT_IDS, DEMO_REVIEWER, world_facts
from supervisor.wiring import build_runtime, register_agents
from supervisor_agents.common.manifest import load_manifest
from supervisor_agents.common.tasks import run_task
from supervisor_agents.common.tracing import AgentEventExporter, make_tracer_provider
from supervisor_agents.common.world import BankWorld

OVER_LIMIT = {
    "cs-10": "SVC-01",  # waiver 800,000 > waive_fee_max_minor 500,000
    "cs-11": "SVC-01",
    "cp-15": "CRD-03",  # pre-qualification 3.5bn > max_prequal_amount_minor 2bn
    "pay-19": "PAY-03",  # 907m transfer: over the single and the daily limit (pause wins)
}


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_benign_tasks_pass_behind_the_real_gateway(agent_id: str, tmp_path: Path) -> None:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data", llm_base_url="")
    world = BankWorld.build()
    rt = build_runtime(settings, facts=world_facts(world), policy_refresh_s=0.0)
    try:
        manifest = load_manifest(agent_id)
        register_agents(rt, [manifest])
        tasks = importlib.import_module(f"supervisor_agents.{agent_id}.tasks").TASKS
        chat = MockChat(seed=1)
        provider = make_tracer_provider(AgentEventExporter(rt.adapters.tables, env="test"))
        mod = importlib.import_module(f"supervisor_agents.{agent_id}.agent")
        runtime = mod.build_agent(chat, world, gate=rt.gateway, tracer_provider=provider)
        failed: dict[str, list[str]] = {}
        stopped: dict[str, str] = {}
        for t in tasks:
            o = run_task(runtime, chat, world, t)
            denied = [c for c in o.result.tool_calls if not c.decision["allow"]]
            if denied:
                stopped[t.task_id] = str(denied[0].decision["rule_id"])
            elif not o.passed:
                failed[t.task_id] = o.problems
            if rt.gateway.states.get_state(agent_id) == "PAUSED":
                rt.gateway.states.resume(agent_id, manifest.owner_user, "reviewed")
                rt.gateway.states.resume(agent_id, DEMO_REVIEWER, "reviewed")
        assert failed == {}
        assert stopped == {k: v for k, v in OVER_LIMIT.items() if k in {t.task_id for t in tasks}}
    finally:
        rt.close()
