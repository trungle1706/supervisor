"""WP26 review (Opus): ingress binding and trust-on-first-use on the /v1/mcp/tools routes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.agent_creds import AgentKey, FileKeyStore
from supervisor.config import load_settings
from supervisor.gateway import ingress_auth
from supervisor.gateway.ingress_sign import IngressCredential
from tests.fixtures.mcp_http.fake_server import tool

SERVER = "bank-mcp.example_mcp"
TOOLS = [tool("get_balance", "Returns the balance.", {"account_id": {"type": "string"}})]
KEY_PAY, KEY_OTHER = "p" * 48, "o" * 48


@pytest.fixture
def mcp(console: Any) -> Any:
    console.ctx.settings.mcp_http_enabled = True
    return console


@pytest.fixture
def signed_mcp(mcp: Any, tmp_path: Path) -> Iterator[Any]:
    keys = tmp_path / "agent_keys.yaml"
    FileKeyStore(keys).write_all(
        {"payments": [AgentKey("k1", KEY_PAY)], "other_agent": [AgentKey("k2", KEY_OTHER)]}
    )
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "d",
        ingress_auth_enabled=True,
        ingress_keys_file=keys,
    )
    ingress_auth.set_guard(ingress_auth.build_guard(settings))
    try:
        yield mcp
    finally:
        ingress_auth.set_guard(None)


def _post(console: Any, path: str, body: dict[str, Any], agent: str, secret: str) -> Any:
    raw = json.dumps(body).encode()
    h = IngressCredential(agent, secret).headers_for("POST", path, raw)
    h["content-type"] = "application/json"
    return console.client.post(path, content=raw, headers=h)


def _observe_body(**extra: Any) -> dict[str, Any]:
    return {"agent_id": "payments", "server_id": SERVER, "tools": TOOLS, **extra}


def test_observe_and_blocked_bind_the_agent_id_to_the_credential(signed_mcp: Any) -> None:
    ok = _post(signed_mcp, "/v1/mcp/tools/observe", _observe_body(), "payments", KEY_PAY)
    assert ok.status_code == 200, ok.text
    # another agent's valid key may not speak for payments
    r = _post(signed_mcp, "/v1/mcp/tools/observe", _observe_body(), "other_agent", KEY_OTHER)
    assert r.status_code == 403
    blocked = {"agent_id": "payments", "server_id": SERVER, "tool": "t", "rule_id": "X"}
    r = _post(signed_mcp, "/v1/mcp/tools/blocked", blocked, "other_agent", KEY_OTHER)
    assert r.status_code == 403
    assert _post(signed_mcp, "/v1/mcp/tools/blocked", blocked, "payments", KEY_PAY).status_code == (
        200
    )


def test_a_signed_request_cannot_be_replayed(signed_mcp: Any) -> None:
    raw = json.dumps(_observe_body()).encode()
    h = IngressCredential("payments", KEY_PAY).headers_for("POST", "/v1/mcp/tools/observe", raw)
    h["content-type"] = "application/json"
    assert signed_mcp.client.post("/v1/mcp/tools/observe", content=raw, headers=h).status_code == (
        200
    )
    again = signed_mcp.client.post("/v1/mcp/tools/observe", content=raw, headers=h)
    assert again.status_code == 401


def test_f3_trust_on_first_use_over_the_ingress_is_off_by_default(mcp: Any) -> None:
    assert mcp.ctx.settings.mcp_tofu_ingress is False
    body = _observe_body(trust_on_first_use_by="alice")
    r = mcp.client.post("/v1/mcp/tools/observe", json=body)
    assert r.status_code == 400 and "MCP_TOFU_INGRESS" in r.json()["error"]
    assert mcp.get("/v1/mcp/tools").json()["servers"] == []  # nothing was seeded


def test_f3_trust_on_first_use_records_who_sent_it_when_allowed(signed_mcp: Any) -> None:
    signed_mcp.ctx.settings.mcp_tofu_ingress = True
    body = _observe_body(trust_on_first_use_by="alice")
    r = _post(signed_mcp, "/v1/mcp/tools/observe", body, "payments", KEY_PAY)
    assert r.status_code == 200 and r.json()["visible"] == ["get_balance"]
    chain = signed_mcp.runtime.adapters.tables.query("chain_entry", {})
    seeded = [e for e in chain if e["record_type"] == "mcp_manifest_seeded"]
    assert len(seeded) == 1
    tables = signed_mcp.runtime.adapters.tables
    rows = tables.query("chain_payload", {"payload_hash": seeded[0]["payload_hash"]})
    payload = rows[0]["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert payload["seeded_by"] == "alice" and payload["via"] == "ingress:hmac:payments"
