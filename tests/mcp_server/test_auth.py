"""WP-G6 authentication: the WP20 HMAC path, the app table, approval, scopes and audit."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from supervisor.gateway.ingress_sign import H_SIGNATURE, H_TIMESTAMP, IngressCredential

from .conftest import Cred, Rig

ADMIN = {"X-Dev-User": "admin.chi"}


def init(rig: Rig, cred: Cred | None) -> Any:
    return rig.rpc(cred, "initialize", {"protocolVersion": "2025-06-18"})


def test_a_signed_request_of_an_approved_app_works(rig: Rig) -> None:
    cred = rig.new_app()
    r = init(rig, cred)
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-06-18" and res["serverInfo"]["name"] == "supervisor-mcp"
    assert "never classify" in res["instructions"].lower()
    row = rig.apps.get(cred.app_id)
    assert row["first_connected_at"] is not None  # the first connection is remembered


def test_a_pending_app_may_connect_but_gets_no_tools(rig: Rig) -> None:
    cred = rig.new_app(approved=False)
    assert "result" in init(rig, cred).json()
    assert rig.rpc(cred, "ping").json()["result"] == {}
    for method, params in (("tools/list", None), ("tools/call", {"name": "regulations"})):
        out = rig.rpc(cred, method, params).json()
        assert out["error"]["code"] == -32001 and "pending" in out["error"]["message"]


def test_a_blocked_app_is_refused_at_once_and_audited(rig: Rig) -> None:
    cred = rig.new_app()
    rig.apps.block(cred.app_id, "admin.chi")
    r = init(rig, cred)
    assert r.status_code == 403 and "blocked" in r.json()["error"]
    rows = rig.actions(permission="mcp.auth")
    assert rows[-1]["outcome"] == "denied" and rows[-1]["detail"] == "app_blocked"
    assert rows[-1]["actor"] == f"unverified:{cred.app_id}"


@pytest.mark.parametrize("reason", ["no_credential", "bad_signature", "stale", "unknown_app"])
def test_a_bad_credential_is_401_and_audited(rig: Rig, reason: str) -> None:
    cred = rig.new_app()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if reason == "bad_signature":
        headers.update(cred.sign(body))
        headers[H_SIGNATURE] = "v1=" + "0" * 64
    elif reason == "stale":
        old = IngressCredential(cred.app_id, cred.secret, clock=lambda: time.time() - 3600)
        headers.update(old.headers_for("POST", "/mcp", body))
    elif reason == "unknown_app":
        headers.update(Cred("mcp-ghost", "x" * 64).sign(body))
    r = rig.console.client.post("/mcp", content=body, headers=headers)
    assert r.status_code == 401, r.text
    assert r.json()["error"] and r.headers["www-authenticate"]
    last = rig.actions(permission="mcp.auth")[-1]
    assert last["outcome"] == "denied" and last["before_hash"] and last["detail"]
    assert "jsonrpc" not in json.dumps(last, default=str)  # a hash of the body, never the body


def test_the_same_message_for_an_unknown_app_and_a_wrong_secret(rig: Rig) -> None:
    cred = rig.new_app()
    wrong = Cred(cred.app_id, "z" * 64)
    ghost = Cred("mcp-ghost", "z" * 64)
    a = init(rig, wrong)
    b = init(rig, ghost)
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_a_replayed_request_is_refused(rig: Rig) -> None:
    cred = rig.new_app()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
    headers = {"Content-Type": "application/json", **cred.sign(body)}
    assert rig.console.client.post("/mcp", content=body, headers=headers).status_code == 200
    again = rig.console.client.post("/mcp", content=body, headers=headers)
    assert again.status_code == 401 and "nonce" in again.json()["error"]


def test_a_signature_for_another_path_does_not_work(rig: Rig) -> None:
    cred = rig.new_app()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
    headers = {"Content-Type": "application/json", **cred.sign(body, "/v1/traces")}
    assert rig.console.client.post("/mcp", content=body, headers=headers).status_code == 401


def test_a_tampered_body_is_refused(rig: Rig) -> None:
    cred = rig.new_app()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
    headers = {"Content-Type": "application/json", **cred.sign(body)}
    other = body.replace(b"ping", b"pong")
    assert rig.console.client.post("/mcp", content=other, headers=headers).status_code == 401


def test_the_key_of_an_agent_does_not_open_the_server(rig: Rig) -> None:
    """A key in the store for an id that has no app row is not an app."""
    from datetime import UTC, datetime, timedelta

    from supervisor.adapters.auth.agent_creds import rotate_keys

    data = rig.keys.read_all()
    data["payments"] = rotate_keys([], "k" * 64, datetime.now(UTC), timedelta(hours=1))
    rig.keys.write_all(data)
    assert init(rig, Cred("payments", "k" * 64)).status_code == 401


def test_an_old_secret_stops_working_when_the_row_changes_key(rig: Rig) -> None:
    cred = rig.new_app()
    rig.apps.set_key(cred.app_id, "n" * 64)  # the row now hashes another current secret
    assert init(rig, cred).status_code == 401


def test_a_tool_needs_its_scope(rig: Rig) -> None:
    cred = rig.new_app(scopes=("library.read",))
    names = {t["name"] for t in rig.rpc(cred, "tools/list").json()["result"]["tools"]}
    assert "regulations" in names and "list_entities" not in names
    err = rig.err(cred, "list_entities", {"kind": "system"})
    assert err["code"] == -32002 and "governance.read" in err["message"]


def test_a_write_tool_needs_the_scope_and_the_role_and_a_refusal_leaves_a_row(rig: Rig) -> None:
    reader = rig.new_app("reader", scopes=("governance.read",))
    err = rig.err(reader, "register_system", {"draft": {}})
    assert err["code"] == -32002
    viewer = rig.new_app("viewer app", scopes=("governance.write",), roles=("viewer",))
    err = rig.err(viewer, "register_system", {"draft": {}})
    assert err["code"] == -32003 and "viewer" in err["message"]
    rows = [r for r in rig.actions() if r["path"] == "/mcp/tools/register_system"]
    assert [r["outcome"] for r in rows] == ["denied", "denied"]
    assert {r["actor"] for r in rows} == {f"mcp:{reader.app_id}", f"mcp:{viewer.app_id}"}
    assert all(r["actor_kind"] == "service_principal" for r in rows)


def test_admin_approves_through_the_route_and_a_viewer_cannot(rig: Rig) -> None:
    cred = rig.new_app(approved=False)
    c = rig.console.client
    r = c.get("/v1/mcp/apps", headers=ADMIN)
    assert r.status_code == 200 and r.json()["apps"][0]["status"] == "pending"
    assert "key_hash" not in r.text and cred.secret not in r.text
    denied = c.post(f"/v1/mcp/apps/{cred.app_id}/approve", headers={"X-Dev-User": "viewer.hoa"})
    assert denied.status_code == 403
    assert (
        c.post(
            f"/v1/mcp/apps/{cred.app_id}/approve", headers={"X-Dev-User": "reviewer.an"}
        ).status_code
        == 403
    )
    ok = c.post(f"/v1/mcp/apps/{cred.app_id}/approve", headers=ADMIN)
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert ok.json()["approved_by"] == "admin.chi"
    assert "result" in rig.rpc(cred, "tools/list").json()
    rows = [r for r in rig.actions() if r["permission"] == "mcp.apps"]
    assert [r["outcome"] for r in rows if r["target_id"] == cred.app_id][-2:] == ["attempted", "ok"]
    again = c.post(f"/v1/mcp/apps/{cred.app_id}/approve", headers=ADMIN)
    assert again.status_code == 400 and "already" in again.json()["error"]
    blocked = c.post(f"/v1/mcp/apps/{cred.app_id}/block", headers=ADMIN)
    assert blocked.json()["status"] == "blocked"
    assert init(rig, cred).status_code == 403
    assert c.post("/v1/mcp/apps/mcp-ghost/approve", headers=ADMIN).status_code == 404
    assert c.post("/v1/mcp/apps/bad id/block", headers=ADMIN).status_code in (400, 404)


def test_an_app_row_never_holds_admin_or_an_unknown_scope(rig: Rig) -> None:
    from supervisor.mcp_server.apps import McpAppError

    for scopes, roles, text in (
        (("governance.read",), ("admin",), "admin"),
        (("nothing.read",), ("viewer",), "unknown scope"),
        ((), ("viewer",), "at least one scope"),
        (("governance.read",), ("boss",), "unknown role"),
    ):
        with pytest.raises(McpAppError, match=text):
            rig.apps.create("bad app", scopes, roles, "admin.chi", "s" * 64)
    with pytest.raises(McpAppError, match="already exists"):
        rig.new_app("twin")
        rig.new_app("twin")


def test_headers_with_a_timestamp_in_the_future_or_garbage_are_401(rig: Rig) -> None:
    cred = rig.new_app()
    body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
    for bad in ({H_TIMESTAMP: "abc"}, {H_TIMESTAMP: "9" * 20}):
        headers = {"Content-Type": "application/json", **cred.sign(body), **bad}
        assert rig.console.client.post("/mcp", content=body, headers=headers).status_code == 401
