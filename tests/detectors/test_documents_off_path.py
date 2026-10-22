"""WP-D1: with DOCUMENT_INTAKE_ENABLED off nothing changes, and context.documents is refused.

The v0.3.0 fingerprint test (test_flag_off_fingerprint.py) proves the gate without detectors is
byte for byte as before. These tests prove the three other off paths of the new feature:

1. detectors off: a request with context.documents is HTTP 400;
2. detectors on, intake off: the same 400, and an answer without documents is the answer it was;
3. intake on, but a call without documents: the answer holds no ``documents`` key and the
   ``document_intake`` detector did not run (the call is answered as before).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from supervisor.config import load_settings
from supervisor.detectors.intake import IntakeService
from supervisor.gateway import wiring
from supervisor.gateway.engine import Gateway
from supervisor.gateway.routes import router
from tests.detectors.conftest import GatewayFactory, make_gate
from tests.detectors.fingerprint import PII_ARGS

DOC = {"name": "a.txt", "media_type": "text/plain", "text": "hello"}


def _client(gw: Gateway) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    wiring.set_gateway(gw)
    return TestClient(app)


def _post(c: TestClient, **extra: Any) -> Any:
    body = {
        "agent_id": "payments",
        "agent_version": "1",
        "tool_name": "get_balance",
        "args": {"account_id": "A-1"},
        **extra,
    }
    return c.post("/v1/gate/check", json=body)


@pytest.fixture
def off(gateway: Gateway) -> Iterator[TestClient]:
    try:
        yield _client(gateway)
    finally:
        wiring.set_gateway(None)


@pytest.fixture
def detectors_only(gw_on: Gateway) -> Iterator[TestClient]:
    try:
        yield _client(gw_on)
    finally:
        wiring.set_gateway(None)


def test_the_flags_default_to_off() -> None:
    s = load_settings()
    assert s.document_intake_enabled is False
    assert s.url_fetch_enabled is False
    assert s.url_fetch_domains == ()


def test_documents_are_refused_with_400_when_detectors_are_off(off: TestClient) -> None:
    r = _post(off, context={"documents": [DOC]})
    assert r.status_code == 400
    assert "DOCUMENT_INTAKE_ENABLED" in r.json()["error"]


def test_documents_are_refused_with_400_when_intake_is_off(detectors_only: TestClient) -> None:
    for value in ([DOC], [], "not a list", None):  # any value, even an empty list
        r = _post(detectors_only, context={"documents": value})
        if value is None:
            assert r.status_code == 200  # an explicit null is the same as no key
        else:
            assert r.status_code == 400, value
            assert "DOCUMENT_INTAKE_ENABLED" in r.json()["error"]


def test_a_call_without_documents_is_answered_as_before(
    detectors_only: TestClient, make_gateway: GatewayFactory, masker: Any
) -> None:
    """Intake off and intake on give the same answer to a call that has no documents."""
    base = _post(detectors_only, context={"trace_id": "t1"}).json()
    gate = make_gate(masker)
    gate.intake = IntakeService()
    on = make_gateway(gate=gate)
    wiring.set_gateway(on)
    try:
        with_intake = _post(_client(on), context={"trace_id": "t1"}).json()
    finally:
        wiring.set_gateway(None)
    for body in (base, with_intake):
        assert "documents" not in body
        assert not any("document_intake" in d for d in body["detectors"])
    drop = {"decision_id", "latency_ms", "latency_us", "total_us", "request_id", "correlation_id"}
    drop |= {"detector_latency_us"}
    assert {k: v for k, v in base.items() if k not in drop} == {
        k: v for k, v in with_intake.items() if k not in drop
    }


def test_in_process_documents_are_ignored_when_intake_is_off(gw_on: Gateway) -> None:
    """The HTTP route and the playground refuse; the in-process gate has no 400, it ignores."""
    res = gw_on.check("payments", "1", "add_payee", dict(PII_ARGS), {"documents": [DOC]})
    assert "documents" not in res
    assert res["coverage"]["inspected"] == ["args"]
    assert gw_on.documents_on is False
