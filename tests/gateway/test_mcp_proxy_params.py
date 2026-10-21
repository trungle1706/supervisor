"""WP26 F13: tools/call params are cleaned before the gate, data methods go through the gate."""

from __future__ import annotations

from typing import Any

from supervisor.gateway.mcp_proxy import McpGateProxy, clean_call_params, data_tool_name
from tests.gateway.test_mcp_proxy import FakeUpstream, call


class Gate:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[str, dict[str, Any], Any]] = []

    def check(self, agent_id, agent_version, tool_name, args, context=None):  # type: ignore[no-untyped-def]
        self.calls.append((tool_name, dict(args), context))
        if self.allow:
            return {"allow": True, "action": "allow"}
        return {
            "allow": False,
            "action": "block",
            "rule_id": "TOOL-UNLISTED",
            "reason": "not in policy",
        }


def test_clean_call_params_keeps_name_arguments_and_progress_token() -> None:
    p = {"name": "t", "arguments": {"a": 1}, "_meta": {"progressToken": 7, "x": "y"}, "extra": 1}
    assert clean_call_params(p) == {
        "name": "t",
        "arguments": {"a": 1},
        "_meta": {"progressToken": 7},
    }
    assert clean_call_params({"name": "t", "_meta": {"secret": 1}}) == {"name": "t"}


def test_smuggled_params_never_reach_the_upstream() -> None:
    up, gate = FakeUpstream(), Gate()
    proxy = McpGateProxy(gate, "payments", "1", up)
    msg = call(1, "get_balance", {"account_id": "A"})
    msg["params"]["_meta"] = {"progressToken": "p1", "instructions": "do more"}
    msg["params"]["task"] = {"ttl": 1}
    assert proxy.handle(msg) is not None
    assert up.forwarded[0]["params"] == {
        "name": "get_balance",
        "arguments": {"account_id": "A"},
        "_meta": {"progressToken": "p1"},
    }


def test_data_methods_are_gated_as_tools() -> None:
    for method in (
        "resources/read",
        "resources/templates/list",
        "prompts/get",
        "completion/complete",
    ):
        up, gate = FakeUpstream(), Gate(allow=False)
        proxy = McpGateProxy(gate, "payments", "1", up)
        r = proxy.handle(
            {"jsonrpc": "2.0", "id": 3, "method": method, "params": {"uri": "file:///x"}}
        )
        assert r is not None and r["error"]["data"]["rule_id"] == "TOOL-UNLISTED"
        assert "blocked by supervisor" in r["error"]["message"]
        assert up.forwarded == []
        assert gate.calls[0][0] == data_tool_name(method) == "mcp." + method.replace("/", ".")
        assert gate.calls[0][2]["mcp_method"] == method
        up2, gate2 = FakeUpstream(), Gate(allow=True)
        McpGateProxy(gate2, "payments", "1", up2).handle(
            {"jsonrpc": "2.0", "id": 4, "method": method, "params": {}}
        )
        assert len(up2.forwarded) == 1  # allowed (policy lists it): forwarded unchanged


def test_listing_methods_still_pass_and_real_gate_refuses_unlisted_data_method(
    gateway: Any,
) -> None:
    up = FakeUpstream()
    proxy = McpGateProxy(gateway, "payments", "1.0.0", up)
    assert proxy.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}) is not None
    assert len(up.forwarded) == 1
    r = proxy.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": "x"}}
    )
    assert r is not None and "error" in r and r["error"]["data"]["allow"] is False
    assert len(up.forwarded) == 1  # the real gate did not list mcp.resources.read for payments
    assert proxy.handle({"jsonrpc": "2.0", "method": "prompts/get"}) is None  # notification form
