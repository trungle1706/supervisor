"""WP20 ingress auth: the verifier, key stores, identity port and rotation (no web layer).

Expert rubric (application-security engineer, OWASP ASVS v4 ch. 2 and 3, NIST SP 800-63B):
  V2.9 / 63B 5.1.x  cryptographic verifier: HMAC-SHA256, 256-bit secret, constant-time compare
  V3.x / 63B 5.2.8  replay resistance: timestamp window + single-use nonce, bound to method+path
  V2.6 / 8.x        look-up secrets are not enumerable: unknown agent == bad signature to the caller
  V2.10 / 3.7       key lifecycle: rotation overlap with expiry, at most two active keys
  V13 / 14          input handling: oversized, duplicated, malformed headers are refused, never 500
Every test below maps to one of these checks.
"""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.agent_creds import (
    AgentKey,
    EnvKeyStore,
    FileKeyStore,
    KeyStoreError,
    SecretScopeKeyStore,
    env_name,
    rotate_keys,
)
from supervisor.adapters.auth.agent_creds_identity import (
    AgentIdentityMap,
    FakeIdentityVerifier,
    IdentityError,
    ScimMeIdentityVerifier,
    VerifiedIdentity,
)
from supervisor.gateway import ingress_auth
from supervisor.gateway.ingress_auth import IngressRejected, IngressVerifier, NonceCache
from supervisor.gateway.ingress_sign import (
    H_AGENT,
    H_NONCE,
    H_SIGNATURE,
    H_TIMESTAMP,
    CredentialError,
    IngressCredential,
    compute_signature,
    credential_from_env,
    new_secret,
)

NOW = 1_800_000_000.0
SECRET_A = "a" * 40
SECRET_OLD = "o" * 40
PATH = "/v1/gate/check"
BODY = b'{"agent_id":"payments","tool_name":"x"}'


class Clock:
    def __init__(self, t: float = NOW) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class MemKeys:
    name = "mem"

    def __init__(self, data: dict[str, list[AgentKey]]) -> None:
        self.data = data

    def keys_for(self, agent_id: str, now: datetime | None = None) -> list[AgentKey]:
        n = now or datetime.fromtimestamp(NOW, UTC)
        return [k for k in self.data.get(agent_id, []) if k.valid_at(n)][:2]


def verifier(clock: Clock | None = None, **kw: Any) -> IngressVerifier:
    keys = kw.pop("keys", MemKeys({"payments": [AgentKey("k1", SECRET_A)]}))
    return IngressVerifier(kind=kw.pop("kind", "hmac"), keys=keys, clock=clock or Clock(), **kw)


def sign(
    secret: str = SECRET_A,
    agent: str = "payments",
    body: bytes = BODY,
    path: str = PATH,
    at: float = NOW,
    nonce: str | None = None,
) -> dict[str, str]:
    cred = IngressCredential(agent, secret, clock=lambda: at)
    headers = cred.headers_for("POST", path, body)
    if nonce:
        headers[H_NONCE] = nonce
        headers[H_SIGNATURE] = compute_signature(
            secret, agent, headers[H_TIMESTAMP], nonce, "POST", path, body
        )
    return headers


def reason_of(v: IngressVerifier, headers: dict[str, str], body: bytes = BODY, path: str = PATH):
    with pytest.raises(IngressRejected) as ei:
        v.authenticate("POST", path, headers, body)
    return ei.value.reason, ei.value.status_code


# ------------------------------------------------------------------ accept / reject basics


def test_valid_signature_is_accepted() -> None:
    ident = verifier().authenticate("POST", PATH, sign(), BODY)
    assert ident.kind == "hmac" and ident.agent_ids == frozenset({"payments"})


def test_missing_credential_is_401() -> None:
    assert reason_of(verifier(), {}) == ("missing_credential", 401)


def test_bad_signature_and_unknown_agent_look_the_same_to_the_caller() -> None:
    v = verifier()
    bad = sign(secret="b" * 40)
    unknown = sign(agent="ghost")
    with pytest.raises(IngressRejected) as e1:
        v.authenticate("POST", PATH, bad, BODY)
    with pytest.raises(IngressRejected) as e2:
        v.authenticate("POST", PATH, unknown, BODY)
    assert (e1.value.reason, e2.value.reason) == ("bad_signature", "unknown_agent")
    assert e1.value.status_code == e2.value.status_code == 401
    assert e1.value.detail == e2.value.detail  # ASVS 2.x: no account enumeration


def test_body_tampering_and_path_binding() -> None:
    v = verifier()
    h = sign()
    assert reason_of(v, h, body=BODY + b" ")[0] == "bad_signature"
    # a signature made for the traces route cannot be replayed on the gate route
    assert reason_of(v, sign(path="/v1/traces"), path=PATH)[0] == "bad_signature"


def test_signature_for_another_agent_header_is_rejected() -> None:
    v = verifier(
        keys=MemKeys({"payments": [AgentKey("k1", SECRET_A)], "other": [AgentKey("k2", "z" * 40)]})
    )
    h = sign()
    h[H_AGENT] = "other"  # claim another agent with payments' signature
    assert reason_of(v, h)[0] == "bad_signature"


def test_compare_is_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """The signature check goes through hmac.compare_digest, once per active key, and a
    wrong signature still runs the compare (no early exit on a prefix)."""
    calls: list[int] = []
    real = ingress_auth.hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(ingress_auth.hmac, "compare_digest", spy)
    keys = MemKeys({"payments": [AgentKey("k2", SECRET_A), AgentKey("k1", SECRET_OLD, "previous")]})
    v = verifier(keys=keys)
    v.authenticate("POST", PATH, sign(), BODY)
    assert len(calls) == 2  # both active keys compared, even though the first matched
    calls.clear()
    reason_of(v, sign(secret="b" * 40))
    assert len(calls) == 2
    calls.clear()
    reason_of(v, sign(agent="ghost"))
    assert len(calls) == 2  # unknown agent: dummy keys, same work (F12)


def test_no_plain_equality_on_signatures() -> None:
    import inspect

    src = inspect.getsource(IngressVerifier._hmac)
    assert "compare_digest" in src and "== sig" not in src and "sig ==" not in src


# ------------------------------------------------------------------ replay and clock skew


def test_replay_within_window_is_refused() -> None:
    v = verifier()
    h = sign()
    v.authenticate("POST", PATH, h, BODY)
    assert reason_of(v, h) == ("replayed_nonce", 401)


def test_replay_outside_window_is_refused_even_after_the_nonce_expired() -> None:
    clock = Clock()
    v = verifier(clock)
    h = sign()
    v.authenticate("POST", PATH, h, BODY)
    clock.t = NOW + 301  # past the window; the nonce may be gone from the cache
    v.nonces._seen.clear()  # worst case: cache lost (restart)
    assert reason_of(v, h) == ("stale_timestamp", 401)


@pytest.mark.parametrize(("skew", "ok"), [(0, True), (299, True), (300, True), (301, False)])
def test_clock_skew_both_directions(skew: int, ok: bool) -> None:
    for sign_of in (-1, 1):
        v = verifier()
        h = sign(at=NOW + sign_of * skew)
        if ok:
            v.authenticate("POST", PATH, h, BODY)
        else:
            assert reason_of(v, h) == ("stale_timestamp", 401)


def test_window_is_a_setting() -> None:
    v = verifier(window_s=10)
    assert reason_of(v, sign(at=NOW - 11))[0] == "stale_timestamp"


def test_nonce_is_per_agent_and_cache_is_bounded() -> None:
    c = NonceCache(600, lambda: NOW, max_entries=2)
    assert c.use("a", "n" * 16) == "ok"
    assert c.use("b", "n" * 16) == "ok"  # same nonce, other agent
    assert c.use("a", "m" * 16) == "full"  # fail closed, never grows without bound
    assert c.use("a", "n" * 16) == "replayed"


def test_nonce_cache_forgets_after_ttl() -> None:
    t = [NOW]
    c = NonceCache(10, lambda: t[0])
    assert c.use("a", "n" * 16) == "ok"
    t[0] += 11
    assert c.use("a", "n" * 16) == "ok"


def test_nonce_is_only_recorded_for_a_valid_signature() -> None:
    v = verifier()
    h = sign(secret="b" * 40)
    reason_of(v, h)
    assert len(v.nonces) == 0  # an attacker cannot fill the cache with garbage


# ------------------------------------------------------------------ header hygiene


def test_oversized_headers_are_refused() -> None:
    v = verifier(max_header=512)
    for name in (H_AGENT, H_SIGNATURE, H_NONCE, H_TIMESTAMP):
        h = sign()
        h[name] = "A" * 10_000
        assert reason_of(v, h) == ("header_too_large", 401)
    big = {"Authorization": "Bearer " + "t" * 5000}
    assert reason_of(verifier(kind="both"), big)[0] == "header_too_large"


@pytest.mark.parametrize(
    "mutate",
    [
        {H_TIMESTAMP: "-5"},
        {H_TIMESTAMP: "1e9"},
        {H_TIMESTAMP: ""},
        {H_TIMESTAMP: "١٢٣٤٥٦٧٨٩٠"},  # non-ASCII digits
        {H_TIMESTAMP: "9" * 40},
        {H_NONCE: "short"},
        {H_NONCE: "bad nonce with spaces!"},
        {H_SIGNATURE: "v1=zz"},
        {H_SIGNATURE: "deadbeef"},
        {H_AGENT: "bad agent\r\nX: y"},
        {H_AGENT: "../../etc"},
    ],
)
def test_malformed_headers_are_401_not_500(mutate: dict[str, str]) -> None:
    h = {**sign(), **mutate}
    reason, status = reason_of(verifier(), h)
    assert status == 401 and reason in ("malformed_credential", "missing_credential")


def test_missing_parts_of_a_signature_set() -> None:
    for name in (H_AGENT, H_TIMESTAMP, H_NONCE):
        h = sign()
        del h[name]
        assert reason_of(verifier(), h)[1] == 401


def test_header_names_are_case_insensitive() -> None:
    h = {k.lower(): v for k, v in sign().items()}
    verifier().authenticate("POST", PATH, h, BODY)


def test_duplicate_credential_header_is_refused() -> None:
    from starlette.datastructures import Headers

    raw = Headers(
        raw=[(k.lower().encode(), v.encode()) for k, v in sign().items()]
        + [(b"x-supervisor-agent", b"ghost")]
    )
    with pytest.raises(IngressRejected) as ei:
        verifier().authenticate("POST", PATH, raw, BODY)
    assert ei.value.reason == "header_too_large"


# ------------------------------------------------------------------ rotation


def test_rotation_overlap_and_expiry() -> None:
    now = datetime.fromtimestamp(NOW, UTC)
    keys = rotate_keys([AgentKey("k1", SECRET_OLD)], SECRET_A, now, timedelta(hours=1))
    assert [k.state for k in keys] == ["current", "previous"]
    assert keys[1].expires_at == now + timedelta(hours=1)
    store = MemKeys({"payments": keys})
    clock = Clock()
    v = verifier(clock, keys=store)
    v.authenticate("POST", PATH, sign(), BODY)  # new key
    v.authenticate("POST", PATH, sign(secret=SECRET_OLD), BODY)  # previous key, inside overlap
    clock.t = NOW + 3600 + 1  # previous key expired
    assert reason_of(v, sign(secret=SECRET_OLD, at=clock.t))[0] == "bad_signature"
    v.authenticate("POST", PATH, sign(at=clock.t), BODY)  # current key unaffected


def test_only_two_keys_stay_active() -> None:
    now = datetime.fromtimestamp(NOW, UTC)
    k1 = rotate_keys([], "1" * 40, now, timedelta(hours=1))
    k2 = rotate_keys(k1, "2" * 40, now, timedelta(hours=1))
    k3 = rotate_keys(k2, "3" * 40, now, timedelta(hours=1))
    assert [k.secret[0] for k in k3] == ["3", "2"]  # the first key is gone at the second rotation


def test_short_secret_and_placeholder_are_never_valid() -> None:
    now = datetime.fromtimestamp(NOW, UTC)
    assert not AgentKey("k", "short").valid_at(now)
    assert not AgentKey("k", "FILL-ME-secret-at-least-32-characters").valid_at(now)
    assert not AgentKey("k", SECRET_A, expires_at=now - timedelta(seconds=1)).valid_at(now)
    assert "aaaa" not in repr(AgentKey("k", SECRET_A))  # no secret in a repr


# ------------------------------------------------------------------ key store backends


def test_file_store_requires_mode_600_and_reloads_on_change(tmp_path: Path) -> None:
    path = tmp_path / "keys.yaml"
    store = FileKeyStore(path)
    assert store.keys_for("payments") == []  # no file: no keys
    store.write_all({"payments": [AgentKey("k1", SECRET_A)]})
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [k.key_id for k in store.keys_for("payments")] == ["k1"]
    store.write_all({"payments": [AgentKey("k2", SECRET_OLD)]})
    assert [k.key_id for k in store.keys_for("payments")] == ["k2"]  # picked up without restart
    if os.name == "posix":
        os.chmod(path, 0o644)
        with pytest.raises(KeyStoreError):
            FileKeyStore(path).keys_for("payments")


def test_a_store_error_is_401_not_500(tmp_path: Path) -> None:
    class Broken:
        name = "broken"

        def keys_for(self, agent_id: str, now: Any = None) -> list[AgentKey]:
            raise KeyStoreError("boom")

    assert reason_of(verifier(keys=Broken()), sign()) == ("key_store_unavailable", 401)


def test_the_sample_key_file_has_no_valid_key() -> None:
    from supervisor.config import REPO_ROOT

    sample = FileKeyStore(REPO_ROOT / "config" / "agent_keys.sample.yaml")
    try:
        assert sample.keys_for("FILL-ME-agent-id") == []
    except KeyStoreError:
        pass  # a checkout with a loose mode is refused too: also "no key"


def test_env_store() -> None:
    env = {
        env_name("payments"): SECRET_A,
        env_name("payments") + "_PREV": SECRET_OLD,
        env_name("payments") + "_PREV_EXPIRES": "2000-01-01T00:00:00Z",
    }
    store = EnvKeyStore(env)
    assert env_name("a.b-c") == "INGRESS_AGENT_KEY_A_B_C"
    keys = store.keys_for("payments", datetime(1999, 1, 1, tzinfo=UTC))
    assert [k.state for k in keys] == ["current", "previous"]
    keys = store.keys_for("payments", datetime(2001, 1, 1, tzinfo=UTC))  # previous expired
    assert [k.state for k in keys] == ["current"]
    assert store.keys_for("ghost") == []


class FakeSecretReader:
    """Fake secret scope (labelled fake): a dict, counts reads. Never a real token."""

    def __init__(self, data: dict[tuple[str, str], str]) -> None:
        self.data = data
        self.reads = 0
        self.fail = False

    def get(self, scope: str, key: str) -> str | None:
        self.reads += 1
        if self.fail:
            raise RuntimeError("scope unavailable")
        return self.data.get((scope, key))


def test_secret_scope_store_with_fake_reader_and_cache() -> None:
    t = [0.0]
    reader = FakeSecretReader(
        {("sc", "agent-payments-current"): SECRET_A, ("sc", "agent-payments-previous"): SECRET_OLD}
    )
    store = SecretScopeKeyStore(reader, "sc", ttl_s=60, clock=lambda: t[0])
    assert len(store.keys_for("payments")) == 2
    n = reader.reads
    store.keys_for("payments")
    assert reader.reads == n  # cached
    t[0] = 61
    store.keys_for("payments")
    assert reader.reads > n  # TTL passed
    reader.fail = True
    t[0] = 200
    assert store.keys_for("payments") == []  # outage: no key, no exception
    with pytest.raises(KeyStoreError):
        SecretScopeKeyStore(reader, "FILL-ME-scope")


# ------------------------------------------------------------------ bearer / identity port


def bearer_verifier(**kw: Any) -> tuple[IngressVerifier, FakeIdentityVerifier]:
    fake = FakeIdentityVerifier({"tok-sp": "sp-app-id", "tok-nomap": "someone-else"})
    ident = AgentIdentityMap({"sp-app-id": frozenset({"payments", "support"})})
    return IngressVerifier(
        kind="databricks_sp", keys=None, identity=fake, identities=ident, clock=Clock(), **kw
    ), fake


def test_bearer_valid_and_maps_to_agent_list() -> None:
    v, _ = bearer_verifier()
    ident = v.authenticate("POST", PATH, {"Authorization": "Bearer tok-sp"}, BODY)
    assert ident.kind == "databricks_sp" and ident.agent_ids == frozenset({"payments", "support"})
    assert ident.allows("support") and not ident.allows("treasury")


def test_bearer_failures() -> None:
    v, _ = bearer_verifier()
    assert reason_of(v, {"Authorization": "Bearer nope"}) == ("invalid_token", 401)
    assert reason_of(v, {"Authorization": "Bearer tok-nomap"}) == ("unknown_principal", 403)
    h = {"Authorization": "Bearer tok-sp", H_AGENT: "treasury"}
    assert reason_of(v, h) == ("agent_mismatch", 403)
    assert reason_of(v, {}) == ("missing_credential", 401)
    # an HMAC signature is not accepted by a databricks_sp-only verifier
    assert reason_of(v, sign())[0] == "missing_credential"


def test_hmac_only_verifier_ignores_bearer() -> None:
    assert reason_of(verifier(), {"Authorization": "Bearer tok-sp"})[0] == "missing_credential"


def test_scim_me_verifier_caches_successes_only_and_hides_the_token() -> None:
    t = [0.0]
    calls: list[str] = []

    def call(token: str) -> VerifiedIdentity:
        calls.append(token)
        if token == "bad":
            raise RuntimeError("401 Unauthorized for token bad")
        return VerifiedIdentity("sp-1")

    v = ScimMeIdentityVerifier("https://example.invalid", ttl_s=300, call=call, clock=lambda: t[0])
    assert v.verify("good").principal == "sp-1"
    v.verify("good")
    assert len(calls) == 1  # cached
    t[0] = 301
    v.verify("good")
    assert len(calls) == 2  # TTL passed
    with pytest.raises(IdentityError) as ei:
        v.verify("bad")
    assert "bad" not in str(ei.value)
    with pytest.raises(IdentityError):
        v.verify("bad")
    assert calls.count("bad") == 1  # a refused token is cached briefly (F8, 30 s)
    t[0] += 31
    with pytest.raises(IdentityError):
        v.verify("bad")
    assert calls.count("bad") == 2  # negative TTL passed
    with pytest.raises(IdentityError):
        ScimMeIdentityVerifier("FILL-ME-host")


def test_identity_map_file(tmp_path: Path) -> None:
    f = tmp_path / "ids.yaml"
    f.write_text(
        "principals:\n"
        "  - principal: sp-1\n    agents: [a1, '*', FILL-ME-agent]\n"
        "  - principal: FILL-ME-sp\n    agents: [a2]\n",
        encoding="utf-8",
    )
    m = AgentIdentityMap.from_file(f)
    assert m.agents_for("sp-1") == frozenset({"a1"})  # wildcard and FILL-ME dropped
    assert m.agents_for("FILL-ME-sp") == frozenset() and m.agents_for("nobody") == frozenset()
    assert AgentIdentityMap.from_file(tmp_path / "missing.yaml").agents_for("sp-1") == frozenset()


def test_committed_identity_sample_maps_nothing() -> None:
    from supervisor.config import REPO_ROOT

    m = AgentIdentityMap.from_file(REPO_ROOT / "config" / "agent_identities.yaml")
    assert m.agents_for("FILL-ME-service-principal-application-id") == frozenset()


# ------------------------------------------------------------------ client credential


def test_client_credential_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(CredentialError):
        IngressCredential("payments", "short")
    with pytest.raises(CredentialError):
        IngressCredential("bad id", SECRET_A)
    with pytest.raises(CredentialError):
        IngressCredential("payments")
    key = tmp_path / "k"
    key.write_text(SECRET_A + "\n", encoding="utf-8")
    if os.name == "posix":
        os.chmod(key, 0o644)
        with pytest.raises(CredentialError):
            credential_from_env("payments", str(key))
        os.chmod(key, 0o600)
    cred = credential_from_env("payments", str(key))
    assert cred is not None and SECRET_A not in repr(cred)
    monkeypatch.setenv("SUPERVISOR_AGENT_KEY", SECRET_OLD)
    assert credential_from_env("payments") is not None
    monkeypatch.delenv("SUPERVISOR_AGENT_KEY")
    assert credential_from_env("payments") is None


def test_headers_are_fresh_each_call() -> None:
    cred = IngressCredential("payments", new_secret())
    a, b = cred.headers_for("POST", PATH, BODY), cred.headers_for("POST", PATH, BODY)
    assert a[H_NONCE] != b[H_NONCE] and a[H_SIGNATURE] != b[H_SIGNATURE]
    assert a[H_TIMESTAMP].isdigit()


def test_scim_me_uses_short_sdk_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    # Review fix: SDK defaults (60 s + 300 s retries) would hold a worker for minutes.
    pytest.importorskip("databricks.sdk")
    import databricks.sdk as dbsdk

    from supervisor.adapters.auth import agent_creds_identity as ident

    seen: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kw: Any) -> None:
            seen.update(kw)

            class Me:
                @staticmethod
                def me() -> Any:
                    return type("U", (), {"user_name": "sp-1", "display_name": "SP"})()

            self.current_user = Me()

    monkeypatch.setattr(dbsdk, "WorkspaceClient", FakeClient)
    assert ident.scim_me("https://h", "tok").principal == "sp-1"
    assert seen["http_timeout_seconds"] <= 10 and seen["retry_timeout_seconds"] <= 15


@pytest.mark.parametrize("header", [H_AGENT, H_NONCE, H_SIGNATURE])
def test_trailing_newline_in_a_credential_header_is_malformed(header: str) -> None:
    h = sign()
    h[header] = h[header] + "\n"
    assert reason_of(verifier(), h) == ("malformed_credential", 401)
