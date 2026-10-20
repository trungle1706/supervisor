"""Databricks service-principal identity for agent ingress (WP20, ADR D14).

``IdentityVerifier`` is the port: a bearer token in, a ``VerifiedIdentity`` out, or
``IdentityError``. Two implementations:

* ``ScimMeIdentityVerifier``  real: workspace SCIM ``Me`` (``current_user.me()``) called with the
  caller's own token, result cached by the SHA-256 of the token for ``ttl_s`` seconds. Only
  successes are cached. The token itself is never stored, logged or put in an error.
* ``FakeIdentityVerifier``    tests: a dict token -> principal, labelled ``fake``.

``AgentIdentityMap`` reads ``config/agent_identities.yaml`` (principal -> allowed agent ids).
A principal that is not listed has no agent: the request is refused with 403.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from supervisor.config import is_placeholder
from supervisor.core.errors import SupervisorError

log = logging.getLogger("supervisor.ingress")


class IdentityError(SupervisorError):
    """The bearer token is not valid, or the identity service is unreachable."""


@dataclass(frozen=True)
class VerifiedIdentity:
    principal: str  # SCIM userName (the application id for a service principal)
    display_name: str = ""


class IdentityVerifier(Protocol):
    name: str

    def verify(self, token: str) -> VerifiedIdentity: ...


class FakeIdentityVerifier:
    """Test double (``mock``): knows a fixed set of tokens. Counts calls, to test caching."""

    name = "fake"

    def __init__(self, tokens: Mapping[str, str]) -> None:
        self.tokens = dict(tokens)
        self.calls = 0

    def verify(self, token: str) -> VerifiedIdentity:
        self.calls += 1
        principal = self.tokens.get(token)
        if principal is None:
            raise IdentityError("token not accepted")
        return VerifiedIdentity(principal, principal)


MeCall = Callable[[str], VerifiedIdentity]
SCIM_HTTP_TIMEOUT_S = 10
SCIM_RETRY_TIMEOUT_S = 15


def scim_me(host: str, token: str) -> VerifiedIdentity:
    """SCIM ``Me`` with the caller's token (fresh client per call, dropped at return)."""
    from databricks.sdk import WorkspaceClient  # optional extra: databricks

    # Short timeouts: the SDK defaults (60 s per call, 300 s of retries) would hold a thread
    # pool worker for minutes per request while the workspace is slow or down.
    client = WorkspaceClient(
        host=host,
        token=token,
        auth_type="pat",
        http_timeout_seconds=SCIM_HTTP_TIMEOUT_S,
        retry_timeout_seconds=SCIM_RETRY_TIMEOUT_S,
    )
    me = client.current_user.me()
    principal = me.user_name or ""
    if not principal:
        raise IdentityError("workspace returned no user name")
    return VerifiedIdentity(principal, me.display_name or "")


class ScimMeIdentityVerifier:
    name = "scim_me"

    def __init__(
        self,
        host: str,
        ttl_s: int = 300,
        call: MeCall | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = 1024,
    ) -> None:
        if is_placeholder(host):
            raise IdentityError("DATABRICKS_HOST is not configured")
        self._host = host
        self._ttl = ttl_s
        self._call = call or (lambda tok: scim_me(self._host, tok))
        self._clock = clock
        self._max = max_entries
        self._cache: dict[str, tuple[float, VerifiedIdentity]] = {}
        self._lock = threading.Lock()

    def verify(self, token: str) -> VerifiedIdentity:
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = self._clock()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and now < hit[0]:
                return hit[1]
        try:
            ident = self._call(token)
        except IdentityError:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK errors: refuse, never 500; no token text
            log.warning("scim me failed: %s", type(exc).__name__)
            raise IdentityError("identity service refused the token") from exc
        with self._lock:
            if len(self._cache) >= self._max:
                self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
                if len(self._cache) >= self._max:
                    self._cache.clear()
            self._cache[key] = (now + self._ttl, ident)
        return ident


class AgentIdentityMap:
    """principal -> frozenset of allowed agent ids."""

    def __init__(self, mapping: Mapping[str, frozenset[str]]) -> None:
        self._map = dict(mapping)

    @classmethod
    def from_file(cls, path: Path) -> AgentIdentityMap:
        try:
            doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            return cls({})
        except (OSError, yaml.YAMLError) as exc:
            raise IdentityError(f"cannot read agent identities: {type(exc).__name__}") from exc
        out: dict[str, set[str]] = {}
        for item in (doc.get("principals") if isinstance(doc, dict) else None) or []:
            if not isinstance(item, dict):
                continue
            principal = str(item.get("principal", "")).strip()
            if is_placeholder(principal):
                continue
            agents = {
                str(a) for a in (item.get("agents") or []) if a and not is_placeholder(str(a))
            }
            agents.discard("*")  # no wildcard: every agent id is listed on purpose
            out.setdefault(principal, set()).update(agents)
        return cls({p: frozenset(a) for p, a in out.items()})

    def agents_for(self, principal: str) -> frozenset[str]:
        return self._map.get(principal, frozenset())
