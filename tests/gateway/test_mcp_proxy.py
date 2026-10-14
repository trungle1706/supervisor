"""MCP proxy: gate before forward, tool error on deny, stdio transport."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from supervisor import sandbox
from supervisor.gateway.mcp_proxy import McpGateProxy, StdioUpstream, run_stdio


class FakeUpstream:
    def __init__(self) -> None:
        self.forwarded: list[dict[str, Any]] = []

    def request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        self.forwarded.append(message)
        if "id" not in message:
            return None
        if message["method"] == "tools/list":
            return {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": []}}
        return {
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }

    def close(self) -> None:
        pass


def call(id_: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }


def test_allowed_call_is_forwarded(gateway: Any) -> None:
    up = FakeUpstream()
    proxy = McpGateProxy(gateway, "payments", "1.0.0", up)
    msg = call(1, "get_balance", {"account_id": "A-1"})
    resp = proxy.handle(msg)
    assert up.forwarded == [msg]
    assert resp is not None and resp["result"]["content"][0]["text"] == "ok"


def test_blocked_call_not_forwarded(gateway: Any) -> None:
    up = FakeUpstream()
    proxy = McpGateProxy(gateway, "payments", "1.0.0", up)
    args = {"payee": "UNKNOWN-PAYEE", "amount_vnd": 5_000_000, "account_id": "A-1"}
    resp = proxy.handle(call(7, "ext_transfer_api", args))
    assert up.forwarded == []
    assert resp is not None and resp["id"] == 7
    assert resp["result"]["isError"] is True
    sup = resp["result"]["_meta"]["supervisor"]
    assert sup["allow"] is False
    assert "PAY-07" in resp["result"]["content"][0]["text"]
    assert sup["rule_id"] == "PAY-07" and sup["action"] == "pause"


def test_other_methods_forwarded_and_notification(gateway: Any) -> None:
    up = FakeUpstream()
    proxy = McpGateProxy(gateway, "payments", "1.0.0", up)
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    lst = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert proxy.handle(init) is not None
    assert proxy.handle(lst) == {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}
    assert proxy.handle(note) is None
    assert up.forwarded == [init, lst, note]


def test_malformed_input(gateway: Any) -> None:
    up = FakeUpstream()
    proxy = McpGateProxy(gateway, "payments", "1.0.0", up)
    out = io.StringIO()
    run_stdio(proxy, io.StringIO("{not json\n[1]\n"), out)
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["error"]["code"] == -32600
    assert up.forwarded == []


class RaisingGate:
    def check(self, *a: Any, **k: Any) -> dict[str, Any]:
        raise RuntimeError("boom")


def test_gate_exception_fails_closed() -> None:
    up = FakeUpstream()
    proxy = McpGateProxy(RaisingGate(), "payments", "1.0.0", up)  # type: ignore[arg-type]
    resp = proxy.handle(call(3, "get_balance", {}))
    assert up.forwarded == []
    assert resp is not None and resp["result"]["isError"] is True


FAKE_SERVER = """
import json, sys
for line in sys.stdin:
    m = json.loads(line)
    if "id" in m:
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"],
                          "result": {"echo": m["method"]}}), flush=True)
"""


def test_stdio_upstream_round_trip(gateway: Any, tmp_path: Path) -> None:
    script = tmp_path / "fake_mcp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    up = StdioUpstream([sandbox.python_executable(), str(script)], cwd=str(tmp_path), timeout_s=10)
    try:
        proxy = McpGateProxy(gateway, "payments", "1.0.0", up)
        resp = proxy.handle(call(5, "get_balance", {"account_id": "A-1"}))
        assert resp == {"jsonrpc": "2.0", "id": 5, "result": {"echo": "tools/call"}}
        assert up._proc.running()
    finally:
        up.close()
    assert not up._proc.running()
