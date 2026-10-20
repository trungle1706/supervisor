"""Per-agent ingress key stores (WP20, ADR D14).

``KeyStore.keys_for(agent_id)`` returns the keys that are valid now: at most two, the
``current`` key and the ``previous`` key (rotation overlap) while it has not expired. An
unknown agent returns an empty list. Three backends:

* ``FileKeyStore``     laptop: YAML file, chmod 600 (checked on POSIX), written atomically by the
                       CLI (``python -m supervisor.gateway.ingress_auth issue|rotate``).
* ``EnvKeyStore``      ``INGRESS_AGENT_KEY_<ID>`` (current) and ``..._<ID>_PREV`` (previous,
                       optional ``..._<ID>_PREV_EXPIRES`` as RFC 3339); ``<ID>`` = agent id upper
                       case, every char outside ``[A-Z0-9]`` becomes ``_``.
* ``SecretScopeKeyStore``  Databricks secret scope / Unity Catalog secret through a
                       ``SecretReader`` port (a fake in tests). Secret names:
                       ``agent-<id>-current``, ``agent-<id>-previous``,
                       ``agent-<id>-previous-expires``. Reads are cached for ``ttl_s``.

Secrets are plain strings of at least ``MIN_SECRET_CHARS`` chars; shorter ones and FILL-ME
placeholders are ignored (the agent then has no valid key). A secret never appears in a repr or log.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import yaml

from supervisor.config import is_placeholder
from supervisor.core.errors import SupervisorError
from supervisor.gateway.ingress_sign import (
    MIN_SECRET_CHARS,
    CredentialError,
    check_key_file_mode,
)

log = logging.getLogger("supervisor.ingress")

ENV_PREFIX = "INGRESS_AGENT_KEY_"


class KeyStoreError(SupervisorError):
    """The key store cannot be read or written (bad mode, bad YAML, unknown backend)."""


@dataclass(frozen=True)
class AgentKey:
    key_id: str
    secret: str
    state: str = "current"  # current | previous
    expires_at: datetime | None = None

    def __repr__(self) -> str:
        return f"AgentKey(key_id={self.key_id!r}, state={self.state!r}, secret=***)"

    def valid_at(self, now: datetime) -> bool:
        if is_placeholder(self.secret) or len(self.secret) < MIN_SECRET_CHARS:
            return False
        return self.expires_at is None or now < self.expires_at


class KeyStore(Protocol):
    name: str

    def keys_for(self, agent_id: str, now: datetime | None = None) -> list[AgentKey]: ...


class SecretReader(Protocol):
    """Port to a secret store. ``get`` returns the value or None when the secret is absent."""

    def get(self, scope: str, key: str) -> str | None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _valid_only(keys: list[AgentKey], now: datetime) -> list[AgentKey]:
    return [k for k in keys if k.valid_at(now)][:2]


# ---------------------------------------------------------------------------- file


class FileKeyStore:
    name = "file"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._cache: tuple[float, dict[str, list[AgentKey]]] | None = None

    def _load(self) -> dict[str, list[AgentKey]]:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return {}
        with self._lock:
            if self._cache is not None and self._cache[0] == st.st_mtime_ns:
                return self._cache[1]
            try:
                check_key_file_mode(self.path)
            except CredentialError as exc:
                raise KeyStoreError(str(exc)) from exc
            try:
                doc = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise KeyStoreError(f"cannot read key file: {type(exc).__name__}") from exc
            out: dict[str, list[AgentKey]] = {}
            agents = doc.get("agents") if isinstance(doc, dict) else None
            for agent_id, entry in (agents or {}).items():
                keys = []
                for k in (entry or {}).get("keys") or []:
                    if not isinstance(k, dict):
                        continue
                    keys.append(
                        AgentKey(
                            key_id=str(k.get("key_id", "")),
                            secret=str(k.get("secret", "")),
                            state=str(k.get("state", "current")),
                            expires_at=parse_ts(k.get("expires_at")),
                        )
                    )
                out[str(agent_id)] = keys
            self._cache = (st.st_mtime_ns, out)
            return out

    def keys_for(self, agent_id: str, now: datetime | None = None) -> list[AgentKey]:
        return _valid_only(self._load().get(agent_id, []), now or _utcnow())

    # -- writes (CLI) --------------------------------------------------------------

    def read_all(self) -> dict[str, list[AgentKey]]:
        return {k: list(v) for k, v in self._load().items()}

    def write_all(self, data: Mapping[str, list[AgentKey]]) -> None:
        doc = {
            "agents": {
                agent: {
                    "keys": [
                        {
                            "key_id": k.key_id,
                            "state": k.state,
                            "secret": k.secret,
                            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                        }
                        for k in keys
                    ]
                }
                for agent, keys in sorted(data.items())
            }
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".agent_keys.")
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("# Per-agent ingress keys. SECRET: chmod 600, never commit.\n")
                yaml.safe_dump(doc, fh, sort_keys=False)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        with self._lock:
            self._cache = None


# ---------------------------------------------------------------------------- env


def env_name(agent_id: str) -> str:
    return ENV_PREFIX + re.sub(r"[^A-Z0-9]", "_", agent_id.upper())


class EnvKeyStore:
    name = "env"

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else os.environ

    def keys_for(self, agent_id: str, now: datetime | None = None) -> list[AgentKey]:
        base = env_name(agent_id)
        keys = []
        cur = self._environ.get(base)
        if cur:
            keys.append(AgentKey("env-current", cur.strip(), "current"))
        prev = self._environ.get(base + "_PREV")
        if prev:
            exp = parse_ts(self._environ.get(base + "_PREV_EXPIRES"))
            keys.append(AgentKey("env-previous", prev.strip(), "previous", exp))
        return _valid_only(keys, now or _utcnow())


# ---------------------------------------------------------------------------- secret scope


class SecretScopeKeyStore:
    name = "secret_scope"

    def __init__(
        self,
        reader: SecretReader,
        scope: str,
        ttl_s: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if is_placeholder(scope):
            raise KeyStoreError("INGRESS_SECRET_SCOPE is not configured (FILL-ME)")
        self._reader = reader
        self._scope = scope
        self._ttl = ttl_s
        self._clock = clock
        self._cache: dict[str, tuple[float, list[AgentKey]]] = {}
        self._lock = threading.Lock()

    def _fetch(self, agent_id: str) -> list[AgentKey]:
        r, s = self._reader, self._scope
        keys = []
        cur = r.get(s, f"agent-{agent_id}-current")
        if cur:
            keys.append(AgentKey("scope-current", cur.strip(), "current"))
        prev = r.get(s, f"agent-{agent_id}-previous")
        if prev:
            exp = parse_ts(r.get(s, f"agent-{agent_id}-previous-expires"))
            keys.append(AgentKey("scope-previous", prev.strip(), "previous", exp))
        return keys

    def keys_for(self, agent_id: str, now: datetime | None = None) -> list[AgentKey]:
        t = self._clock()
        with self._lock:
            hit = self._cache.get(agent_id)
            if hit is not None and t - hit[0] < self._ttl:
                keys = hit[1]
            else:
                try:
                    keys = self._fetch(agent_id)
                except Exception as exc:  # noqa: BLE001 - a reader outage is "no key": 401, never 500
                    log.error("secret scope read failed: %s", type(exc).__name__)
                    return []
                if len(self._cache) > 4096:
                    self._cache.clear()
                self._cache[agent_id] = (t, keys)
        return _valid_only(keys, now or _utcnow())


class DatabricksSecretReader:
    """``SecretReader`` over the workspace secrets API (OAuth through the SDK default auth).
    Not exercised against a live workspace here; tests use a fake reader."""

    def __init__(self, host: str | None = None) -> None:
        self._host = host

    def get(self, scope: str, key: str) -> str | None:
        import base64

        from databricks.sdk import WorkspaceClient  # optional extra: databricks
        from databricks.sdk.errors import NotFound

        client = WorkspaceClient(host=self._host) if self._host else WorkspaceClient()
        try:
            resp = client.secrets.get_secret(scope=scope, key=key)
        except NotFound:
            return None
        if not resp.value:
            return None
        return base64.b64decode(resp.value).decode("utf-8")


# ---------------------------------------------------------------------------- rotation (pure)


def make_key_id(now: datetime) -> str:
    return "k-" + now.strftime("%Y%m%d%H%M%S")


def rotate_keys(
    existing: list[AgentKey], new_secret: str, now: datetime, overlap: timedelta
) -> list[AgentKey]:
    """New current key; the old current becomes ``previous`` and expires after ``overlap``.
    An older previous key is dropped, so at most two keys are active."""
    new = AgentKey(make_key_id(now), new_secret, "current", None)
    old_current = [k for k in existing if k.state == "current"]
    out = [new]
    if old_current:
        out.append(
            AgentKey(old_current[0].key_id, old_current[0].secret, "previous", now + overlap)
        )
    return out
