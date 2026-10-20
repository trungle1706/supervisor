"""WP20: ingress auth on POST /v1/traces through the receiver's auth hook.

A batch may only carry spans of the authenticated agent id(s): otherwise HTTP 403, the whole
batch is dropped, the count of foreign spans is in ``X-Supervisor-Rejected`` and one audit row
(hash only) is written.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supervisor.adapters.auth.agent_creds import AgentKey, FileKeyStore
from supervisor.adapters.auth.agent_creds_identity import AgentIdentityMap, FakeIdentityVerifier
from supervisor.adapters.factory import Adapters
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.app import app
from supervisor.gateway import ingress_auth
from supervisor.gateway.ingress_auth import IngressGuard, IngressVerifier
from supervisor.gateway.ingress_sign import IngressCredential
from supervisor.recorder import otlp_receiver
from supervisor.recorder.capture import AgentCapture, CapturePolicy
from supervisor.recorder.normalise import spans_to_otlp_json
from supervisor.recorder.otlp_receiver import recorder_dep
from supervisor.recorder.service import build_recorder
from tests.recorder.conftest import payments_spans

SECRET = "t" * 48


class Rig:
    def __init__(self, client: TestClient, audit: list[dict[str, Any]], adapters: Adapters):
        self.client = client
        self.audit = audit
        self.adapters = adapters
        self.guard: IngressGuard = ingress_auth.get_guard()

    def events(self) -> list[dict[str, Any]]:
        return self.adapters.tables.query("agent_event", {})


@pytest.fixture
def rig(adapters: Adapters, masker: VnRegexMasker, tmp_path: Path, monkeypatch) -> Iterator[Rig]:
    rec = build_recorder(
        adapters.settings,
        adapters.tables,
        masker=masker,
        policy=CapturePolicy({"payments": AgentCapture("masked")}),
    )
    keys = tmp_path / "k.yaml"
    FileKeyStore(keys).write_all(
        {"payments": [AgentKey("k1", SECRET)], "treasury": [AgentKey("k2", "u" * 48)]}
    )
    audit: list[dict[str, Any]] = []
    verifier = IngressVerifier(
        kind="both",
        keys=FileKeyStore(keys),
        identity=FakeIdentityVerifier({"tok-sp": "sp-1", "tok-other": "sp-2"}),
        identities=AgentIdentityMap({"sp-1": frozenset({"payments"}), "sp-2": frozenset({"x"})}),
    )
    guard = IngressGuard(
        enabled=True,
        verifier=verifier,
        audit=audit.append,
        body_cap=lambda _p: 200_000,
    )
    ingress_auth.set_guard(guard)
    app.dependency_overrides[recorder_dep] = lambda: rec
    monkeypatch.setattr(otlp_receiver, "_limits", lambda: (200_000, 50))
    try:
        yield Rig(TestClient(app), audit, adapters)
    finally:
        app.dependency_overrides.pop(recorder_dep, None)
        ingress_auth.set_guard(None)


def batch() -> bytes:
    return json.dumps(spans_to_otlp_json(payments_spans())).encode("utf-8")


def sign(
    body: bytes, agent: str = "payments", secret: str = SECRET, **extra: str
) -> dict[str, str]:
    h = IngressCredential(agent, secret).headers_for("POST", "/v1/traces", body)
    return {"content-type": "application/json", **h, **extra}


def test_signed_batch_for_own_agent_is_stored(rig: Rig) -> None:
    body = batch()
    r = rig.client.post("/v1/traces", content=body, headers=sign(body))
    assert r.status_code == 200 and r.headers["x-supervisor-accepted"] == "7"
    assert len(rig.events()) == 7 and rig.audit == []


def test_signed_gzip_batch(rig: Rig) -> None:
    body = gzip.compress(batch())  # the signature covers the bytes on the wire
    r = rig.client.post(
        "/v1/traces", content=body, headers=sign(body, **{"content-encoding": "gzip"})
    )
    assert r.status_code == 200 and r.headers["x-supervisor-accepted"] == "7"


def test_unsigned_batch_is_401_and_nothing_is_written(rig: Rig) -> None:
    r = rig.client.post("/v1/traces", content=batch(), headers={"content-type": "application/json"})
    assert r.status_code == 401
    assert rig.events() == []
    assert [a["reason"] for a in rig.audit] == ["missing_credential"]
    assert rig.guard.counts["ingress_rejected"] == 1


def test_batch_with_spans_of_another_agent_is_403_with_count(rig: Rig) -> None:
    body = batch()  # spans are for "payments"; the credential is treasury's
    r = rig.client.post("/v1/traces", content=body, headers=sign(body, "treasury", "u" * 48))
    assert r.status_code == 403
    assert r.headers["x-supervisor-rejected"] == "7"
    assert rig.events() == []  # the whole batch is dropped
    assert rig.audit[-1]["reason"] == "span_agent_mismatch"
    assert rig.audit[-1]["claimed"] == "treasury"
    assert rig.guard.counts["ingress_rejected_span_agent_mismatch"] == 1


def test_mixed_batch_is_rejected_whole(rig: Rig) -> None:
    payload = spans_to_otlp_json(payments_spans())
    own = payload["resourceSpans"]
    foreign = json.loads(json.dumps(own).replace('"payments"', '"treasury"'))
    payload["resourceSpans"] = own + foreign
    body = json.dumps(payload).encode()
    r = rig.client.post("/v1/traces", content=body, headers=sign(body))
    assert r.status_code == 403 and int(r.headers["x-supervisor-rejected"]) >= 1
    assert rig.events() == []  # not even the agent's own spans are written


def test_bad_signature_replay_and_stale(rig: Rig) -> None:
    body = batch()
    assert (
        rig.client.post("/v1/traces", content=body, headers=sign(body, secret="v" * 48)).status_code
        == 401
    )
    h = sign(body)
    assert rig.client.post("/v1/traces", content=body, headers=h).status_code == 200
    assert rig.client.post("/v1/traces", content=body, headers=h).status_code == 401
    assert [a["reason"] for a in rig.audit] == ["bad_signature", "replayed_nonce"]


def test_signature_for_another_route_is_not_valid_here(rig: Rig) -> None:
    body = batch()
    h = IngressCredential("payments", SECRET).headers_for("POST", "/gate/check", body)
    r = rig.client.post(
        "/v1/traces", content=body, headers={"content-type": "application/json", **h}
    )
    assert r.status_code == 401


def test_bearer_token_for_the_mapped_agent(rig: Rig) -> None:
    body = batch()
    ok = rig.client.post(
        "/v1/traces",
        content=body,
        headers={"content-type": "application/json", "authorization": "Bearer tok-sp"},
    )
    assert ok.status_code == 200
    other = rig.client.post(
        "/v1/traces",
        content=body,
        headers={"content-type": "application/json", "authorization": "Bearer tok-other"},
    )
    assert other.status_code == 403 and other.headers["x-supervisor-rejected"] == "7"


def test_receiver_stays_open_when_the_flag_is_off(
    adapters: Adapters, masker: VnRegexMasker
) -> None:
    rec = build_recorder(
        adapters.settings,
        adapters.tables,
        masker=masker,
        policy=CapturePolicy({"payments": AgentCapture("masked")}),
    )
    ingress_auth.set_guard(None)
    app.dependency_overrides[recorder_dep] = lambda: rec
    try:
        r = TestClient(app).post(
            "/v1/traces", content=batch(), headers={"content-type": "application/json"}
        )
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(recorder_dep, None)


def _named_span_batch(name: str) -> bytes:
    """One OTLP span whose agent id comes only from the span name (semconv fallback)."""
    span = {
        "traceId": "a" * 32,
        "spanId": "b" * 16,
        "name": name,
        "kind": 3,  # CLIENT
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000001000000000",
        "attributes": [],
    }
    doc = {"resourceSpans": [{"resource": {"attributes": []}, "scopeSpans": [{"spans": [span]}]}]}
    return json.dumps(doc).encode("utf-8")


def test_span_named_for_another_agent_is_refused(rig: Rig) -> None:
    # Review fix: with RECORDER_SEMCONV on, "invoke_agent treasury" gives agent id "treasury"
    # through the span name only. The check must see the same agent id as the normaliser.
    body = _named_span_batch("invoke_agent treasury")
    r = rig.client.post("/v1/traces", content=body, headers=sign(body))
    assert r.status_code == 403, r.text
    assert [e for e in rig.events() if e.get("agent_id") == "treasury"] == []
