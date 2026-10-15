"""WP18: OpenAPI document (tags, security schemes, /v1/gate twins) and /v1/gate behaviour."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supervisor.app import app
from supervisor.gateway import wiring
from supervisor.gateway.engine import Gateway
from tests.gateway.conftest import (  # noqa: F401 - fixtures
    adapters,
    baseline,
    clock,
    evidence,
    gateway,
)

METHODS = {"get", "put", "post", "delete", "patch"}


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    r = TestClient(app).get("/openapi.json")
    assert r.status_code == 200
    return r.json()


def _ops(doc: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path, item in doc["paths"].items():
        if path.startswith("/_"):  # probe routes other tests add to the shared app
            continue
        for method, op in item.items():
            if method in METHODS:
                yield path, method, op


def test_document_is_valid_openapi(doc: dict[str, Any]) -> None:
    assert doc["openapi"].startswith("3.")
    assert doc["info"]["title"] == "Supervisor"
    assert doc["paths"]


def test_every_operation_has_a_declared_tag(doc: dict[str, Any]) -> None:
    declared = {t["name"] for t in doc["tags"]}
    assert declared == {"gate", "traces", "console", "ops"}
    assert all(t["description"] for t in doc["tags"])
    for path, method, op in _ops(doc):
        assert op.get("tags"), (method, path)
        assert set(op["tags"]) <= declared, (method, path, op["tags"])
    assert any(p.startswith("/console") for p in doc["paths"])


def test_security_schemes(doc: dict[str, Any]) -> None:
    schemes = doc["components"]["securitySchemes"]
    assert schemes["devHeader"]["name"] == "X-Dev-User"
    assert schemes["databricksSSO"]["name"] == "X-Forwarded-Email"
    assert all(s["type"] == "apiKey" and s["in"] == "header" for s in schemes.values())
    pause = doc["paths"]["/v1/gate/pause"]["post"]
    assert {"devHeader": []} in pause["security"]
    assert doc["paths"]["/v1/gate/check"]["post"]["security"] == []
    assert doc["paths"]["/v1/traces"]["post"]["security"] == []
    assert "Agent ingress" in doc["paths"]["/v1/gate/check"]["post"]["description"]


def test_every_gate_path_has_a_v1_twin_and_old_ones_are_deprecated(doc: dict[str, Any]) -> None:
    old = [p for p in doc["paths"] if p.startswith("/gate/")]
    assert old
    for p in old:
        twin = "/v1" + p
        assert twin in doc["paths"], twin
        for method, op in doc["paths"][p].items():
            if method in METHODS:
                assert op.get("deprecated") is True, (method, p)
                assert not doc["paths"][twin][method].get("deprecated"), (method, twin)
    assert "/v1/traces" in doc["paths"]


def test_openapi_is_cached() -> None:
    assert app.openapi() is app.openapi()


@pytest.fixture
def client(gateway: Gateway) -> Iterator[TestClient]:  # noqa: F811
    wiring.set_gateway(gateway)
    try:
        yield TestClient(app)
    finally:
        wiring.set_gateway(None)


def test_v1_gate_check_behaves_like_gate_check(client: TestClient) -> None:
    body = {
        "agent_id": "payments",
        "agent_version": "1.0",
        "tool_name": "transfer",
        "args": {"from_account_id": "ACC-1", "payee_id": "P1", "amount_minor": 1000},
    }
    old = client.post("/gate/check", json=body)
    new = client.post("/v1/gate/check", json=body)
    assert old.status_code == new.status_code == 200
    keys = ("allow", "action", "rule_id", "fail_mode")
    assert {k: old.json()[k] for k in keys} == {k: new.json()[k] for k in keys}
    unknown = {**body, "tool_name": "brand_new_tool"}
    for path in ("/gate/check", "/v1/gate/check"):
        r = client.post(path, json=unknown)
        assert r.status_code == 200 and r.json()["allow"] is False
        assert client.post(path, json={"agent_id": "payments"}).status_code == 400
