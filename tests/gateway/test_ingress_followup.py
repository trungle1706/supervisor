"""WP20 review follow-up (F8-F11 and the databricks_proxy kind)."""
# ruff: noqa: E501

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supervisor.adapters.auth.agent_creds import AgentKey, SecretScopeKeyStore
from supervisor.adapters.auth.agent_creds_identity import (
    AgentIdentityMap,
    IdentityError,
    ScimMeIdentityVerifier,
    VerifiedIdentity,
)
from supervisor.adapters.factory import Adapters
from supervisor.app import app
from supervisor.config import load_settings
from supervisor.gateway import ingress_auth, wiring
from supervisor.gateway.engine import Gateway
from supervisor.gateway.ingress_auth import (
    IngressGuard,
    IngressVerifier,
    NonceCache,
    _CIHeaders,
)
from supervisor.gateway.ingress_sign import H_AGENT, IngressCredential

from .test_ingress_verifier import BODY, NOW, PATH, Clock, FakeSecretReader, reason_of, sign

AGENT = "customer_service"


# ------------------------------------------------------------------ F8


def test_unregistered_agent_never_reaches_the_secret_scope() -> None:
    reader = FakeSecretReader({("sc", "agent-payments-current"): "a" * 40})
    store = SecretScopeKeyStore(reader, "sc", ttl_s=60)
    v = IngressVerifier(
        kind="hmac",
        keys=store,
        clock=Clock(),
        known_agent=lambda a: a == "payments",
        registry_before_keys=True,
    )
    for i in range(20):  # random agent ids: a local refusal each, no network read
        assert reason_of(v, sign(agent=f"ghost{i}"))[0] == "unknown_agent"
    assert reader.reads == 0
    v.authenticate("POST", PATH, sign(secret="a" * 40), BODY)  # the real agent still works
    assert reader.reads > 0


def test_registry_outage_refuses_without_a_500() -> None:
    def boom(_a: str) -> bool:
        raise RuntimeError("store down")

    v = IngressVerifier(
        kind="hmac", keys=None, clock=Clock(), known_agent=boom, registry_before_keys=True
    )
    assert reason_of(v, sign())[1] == 401


def test_bearer_claimed_agent_outside_the_identity_map_skips_scim() -> None:
    calls: list[str] = []

    class Spy:
        name = "spy"

        def verify(self, token: str) -> VerifiedIdentity:
            calls.append(token)
            return VerifiedIdentity("sp-1")

    v = IngressVerifier(
        kind="databricks_sp",
        keys=None,
        identity=Spy(),
        identities=AgentIdentityMap({"sp-1": frozenset({"payments"})}),
        clock=Clock(),
    )
    h = {"Authorization": "Bearer tok", H_AGENT: "ghost"}
    assert reason_of(v, h) == ("agent_mismatch", 403)
    assert calls == []
    v.authenticate("POST", PATH, {"Authorization": "Bearer tok", H_AGENT: "payments"}, BODY)
    assert calls == ["tok"]


def test_scim_calls_are_capped_by_a_semaphore() -> None:
    running = 0
    peak = 0
    lock = threading.Lock()
    gate = threading.Event()

    def slow(token: str) -> VerifiedIdentity:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        gate.wait(2)
        with lock:
            running -= 1
        return VerifiedIdentity("sp")

    v = ScimMeIdentityVerifier("https://example.invalid", call=slow, max_concurrent=2, wait_s=0.2)
    results: list[str] = []

    def work(i: int) -> None:
        try:
            v.verify(f"tok{i}")
            results.append("ok")
        except IdentityError:
            results.append("busy")

    threads = [threading.Thread(target=work, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    time.sleep(0.5)
    gate.set()
    for t in threads:
        t.join()
    assert peak <= 2
    assert results.count("busy") >= 1  # the rest were refused (401), not queued without bound


def test_scim_negative_cache_expires() -> None:
    t = [0.0]
    n = [0]

    def deny(token: str) -> VerifiedIdentity:
        n[0] += 1
        raise RuntimeError("401")

    v = ScimMeIdentityVerifier(
        "https://example.invalid", call=deny, clock=lambda: t[0], negative_ttl_s=30
    )
    for _ in range(5):
        with pytest.raises(IdentityError):
            v.verify("bad")
    assert n[0] == 1
    t[0] = 31
    with pytest.raises(IdentityError):
        v.verify("bad")
    assert n[0] == 2


# ------------------------------------------------------------------ F10


def test_per_agent_nonce_cap_protects_other_agents() -> None:
    c = NonceCache(600, lambda: NOW, max_entries=100, per_agent_max=3)
    for i in range(3):
        assert c.use("a", f"n{i:015d}") == "ok"
    assert c.use("a", "n" + "9" * 15) == "full"  # agent a is capped
    assert c.use("b", "n" + "9" * 15) == "ok"  # agent b is not affected


def test_nonce_eviction_is_from_the_front_and_counts_follow() -> None:
    t = [NOW]
    c = NonceCache(10, lambda: t[0], max_entries=100, per_agent_max=2)
    assert c.use("a", "n" * 16) == "ok"
    assert c.use("a", "m" * 16) == "ok"
    assert c.use("a", "o" * 16) == "full"
    t[0] += 11  # both expired: dropped from the front, the per-agent count falls with them
    assert c.use("a", "o" * 16) == "ok"
    assert len(c) == 1 and c._count == {"a": 1}


def test_nonce_cache_does_not_scan_when_full() -> None:
    """Fill to the cap with live entries: the next insert answers `full` without a rebuild."""
    c = NonceCache(600, lambda: NOW, max_entries=1000, per_agent_max=2000)
    for i in range(1000):
        c.use("a", f"{i:016d}")
    seen_before = c._seen
    assert c.use("b", "z" * 16) == "full"
    assert c._seen is seen_before  # same object: no `{... for ... in ...}` rebuild


# ------------------------------------------------------------------ F9 / F11 / proxy via the app


@pytest.fixture
def rig(gateway: Gateway, adapters: Adapters, tmp_path: Path) -> Iterator[Any]:
    wiring.set_gateway(gateway)
    keys = tmp_path / "k.yaml"
    from supervisor.adapters.auth.agent_creds import FileKeyStore

    FileKeyStore(keys).write_all({AGENT: [AgentKey("k1", "s" * 48)]})
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "d",
        ingress_auth_enabled=True,
        ingress_keys_file=keys,
        ingress_audit_throttle_s=60,
    )
    guard = ingress_auth.build_guard(settings)
    ingress_auth.set_guard(guard)
    try:
        yield guard, TestClient(app), adapters, gateway
    finally:
        ingress_auth.set_guard(None)
        wiring.set_gateway(None)


def rows(adapters: Adapters) -> list[dict[str, Any]]:
    return [
        r for r in adapters.tables.query("console_action", {}) if r["permission"] == "ingress.auth"
    ]


def test_audit_throttle_writes_one_row_and_counts_the_rest(rig: Any) -> None:
    guard, client, adapters, gateway = rig
    for _ in range(5):
        assert client.post("/gate/check", content=b"{}").status_code == 401
    assert len(rows(adapters)) == 1  # same reason, same client: one row per 60 s
    counts = gateway.metrics.snapshot()["counts"]
    assert counts["ingress_rejected"] == 5  # every rejection is still counted
    assert counts["ingress_audit_suppressed"] == 4
    # another reason is another key: written
    bad = IngressCredential(AGENT, "w" * 48).headers_for("POST", "/gate/check", b"{}")
    assert client.post("/gate/check", content=b"{}", headers=bad).status_code == 401
    assert len(rows(adapters)) == 2


def test_throttle_off_audits_every_rejection(
    gateway: Gateway, adapters: Adapters, tmp_path: Path
) -> None:
    wiring.set_gateway(gateway)
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "d",
        ingress_auth_enabled=True,
        ingress_keys_file=tmp_path / "none.yaml",
    )
    assert settings.ingress_audit_throttle_s == 0
    ingress_auth.set_guard(ingress_auth.build_guard(settings))
    try:
        for _ in range(3):
            TestClient(app).post("/gate/check", content=b"{}")
        assert len(rows(adapters)) == 3
    finally:
        ingress_auth.set_guard(None)
        wiring.set_gateway(None)


def test_throttle_map_is_bounded_and_next_row_carries_the_skipped_count() -> None:
    t = [0.0]
    g = IngressGuard(enabled=True, audit=lambda _i: None, audit_throttle_s=10, clock=lambda: t[0])

    class Req:
        client = type("C", (), {"host": "10.0.0.1"})()

    assert g._throttled(Req(), "bad_signature", None) == 0
    assert g._throttled(Req(), "bad_signature", None) is None
    assert g._throttled(Req(), "bad_signature", None) is None
    t[0] = 11
    assert g._throttled(Req(), "bad_signature", None) == 2  # two were skipped
    for i in range(ingress_auth.AUDIT_THROTTLE_MAX_KEYS + 50):
        g._throttled(Req(), "bad_signature", f"agent{i}")
    assert len(g._throttle) <= ingress_auth.AUDIT_THROTTLE_MAX_KEYS


def test_headers_are_checked_before_the_body_is_buffered(
    rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _guard, client, _a, _g = rig

    async def must_not_run(*_a: Any, **_k: Any) -> bytes:
        raise AssertionError("body was buffered for a request with a bad header set")

    monkeypatch.setattr(ingress_auth, "_read_capped", must_not_run)
    big = b"x" * 200_000
    assert client.post("/gate/check", content=big).status_code == 401  # no credential
    h = IngressCredential(AGENT, "s" * 48, clock=lambda: 1000).headers_for(
        "POST", "/gate/check", b""
    )
    assert client.post("/gate/check", content=big, headers=h).status_code == 401  # stale
    h2 = IngressCredential(AGENT, "s" * 48).headers_for("POST", "/gate/check", b"")
    h2["X-Supervisor-Nonce"] = "short"
    assert client.post("/gate/check", content=big, headers=h2).status_code == 401  # malformed


# ------------------------------------------------------------------ databricks_proxy


def proxy_verifier(**kw: Any) -> IngressVerifier:
    ident = AgentIdentityMap.__new__(AgentIdentityMap)
    ident._map = {
        "sp-app-id": frozenset({"payments"}),
        "ana@example.invalid": frozenset({"support"}),
    }
    return IngressVerifier(
        kind=kw.pop("kind", "databricks_proxy"), keys=None, identities=ident, clock=Clock(), **kw
    )


def test_proxy_identity_header_maps_to_agent_ids() -> None:
    v = proxy_verifier()
    ident = v.authenticate("POST", PATH, {"X-Forwarded-Email": "sp-app-id"}, BODY)
    assert ident.kind == "databricks_proxy" and ident.agent_ids == frozenset({"payments"})
    ident = v.authenticate("POST", PATH, {"X-Forwarded-User": "sp-app-id"}, BODY)
    assert ident.allows("payments")
    # e-mail style principals are case-insensitive
    assert v.authenticate("POST", PATH, {"x-forwarded-email": "Ana@Example.invalid"}, BODY).allows(
        "support"
    )


def test_proxy_identity_failures() -> None:
    v = proxy_verifier()
    assert reason_of(v, {"X-Forwarded-Email": "stranger"}) == ("unknown_principal", 403)
    h = {"X-Forwarded-User": "sp-app-id", H_AGENT: "support"}
    assert reason_of(v, h) == ("agent_mismatch", 403)
    assert reason_of(v, {}) == ("missing_credential", 401)
    assert reason_of(v, {"X-Forwarded-Email": "x" * 2000})[0] == "header_too_large"


def test_proxy_kind_does_not_accept_bearer_or_hmac_and_vice_versa() -> None:
    assert reason_of(proxy_verifier(), {"Authorization": "Bearer t"})[0] == "missing_credential"
    assert reason_of(proxy_verifier(), sign())[0] == "missing_credential"
    sp_only = proxy_verifier(kind="databricks_sp")
    assert reason_of(sp_only, {"X-Forwarded-Email": "sp-app-id"})[0] == "missing_credential"


def test_all_kind_prefers_signature_then_bearer_then_proxy() -> None:
    v = proxy_verifier(kind="all")

    def route(h: dict[str, str]) -> str:
        return v._route(_CIHeaders(h))

    sig = "v1=" + "0" * 64
    assert route({"x-supervisor-signature": sig, "authorization": "Bearer t"}) == "hmac"
    assert route({"authorization": "Bearer t", "x-forwarded-user": "u"}) == "databricks_sp"
    assert route({"x-forwarded-user": "u"}) == "databricks_proxy"


def test_defaults_proxy_in_app_mode_and_ignored_elsewhere(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    assert (
        load_settings(supervisor_mode="databricks_app").effective_ingress_kind == "databricks_proxy"
    )
    assert load_settings(supervisor_mode="laptop").effective_ingress_kind == "hmac"
    ids = tmp_path / "ids.yaml"
    ids.write_text("principals:\n  - principal: ana\n    agents: [a1]\n", encoding="utf-8")
    off_app = load_settings(
        supervisor_mode="laptop",
        ingress_auth_enabled=True,
        ingress_credential_kind="databricks_proxy",
        ingress_identities_file=ids,
    )
    v = ingress_auth.build_verifier(off_app)
    # a typed X-Forwarded-User off the App is NOT an identity
    assert reason_of(v, {"X-Forwarded-User": "ana"})[0] == "missing_credential"
    in_app = load_settings(
        supervisor_mode="databricks_app",
        ingress_auth_enabled=True,
        ingress_identities_file=ids,
    )
    v2 = ingress_auth.build_verifier(in_app)
    assert v2.authenticate("POST", PATH, {"X-Forwarded-User": "ana"}, BODY).allows("a1")


def test_proxy_kind_through_the_app(gateway: Gateway, adapters: Adapters, tmp_path: Path) -> None:
    ids = tmp_path / "ids.yaml"
    ids.write_text(f"principals:\n  - principal: ana\n    agents: [{AGENT}]\n", encoding="utf-8")
    settings = load_settings(
        supervisor_mode="databricks_app",
        sql_backend="sqlite",
        data_dir=tmp_path / "d",
        ingress_auth_enabled=True,
        ingress_identities_file=ids,
    )
    wiring.set_gateway(gateway)
    ingress_auth.set_guard(ingress_auth.build_guard(settings))
    try:
        c = TestClient(app)
        body = b'{"agent_id":"customer_service","agent_version":"1","tool_name":"read_ticket","args":{}}'
        ok = c.post("/gate/check", content=body, headers={"x-forwarded-user": "ana"})
        assert ok.status_code == 200 and ok.json()["allow"] is True
        other = body.replace(b"customer_service", b"payments")
        assert (
            c.post("/gate/check", content=other, headers={"x-forwarded-user": "ana"}).status_code
            == 403
        )
        assert (
            c.post("/gate/check", content=body, headers={"x-forwarded-user": "eve"}).status_code
            == 403
        )
        assert c.post("/gate/check", content=body).status_code == 401
    finally:
        ingress_auth.set_guard(None)
        wiring.set_gateway(None)
