"""WP37 HTTP contract of POST /v1/gate/check and GET /v1/gate/detectors."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from supervisor.gateway import wiring
from supervisor.gateway.engine import Gateway
from supervisor.gateway.routes import router
from tests.detectors.fingerprint import PII_ARGS

HEADER = "X-Supervisor-Correlation-Id"


def _client(gw: Gateway) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    wiring.set_gateway(gw)
    return TestClient(app)


@pytest.fixture
def on(gw_on: Gateway) -> Iterator[TestClient]:
    try:
        yield _client(gw_on)
    finally:
        wiring.set_gateway(None)


@pytest.fixture
def off(gateway: Gateway) -> Iterator[TestClient]:
    try:
        yield _client(gateway)
    finally:
        wiring.set_gateway(None)


def _post(
    c: TestClient, tool: str, args: dict[str, Any], agent: str = "payments", **kw: Any
) -> Any:
    body = {"agent_id": agent, "agent_version": "1", "tool_name": tool, "args": args, **kw}
    return c.post("/v1/gate/check", json=body)


def test_check_returns_v2_and_echoes_the_correlation_header(on: TestClient) -> None:
    r = on.post(
        "/v1/gate/check",
        json={
            "agent_id": "payments",
            "agent_version": "1",
            "tool_name": "add_payee",
            "args": PII_ARGS,
        },
        headers={HEADER: "corr-abc.1", "X-Request-Id": "req-42"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "transform" and body["correlation_id"] == "corr-abc.1"
    assert r.headers[HEADER] == "corr-abc.1"
    assert body["allow"] is True and body["rule_id"] is None  # the old fields
    assert body["request_id"]  # the request id of the HTTP layer


def test_correlation_id_is_generated_when_the_header_is_missing(on: TestClient) -> None:
    body = _post(on, "get_balance", {}).json()
    assert len(body["correlation_id"]) == 32


@pytest.mark.parametrize("bad", ["x" * 129, "has space", "semi;colon", "slash/x"])
def test_a_malformed_correlation_header_is_a_400(on: TestClient, bad: str) -> None:
    r = on.post(
        "/v1/gate/check",
        json={"agent_id": "payments", "agent_version": "1", "tool_name": "get_balance", "args": {}},
        headers={HEADER: bad},
    )
    assert r.status_code == 400 and HEADER in r.json()["error"]


def test_direction_output_over_http(on: TestClient) -> None:
    r = on.post(
        "/v1/gate/check",
        json={
            "agent_id": "payments",
            "agent_version": "1",
            "tool_name": "get_balance",
            "args": {},
            "context": {"output": "Phone 0912345678"},
            "direction": "output",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["direction"] == "output" and body["status"] == "report"
    assert "0912345678" not in r.text


def test_an_unknown_direction_is_a_400(on: TestClient) -> None:
    r = _post(on, "get_balance", {}, direction="sideways")
    assert r.status_code == 400 and r.json()["error"] == "invalid request"


def test_flag_off_the_answer_is_unchanged_and_output_is_refused(off: TestClient) -> None:
    body = _post(off, "get_balance", {}).json()
    assert not {"status", "findings", "coverage", "correlation_id", "request_id"} & set(body)
    assert HEADER not in _post(off, "get_balance", {}).headers
    r = _post(off, "get_balance", {}, direction="output")
    assert r.status_code == 400 and "DETECTORS_ENABLED" in r.json()["error"]
    assert _post(off, "get_balance", {}, direction="input").status_code == 200
    assert off.get("/v1/gate/detectors").json() == {"enabled": False, "detectors": []}


def test_the_catalogue_endpoint(on: TestClient) -> None:
    body = on.get("/v1/gate/detectors").json()
    assert body["enabled"] is True
    assert [d["slug"] for d in body["detectors"]] == [
        "dlp_vn",
        "injection_regex",
        "injection_classifier",
        "judge_advisory",
        "judge_moderation",  # WP-D4
    ]


def test_a_correlation_header_with_the_flag_off_is_ignored(off: TestClient) -> None:
    r = off.post(
        "/v1/gate/check",
        json={"agent_id": "payments", "agent_version": "1", "tool_name": "get_balance", "args": {}},
        headers={HEADER: "bad value!"},
    )
    assert r.status_code == 200 and "correlation_id" not in r.json()


def test_the_route_calls_a_stub_gateway_with_the_old_signature() -> None:
    """The route only passes the new keywords to a gateway that has detectors on."""
    seen: dict[str, Any] = {}

    class Stub:
        detectors_on = False

        def check(self, agent_id, agent_version, tool_name, args, context=None):  # noqa: ANN001, ANN201
            seen["called"] = True
            return {"allow": True}

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    wiring.set_gateway(Stub())  # type: ignore[arg-type]
    try:
        r = TestClient(app).post(
            "/v1/gate/check",
            json={"agent_id": "a", "agent_version": "1", "tool_name": "t", "args": {}},
        )
        assert r.status_code == 200 and seen["called"]
    finally:
        wiring.set_gateway(None)
