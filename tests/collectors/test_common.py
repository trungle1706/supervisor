"""GateClient: id cleaning, size cap, fail mode, verdicts (WP38)."""

from __future__ import annotations

import pytest

from supervisor.gateway.adapters.common import (
    GateClient,
    clean_id,
    safe_tool_name,
    text_of,
)
from supervisor.gateway.sdk import SupervisorBlocked, SupervisorPaused
from tests.collectors.fakes import (
    ALLOW,
    BLOCK,
    PAUSE,
    DownGate,
    FakeGate,
    OldGate,
    RaisingGate,
    transform,
)


def client(gate, **kw):  # type: ignore[no-untyped-def]
    return GateClient(gate, "agent-1", "1", **kw)


def test_fail_mode_is_closed_by_default_and_validated() -> None:
    assert client(FakeGate()).fail_mode == "closed"
    with pytest.raises(ValueError):
        client(FakeGate(), fail_mode="maybe")
    with pytest.raises(ValueError):
        GateClient(FakeGate(), "bad id!", "1")


@pytest.mark.parametrize("value", ["a\nb", "a b", "x" * 129, "café", "", 5, None, ["a"]])
def test_clean_id_rejects_what_is_not_a_plain_id(value: object) -> None:
    assert clean_id(value) is None


def test_clean_id_accepts_the_documented_charset() -> None:
    assert clean_id("user:42@bank.vn_x-1") == "user:42@bank.vn_x-1"


def test_safe_tool_name_keeps_valid_names_and_maps_others_stably() -> None:
    assert safe_tool_name("transfer") == "transfer"
    a, b = safe_tool_name("chuyển tiền"), safe_tool_name("chuyển tiềm")
    assert a != b and a == safe_tool_name("chuyển tiền")
    assert clean_id(a) and clean_id(b) and clean_id(safe_tool_name("转账"))
    assert clean_id(safe_tool_name("../etc/passwd")) and clean_id(safe_tool_name(""))
    assert clean_id(safe_tool_name("x" * 500))


def test_text_of_reads_strings_and_blocks() -> None:
    assert text_of("hi") == "hi"
    assert text_of([{"type": "text", "text": "a"}, {"type": "image"}, "b"]) == "a\nb"
    assert text_of(5) == "" and text_of(None) == ""


def test_the_call_carries_direction_correlation_and_clean_ids() -> None:
    gate = FakeGate()
    c = client(gate, risk_classes={"pay": "money"})
    ans = c.check("pay", {"x": 1}, consumer_id="u-1", session_id="s-1", correlation_id="cid-1")
    call = gate.calls[0]
    assert call["direction"] == "input" and call["correlation_id"] == "cid-1"
    assert call["context"] == {
        "declared_risk_class": "money",
        "consumer_id": "u-1",
        "session_id": "s-1",
    }
    assert ans.correlation_id == "cid-1" and ans.status == "allow"


def test_a_bad_correlation_id_is_replaced_and_a_bad_consumer_is_dropped() -> None:
    gate = FakeGate()
    c = client(gate)
    c.check("t", {}, correlation_id="a\r\nX-Evil: 1", consumer_id="a\nb", session_id="s s")
    call = gate.calls[0]
    assert "\n" not in call["correlation_id"] and clean_id(call["correlation_id"])
    assert "consumer_id" not in call["context"] and "session_id" not in call["context"]


def test_an_old_gate_without_v2_still_works_for_input_and_fails_closed_for_output() -> None:
    gate = OldGate()
    c = client(gate)
    assert c.check("t", {"a": 1}).allow is True and gate.calls
    out = c.check("t", {}, direction="output", context={"output": "x"})
    assert out.allow is False and out.rule_id == "GATE-DIRECTION"


def test_oversize_payload_is_not_sent_and_closed_blocks() -> None:
    gate = FakeGate()
    c = client(gate, max_payload_bytes=100)
    ans = c.check("t", {"blob": "x" * 500})
    assert gate.calls == [] and ans.allow is False and ans.rule_id == "SDK-PAYLOAD-TOO-LARGE"


def test_oversize_payload_in_open_mode_on_a_plain_tool_is_a_marked_pass() -> None:
    gate = FakeGate()
    c = client(gate, fail_mode="open", max_payload_bytes=100)
    ans = c.check("t", {"blob": "x" * 500})
    assert ans.allow is True and ans.rule_id == "SDK-UNINSPECTED" and gate.calls == []
    money = client(gate, fail_mode="open", max_payload_bytes=100, risk_classes={"pay": "money"})
    assert money.check("pay", {"blob": "x" * 500}).allow is False


def test_unserialisable_and_deep_payloads_do_not_crash() -> None:
    gate = FakeGate()
    c = client(gate)
    deep: dict = {}
    cur = deep
    for _ in range(5000):
        cur["a"] = {}
        cur = cur["a"]
    assert c.check("t", deep).allow is False
    assert c.check("t", {"x": "\ud800"}).allow in (True, False)  # a lone surrogate: no exception
    assert c.check("t", {"x": object()}).allow in (True, False)


@pytest.mark.parametrize("gate", [RaisingGate(), FakeGate({"allow": "yes"}), FakeGate({})])
def test_a_broken_gate_or_answer_is_closed(gate) -> None:  # type: ignore[no-untyped-def]
    ans = client(gate).check("t", {})
    assert ans.allow is False and ans.rule_id == "GATE-ERROR"
    assert client(gate, fail_mode="open").check("t", {}).allow is True  # plain tool, open mode


def test_unreachable_gate_closed_open_and_money() -> None:
    assert client(DownGate()).check("t", {}).allow is False
    assert client(DownGate(allow=True)).check("t", {}).allow is False  # closed wins
    open_ = client(DownGate(), fail_mode="open")
    assert open_.check("t", {}).allow is True
    money = client(DownGate(), fail_mode="open", risk_classes={"pay": "money"})
    assert money.check("pay", {}).allow is False  # money is always closed


def test_an_auth_refusal_is_never_opened() -> None:
    gate = FakeGate({"allow": False, "action": "block", "rule_id": "GATE-AUTH", "reason": "x"})
    assert client(gate, fail_mode="open").check("t", {}).allow is False


def test_enforce_raises_typed_exceptions() -> None:
    c = client(FakeGate(BLOCK))
    with pytest.raises(SupervisorBlocked) as e:
        c.enforce(c.check("t", {}))
    assert not isinstance(e.value, SupervisorPaused) and e.value.decision["rule_id"] == "PAY-06"
    assert "correlation_id" in e.value.decision
    c2 = client(FakeGate(PAUSE))
    with pytest.raises(SupervisorPaused):
        c2.enforce(c2.check("t", {}))
    c3 = client(FakeGate(ALLOW))
    assert c3.enforce(c3.check("t", {})).allow is True


def test_a_transform_without_values_is_a_block() -> None:
    bad = {"allow": True, "action": "allow", "status": "transform", "transformed_payload": {}}
    c = client(FakeGate(bad))
    with pytest.raises(SupervisorBlocked) as e:
        c.enforce(c.check("t", {}))
    assert e.value.decision["rule_id"] == "SDK-TRANSFORM-UNAPPLIED"
    ok = client(FakeGate(transform(args={"a": "<X>"})))
    assert ok.enforce(ok.check("t", {})).transformed_args == {"a": "<X>"}


def test_status_is_derived_for_an_old_answer() -> None:
    assert client(FakeGate(ALLOW)).check("t", {}).status == "allow"
    assert client(FakeGate({"allow": True, "action": "log"})).check("t", {}).status == "report"
    assert client(FakeGate({"allow": False, "action": "pause"})).check("t", {}).status == "pause"
    assert client(FakeGate({"allow": False, "action": "block"})).check("t", {}).status == "block"
