from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from supervisor.app import app
from supervisor.config import load_settings
from supervisor.gateway import wiring as gate_wiring
from supervisor.wiring import build_runtime


@pytest.fixture
def runtime(tmp_path) -> Iterator[object]:
    s = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data", llm_base_url="")
    rt = build_runtime(s)
    old = gate_wiring._runtime
    gate_wiring._runtime = rt
    try:
        yield rt
    finally:
        gate_wiring._runtime = old
        rt.close()


def test_health_and_healthz_unchanged():
    c = TestClient(app)
    h = c.get("/health")
    assert h.status_code == 200 and h.json()["status"] == "ok" and h.json()["version"]
    assert c.get("/healthz").json() == {"status": "ok"}
    assert "x-request-id" in h.headers and "content-security-policy" in h.headers


def test_ready_200_without_leaks(runtime, tmp_path):
    r = TestClient(app).get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["checks"]["store"] and body["checks"]["signer"] and body["checks"]["runtime"]
    assert body["checks"]["scheduler"] in ("running", "off", "not-leader")
    text = r.text
    assert str(runtime.settings.data_dir) not in text and "sqlite" not in text.lower()
    assert str(tmp_path) not in text


def test_ready_503_names_failed_checks_only(runtime):
    class Boom:
        def query(self, *a, **k):
            raise RuntimeError("password=hunter2 host=db.internal /var/x.sqlite")

    runtime.adapters.state = Boom()
    r = TestClient(app).get("/ready")
    assert r.status_code == 503
    assert r.json()["failed"] == ["store"]
    assert "hunter2" not in r.text and "db.internal" not in r.text and ".sqlite" not in r.text


def test_ready_503_without_runtime(monkeypatch):
    monkeypatch.setattr(gate_wiring, "_runtime", None)
    r = TestClient(app).get("/ready")
    assert r.status_code == 503 and "runtime" in r.json()["failed"]


def test_gate_chunked_oversized_body_is_413(runtime):
    """The gate's own body parser must not turn the body-limit stop into a 400."""

    def chunks():
        for _ in range(12):
            yield b"a" * 1_000_000

    r = TestClient(app).post("/gate/check", content=chunks())
    assert r.status_code == 413 and "too large" in r.json()["error"]
