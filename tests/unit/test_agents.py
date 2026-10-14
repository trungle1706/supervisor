from __future__ import annotations

import importlib
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.adapters.llm.mock import MockChat
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from supervisor_agents import AGENT_IDS
from supervisor_agents.common.gate import RecordingHook
from supervisor_agents.common.manifest import RISK_CLASSES, load_manifest
from supervisor_agents.common.tasks import final, run_task, tool
from supervisor_agents.common.tracing import AgentEventExporter, make_tracer_provider
from supervisor_agents.common.world import BankWorld

T0 = datetime(2026, 10, 14, 5, 0, tzinfo=UTC)


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    a = build_adapters(settings, clock=FixedClock(T0))
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


def _agent(
    agent_id: str, world: BankWorld, chat: MockChat, exporter: AgentEventExporter, gate: Any = None
):
    mod = importlib.import_module(f"supervisor_agents.{agent_id}.agent")
    return mod.build_agent(
        chat, world, gate=gate, tracer_provider=make_tracer_provider(exporter), env=exporter.env
    )


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_manifest_valid(agent_id: str) -> None:
    m = load_manifest(agent_id)
    assert m.id == agent_id and m.version and m.owner and m.model_family
    assert m.risk_tier in ("low", "medium", "high", "critical")
    assert {t.risk_class for t in m.tools} <= set(RISK_CLASSES)
    assert all(type(v) is int for v in m.limits.values())
    mod = importlib.import_module(f"supervisor_agents.{agent_id}.agent")
    assert set(mod.make_tools(BankWorld.build()).names()) == set(m.tool_names)
    assert m.agent_row(T0).agent_id == agent_id
    assert len(m.version_row(T0).tool_manifest_hash or "") == 64


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_agent_completes_20_tasks_and_writes_agent_events(
    agent_id: str, adapters: Adapters
) -> None:
    tasks = importlib.import_module(f"supervisor_agents.{agent_id}.tasks").TASKS
    assert len(tasks) == 20 and len({t.task_id for t in tasks}) == 20
    world = BankWorld.build()
    chat = MockChat(seed=1)
    exporter = AgentEventExporter(adapters.tables, env="test")
    gate = RecordingHook()
    runtime = _agent(agent_id, world, chat, exporter, gate)
    outcomes = [run_task(runtime, chat, world, t) for t in tasks]
    failed = {o.task.task_id: o.problems for o in outcomes if not o.passed}
    assert failed == {}

    n_tools = sum(len(o.result.tool_calls) for o in outcomes)
    assert len(gate.calls) == n_tools  # gate checked before every tool call
    rows = adapters.tables.query("agent_event", where={"agent_id": agent_id})
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["event_type"]] = by_type.get(r["event_type"], 0) + 1
    assert by_type["tool_call"] == n_tools
    assert by_type["llm_call"] == sum(o.result.steps for o in outcomes)
    assert by_type["message"] == 2 * len(tasks)  # inbound task + final answer
    assert len({r["trace_id"] for r in rows}) == len(tasks)
    for r in rows:
        assert r["agent_version"] == "1.0.0" and r["env"] == "test" and r["source"] == "otel"
        assert r["args_masked"] is None and r["capture_level"] == "digest"
        if r["event_type"] == "tool_call":
            assert r["tool_name"] and len(r["args_hash"]) == 64 and r["parent_span_id"]
        if r["amount_minor"] is not None:
            assert type(r["amount_minor"]) is int and r["currency"] == "VND"


def test_spans_follow_genai_conventions_and_record_gate_decision() -> None:
    world = BankWorld.build()
    chat = MockChat(scripts={"t": [tool("get_balance", account_id="ACC-0000000001"), final("ok")]})
    exporter = AgentEventExporter()
    rt = _agent("payments", world, chat, exporter)
    with chat.scenario("t"):
        rt.run("balance?")
    spans = {
        s.attributes["supervisor.event_type"]: s.attributes
        for s in exporter.spans
        if s.attributes.get("supervisor.event_type") != "message"
    }
    llm, tc = spans["llm_call"], spans["tool_call"]
    assert llm["gen_ai.operation.name"] == "chat" and llm["gen_ai.request.model"] == chat.model_id
    assert llm["gen_ai.system"] == "mock" and llm["supervisor.llm.is_mock"] is True
    assert tc["gen_ai.operation.name"] == "execute_tool" and tc["gen_ai.tool.name"] == "get_balance"
    for key in (
        "supervisor.agent_id",
        "supervisor.agent_version",
        "supervisor.tool_name",
        "supervisor.args_hash",
    ):
        assert key in tc
    assert tc["supervisor.gate.allow"] is True and tc["supervisor.gate.action"] == "allow"


class _Hook:
    def __init__(self, decide: Any) -> None:
        self.decide = decide

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        return self.decide(tool_name, args, context)


def test_block_skips_tool_and_pause_stops_run() -> None:
    world = BankWorld.build()
    script = [
        tool(
            "ext_transfer_api",
            to_bank_swift="XYZBANKXX",
            to_account="0000123",
            amount_minor=95_000_000,
            currency="VND",
            memo="x",
        ),
        final("done"),
    ]
    block = _Hook(
        lambda t, a, c: {
            "allow": False,
            "action": "block",
            "rule_id": "R1",
            "reason": "test",
            "latency_ms": 1,
        }
    )
    chat = MockChat(scripts={"b": script})
    exporter = AgentEventExporter()
    rt = _agent("payments", world, chat, exporter, block)
    with chat.scenario("b"):
        res = rt.run("x")
    assert res.status == "completed" and res.tool_calls[0].status == "blocked"
    assert world.external_transfers == []
    ev = [e for e in exporter.events if e.event_type == "tool_call"][0]
    assert ev.status == "blocked" and ev.amount_minor == 95_000_000

    pause = _Hook(
        lambda t, a, c: {
            "allow": False,
            "action": "pause",
            "rule_id": "R2",
            "reason": "p",
            "latency_ms": 1,
        }
    )
    chat = MockChat(scripts={"p": script})
    rt = _agent("payments", world, chat, AgentEventExporter(), pause)
    with chat.scenario("p"):
        res = rt.run("x")
    assert res.status == "paused" and world.external_transfers == []


def test_gate_hook_error_fails_closed_for_money_open_for_read_only() -> None:
    def boom(t: str, a: Any, c: Any) -> Any:
        raise RuntimeError("gate down")

    world = BankWorld.build()
    chat = MockChat(
        scripts={
            "e": [
                tool("get_balance", account_id="ACC-0000000001"),
                tool(
                    "transfer",
                    from_account_id="ACC-0000000001",
                    payee_id="PAY-0001",
                    amount_minor=1000,
                    memo="x",
                ),
                final("end"),
            ]
        }
    )
    rt = _agent("payments", world, chat, AgentEventExporter(), _Hook(boom))
    with chat.scenario("e"):
        res = rt.run("x")
    assert [c.status for c in res.tool_calls] == ["ok", "blocked"]
    assert res.tool_calls[1].decision["rule_id"] == "gate_hook_error"
    assert world.transfers == []


def test_context_passed_to_gate_has_trace_and_risk_class() -> None:
    world = BankWorld.build()
    hook = RecordingHook()
    chat = MockChat(
        scripts={
            "c": [
                tool(
                    "waive_fee",
                    account_id="ACC-0000000001",
                    fee_code="SMS_BANKING",
                    amount_minor=10_000,
                    reason="r",
                ),
                final("ok"),
            ]
        }
    )
    rt = _agent("customer_service", world, chat, AgentEventExporter(), hook)
    with chat.scenario("c"):
        rt.run("x", context={"customer_id": "CUS-000001"})
    ctx = hook.calls[0]["context"]
    assert (
        ctx["risk_class"] == "money"
        and len(ctx["trace_id"]) == 32
        and ctx["customer_id"] == "CUS-000001"
    )


def test_garbled_gate_decision_fails_closed_for_money() -> None:
    world = BankWorld.build()
    garbled = _Hook(lambda t, a, c: {"allow": "yes", "action": "approve"})
    chat = MockChat(
        scripts={
            "g": [
                tool("get_balance", account_id="ACC-0000000001"),
                tool(
                    "transfer",
                    from_account_id="ACC-0000000001",
                    payee_id="PAY-0001",
                    amount_minor=1000,
                    memo="x",
                ),
                final("end"),
            ]
        }
    )
    rt = _agent("payments", world, chat, AgentEventExporter(), garbled)
    with chat.scenario("g"):
        res = rt.run("x")
    assert [c.status for c in res.tool_calls] == ["ok", "blocked"]
    assert res.tool_calls[1].decision["rule_id"] == "gate_hook_invalid"
    assert world.transfers == []


def test_broken_tool_and_truncated_llm_do_not_crash_the_run() -> None:
    from supervisor.adapters.llm.errors import TruncatedError

    world = BankWorld.build()
    chat = MockChat(scripts={"t": [tool("get_balance", account_id="ACC-0000000001"), final("x")]})
    rt = _agent("payments", world, chat, AgentEventExporter())

    def broken(args: Any) -> Any:
        raise AttributeError("boom")

    rt.tools.register("get_balance", broken)
    with chat.scenario("t"):
        res = rt.run("x")
    assert res.status == "completed" and res.tool_calls[0].status == "error"

    class Cut:
        family, model_id, is_mock = "mock", "mock-cut", True

        def complete_json(self, *a: Any, **k: Any) -> Any:
            raise TruncatedError("cut off")

    exporter2 = AgentEventExporter()
    rt2 = _agent("payments", world, Cut(), exporter2)  # type: ignore[arg-type]
    assert rt2.run("x").status == "llm_error"
    assert [e.status for e in exporter2.events if e.event_type == "llm_call"] == ["truncated"]
