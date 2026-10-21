"""LiteLLM guardrail and Claude Code hook adapters, and the SDK additions (fake gate only)."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import types
from typing import Any

import pytest

from supervisor.gateway.adapters import claude_code_hook as hook
from supervisor.gateway.adapters.litellm_guardrail import (
    SupervisorGuardrail,
    build_litellm_guardrail,
)
from supervisor.gateway.sdk import HttpGate, InProcessGate, SupervisorBlocked, SupervisorPaused
from tests.collectors.fakes import ALLOW, BLOCK, PAUSE, DownGate, FakeGate, transform

# --------------------------------------------------------------------------- LiteLLM


def guard(gate: Any, **kw: Any) -> SupervisorGuardrail:
    return SupervisorGuardrail(gate, "agent-1", "1", **kw)


def data(text: str = "hello") -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": text}], "litellm_call_id": "call-1"}


KEY = types.SimpleNamespace(user_id="u-5", team_id="t-1")


def pre(g: SupervisorGuardrail, d: dict, key: Any = KEY) -> dict:
    return asyncio.run(g.async_pre_call_hook(key, None, d, "completion"))


def test_pre_call_allows_and_sends_messages_consumer_and_session() -> None:
    gate = FakeGate(ALLOW)
    out = pre(guard(gate), data())
    call = gate.calls[0]
    assert out["messages"][0]["content"] == "hello"
    assert call["tool_name"] == "llm_request" and call["args"]["messages"][0]["content"] == "hello"
    assert call["context"]["consumer_id"] == "u-5" and call["context"]["session_id"] == "call-1"
    assert out["metadata"]["supervisor_correlation_id"] == call["correlation_id"]


def test_pre_call_block_and_pause_raise_typed_exceptions() -> None:
    with pytest.raises(SupervisorBlocked):
        pre(guard(FakeGate(BLOCK)), data())
    with pytest.raises(SupervisorPaused):
        pre(guard(FakeGate(PAUSE)), data())
    with pytest.raises(SupervisorBlocked):
        pre(guard(DownGate()), data())


def test_pre_call_masked_messages_replace_the_request() -> None:
    masked = [{"role": "user", "content": "<PERSON>"}]
    out = pre(guard(FakeGate(transform(args={"messages": masked}))), data("Nguyen Van A"))
    assert out["messages"] == masked


def test_pre_call_without_messages_is_left_alone_and_consumer_falls_back() -> None:
    gate = FakeGate(ALLOW)
    assert pre(guard(gate), {"input": ["x"]}) == {"input": ["x"]} and gate.calls == []
    pre(guard(gate), data(), key=types.SimpleNamespace(user_id="bad id\n", team_id="t-2"))
    assert gate.calls[0]["context"]["consumer_id"] == "t-2"
    pre(guard(gate), data(), key={"user_id": "dict-user"})
    assert gate.calls[1]["context"]["consumer_id"] == "dict-user"


def test_post_call_checks_the_answer_text_and_can_mask_or_block() -> None:
    resp = types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="the answer"))]
    )
    gate = FakeGate(ALLOW)
    g = guard(gate)
    d = pre(g, data())
    out = asyncio.run(g.async_post_call_success_hook(d, KEY, resp))
    assert out is resp and gate.calls[1]["direction"] == "output"
    assert gate.calls[1]["context"]["output"] == "the answer"
    assert gate.calls[1]["correlation_id"] == gate.calls[0]["correlation_id"]
    mg = guard(
        FakeGate(lambda c: transform(output="MASKED") if c["direction"] == "output" else ALLOW)
    )
    asyncio.run(mg.async_post_call_success_hook(data(), KEY, resp))
    assert resp.choices[0].message.content == "MASKED"
    with pytest.raises(SupervisorBlocked):
        asyncio.run(guard(FakeGate(BLOCK)).async_post_call_success_hook(data(), KEY, resp))


def test_post_call_handles_dict_responses_and_empty_ones() -> None:
    resp = {"choices": [{"message": {"content": "x"}}]}
    g = guard(FakeGate(lambda c: transform(output="Y") if c["direction"] == "output" else ALLOW))
    asyncio.run(g.async_post_call_success_hook(data(), KEY, resp))
    assert resp["choices"][0]["message"]["content"] == "Y"
    gate = FakeGate(ALLOW)
    assert asyncio.run(guard(gate).async_post_call_success_hook(data(), KEY, {})) == {}
    assert gate.calls == []
    assert asyncio.run(
        guard(gate, check_output=False).async_post_call_success_hook(data(), KEY, resp)
    )


def test_build_guardrail_makes_a_subclass_of_the_framework_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CustomGuardrail:
        def __init__(self, guardrail_name: str, event_hook: list[str]) -> None:
            self.guardrail_name, self.event_hook = guardrail_name, event_hook

    chain = ["litellm", "litellm.integrations", "litellm.integrations.custom_guardrail"]
    mods = {n: types.ModuleType(n) for n in chain}
    mods[chain[-1]].CustomGuardrail = CustomGuardrail  # type: ignore[attr-defined]
    for n, m in mods.items():
        monkeypatch.setitem(sys.modules, n, m)
    built = build_litellm_guardrail(FakeGate(ALLOW), "agent-1", guardrail_name="sup")
    assert isinstance(built, CustomGuardrail) and built.guardrail_name == "sup"
    out = asyncio.run(built.async_pre_call_hook(KEY, None, data(), "completion"))
    assert out["messages"]


def test_build_guardrail_without_litellm_says_so() -> None:
    with pytest.raises(ImportError):
        build_litellm_guardrail(FakeGate(), "agent-1")


# --------------------------------------------------------------------------- Claude Code hook

ENV = {
    "SUPERVISOR_URL": "http://x",
    "SUPERVISOR_AGENT_ID": "dev-agent",
    "SUPERVISOR_CONSUMER_ID": "me",
}


def event(**kw: Any) -> str:
    base = {
        "session_id": "s1",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }
    return json.dumps({**base, **kw})


def run_hook(text: str, gate: Any, env: dict | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = hook.run(text, env if env is not None else ENV, gate, out, err)
    return code, out.getvalue(), err.getvalue()


def test_hook_allows_with_exit_zero_and_sends_the_event() -> None:
    gate = FakeGate(ALLOW)
    code, out, err = run_hook(event(), gate)
    assert (code, out, err) == (0, "", "")
    call = gate.calls[0]
    assert call["tool_name"] == "Bash" and call["args"] == {"command": "ls"}
    assert call["context"]["consumer_id"] == "me" and call["context"]["session_id"] == "s1"


def test_hook_exits_two_on_block_and_pause_with_an_ascii_one_line_message() -> None:
    bad = {**BLOCK, "reason": "no được\nsecond line \x1b[31m"}
    code, out, err = run_hook(event(), FakeGate(bad))
    assert code == 2 and out == "" and err.startswith("[BLOCK] supervisor: blocked by PAY-06")
    assert err.isascii() and err.count("\n") == 1 and "\x1b" not in err
    code, _, err = run_hook(event(), FakeGate(PAUSE))
    assert code == 2 and "paused by PAY-07" in err


def test_hook_is_closed_when_the_gate_is_down_and_open_only_if_asked() -> None:
    assert run_hook(event(), DownGate())[0] == 2
    assert run_hook(event(), DownGate(), {**ENV, "SUPERVISOR_FAIL_MODE": "open"})[0] == 0
    assert run_hook(event(), DownGate(), {**ENV, "SUPERVISOR_FAIL_MODE": "bogus"})[0] == 2


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[]", "42", '{"tool_name": 5, "tool_input": {}}', event(tool_input="rm")],
)
def test_hook_refuses_an_event_it_cannot_read(text: str) -> None:
    gate = FakeGate(ALLOW)
    assert run_hook(text, gate)[0] == 2 and gate.calls == []


def test_hook_ignores_other_events_and_refuses_a_huge_one() -> None:
    gate = FakeGate(ALLOW)
    assert run_hook(event(hook_event_name="PostToolUse"), gate)[0] == 0 and gate.calls == []
    huge = event(tool_input={"command": "x" * (hook.MAX_EVENT_BYTES + 10)})
    assert run_hook(huge, gate)[0] == 2 and gate.calls == []


def test_hook_without_settings_is_closed() -> None:
    code, _, err = run_hook(event(), None, {})
    assert code == 2 and "not set" in err


def test_hook_prints_updated_input_for_a_transform() -> None:
    code, out, _ = run_hook(event(), FakeGate(transform(args={"command": "echo <X>"})))
    body = json.loads(out)["hookSpecificOutput"]
    assert code == 0 and body["updatedInput"] == {"command": "echo <X>"}


def test_hook_mcp_tool_names_get_the_mcp_protocol() -> None:
    gate = FakeGate(ALLOW)
    run_hook(event(tool_name="mcp__files__read"), gate)
    assert gate.calls[0]["context"]["protocol"] == "mcp"


def test_hook_main_help_and_module_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert hook.main(["--help"]) == 0
    assert "PreToolUse" in capsys.readouterr().out


def test_hook_builds_an_http_gate_from_the_environment() -> None:
    assert hook.build_gate({}) is None
    gate = hook.build_gate({"SUPERVISOR_URL": "http://127.0.0.1:1", "SUPERVISOR_AGENT_ID": "a"})
    assert isinstance(gate, HttpGate) and gate.base_url == "http://127.0.0.1:1"


# --------------------------------------------------------------------------- SDK additions


def test_http_gate_sends_direction_only_when_output_and_the_header_when_given() -> None:
    sent: list[tuple[str, dict]] = []
    signed: list[tuple[bytes, dict]] = []

    def transport(url: str, payload: dict, timeout: float) -> dict:
        sent.append((url, payload))
        return {"allow": True, "action": "allow"}

    def signed_transport(url: str, body: bytes, headers: dict, timeout: float) -> dict:
        signed.append((body, dict(headers)))
        return {"allow": True, "action": "allow"}

    gate = HttpGate("http://s", transport=transport, signed_transport=signed_transport)
    gate.check("a", "1", "t", {"x": 1}, {})
    assert "direction" not in sent[0][1] and not signed  # the old call is unchanged
    gate.check_v2("a", "1", "t", {}, {"output": "x"}, direction="output", correlation_id="cid-1")
    body, headers = signed[0]
    assert json.loads(body)["direction"] == "output"
    assert headers["X-Supervisor-Correlation-Id"] == "cid-1"
    assert headers["Content-Type"] == "application/json"


def test_http_gate_header_constant_matches_the_server() -> None:
    from supervisor.gateway.detector_gate import CORRELATION_HEADER
    from supervisor.gateway.sdk import CORRELATION_HEADER as SDK_HEADER

    assert SDK_HEADER == CORRELATION_HEADER


def test_in_process_gate_forwards_direction_and_refuses_output_without_detectors() -> None:
    class GW:
        detectors_on = False

        def __init__(self) -> None:
            self.kw: dict = {}

        def check(self, *a: Any, **kw: Any) -> dict:
            self.kw = kw
            return {"allow": True, "action": "allow"}

    gw = GW()
    g = InProcessGate(gw)
    assert g.check("a", "1", "t", {}, None)["allow"] is True and gw.kw == {}
    assert g.check_v2("a", "1", "t", {}, {"output": "x"}, direction="output")["allow"] is False
    gw.detectors_on = True
    assert g.check_v2("a", "1", "t", {}, {"output": "x"}, direction="output")["allow"] is True
    assert gw.kw == {"direction": "output", "correlation_id": None}
