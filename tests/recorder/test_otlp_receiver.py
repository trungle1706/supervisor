"""POST /v1/traces: valid batch, duplicates, oversized, wrong content type, bad JSON."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supervisor.adapters.factory import Adapters
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.app import app
from supervisor.recorder import otlp_receiver
from supervisor.recorder.capture import AgentCapture, CapturePolicy
from supervisor.recorder.normalise import spans_to_otlp_json
from supervisor.recorder.otlp_receiver import recorder_dep
from supervisor.recorder.service import build_recorder
from tests.recorder.conftest import PII_NAME, payments_spans


@pytest.fixture
def client(
    adapters: Adapters, masker: VnRegexMasker, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    rec = build_recorder(
        adapters.settings,
        adapters.tables,
        masker=masker,
        policy=CapturePolicy({"payments": AgentCapture("masked")}),
    )
    app.dependency_overrides[recorder_dep] = lambda: rec
    monkeypatch.setattr(otlp_receiver, "_limits", lambda: (200_000, 50))
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(recorder_dep, None)


def _body() -> bytes:
    return json.dumps(spans_to_otlp_json(payments_spans())).encode("utf-8")


def test_valid_batch_is_stored_masked_and_replay_is_idempotent(
    client: TestClient, adapters: Adapters
) -> None:
    body = _body()
    r = client.post("/v1/traces", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 200 and r.json() == {}
    assert r.headers["x-supervisor-accepted"] == "7"
    rows = adapters.tables.query("agent_event", {"agent_id": "payments"})
    assert len(rows) == 7 and {x["source"] for x in rows} == {"otlp"}
    assert all(x["capture_level"] == "masked" for x in rows)
    assert PII_NAME not in json.dumps(rows, default=str, ensure_ascii=False)
    # same batch again, gzip-compressed: nothing new, no error
    r2 = client.post(
        "/v1/traces",
        content=gzip.compress(body),
        headers={"content-type": "application/json; charset=utf-8", "content-encoding": "gzip"},
    )
    assert r2.status_code == 200 and r2.headers["x-supervisor-duplicates"] == "7"
    assert r2.headers["x-supervisor-accepted"] == "0"
    assert len(adapters.tables.query("agent_event")) == 7


def test_oversized_body_is_400(client: TestClient) -> None:
    big = b'{"resourceSpans": [], "pad": "' + b"x" * 300_000 + b'"}'
    r = client.post("/v1/traces", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 400 and "OTLP_MAX_BODY_BYTES" in r.json()["error"]


def test_gzip_bomb_is_400(client: TestClient) -> None:
    bomb = gzip.compress(b'{"resourceSpans": [], "pad": "' + b"x" * 5_000_000 + b'"}')
    r = client.post(
        "/v1/traces",
        content=bomb,
        headers={"content-type": "application/json", "content-encoding": "gzip"},
    )
    assert r.status_code == 400 and "OTLP_MAX_BODY_BYTES" in r.json()["error"]


def test_too_many_spans_is_400(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(otlp_receiver, "_limits", lambda: (200_000, 3))
    r = client.post("/v1/traces", content=_body(), headers={"content-type": "application/json"})
    assert r.status_code == 400 and "OTLP_MAX_SPANS" in r.json()["error"]


@pytest.mark.parametrize("ctype", ["application/x-protobuf", "application/protobuf"])
def test_protobuf_is_415_with_message(client: TestClient, ctype: str) -> None:
    r = client.post("/v1/traces", content=b"\x0a\x00", headers={"content-type": ctype})
    assert r.status_code == 415 and "http/json" in r.json()["error"]


def test_other_content_type_is_415(client: TestClient) -> None:
    r = client.post("/v1/traces", content=b"x", headers={"content-type": "text/plain"})
    assert r.status_code == 415


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[1,2]",
        b'{"resourceSpans": [{"scopeSpans": [{"spans": [{"traceId": "x"}]}]}]}',
    ],
)
def test_malformed_payload_is_400(client: TestClient, body: bytes, adapters: Adapters) -> None:
    r = client.post("/v1/traces", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]
    assert adapters.tables.query("agent_event") == []


def test_store_down_spools_and_returns_200(
    client: TestClient, adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(adapters.tables, "append", boom)
    r = client.post("/v1/traces", content=_body(), headers={"content-type": "application/json"})
    assert r.status_code == 200 and r.headers["x-supervisor-spooled"] == "7"
    spool = adapters.settings.recorder_spool_dir
    assert spool is not None and len(list(spool.glob("*.jsonl"))) == 1
