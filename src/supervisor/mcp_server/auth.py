"""Authentication of a connected app (WP-G6): the WP20 HMAC credential path.

The app signs every request like an agent does (``X-Supervisor-Agent`` = the app id,
timestamp, nonce, signature over method, path and body hash; ``gateway/ingress_sign.py``). The
check is the one of ``IngressVerifier`` (header sizes, 5 minute window, constant-time compare,
single-use nonce), with the keys of the WP20 key store and one more step: the app id must be a
row of ``mcp_app`` and the current key must be the one the row hashes (a previous key stays valid
while the store says so). ``MCP_SERVER_ENABLED`` does not need ``INGRESS_AUTH_ENABLED``; the MCP
server always requires the credential.

Status: ``blocked`` is refused here (403). ``pending`` is let through to the protocol layer,
which answers ``initialize`` and ``ping`` and refuses everything else until an admin approves.
Every refusal writes one ``console_action`` row (permission ``mcp.auth``, outcome ``denied``,
detail = reason code, before_hash = SHA-256 of the body).
"""

from __future__ import annotations

import hmac
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from supervisor.adapters.auth.agent_creds import AgentKey, KeyStore
from supervisor.adapters.auth.audit import audit_active, write_action
from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.gateway.ingress_auth import IngressRejected, IngressVerifier, build_key_store
from supervisor.gateway.ingress_sign import AGENT_ID_RE, H_AGENT, body_sha256
from supervisor.mcp_server.apps import McpAppService, key_hash_of

log = logging.getLogger("supervisor.mcp_server")

AUTH_METHOD = "mcp_hmac"


class AuthFailure(Exception):
    """A refused request: HTTP status, public message, reason code (audited, not shown)."""

    def __init__(self, status: int, message: str, reason: str, claimed: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.reason = reason
        self.claimed = claimed


@dataclass(frozen=True)
class AppIdentity:
    """A signed-in app: its row (no key hash), the principal it acts as, its scopes."""

    app: dict[str, Any]
    principal: AuthPrincipal
    scopes: frozenset[str]

    @property
    def approved(self) -> bool:
        return self.app["status"] == "approved"


class AppKeyStore:
    """Wraps the WP20 key store: a key counts only for an app that has a row, and the current key
    must match the hash in the row."""

    name = "mcp_app"

    def __init__(self, inner: KeyStore, apps: McpAppService) -> None:
        self.inner = inner
        self.apps = apps

    def keys_for(self, agent_id: str, now: datetime | None = None) -> list[AgentKey]:
        row = self.apps.get_row(agent_id)
        if row is None:
            return []
        out = []
        for k in self.inner.keys_for(agent_id, now):
            if k.state != "current" or hmac.compare_digest(
                key_hash_of(k.secret).encode(), str(row["key_hash"]).encode()
            ):
                out.append(k)
        return out


_lock = threading.Lock()
_verifier: IngressVerifier | None = None
_built_for: int | None = None


def set_verifier(verifier: IngressVerifier | None) -> None:
    """Install a verifier (tests). None = build from the settings again."""
    global _verifier, _built_for
    with _lock:
        _verifier = verifier
        _built_for = None


def verifier_for(settings: Any, apps: McpAppService) -> IngressVerifier:
    global _verifier, _built_for
    with _lock:
        if _verifier is not None and (_built_for is None or _built_for == id(settings)):
            return _verifier
        _verifier = IngressVerifier(
            kind="hmac",
            keys=AppKeyStore(build_key_store(settings), apps),
            window_s=settings.ingress_replay_window_s,
            max_header=settings.ingress_max_header_bytes,
            nonce_cap_per_agent=settings.ingress_nonce_cap_per_agent,
        )
        _built_for = id(settings)
        return _verifier


def principal_of(row: dict[str, Any], roles: list[str]) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=f"mcp:{row['app_id']}",
        kind="service_principal",
        auth_method=AUTH_METHOD,
        roles=frozenset(r for r in roles if r != "admin"),  # an app never holds admin
        display_name=str(row["app_id"]),
    )


def precheck(ctx: Any, apps: McpAppService, headers: Any) -> None:
    """Header-only checks (sizes, shape, timestamp window): a bad request never makes the
    server buffer a body. Raises ``AuthFailure``."""
    claimed = headers.get(H_AGENT)
    claimed = claimed if isinstance(claimed, str) and AGENT_ID_RE.match(claimed) else None
    try:
        verifier_for(ctx.settings, apps).precheck(headers)
    except IngressRejected as exc:
        raise AuthFailure(exc.status_code, str(exc.detail), exc.reason, claimed) from exc
    except Exception as exc:  # noqa: BLE001 - a verifier bug is a 401, never a 500
        log.error("mcp precheck failed: %s", type(exc).__name__)
        raise AuthFailure(401, "authentication failed", "auth_unavailable", claimed) from exc


def authenticate(
    ctx: Any, apps: McpAppService, method: str, path: str, headers: Any, body: bytes
) -> AppIdentity:
    """The signed-in app, or ``AuthFailure``. Never raises anything else."""
    claimed = headers.get(H_AGENT)
    claimed = claimed if isinstance(claimed, str) and AGENT_ID_RE.match(claimed) else None
    try:
        verifier = verifier_for(ctx.settings, apps)
        ident = verifier.authenticate(method, path, headers, body)
    except IngressRejected as exc:
        raise AuthFailure(exc.status_code, str(exc.detail), exc.reason, claimed) from exc
    except Exception as exc:  # noqa: BLE001 - a store or verifier bug is a 401, never a 500
        log.error("mcp auth failed: %s", type(exc).__name__)
        raise AuthFailure(401, "authentication failed", "auth_unavailable", claimed) from exc
    row = apps.get_row(ident.principal)
    if row is None:  # the key store had the id but the table has no row (race, or a removed app)
        raise AuthFailure(401, "authentication failed", "unknown_agent", claimed)
    if row["status"] == "blocked":
        raise AuthFailure(403, "this app is blocked by an admin", "app_blocked", row["app_id"])
    try:
        apps.mark_connected(row)
    except Exception as exc:  # noqa: BLE001 - a bookkeeping write never refuses a signed call
        log.warning("mcp first-connect mark failed: %s", type(exc).__name__)
    view = apps.view(row)
    return AppIdentity(
        app=view,
        principal=principal_of(row, view["roles"]),
        scopes=frozenset(view["scopes"]),
    )


def audit_refusal(ctx: Any, failure: AuthFailure, path: str, body: bytes | None) -> None:
    """One ``console_action`` row for a refused request. Never raises."""
    if not audit_active(ctx.settings):
        return
    try:
        write_action(
            ctx.tables,
            ctx.clock,
            request_id=None,
            actor=None,
            actor_fallback=(f"unverified:{failure.claimed or 'none'}", "agent", AUTH_METHOD),
            permission="mcp.auth",
            method="POST",
            path=path,
            outcome="denied",
            target_kind=None,
            target_id=None,
            before_hash=body_sha256(body) if body is not None else None,
            detail=failure.reason,
        )
    except Exception as exc:  # noqa: BLE001 - an audit failure must not become a 500
        log.error("mcp auth audit write failed: %s", type(exc).__name__)
