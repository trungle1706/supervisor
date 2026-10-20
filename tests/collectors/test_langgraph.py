"""LangGraph / deepagents tool middleware with fake requests (LangGraph is not installed)."""

from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest

from supervisor.gateway.adapters.langgraph import SupervisorToolMiddleware
from supervisor.gateway.sdk import SupervisorBlocked, SupervisorPaused
from tests.collectors.fakes import ALLOW, BLOCK, PAUSE, DownGate, FakeGate, transform


@dataclass
class Msg:
    content: Any
    status: str = "ok"


@dataclass
class Req:
    tool_call: dict[str, Any]
    runtime: Any = None
    state: dict[str, Any] = field(default_factory=dict)

    def override(self, **kw: Any) -> Req:
        return Req(**{**self.__dict__, **kw})


def req(name: str = "transfer", args: Any = None, tid: str = "call-1", thread: str = "th-1") -> Req:
    rt = types.SimpleNamespace(config={"configurable": {"thread_id": thread}})
    return Req({"name": name, "args": {"amount_minor": 5} if args is None else args, "id": tid}, rt)


def mw(gate: Any, **kw: Any) -> SupervisorToolMiddleware:
    return SupervisorToolMiddleware(gate, "agent-1", "1", **kw)


class Tool:
    def __init__(self, out: Any = "done") -> None:
        self.seen: list[Req] = []
        self.out = out

    def __call__(self, request: Req) -> Msg:
        self.seen.append(request)
        return Msg(self.out)

    async def acall(self, request: Req) -> Msg:
        return self(request)


def test_allowed_call_runs_and_sends_both_phases_with_one_correlation_id() -> None:
    gate, tool = FakeGate(ALLOW), Tool()
    out = mw(gate, consumer_id="user-7").wrap_tool_call(req(), tool)
    assert out.content == "done" and len(tool.seen) == 1
    first, second = gate.calls
    assert first["direction"] == "input" and second["direction"] == "output"
    assert second["context"]["output"] == "done"
    assert first["correlation_id"] == second["correlation_id"]
    assert first["context"]["session_id"] == "th-1" and first["context"]["consumer_id"] == "user-7"
    assert first["context"]["tool_call_id"] == "call-1"
    assert first["args"] == {"amount_minor": 5} and first["tool_name"] == "transfer"


def test_block_raises_and_the_tool_does_not_run() -> None:
    tool = Tool()
    with pytest.raises(SupervisorBlocked) as e:
        mw(FakeGate(BLOCK)).wrap_tool_call(req(), tool)
    assert tool.seen == [] and e.value.decision["rule_id"] == "PAY-06"
    assert e.value.decision["correlation_id"]


def test_pause_raises_the_typed_pause_exception() -> None:
    tool = Tool()
    with pytest.raises(SupervisorPaused):
        mw(FakeGate(PAUSE)).wrap_tool_call(req(), tool)
    assert tool.seen == []


def test_masked_args_replace_the_original_for_the_tool() -> None:
    gate = FakeGate(
        lambda c: (
            transform(args={"name": "<PERSON>"})
            if c["direction"] == "input"
            else {"allow": True, "action": "allow"}
        )
    )
    tool = Tool()
    mw(gate).wrap_tool_call(req(args={"name": "Nguyen Van A"}), tool)
    assert tool.seen[0].tool_call["args"] == {"name": "<PERSON>"}
    assert tool.seen[0].tool_call["id"] == "call-1"


def test_masked_output_replaces_the_result() -> None:
    def answer(c: dict) -> dict:
        return transform(output="<MASKED>") if c["direction"] == "output" else dict(ALLOW)

    out = mw(FakeGate(answer)).wrap_tool_call(req(), Tool("0912345678"))
    assert out.content == "<MASKED>"


def test_apply_transform_off_leaves_the_call_alone() -> None:
    gate = FakeGate(lambda c: transform(args={"a": "x"}))
    tool = Tool()
    mw(gate, apply_transform=False).wrap_tool_call(req(args={"a": "raw"}), tool)
    assert tool.seen[0].tool_call["args"] == {"a": "raw"}


def test_output_block_raises_after_the_tool_ran() -> None:
    gate = FakeGate(lambda c: dict(BLOCK) if c["direction"] == "output" else dict(ALLOW))
    tool = Tool("secret")
    with pytest.raises(SupervisorBlocked):
        mw(gate).wrap_tool_call(req(), tool)
    assert len(tool.seen) == 1


def test_check_output_off_and_empty_output_send_one_call() -> None:
    gate = FakeGate(ALLOW)
    mw(gate, check_output=False).wrap_tool_call(req(), Tool())
    assert len(gate.calls) == 1
    gate2 = FakeGate(ALLOW)
    mw(gate2).wrap_tool_call(req(), Tool(""))
    assert len(gate2.calls) == 1


def test_list_content_is_read_as_text() -> None:
    gate = FakeGate(ALLOW)
    mw(gate).wrap_tool_call(req(), Tool([{"type": "text", "text": "hello"}]))
    assert gate.calls[1]["context"]["output"] == "hello"


def test_fail_closed_when_the_gate_is_down_and_open_only_for_plain_tools() -> None:
    tool = Tool()
    with pytest.raises(SupervisorBlocked):
        mw(DownGate()).wrap_tool_call(req(), tool)
    assert tool.seen == []
    ok = mw(DownGate(), fail_mode="open").wrap_tool_call(req("lookup"), tool)
    assert ok.content == "done"
    with pytest.raises(SupervisorBlocked):
        mw(DownGate(), fail_mode="open", risk_classes={"transfer": "money"}).wrap_tool_call(
            req(), tool
        )


def test_non_dict_args_and_strange_ids_do_not_crash() -> None:
    gate = FakeGate(ALLOW)
    mw(gate, consumer_id=lambda r: "bad id\n", session_id=lambda r: 1 / 0).wrap_tool_call(
        req(args="just text", tid="x y"), Tool()
    )
    call = gate.calls[0]
    assert call["args"] == {"value": "just text"}
    assert "consumer_id" not in call["context"] and "session_id" not in call["context"]
    assert "tool_call_id" not in call["context"]


def test_unicode_tool_name_is_mapped_not_rejected() -> None:
    gate = FakeGate(ALLOW)
    mw(gate).wrap_tool_call(req("chuyển_tiền"), Tool())
    assert gate.calls[0]["tool_name"].isascii()


def test_on_block_message_returns_a_tool_message_but_a_pause_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ToolMessage:
        def __init__(self, **kw: Any) -> None:
            self.__dict__.update(kw)

    fake = types.ModuleType("langchain_core.messages")
    fake.ToolMessage = ToolMessage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_core", types.ModuleType("langchain_core"))
    monkeypatch.setitem(sys.modules, "langchain_core.messages", fake)
    out = mw(FakeGate(BLOCK), on_block="message").wrap_tool_call(req(), Tool())
    assert out.status == "error" and "PAY-06" in out.content and out.tool_call_id == "call-1"
    with pytest.raises(SupervisorPaused):
        mw(FakeGate(PAUSE), on_block="message").wrap_tool_call(req(), Tool())
    with pytest.raises(ValueError):
        mw(FakeGate(), on_block="shrug")


def test_on_block_message_without_langchain_raises() -> None:
    with pytest.raises(SupervisorBlocked):
        mw(FakeGate(BLOCK), on_block="message").wrap_tool_call(req(), Tool())


def test_async_path_matches_the_sync_path() -> None:
    gate, tool = FakeGate(ALLOW), Tool()
    out = asyncio.run(mw(gate).awrap_tool_call(req(), tool.acall))
    assert out.content == "done" and [c["direction"] for c in gate.calls] == ["input", "output"]
    with pytest.raises(SupervisorBlocked):
        asyncio.run(mw(FakeGate(BLOCK)).awrap_tool_call(req(), tool.acall))
    with pytest.raises(SupervisorPaused):
        asyncio.run(mw(FakeGate(PAUSE)).awrap_tool_call(req(), tool.acall))


def test_pause_in_the_middle_of_a_run_stops_that_call_and_every_later_one() -> None:
    state = {"n": 0}

    def answer(c: dict) -> dict:
        state["n"] += 1
        return dict(PAUSE) if state["n"] >= 3 else dict(ALLOW)  # call 1 = 2 gate calls

    m, tool = mw(FakeGate(answer)), Tool()
    assert m.wrap_tool_call(req(), tool).content == "done"
    for _ in range(2):
        with pytest.raises(SupervisorPaused):
            m.wrap_tool_call(req(), tool)
    assert len(tool.seen) == 1


def test_as_agent_middleware_builds_a_subclass_of_the_framework_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = types.ModuleType("langchain.agents.middleware")

    class AgentMiddleware:
        pass

    base.AgentMiddleware = AgentMiddleware  # type: ignore[attr-defined]
    for name in ("langchain", "langchain.agents"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "langchain.agents.middleware", base)
    gate, tool = FakeGate(ALLOW), Tool()
    built = mw(gate).as_agent_middleware()
    assert isinstance(built, AgentMiddleware)
    assert built.wrap_tool_call(req(), tool).content == "done"
    assert asyncio.run(built.awrap_tool_call(req(), tool.acall)).content == "done"


def test_as_agent_middleware_without_langchain_says_so() -> None:
    with pytest.raises(ImportError):
        mw(FakeGate()).as_agent_middleware()


def test_the_module_does_not_import_langgraph_or_langchain() -> None:
    import ast
    import pathlib

    import supervisor.gateway.adapters.langgraph as mod

    tree = ast.parse(pathlib.Path(mod.__file__).read_text(encoding="utf-8"))
    top = [
        n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)
    ]  # module level only: lazy imports sit inside functions
    names = [getattr(n, "module", None) or a.name for n in top for a in getattr(n, "names", [])]
    assert not any(str(n).startswith(("langchain", "langgraph", "deepagents")) for n in names)
