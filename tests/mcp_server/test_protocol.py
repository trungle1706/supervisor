"""WP-G6 JSON-RPC layer: initialize, ping, tools/list, tools/call, batches, errors. An answer to
a request is HTTP 200 with a result or an error; malformed input is HTTP 400; never a 500."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from supervisor.mcp_server import protocol
from supervisor.mcp_server.server import get_server

from .conftest import Rig


def test_initialize_negotiates_the_version(rig: Rig) -> None:
    cred = rig.new_app()
    for asked, got in (
        ("2025-03-26", "2025-03-26"),
        ("2024-11-05", "2024-11-05"),
        ("1999-01-01", "2025-06-18"),
        (None, "2025-06-18"),
    ):
        params = {"protocolVersion": asked} if asked else {}
        res = rig.rpc(cred, "initialize", params).json()["result"]
        assert res["protocolVersion"] == got
        assert res["capabilities"] == {"tools": {"listChanged": False}}


def test_notifications_get_no_answer(rig: Rig) -> None:
    cred = rig.new_app()
    r = rig.post(cred, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and r.content == b""
    r = rig.post(cred, {"jsonrpc": "2.0", "method": "no/such/thing"})
    assert r.status_code == 202


def test_a_batch_gets_a_batch_of_answers(rig: Rig) -> None:
    cred = rig.new_app()
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": "b", "method": "nope"},
        7,
    ]
    r = rig.post(cred, batch)
    assert r.status_code == 200
    out = r.json()
    assert [o.get("id") for o in out] == [1, "b", None]
    assert out[0]["result"] == {}
    assert out[1]["error"]["code"] == -32601 and out[2]["error"]["code"] == -32600
    only_notes = rig.post(cred, [{"jsonrpc": "2.0", "method": "x"}])
    assert only_notes.status_code == 202


def test_tools_list_gives_schemas(rig: Rig) -> None:
    cred = rig.new_app()
    tools = rig.rpc(cred, "tools/list").json()["result"]["tools"]
    by = {t["name"]: t for t in tools}
    assert len(by) >= 18
    reg = by["register_system"]["inputSchema"]
    assert reg["properties"]["confirm"]["type"] == "boolean" and "draft" in reg["required"]
    assert by["regulations"]["annotations"]["readOnlyHint"] is True
    assert by["register_system"]["annotations"]["readOnlyHint"] is False


@pytest.mark.parametrize(
    "body",
    [
        "null",
        "7",
        '"text"',
        "[]",
        "{}",
        '{"jsonrpc":"1.0","id":1,"method":"ping"}',
        '{"jsonrpc":"2.0","id":1}',
        '{"jsonrpc":"2.0","id":1,"method":5}',
        '{"jsonrpc":"2.0","id":true,"method":"ping"}',
        '{"jsonrpc":"2.0","id":[1],"method":"ping"}',
        '{"jsonrpc":"2.0","id":1,"method":"ping","params":[1]}',
        '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{}}',
        '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":5}}',
        '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"regulations","arguments":[1]}}',
        '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"regulations","arguments":{"x":1}}}',
        '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"obligations","arguments":{"query":5}}}',
        '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"obligations","arguments":{"query":"'
        + "a" * 5000
        + '"}}}',
        '{"jsonrpc":"2.0","id":1,"method":"resources/list"}',
        '{"jsonrpc":"2.0","id":1,"method":"prompts/list"}',
        "[" * 5000,
        '{"a":' * 3000,
        "\xff\xfe",
        "{",
        "",
    ],
)
def test_malformed_input_is_a_400_or_a_json_rpc_error_never_a_500(rig: Rig, body: str) -> None:
    cred = rig.new_app()
    r = rig.post(cred, None, raw=body.encode("utf-8", "surrogateescape"))
    assert r.status_code in (200, 202, 400), (r.status_code, r.text[:200])
    if r.status_code != 202:
        out = r.json()
        for o in out if isinstance(out, list) else [out]:
            assert "error" in o or "result" in o


def test_a_parse_error_is_400_with_a_json_rpc_body(rig: Rig) -> None:
    cred = rig.new_app()
    r = rig.post(cred, None, raw=b"{not json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32700 and r.json()["id"] is None


def test_an_oversized_body_is_413(rig: Rig) -> None:
    cred = rig.new_app()
    r = rig.post(cred, None, raw=b" " * 300_000)
    assert r.status_code == 413 and r.json()["error"]
    big_batch = [{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(60)]
    assert rig.post(cred, big_batch).status_code == 400


def test_get_and_delete_are_not_offered(rig: Rig) -> None:
    cred = rig.new_app()
    for method in ("get", "delete", "put"):
        r = getattr(rig.console.client, method)("/mcp", headers=cred.sign(b""))
        assert r.status_code == 405


def test_a_failing_tool_is_a_json_rpc_error_without_a_trace(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cred = rig.new_app()
    server = get_server()
    tool = server.registry.get("regulations")
    assert tool is not None

    def boom(*a: Any) -> dict[str, Any]:
        raise RuntimeError("secret internal detail /home/x/y.py")

    monkeypatch.setitem(
        server.registry._tools, "regulations", dataclasses.replace(tool, handler=boom)
    )
    r = rig.rpc(cred, "tools/call", {"name": "regulations", "arguments": {}})
    assert r.status_code == 200
    err = r.json()["error"]
    assert err["code"] == -32603 and "RuntimeError" in err["message"]
    assert "secret" not in r.text and "/home" not in r.text and "Traceback" not in r.text


def test_a_store_failure_is_a_message_not_a_500(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from supervisor.core.errors import SqlError

    cred = rig.new_app()

    def down(*a: Any, **k: Any) -> Any:
        raise SqlError("store is down")

    monkeypatch.setattr(rig.ctx.systems, "list_systems", down)
    out = rig.call(cred, "list_entities", {"kind": "system"})
    assert out["error"]["code"] == -32602 and "store is down" in out["error"]["message"]


def test_a_result_that_is_too_large_is_refused(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cred = rig.new_app()
    monkeypatch.setattr(protocol, "MAX_RESULT_CHARS", 100)
    err = rig.err(cred, "regulations")
    assert err["code"] == -32011


def test_an_audit_store_that_fails_stops_the_write(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M4: no ``attempted`` row, no action."""
    from supervisor.adapters.auth import audit

    cred = rig.new_app()
    real = rig.ctx.tables.append

    def failing(table: str, rows: Any) -> int:
        if table == "console_action":
            raise OSError("disk full")
        return real(table, rows)

    monkeypatch.setattr(rig.ctx.tables, "append", failing)
    draft = {
        "name": "Pay assist",
        "owner_team": "Payments Ops",
        "purpose": "x",
        "system_type": "assistant",
        "org_role": "deployer",
        "user_segment": "internal",
        "personal_data": "none",
        "human_control": "post_review",
    }
    err = rig.err(cred, "register_system", {"draft": draft, "confirm": True})
    assert err["code"] == -32010 and "was not done" in err["message"]
    assert rig.ctx.state.query("ai_system") == []
    assert audit.AuditUnavailable


def test_the_roles_and_scopes_of_one_app_do_not_leak_to_another(rig: Rig) -> None:
    a = rig.new_app("alpha", scopes=("library.read",))
    b = rig.new_app("beta", scopes=("governance.read", "library.read"))
    assert rig.err(a, "kpis")["code"] == -32002
    assert "coverage" in rig.ok(b, "kpis")
    assert json.dumps(rig.ok(a, "regulations"))
