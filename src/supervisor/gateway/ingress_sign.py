"""Ingress request signing (WP20, ADR D14): the pure part shared by the SDK and the server.

No web, SQL or Databricks imports, so an agent process can use it without the server stack.

Signature (HMAC-SHA256, hex, header ``X-Supervisor-Signature: v1=<hex>``) over this string::

    v1 \\n <agent_id> \\n <timestamp> \\n <nonce> \\n <METHOD> \\n <path> \\n <sha256 hex of body>

* ``timestamp`` = Unix seconds (``X-Supervisor-Timestamp``), checked against a 5-minute window.
* ``nonce``     = 16-64 chars ``[A-Za-z0-9_-]`` (``X-Supervisor-Nonce``), single use per agent.
* The body hash is over the exact bytes on the wire (compressed bytes for a gzip batch).
* Method and path are part of the string: a signature for ``/v1/traces`` cannot be replayed
  on ``/gate/check``.
The key is the secret string as written (UTF-8 bytes), at least ``MIN_SECRET_CHARS`` chars.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import stat
import time
from collections.abc import Callable
from pathlib import Path

H_AGENT = "X-Supervisor-Agent"
H_SIGNATURE = "X-Supervisor-Signature"
H_TIMESTAMP = "X-Supervisor-Timestamp"
H_NONCE = "X-Supervisor-Nonce"
SIG_PREFIX = "v1="
VERSION = "v1"
MIN_SECRET_CHARS = 32
ENV_KEY = "SUPERVISOR_AGENT_KEY"
ENV_KEY_FILE = "SUPERVISOR_AGENT_KEY_FILE"

AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}\Z")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}\Z")
SIG_RE = re.compile(r"^v1=[0-9a-f]{64}\Z")


class CredentialError(Exception):
    """The client credential cannot be loaded (missing, too short, key file readable by others)."""


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def string_to_sign(
    agent_id: str, timestamp: str, nonce: str, method: str, path: str, body_hash: str
) -> bytes:
    parts = (VERSION, agent_id, timestamp, nonce, method.upper(), path, body_hash)
    return "\n".join(parts).encode("utf-8")


def compute_signature(
    secret: str, agent_id: str, timestamp: str, nonce: str, method: str, path: str, body: bytes
) -> str:
    mac = hmac.new(
        secret.encode("utf-8"),
        string_to_sign(agent_id, timestamp, nonce, method, path, body_sha256(body)),
        hashlib.sha256,
    )
    return SIG_PREFIX + mac.hexdigest()


def new_nonce() -> str:
    return secrets.token_urlsafe(18)  # 24 chars


def new_secret() -> str:
    return secrets.token_hex(32)  # 64 hex chars, 256 bits


def check_key_file_mode(path: Path) -> None:
    """On POSIX a key file must not be readable by group or others (chmod 600)."""
    if os.name != "posix":
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise CredentialError(f"key file {path.name} has mode {mode:o}; run: chmod 600 <file>")


class IngressCredential:
    """What an agent sends with a request: an HMAC signature or a bearer token.

    ``headers_for(method, path, body)`` returns the headers to add; call it once per request
    (it makes a fresh nonce and timestamp). ``bearer`` is a callable so a Databricks agent can
    hand over a token that its own SDK refreshes; the token is never stored here."""

    def __init__(
        self,
        agent_id: str | None = None,
        secret: str | None = None,
        bearer: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (secret is None) == (bearer is None):
            raise CredentialError("give exactly one of secret (HMAC) or bearer")
        if secret is not None:
            if agent_id is None or not AGENT_ID_RE.match(agent_id):
                raise CredentialError("an HMAC credential needs a valid agent id")
            if len(secret) < MIN_SECRET_CHARS:
                raise CredentialError(f"the secret must have at least {MIN_SECRET_CHARS} chars")
        self.agent_id = agent_id
        self._secret = secret
        self._bearer = bearer
        self._clock = clock

    def __repr__(self) -> str:
        kind = "hmac" if self._secret else "bearer"
        return f"IngressCredential(kind={kind}, agent={self.agent_id})"

    def headers_for(self, method: str, path: str, body: bytes) -> dict[str, str]:
        if self._bearer is not None:
            headers = {"Authorization": f"Bearer {self._bearer()}"}
            if self.agent_id:
                headers[H_AGENT] = self.agent_id
            return headers
        assert self._secret is not None and self.agent_id is not None
        ts = str(int(self._clock()))
        nonce = new_nonce()
        return {
            H_AGENT: self.agent_id,
            H_TIMESTAMP: ts,
            H_NONCE: nonce,
            H_SIGNATURE: compute_signature(
                self._secret, self.agent_id, ts, nonce, method, path, body
            ),
        }


def credential_from_env(agent_id: str, key_file: str | None = None) -> IngressCredential | None:
    """HMAC credential from ``key_file`` or ``SUPERVISOR_AGENT_KEY_FILE`` (first line is the
    secret) or ``SUPERVISOR_AGENT_KEY``. None when none of them is set (unsigned client)."""
    path = key_file or os.environ.get(ENV_KEY_FILE)
    if path:
        p = Path(path)
        try:
            check_key_file_mode(p)
            secret = p.read_text(encoding="utf-8").splitlines()[0].strip()
        except (OSError, IndexError) as exc:
            raise CredentialError(f"cannot read the key file: {type(exc).__name__}") from exc
        return IngressCredential(agent_id, secret)
    env = os.environ.get(ENV_KEY)
    if env:
        return IngressCredential(agent_id, env.strip())
    return None
