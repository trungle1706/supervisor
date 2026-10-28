"""WP-F3: a live factory agent reaches the orchestrator (catalogue adapter + RoutingRunner)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from supervisor.factory import catalog, gate, probe
from supervisor.factory import runtime as rt
from supervisor.factory.schemas.assessment_report_v1 import AssessmentReportV1
from supervisor.onboard import orchestrator as orch
from tests.factory.f3_helpers import FakeChat, make_env, to_live


@pytest.fixture
def env(adapters: Any, sink: Any, tmp_path: Path) -> gate.GateEnv:
    return make_env(adapters, sink, FakeChat(), tmp_path)


def test_only_a_live_version_is_in_the_catalogue(env: gate.GateEnv) -> None:
    cat = catalog.FactoryCatalog(env.store)
    assert cat.live_agent("model") is None  # nothing yet: the rule proposal stays
    env.store.create_from_template("model", "mr-agent", "Mine", "reviewer.an")
    assert cat.live_agent("model") is None  # a draft is never used
    to_live(env)
    live = cat.live_agent("model")
    assert live is not None and (live.agent_id, live.version) == ("mr-agent", "0.1")
    assert live.definition["lifecycle"]["state"] == "live"
    assert cat.live_agent("cybersecurity") is None


def test_the_plan_names_the_live_agent_and_takes_its_loop_budget(env: gate.GateEnv) -> None:
    to_live(env)
    system = {"system_id": "payments", "name": "Payments"}
    p = orch.plan(system, "high_self", {}, None, catalog=catalog.FactoryCatalog(env.store))
    item = next(i for i in p.items if i.dimension_id == "model")
    assert item.agent == "mr-agent@0.1" and item.agent_version == "0.1"
    other = next(i for i in p.items if i.dimension_id == "data_governance")
    assert other.agent == "rule"


def test_routing_runner_runs_the_harness_for_a_live_agent(
    env: gate.GateEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = to_live(env)
    monkeypatch.setattr(rt, "gateway_model", lambda inputs: probe.ProbeModel(probe.answer_good))
    req = orch.AgentRequest(
        run_id="orc_1",
        system_id="payments",
        attempt_n=1,
        dimension_id="model",
        report_id="orc_1-model",
        agent_id="mr-agent",
        agent_version="0.1",
        definition=live["definition"],
        inputs={
            "system": {"system_id": "payments", "owner_user": "chu-he-thong"},
            "facts": None,
            "proposal": {
                "checks": [
                    {
                        "kind": "pack",
                        "id": "perturbation",
                        "state": "ok",
                        "required": True,
                        "pointers": ["eval_result:r1:perturbation"],
                    }
                ]
            },
            "prior": {},
            "now": "2026-10-28T09:00:00Z",
        },
        budget_seconds=30,
        budget_tokens=40000,
    )
    report = orch.RoutingRunner().run(req)
    AssessmentReportV1.model_validate(report)
    assert report["agent_id"] == "mr-agent" and report["system_id"] == "payments"
    assert report["report_id"] == "orc_1-model" and report["model_id"] == "harness-probe"
    # the rule proposal's pack pointer is a pack result the agent may cite
    refs = report["harness_trace"]["context"]["source_refs"]
    assert "eval_result:r1:perturbation" in refs
    assert report["harness_trace"]["context"]["tokens_used"] <= 12000


def test_the_catalogue_is_none_while_the_flag_is_off(env: gate.GateEnv) -> None:
    ctx = type("C", (), {})()
    ctx.settings, ctx.state, ctx.tables, ctx.clock = env.settings, env.state, env.tables, env.clock
    env.settings.agent_factory_gate = False
    assert catalog.for_console(ctx) is None
    env.settings.agent_factory_gate = True
    assert isinstance(catalog.for_console(ctx), catalog.FactoryCatalog)
