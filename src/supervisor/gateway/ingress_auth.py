"""Agent ingress authentication (WP20, ADR D14, docs/ingress-auth.md).

Every agent-facing write route (``/gate/check``, ``/v1/gate/check``, ``/v1/traces``) can require
a per-agent credential. Off by default (``INGRESS_AUTH_ENABLED=0``): the routes then behave as
before. Two credential kinds, both deterministic (no model is involved, R1):

* HMAC-SHA256 per agent: ``X-Supervisor-Agent`` + ``X-Supervisor-Timestamp`` +
  ``X-Supervisor-Nonce`` + ``X-Supervisor-Signature`` (format: ``gateway/ingress_sign.py``).
  Checks, in this order: header sizes and shape, timestamp window (default 5 min), key lookup
  (current + previous key), constant-time compare (``hmac.compare_digest``), single-use nonce.
* Databricks service-principal OAuth bearer token (``Authorization: Bearer``): validated by the
  ``IdentityVerifier`` port (SCIM ``Me``, cached), then mapped to the agent ids it may speak
  for in ``config/agent_identities.yaml``.

Rejections are 401 (no or bad credential) or 403 (valid credential, wrong agent), never 500.
Each rejection writes one ``console_action`` row (permission ``ingress.auth``, outcome
``denied``, ``detail`` = reason code, ``before_hash`` = SHA-256 of the body; never the body) and
bumps ``ingress_rejected`` / ``ingress_rejected_<reason>`` in ``/gate/metrics``.

CLI (ASCII output)::

    python -m supervisor.gateway.ingress_auth issue  <agent_id> [--out-key-file PATH]
    python -m supervisor.gateway.ingress_auth rotate <agent_id> [--overlap-hours N]
    python -m supervisor.gateway.ingress_auth list
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from supervisor.adapters.auth.agent_creds import (
    EnvKeyStore,
    FileKeyStore,
    KeyStore,
    KeyStoreError,
    SecretScopeKeyStore,
    env_name,
    rotate_keys,
)
from supervisor.adapters.auth.agent_creds_identity import (
    AgentIdentityMap,
    IdentityError,
    IdentityVerifier,
    ScimMeIdentityVerifier,
)
from supervisor.gateway.ingress_sign import (
    AGENT_ID_RE,
    H_AGENT,
    H_NONCE,
    H_SIGNATURE,
    H_TIMESTAMP,
    NONCE_RE,
    SIG_RE,
    body_sha256,
    compute_signature,
    new_secret,
)

if TYPE_CHECKING:
    from supervisor.config import Settings

log = logging.getLogger("supervisor.ingress")

INGRESS_ATTR = "_supervisor_ingress_guard"  # set on a dependency that enforces ingress auth
BEARER_MAX_BYTES = 4096
BODY_FALLBACK_CAP = 10_000_000
NONCE_CACHE_MAX = 200_000
FWD_TOKEN_HEADER = "x-forwarded-access-token"  # noqa: S105 - a header name, not a secret

# reason code -> (HTTP status, public message). unknown_agent and bad_signature share a
# message on purpose: the caller cannot learn which agent ids exist.
_GENERIC = "authentication failed"
REASONS: dict[str, tuple[int, str]] = {
    "missing_credential": (401, "credential required"),
    "malformed_credential": (401, "malformed credential"),
    "header_too_large": (401, "malformed credential"),
    "stale_timestamp": (401, "timestamp outside the allowed window; check the agent clock"),
    "unknown_agent": (401, _GENERIC),
    "bad_signature": (401, _GENERIC),
    "replayed_nonce": (401, "nonce already used"),
    "invalid_token": (401, _GENERIC),
    "key_store_unavailable": (401, _GENERIC),
    "auth_unavailable": (401, _GENERIC),
    "agent_mismatch": (403, "credential is not valid for this agent id"),
    "unknown_principal": (403, "principal is not mapped to any agent"),
    "span_agent_mismatch": (403, "trace batch carries spans of another agent"),
    "body_too_large": (413, "body too large"),
    "nonce_cache_full": (429, "too many recent requests; retry later"),
}


class IngressRejected(HTTPException):
    """A refused ingress call. ``app.py`` answers it as ``{"error": ...}`` (4xx, never 500)."""

    def __init__(self, reason: str, extra_headers: Mapping[str, str] | None = None) -> None:
        status, message = REASONS[reason]
        headers = dict(extra_headers or {})
        if status == 401:
            headers["WWW-Authenticate"] = 'Bearer realm="supervisor"'
        super().__init__(status_code=status, detail=message, headers=headers or None)
        self.reason = reason


@dataclass(frozen=True)
class IngressIdentity:
    kind: str  # hmac | databricks_sp
    principal: str  # agent id (hmac) or the service principal name
    agent_ids: frozenset[str]  # agent ids this caller may speak for
    claimed_agent: str | None = None

    def allows(self, agent_id: str | None) -> bool:
        return agent_id is not None and agent_id in self.agent_ids


class NonceCache:
    """Single-use nonces per agent, kept for ``ttl_s`` seconds (memory only: one process)."""

    def __init__(self, ttl_s: int, clock: Callable[[], float] = time.time, max_entries: int = 0):
        self._ttl = ttl_s
        self._clock = clock
        self._max = max_entries or NONCE_CACHE_MAX
        self._seen: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._seen)

    def use(self, agent_id: str, nonce: str) -> str:
        """Record the nonce. Returns ``ok``, ``replayed`` or ``full``."""
        now = self._clock()
        with self._lock:
            key = (agent_id, nonce)
            exp = self._seen.get(key)
            if exp is not None and exp > now:
                return "replayed"
            if len(self._seen) >= self._max:
                self._seen = {k: v for k, v in self._seen.items() if v > now}
                if len(self._seen) >= self._max:
                    return "full"
            self._seen[key] = now + self._ttl
            return "ok"


class _HeadersLike(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...


class _CIHeaders:
    """Case-insensitive view for a plain dict (Starlette ``Headers`` already is)."""

    def __init__(self, raw: Mapping[str, str]) -> None:
        self._raw = {k.lower(): v for k, v in raw.items()}

    def get(self, key: str, default: Any = None) -> Any:
        return self._raw.get(key.lower(), default)


def _count(headers: Any, name: str) -> int:
    getlist = getattr(headers, "getlist", None)
    if callable(getlist):
        return len(getlist(name))
    return 1 if headers.get(name) is not None else 0


class IngressVerifier:
    """Pure check of one request: no web objects, no I/O besides the key store and the
    identity verifier. ``authenticate`` raises ``IngressRejected``."""

    def __init__(
        self,
        *,
        kind: str,
        keys: KeyStore | None,
        identity: IdentityVerifier | None = None,
        identities: AgentIdentityMap | None = None,
        window_s: int = 300,
        max_header: int = 512,
        clock: Callable[[], float] = time.time,
        nonces: NonceCache | None = None,
    ) -> None:
        self.kind = kind  # hmac | databricks_sp | both
        self.keys = keys
        self.identity = identity
        self.identities = identities or AgentIdentityMap({})
        self.window_s = window_s
        self.max_header = max_header
        self.clock = clock
        self.nonces = nonces or NonceCache(2 * window_s + 5, clock)

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def claimed_agent(headers: _HeadersLike) -> str | None:
        v = headers.get(H_AGENT)
        return v if isinstance(v, str) and AGENT_ID_RE.match(v) else None

    def _bearer(self, headers: _HeadersLike) -> str | None:
        auth = headers.get("authorization")
        if isinstance(auth, str) and auth[:7].lower() == "bearer ":
            return auth[7:].strip()
        fwd = headers.get(FWD_TOKEN_HEADER)
        return fwd.strip() if isinstance(fwd, str) and fwd.strip() else None

    # -- main -----------------------------------------------------------------

    def authenticate(
        self, method: str, path: str, headers: _HeadersLike, body: bytes
    ) -> IngressIdentity:
        if isinstance(headers, dict):
            headers = _CIHeaders(headers)
        for name in (H_AGENT, H_TIMESTAMP, H_NONCE, H_SIGNATURE):
            v = headers.get(name)
            if v is not None and (len(v) > self.max_header or _count(headers, name) > 1):
                raise IngressRejected("header_too_large")
        bearer = self._bearer(headers)
        if bearer is not None and len(bearer) > BEARER_MAX_BYTES:
            raise IngressRejected("header_too_large")
        sig = headers.get(H_SIGNATURE)
        if sig is not None and self.kind in ("hmac", "both"):
            return self._hmac(method, path, headers, body, sig)
        if bearer and self.kind in ("databricks_sp", "both"):
            return self._bearer_identity(headers, bearer)
        raise IngressRejected("missing_credential")

    def _hmac(
        self, method: str, path: str, headers: _HeadersLike, body: bytes, sig: str
    ) -> IngressIdentity:
        agent = headers.get(H_AGENT)
        ts = headers.get(H_TIMESTAMP)
        nonce = headers.get(H_NONCE)
        if not (agent and ts and nonce):
            raise IngressRejected("malformed_credential")
        if not (AGENT_ID_RE.match(agent) and NONCE_RE.match(nonce) and SIG_RE.match(sig)):
            raise IngressRejected("malformed_credential")
        if not (ts.isascii() and ts.isdigit() and len(ts) <= 12):
            raise IngressRejected("malformed_credential")
        if abs(self.clock() - int(ts)) > self.window_s:
            raise IngressRejected("stale_timestamp")
        try:
            keys = (
                self.keys.keys_for(agent, datetime.fromtimestamp(self.clock(), UTC))
                if self.keys is not None
                else []
            )
        except KeyStoreError as exc:
            log.error("ingress key store unavailable: %s", type(exc).__name__)
            raise IngressRejected("key_store_unavailable") from exc
        # Always run the compare, with a dummy key for an unknown agent, so timing does not
        # tell a known agent id from an unknown one.
        candidates = [k.secret for k in keys] or ["x" * 32]
        ok = False
        for secret in candidates:
            expected = compute_signature(secret, agent, ts, nonce, method, path, body)
            ok |= hmac.compare_digest(expected.encode("ascii"), sig.encode("ascii"))
        if not keys:
            raise IngressRejected("unknown_agent")
        if not ok:
            raise IngressRejected("bad_signature")
        state = self.nonces.use(agent, nonce)  # only a valid signature reaches the cache
        if state == "replayed":
            raise IngressRejected("replayed_nonce")
        if state == "full":
            raise IngressRejected("nonce_cache_full")
        return IngressIdentity("hmac", agent, frozenset({agent}), agent)

    def _bearer_identity(self, headers: _HeadersLike, token: str) -> IngressIdentity:
        if self.identity is None:
            raise IngressRejected("auth_unavailable")
        try:
            who = self.identity.verify(token)
        except IdentityError as exc:
            raise IngressRejected("invalid_token") from exc
        agents = self.identities.agents_for(who.principal)
        if not agents:
            raise IngressRejected("unknown_principal")
        claimed = headers.get(H_AGENT)
        if claimed is not None and claimed not in agents:
            raise IngressRejected("agent_mismatch")
        return IngressIdentity("databricks_sp", who.principal, agents, claimed)


# ---------------------------------------------------------------------------- guard


AuditFn = Callable[[dict[str, Any]], None]


@dataclass
class IngressGuard:
    """Verifier + metrics + audit. ``enabled=False`` makes every call a no-op."""

    enabled: bool
    verifier: IngressVerifier | None = None
    audit: AuditFn | None = None
    bump: Callable[[str], None] | None = None
    body_cap: Callable[[str], int] = field(default=lambda _p: BODY_FALLBACK_CAP)
    counts: dict[str, int] = field(default_factory=dict)

    def _count(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1
        if self.bump is not None:
            try:
                self.bump(name)
            except Exception:  # noqa: BLE001, S110 - metrics never break a request
                pass

    async def record_reject(
        self, request: Request, reason: str, body_hash: str | None, claimed: str | None
    ) -> None:
        """Metrics + one audit row. Never raises. The audit write runs in the thread pool: in
        databricks_app mode it is a SQL statement over HTTP and must not block the event loop."""
        self._count("ingress_rejected")
        self._count(f"ingress_rejected_{reason}")
        log.warning(
            "ingress rejected reason=%s path=%s agent=%s", reason, request.url.path, claimed or "-"
        )
        if self.audit is None:
            return
        try:
            await run_in_threadpool(
                self.audit,
                {
                    "request": request,
                    "reason": reason,
                    "body_hash": body_hash,
                    "claimed": claimed,
                },
            )
        except Exception as exc:  # noqa: BLE001 - an audit failure must not become a 500
            log.error("ingress audit write failed: %s", type(exc).__name__)

    async def authenticate(self, request: Request) -> IngressIdentity | None:
        """The FastAPI-side entry: read the body, check the credential, bind the identity to
        ``request.state.ingress``. None when ingress auth is off."""
        if not self.enabled:
            return None
        cached = getattr(request.state, "ingress", None)
        if isinstance(cached, IngressIdentity):
            return cached
        body_hash: str | None = None
        claimed: str | None = None
        try:
            if self.verifier is None:
                raise IngressRejected("auth_unavailable")
            claimed = self.verifier.claimed_agent(request.headers)
            body = await _read_capped(request, self.body_cap(request.url.path))
            body_hash = body_sha256(body)
            request.state.ingress_body_hash = body_hash
            try:
                ident = await run_in_threadpool(
                    self.verifier.authenticate,
                    request.method,
                    request.url.path,
                    request.headers,
                    body,
                )
            except IngressRejected:
                raise
            except Exception as exc:  # noqa: BLE001 - a store or verifier bug: 401, never 500
                log.error("ingress verifier failed: %s", type(exc).__name__)
                raise IngressRejected("auth_unavailable") from exc
        except IngressRejected as exc:
            await self.record_reject(request, exc.reason, body_hash, claimed)
            raise
        request.state.ingress = ident
        self._count("ingress_accepted")
        return ident

    async def reject_later(self, request: Request, reason: str, headers: Mapping[str, str]) -> None:
        """Reject after authentication (agent id mismatch found in the body). Raises."""
        ident = getattr(request.state, "ingress", None)
        claimed = ident.claimed_agent if isinstance(ident, IngressIdentity) else None
        await self.record_reject(
            request, reason, getattr(request.state, "ingress_body_hash", None), claimed
        )
        raise IngressRejected(reason, headers)


async def _read_capped(request: Request, cap: int) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise IngressRejected("body_too_large")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            raise IngressRejected("body_too_large")
    body = bytes(buf)
    request._body = body  # noqa: SLF001 - Starlette's own cache: the route can read it again
    return body


# ---------------------------------------------------------------------------- wiring

_lock = threading.Lock()
_override: IngressGuard | None = None
_built: tuple[int, IngressGuard] | None = None


def set_guard(guard: IngressGuard | None) -> None:
    """Install a guard (tests, embedding). None = build from settings again."""
    global _override, _built
    with _lock:
        _override = guard
        _built = None


def build_key_store(settings: Settings) -> KeyStore:
    kind = settings.effective_ingress_key_store
    if kind == "env":
        return EnvKeyStore()
    if kind == "secret_scope":
        from supervisor.adapters.auth.agent_creds import DatabricksSecretReader

        return SecretScopeKeyStore(
            DatabricksSecretReader(settings.databricks_host),
            settings.ingress_secret_scope,
            settings.ingress_key_cache_ttl_s,
        )
    assert settings.ingress_keys_file is not None
    return FileKeyStore(settings.ingress_keys_file)


def build_verifier(settings: Settings) -> IngressVerifier:
    kind = settings.effective_ingress_kind
    keys = build_key_store(settings) if kind in ("hmac", "both") else None
    identity: IdentityVerifier | None = None
    identities = None
    if kind in ("databricks_sp", "both"):
        assert settings.ingress_identities_file is not None
        identities = AgentIdentityMap.from_file(settings.ingress_identities_file)
        if settings.databricks_host:
            identity = ScimMeIdentityVerifier(
                settings.databricks_host, settings.ingress_identity_cache_ttl_s
            )
        else:
            log.error("INGRESS credential kind needs DATABRICKS_HOST; bearer tokens are refused")
    return IngressVerifier(
        kind=kind,
        keys=keys,
        identity=identity,
        identities=identities,
        window_s=settings.ingress_replay_window_s,
        max_header=settings.ingress_max_header_bytes,
    )


def _audit_to_gateway(settings: Settings) -> AuditFn:
    """Write one ``console_action`` row to the installed gateway's store (never builds one)."""
    from supervisor.adapters.auth.audit import audit_active, request_id_of, write_action
    from supervisor.gateway import wiring

    def audit(info: dict[str, Any]) -> None:
        if not audit_active(settings):
            return
        gw = wiring.peek_gateway()
        if gw is None:
            log.error("ingress audit skipped: no gateway store installed")
            return
        request: Request = info["request"]
        claimed = info["claimed"]
        write_action(
            gw.tables,
            gw.clock,
            request_id=request_id_of(request),
            actor=None,
            actor_fallback=(f"unverified:{claimed or 'none'}", "agent", "ingress"),
            permission="ingress.auth",
            method=request.method,
            path=request.url.path,
            outcome="denied",
            target_kind="agent" if claimed else None,
            target_id=claimed,
            before_hash=info["body_hash"],
            detail=info["reason"],
        )

    return audit


def _bump_gateway(name: str) -> None:
    from supervisor.gateway import wiring

    gw = wiring.peek_gateway()
    if gw is not None:
        gw.metrics.bump(name)


def build_guard(settings: Settings) -> IngressGuard:
    if not settings.ingress_auth_enabled:
        return IngressGuard(enabled=False)

    def cap(path: str) -> int:
        if path.endswith("/v1/traces"):
            return int(settings.otlp_max_body_bytes)
        return int(settings.max_request_bytes) or BODY_FALLBACK_CAP

    try:
        verifier: IngressVerifier | None = build_verifier(settings)
    except Exception as exc:  # noqa: BLE001 - misconfig: fail closed (every call 401)
        log.error("ingress auth is ON but the verifier cannot be built: %s", type(exc).__name__)
        verifier = None
    return IngressGuard(
        enabled=True,
        verifier=verifier,
        audit=_audit_to_gateway(settings),
        bump=_bump_gateway,
        body_cap=cap,
    )


def get_guard() -> IngressGuard:
    """The process guard: the installed one, else built from the settings (cached per settings
    object, so a settings reload rebuilds it)."""
    global _built
    from supervisor.config import get_settings

    with _lock:
        if _override is not None:
            return _override
        settings = get_settings()
        if _built is None or _built[0] != id(settings):
            _built = (id(settings), build_guard(settings))
        return _built[1]


async def ingress_gate(request: Request) -> IngressIdentity | None:
    """FastAPI dependency for ``POST /gate/check`` and ``/v1/gate/check``: authenticate, then
    require the body's ``agent_id`` to be one the credential speaks for (spoofing: 403)."""
    guard = get_guard()
    ident = await guard.authenticate(request)
    if ident is None:
        return None
    try:
        payload = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return ident  # the route answers 400 for a malformed body, after authentication
    agent = payload.get("agent_id") if isinstance(payload, dict) else None
    if isinstance(agent, str) and not ident.allows(agent):
        await guard.reject_later(request, "agent_mismatch", {})
    return ident


setattr(ingress_gate, INGRESS_ATTR, True)  # noqa: B010 - the contract test looks for it


async def ingress_traces(request: Request) -> IngressIdentity | None:
    """Authenticate ``POST /v1/traces``. The span agent ids are checked by the receiver once
    the batch is parsed (``check_span_agents``)."""
    return await get_guard().authenticate(request)


setattr(ingress_traces, INGRESS_ATTR, True)  # noqa: B010


async def check_span_agents(request: Request, agent_ids: list[str | None]) -> None:
    """A batch may only carry spans of agents the credential speaks for. Raises 403 with the
    number of foreign spans in ``X-Supervisor-Rejected``; nothing of the batch is written."""
    ident = getattr(request.state, "ingress", None)
    if not isinstance(ident, IngressIdentity):
        return
    foreign = sum(1 for a in agent_ids if a is not None and not ident.allows(a))
    if foreign:
        await get_guard().reject_later(
            request, "span_agent_mismatch", {"X-Supervisor-Rejected": str(foreign)}
        )


def startup_check(settings: Settings) -> None:
    """One log line at startup: a warning when ingress auth is off outside dev mode."""
    if settings.ingress_auth_enabled:
        if get_guard().verifier is None:
            log.error("INGRESS_AUTH_ENABLED=1 but the verifier is not usable: ingress is refused")
        return
    if settings.supervisor_mode != "dev":
        log.warning(
            "INGRESS_AUTH_ENABLED=0: /gate/check and /v1/traces accept any caller for any agent id"
        )


# ---------------------------------------------------------------------------- CLI


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _write_client_file(path: Path, secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(secret + "\n")
    if os.name == "posix":
        os.chmod(path, 0o600)


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m supervisor.gateway.ingress_auth",
        description="Issue and rotate per-agent ingress keys (HMAC).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, text in (("issue", "first key for an agent"), ("rotate", "new current key")):
        s = sub.add_parser(name, help=text)
        s.add_argument("agent_id")
        s.add_argument("--keys-file", help="key store file (default: INGRESS_KEYS_FILE)")
        s.add_argument("--out-key-file", help="write the secret here (chmod 600), do not print it")
        s.add_argument("--overlap-hours", type=int, help="previous key lifetime (rotate)")
    ls = sub.add_parser("list", help="agents, key ids, state, expiry (no secrets)")
    ls.add_argument("--keys-file")
    ns = p.parse_args(argv)

    from supervisor.config import load_settings

    settings = load_settings()
    store_kind = settings.effective_ingress_key_store
    path = Path(ns.keys_file) if ns.keys_file else settings.ingress_keys_file
    assert path is not None
    store = FileKeyStore(path)
    now = _utcnow()

    if ns.cmd == "list":
        try:
            data = store.read_all()
        except KeyStoreError as exc:
            _out(f"[FAIL] {exc}")
            return 1
        for agent, keys in sorted(data.items()):
            for k in keys:
                exp = k.expires_at.isoformat() if k.expires_at else "-"
                _out(f"{agent} {k.key_id} {k.state} expires={exp}")
        _out(f"[OK] {len(data)} agent(s) in {path.name}")
        return 0

    agent_id = ns.agent_id
    if not AGENT_ID_RE.match(agent_id):
        _out("[FAIL] agent id must match [A-Za-z0-9_.:@-]{1,128}")
        return 2
    overlap = timedelta(hours=ns.overlap_hours or settings.ingress_key_overlap_hours)
    secret = new_secret()
    out_file = Path(ns.out_key_file) if ns.out_key_file else None

    if store_kind != "file" and not ns.keys_file:
        # env / secret scope: the CLI cannot write them; it prints what to set, once.
        _out(f"[OK] new key for {agent_id} (shown once; store kind is {store_kind})")
        if store_kind == "env":
            _out(f"     set {env_name(agent_id)}=<secret>")
            if ns.cmd == "rotate":
                _out(f"     move the old value to {env_name(agent_id)}_PREV and set")
                _out(f"     {env_name(agent_id)}_PREV_EXPIRES=<RFC 3339 time, now + overlap>")
        else:
            _out(f"     put it in secret agent-{agent_id}-current of scope")
            _out(f"     {settings.ingress_secret_scope or 'FILL-ME-scope'}")
            if ns.cmd == "rotate":
                _out(f"     move the old value to agent-{agent_id}-previous (+ -previous-expires)")
        if out_file:
            _write_client_file(out_file, secret)
            _out(f"     secret written to {out_file.name} (chmod 600)")
        else:
            _out(f"     secret: {secret}")
        return 0

    try:
        data = store.read_all()
    except KeyStoreError as exc:
        _out(f"[FAIL] {exc}")
        return 1
    existing = data.get(agent_id, [])
    if ns.cmd == "issue" and existing:
        _out(f"[FAIL] {agent_id} already has keys; use rotate")
        return 1
    if ns.cmd == "rotate" and not existing:
        _out(f"[FAIL] {agent_id} has no key; use issue")
        return 1
    data[agent_id] = rotate_keys(existing, secret, now, overlap)
    store.write_all(data)
    verb = "issued" if ns.cmd == "issue" else "rotated"
    _out(f"[OK] key {verb} for {agent_id} in {path.name}")
    if ns.cmd == "rotate":
        _out(f"     previous key valid until {(now + overlap).isoformat(timespec='seconds')}")
    if out_file:
        _write_client_file(out_file, secret)
        _out(f"     secret written to {out_file.name} (chmod 600); give it to the agent")
    else:
        _out(f"     secret (shown once): {secret}")
    return 0


def main(argv: list[str] | None = None) -> int:
    from supervisor.core.errors import SupervisorError

    try:
        return _cli(argv)
    except SupervisorError as exc:
        _out(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
