"""WP38 review (Opus): adversarial answers for the four collector adapters. None of these
shapes comes from the harness templates. See REVIEW_WP38.md section 'adversarial cases'."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from supervisor.gateway.adapters.common import GateClient
from supervisor.gateway.sdk import HttpGate, SupervisorBlocked, SupervisorPaused
from tests.collectors.fakes import ALLOW, PAUSE, FakeGate, OldGate
from tests.collectors.test_fastapi_mw import App, build, call
from tests.collectors.test_langgraph import Tool, mw, req
from tests.collectors.test_litellm_and_hook import data, event, guard, pre, run_hook

ALLOW_BUT_BLOCK = {**ALLOW, "status": "block"}  # allow: true next to status block
ALLOW_UNKNOWN_ACTION = {**ALLOW, "action": "report"}  # an action old clients do not know
ALLOW_UNKNOWN_STATUS = {**ALLOW, "status": "quarantine"}
TP_NOT_A_DICT = {**ALLOW, "status": "report", "transformed_payload": "masked"}
OBSERVED = {
    **ALLOW,
    "action": "log",
    "status": "report",
    "mode": "observe",
    "observed_decision": {"allow": False, "action": "block", "rule_id": "PAY-06"},
}
V1_MASKED = {**ALLOW, "transformed_args": {"a": "<PERSON>"}}  # WP24b gate, no v2 status


def _all_refuse(answer: dict[str, Any]) -> None:
    tool = Tool()
    with pytest.raises(SupervisorBlocked):
        mw(FakeGate(answer)).wrap_tool_call(req(), tool)
    assert tool.seen == []
    status, _, _ = call(build(FakeGate(answer))[0])
    assert status == 403
    with pytest.raises(SupervisorBlocked):
        pre(guard(FakeGate(answer)), data())
    code, _, err = run_hook(event(), FakeGate(answer))
    assert code == 2 and err.isascii()


@pytest.mark.parametrize(
    "answer", [ALLOW_BUT_BLOCK, ALLOW_UNKNOWN_ACTION, ALLOW_UNKNOWN_STATUS, TP_NOT_A_DICT]
)
def test_contradicting_or_unknown_answers_fail_closed_in_every_adapter(answer: dict) -> None:
    _all_refuse(answer)


def test_an_observe_answer_passes_in_every_adapter() -> None:
    tool = Tool()
    assert mw(FakeGate(OBSERVED)).wrap_tool_call(req(), tool).content == "done"
    status, _, _ = call(build(FakeGate(OBSERVED))[0])
    assert status == 200
    assert pre(guard(FakeGate(OBSERVED)), data())["messages"][0]["content"] == "hello"
    assert run_hook(event(), FakeGate(OBSERVED))[0] == 0


def test_a_v1_only_masked_answer_is_applied_not_ignored() -> None:
    """An older gate (inline redaction, detectors off) has transformed_args and no status."""
    tool = Tool()
    mw(OldGate(V1_MASKED), check_output=False).wrap_tool_call(
        req(args={"a": "Nguyen Van An"}), tool
    )
    assert tool.seen[0].tool_call["args"] == {"a": "<PERSON>"}
    code, out, _ = run_hook(event(), OldGate(V1_MASKED))
    assert code == 0 and json.loads(out)["hookSpecificOutput"]["updatedInput"] == {"a": "<PERSON>"}


def test_a_pause_on_the_output_check_raises_paused_after_the_tool_ran() -> None:
    gate = FakeGate(lambda c: dict(PAUSE) if c["direction"] == "output" else dict(ALLOW))
    tool = Tool("secret")
    with pytest.raises(SupervisorPaused):
        mw(gate, on_block="message").wrap_tool_call(req(), tool)  # a pause is never a message
    assert len(tool.seen) == 1


def test_apply_transform_off_cannot_skip_masking_on_a_money_tool() -> None:
    masked = {**ALLOW, "status": "transform", "transformed_payload": {"args": {"a": "x"}}}
    gate = FakeGate(lambda c: dict(masked) if c["direction"] == "input" else dict(ALLOW))
    tool = Tool()
    m = mw(gate, apply_transform=False, risk_classes={"transfer": "money"})
    m.wrap_tool_call(req(args={"a": "raw"}), tool)
    assert tool.seen[0].tool_call["args"] == {"a": "x"}  # applied, not skipped


def test_litellm_transform_without_messages_is_a_block() -> None:
    gate = FakeGate({**ALLOW, "status": "transform", "transformed_payload": {"args": {"x": 1}}})
    with pytest.raises(SupervisorBlocked) as e:
        pre(guard(gate), data())
    assert e.value.decision["rule_id"] == "SDK-TRANSFORM-UNAPPLIED"


def test_asgi_transform_without_body_or_text_is_a_block() -> None:
    gate = FakeGate({**ALLOW, "status": "transform", "transformed_payload": {"args": {"x": 1}}})
    mw_, app = build(gate, check_output=False)
    status, _, out = call(mw_)
    assert status == 403 and app.bodies == [] and b"SDK-TRANSFORM-UNAPPLIED" in out


def test_asgi_open_mode_never_sends_a_cut_response() -> None:
    app = App(reply=b'{"x": "' + b"a" * 4000 + b'"}')
    app.chunks = 8
    mw_, _ = build(FakeGate(ALLOW), app, fail_mode="open", max_response_bytes=1000)
    status, _, out = call(mw_)
    assert status == 502 and b"aaaa" not in out


def test_zero_width_and_newline_consumer_ids_are_dropped_before_the_wire() -> None:
    gate = FakeGate(ALLOW)
    client = GateClient(gate, "agent-1")
    for bad in ("pi​lot", "pilot\r\nX-Evil: 1", "pіlot", "x" * 129):
        client.check("t", {}, consumer_id=bad, session_id=bad)
    assert all("consumer_id" not in c["context"] for c in gate.calls)
    assert all("session_id" not in c["context"] for c in gate.calls)


def test_http_gate_keeps_a_custom_transport_when_a_correlation_id_is_sent() -> None:
    seen: list[str] = []

    def transport(url: str, payload: dict, timeout: float) -> dict:
        seen.append(url)
        return dict(ALLOW)

    gate = HttpGate("http://s", transport=transport)
    out = gate.check_v2("a", "1", "t", {}, {}, correlation_id="c-1")
    assert out["allow"] is True and seen == ["http://s/v1/gate/check"]


def test_asgi_input_pause_is_503_and_names_no_secret() -> None:
    status, headers, out = call(build(FakeGate(PAUSE))[0])
    assert status == 503 and json.loads(out)["error"] == "paused"
    assert "authorization" not in {k.lower() for k in headers}


def test_async_langgraph_path_refuses_a_contradiction_too() -> None:
    tool = Tool()
    with pytest.raises(SupervisorBlocked):
        asyncio.run(mw(FakeGate(ALLOW_BUT_BLOCK)).awrap_tool_call(req(), tool.acall))
    assert tool.seen == []


def test_hook_gate_uses_the_standard_library_transport() -> None:
    from supervisor.gateway.adapters import claude_code_hook as hook

    gate = hook.build_gate({"SUPERVISOR_URL": "http://127.0.0.1:9", "SUPERVISOR_AGENT_ID": "a-1"})
    assert gate is not None
    assert gate.transport is hook._post_json_stdlib  # type: ignore[attr-defined]
    assert gate.signed_transport is hook._post_stdlib  # type: ignore[attr-defined]
    with pytest.raises(ValueError):
        hook._post_stdlib("file:///etc/passwd", b"{}", {}, 1.0)


def test_hook_stdlib_transport_401_is_gate_auth_and_unreachable_exits_2() -> None:
    from supervisor.gateway.adapters import claude_code_hook as hook

    def refused(url: str, body: bytes, headers: Any, timeout: float) -> dict:
        raise hook._HttpStatusError(401)

    gate = HttpGate("http://s", signed_transport=refused)
    assert gate.check_v2("a", "1", "t", {}, {}, correlation_id="c")["rule_id"] == "GATE-AUTH"
    env = {"SUPERVISOR_URL": "http://127.0.0.1:9", "SUPERVISOR_AGENT_ID": "a-1"}
    code, _, err = run_hook(event(), None, env)
    assert code == 2 and err.isascii()
