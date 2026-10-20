"""WP20: ingress auth on POST /gate/check and /v1/gate/check (real app, SQLite store).

Rubric (see test_ingress_verifier.py): every rejection is 401/403 (never 500), writes one audit
row that holds a body hash and no body text, and is counted in /gate/metrics.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supervisor.adapters.auth.agent_creds import AgentKey, FileKeyStore
from supervisor.adapters.factory import Adapters
from supervisor.app import app
from supervisor.config import load_settings
from supervisor.core.canonical import sha256_hex  # noqa: F401 - parity with other suites
from supervisor.gateway import ingress_auth, wiring
from supervisor.gateway.engine import Gateway
from supervisor.gateway.ingress_sign import H_NONCE, H_SIGNATURE, IngressCredential

SECRET = "s" * 48
AGENT = "customer_service"
PIN = "PII-MARKER-Nguyen-Van-A-0912345678"


def make_body(agent: str = AGENT, tool: str = "read_ticket", args: dict[str, Any] | None = None):
    return json.dumps(
        {
            "agent_id": agent,
            "agent_version": "1",
            "tool_name": tool,
            "args": args if args is not None else {"ticket_id": "T1"},
        }
    ).encode()


@pytest.fixture
def keys_file(tmp_path: Path) -> Path:
    path = tmp_path / "agent_keys.yaml"
    FileKeyStore(path).write_all(
        {AGENT: [AgentKey("k1", SECRET)], "payments": [AgentKey("k2", "p" * 48)]}
    )
    return path


@pytest.fixture
def secured(
    gateway: Gateway, adapters: Adapters, keys_file: Path, tmp_path: Path
) -> Iterator[TestClient]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "d",
        ingress_auth_enabled=True,
        ingress_keys_file=keys_file,
    )
    wiring.set_gateway(gateway)
    ingress_auth.set_guard(ingress_auth.build_guard(settings))
    try:
        yield TestClient(app)
    finally:
        ingress_auth.set_guard(None)
        wiring.set_gateway(None)


def signed(path: str, body: bytes, agent: str = AGENT, secret: str = SECRET) -> dict[str, str]:
    h = IngressCredential(agent, secret).headers_for("POST", path, body)
    h["content-type"] = "application/json"
    return h


def audit_rows(adapters: Adapters) -> list[dict[str, Any]]:
    return [
        r for r in adapters.tables.query("console_action", {}) if r["permission"] == "ingress.auth"
    ]


@pytest.mark.parametrize("path", ["/gate/check", "/v1/gate/check"])
def test_signed_call_reaches_the_gate(secured: TestClient, path: str) -> None:
    body = make_body()
    r = secured.post(path, content=body, headers=signed(path, body))
    assert r.status_code == 200 and r.json()["allow"] is True


def test_default_is_off_and_unsigned_calls_work(gateway: Gateway) -> None:
    wiring.set_gateway(gateway)
    ingress_auth.set_guard(None)
    try:
        assert load_settings().ingress_auth_enabled is False
        assert ingress_auth.get_guard().enabled is False
        r = TestClient(app).post(
            "/gate/check", content=make_body(), headers={"content-type": "application/json"}
        )
        assert r.status_code == 200
    finally:
        wiring.set_gateway(None)


@pytest.mark.parametrize("path", ["/gate/check", "/v1/gate/check"])
def test_unsigned_call_is_401_with_audit_row_and_metric(
    secured: TestClient, adapters: Adapters, gateway: Gateway, path: str
) -> None:
    body = make_body(args={"note": PIN})
    r = secured.post(path, content=body, headers={"content-type": "application/json"})
    assert r.status_code == 401 and "error" in r.json()
    assert r.headers["www-authenticate"].startswith("Bearer")
    rows = audit_rows(adapters)
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome"] == "denied" and row["detail"] == "missing_credential"
    import hashlib

    assert row["before_hash"] == hashlib.sha256(body).hexdigest()
    assert PIN not in json.dumps(row, default=str)  # hash only, no body, no PII
    counts = gateway.metrics.snapshot()["counts"]
    assert counts["ingress_rejected"] == 1 and counts["ingress_rejected_missing_credential"] == 1
    assert secured.get("/gate/metrics").json()["counts"]["ingress_rejected"] == 1


def test_each_rejection_kind_is_401_or_403_and_audited(
    secured: TestClient, adapters: Adapters
) -> None:
    path = "/gate/check"
    body = make_body()
    cases: list[tuple[str, dict[str, str], bytes, int]] = []
    cases.append(("bad_signature", signed(path, body, secret="x" * 48), body, 401))
    cases.append(("unknown_agent", signed(path, body, agent="ghost"), body, 401))
    stale = IngressCredential(AGENT, SECRET, clock=lambda: 1_000_000).headers_for(
        "POST", path, body
    )
    cases.append(("stale_timestamp", {**stale, "content-type": "application/json"}, body, 401))
    big = {**signed(path, body), H_SIGNATURE: "v1=" + "a" * 5000}
    cases.append(("header_too_large", big, body, 401))
    spoof = make_body(agent="payments")  # signed as customer_service, body names payments
    cases.append(("agent_mismatch", signed(path, spoof), spoof, 403))
    for reason, headers, payload, status in cases:
        r = secured.post(path, content=payload, headers=headers)
        assert r.status_code == status, (reason, r.status_code, r.text)
        assert "Traceback" not in r.text
    got = [r["detail"] for r in audit_rows(adapters)]
    assert got == [c[0] for c in cases]
    assert all(r["actor"].startswith("unverified:") for r in audit_rows(adapters))


def test_replayed_request_is_refused_and_audited(secured: TestClient, adapters: Adapters) -> None:
    body = make_body()
    h = signed("/gate/check", body)
    assert secured.post("/gate/check", content=body, headers=h).status_code == 200
    r = secured.post("/gate/check", content=body, headers=h)
    assert r.status_code == 401 and r.json()["error"] == "nonce already used"
    assert audit_rows(adapters)[-1]["detail"] == "replayed_nonce"


def test_agent_id_spoofing_header_vs_body(secured: TestClient, evidence: Any) -> None:
    """Valid credential for customer_service, body asks the gate about payments: 403, and the
    gate is not asked (no decision row for payments)."""
    body = make_body(agent="payments", tool="transfer", args={"amount_minor": 1})
    r = secured.post("/gate/check", content=body, headers=signed("/gate/check", body))
    assert r.status_code == 403
    assert evidence.of_type("gate_decision") == []


def test_header_agent_spoof_with_another_agents_signature(secured: TestClient) -> None:
    body = make_body(agent="payments")
    h = signed("/gate/check", body, agent=AGENT)  # signed with customer_service key
    h["X-Supervisor-Agent"] = "payments"  # but claims payments
    assert secured.post("/gate/check", content=body, headers=h).status_code == 401


def test_bad_body_after_valid_auth_is_400_not_500(secured: TestClient) -> None:
    for body in (b"not json", b"[]", b"{}", b'{"agent_id": 5}', b"\xff\xfe"):
        r = secured.post("/gate/check", content=body, headers=signed("/gate/check", body))
        assert r.status_code in (400, 403), (body, r.status_code)


def test_body_over_the_cap_is_413_and_audited(
    secured: TestClient, adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = ingress_auth.get_guard()
    monkeypatch.setattr(guard, "body_cap", lambda _p: 100)
    body = make_body(args={"x": "y" * 500})
    r = secured.post("/gate/check", content=body, headers=signed("/gate/check", body))
    assert r.status_code == 413
    assert audit_rows(adapters)[-1]["detail"] == "body_too_large"


def test_audit_store_failure_does_not_become_a_500(
    secured: TestClient, gateway: Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("store down")

    monkeypatch.setattr(gateway.tables, "append", boom)
    r = secured.post(
        "/gate/check", content=make_body(), headers={"content-type": "application/json"}
    )
    assert r.status_code == 401


def test_nonce_header_with_garbage_is_401(secured: TestClient) -> None:
    body = make_body()
    h = signed("/gate/check", body)
    h[H_NONCE] = "bad nonce"
    assert secured.post("/gate/check", content=body, headers=h).status_code == 401


def test_misconfigured_verifier_fails_closed(gateway: Gateway) -> None:
    wiring.set_gateway(gateway)
    ingress_auth.set_guard(ingress_auth.IngressGuard(enabled=True, verifier=None))
    try:
        r = TestClient(app).post(
            "/gate/check", content=make_body(), headers={"content-type": "application/json"}
        )
        assert r.status_code == 401
    finally:
        ingress_auth.set_guard(None)
        wiring.set_gateway(None)


@pytest.mark.parametrize("doc", ["agents: [a, b]\n", "agents:\n  customer_service: [1]\n"])
def test_malformed_key_file_is_401_not_500(
    secured: TestClient, keys_file: Path, adapters: Adapters, doc: str
) -> None:
    # Review fix: a key file with the wrong shape raised AttributeError (HTTP 500).
    keys_file.write_text(doc, encoding="utf-8")
    os.chmod(keys_file, 0o600)
    body = make_body()
    r = secured.post("/gate/check", content=body, headers=signed("/gate/check", body))
    assert r.status_code == 401
    assert [row["detail"] for row in audit_rows(adapters)] == ["key_store_unavailable"]


def test_unexpected_verifier_error_is_401_not_500(secured: TestClient) -> None:
    class Exploding:
        name = "boom"

        def keys_for(self, agent_id: str, now: Any = None) -> list[Any]:
            raise RuntimeError("bug")

    guard = ingress_auth.get_guard()
    assert guard.verifier is not None
    guard.verifier.keys = Exploding()
    body = make_body()
    r = secured.post("/gate/check", content=body, headers=signed("/gate/check", body))
    assert r.status_code == 401 and r.json() == {"error": "authentication failed"}


def test_chunked_body_over_the_app_limit_is_413_not_401(secured: TestClient) -> None:
    # Review: the body-limit middleware's own error must pass through the guard unchanged.
    def gen() -> Iterator[bytes]:
        for _ in range(200):
            yield b"x" * 100_000

    r = secured.post("/gate/check", content=gen(), headers={"content-type": "application/json"})
    assert r.status_code == 413
