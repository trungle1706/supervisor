"""HTTP routes of the gateway (/gate/*)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from supervisor.gateway import wiring
from supervisor.gateway.engine import Gateway
from supervisor.gateway.routes import router


@pytest.fixture
def client(gateway: Gateway) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    wiring.set_gateway(gateway)
    try:
        yield TestClient(app)
    finally:
        wiring.set_gateway(None)


def _check(client: TestClient, agent: str, tool: str, args: dict[str, Any] | None = None) -> Any:
    return client.post(
        "/gate/check",
        json={"agent_id": agent, "agent_version": "1", "tool_name": tool, "args": args or {}},
    )


def _ctl(client: TestClient, verb: str, agent: str, principal: str | None, **kw: Any) -> Any:
    body = {"agent_id": agent, "reason": "test reason"}
    if principal:
        body["principal"] = principal
    return client.post(f"/gate/{verb}", json=body, **kw)


def test_check_allows_read_and_blocks_unapproved_tool(client: TestClient) -> None:
    r = _check(client, "customer_service", "get_ticket", {"ticket_id": "T1"})
    assert r.status_code == 200
    assert r.json()["allow"] is True
    r = _check(client, "customer_service", "ext_transfer_api", {"amount_minor": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["allow"] is False
    assert body["rule_id"] == "SVC-07"
    assert body["action"] == "pause"


def test_pause_then_money_denied_read_allowed(client: TestClient) -> None:
    r = _ctl(client, "pause", "payments", "owner.payments")
    assert r.status_code == 200 and r.json()["state"] == "PAUSED"
    d = _check(client, "payments", "internal_transfer", {"amount_minor": 1}).json()
    assert d["allow"] is False and d["reason"] == "agent paused"
    assert _check(client, "payments", "get_account_balance", {}).json()["allow"] is True


def test_resume_needs_two_people(client: TestClient) -> None:
    _ctl(client, "pause", "payments", "owner.payments")
    r = _ctl(client, "resume", "payments", "owner.payments")
    assert r.status_code == 200 and r.json()["status"] == "pending"
    r = _ctl(client, "resume", "payments", "owner.payments")
    assert r.status_code == 400 and "error" in r.json()
    r = _ctl(client, "resume", "payments", "reviewer.an")
    assert r.status_code == 200 and r.json()["status"] == "resumed"
    assert client.get("/gate/agents/payments/state").json()["state"] == "RUNNING"


def test_forwarded_user_overrides_body_principal(client: TestClient) -> None:
    _ctl(client, "pause", "payments", "owner.payments")
    r = _ctl(client, "resume", "payments", "nobody", headers={"X-Forwarded-User": "owner.payments"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    state = client.get("/gate/agents/payments/state").json()
    assert state["pending_resume"][0]["principal"] == "owner.payments"


def test_missing_principal_and_bad_body_are_400(client: TestClient) -> None:
    assert _ctl(client, "pause", "payments", None).status_code == 400
    assert client.post("/gate/check", json={"agent_id": "payments"}).status_code == 400
    assert client.post("/gate/check", content=b"not json").status_code == 400
    extra = {"agent_id": "a", "agent_version": "1", "tool_name": "t", "args": {}, "x": 1}
    assert client.post("/gate/check", json=extra).status_code == 400


def test_unknown_agent_is_400(client: TestClient) -> None:
    r = _ctl(client, "pause", "ghost", "owner.payments")
    assert r.status_code == 400 and "error" in r.json()
    assert client.get("/gate/agents/ghost/state").status_code == 400


def test_quarantine_release_needs_admin(client: TestClient) -> None:
    r = _ctl(client, "quarantine", "payments", "reviewer.an")
    assert r.status_code == 200 and r.json()["state"] == "QUARANTINED"
    assert _ctl(client, "release", "payments", "reviewer.an").status_code == 400
    r = _ctl(client, "release", "payments", "admin.chi")
    assert r.status_code == 200 and r.json()["state"] == "PAUSED"


def test_state_and_metrics(client: TestClient) -> None:
    _check(client, "payments", "get_account_balance", {})
    s = client.get("/gate/agents/payments/state").json()
    assert s["agent_id"] == "payments" and s["state"] == "RUNNING"
    m = client.get("/gate/metrics").json()
    lat = m["latency_us"]
    for key in ("p50", "p95", "p99"):
        assert isinstance(lat[key], int) and not isinstance(lat[key], bool)


def test_router_mounted_in_app(gateway: Gateway) -> None:
    from supervisor.app import app

    wiring.set_gateway(gateway)
    try:
        c = TestClient(app)
        assert _check(c, "payments", "get_account_balance", {}).json()["allow"] is True
        assert c.post("/gate/check", json={}).status_code == 400
    finally:
        wiring.set_gateway(None)
