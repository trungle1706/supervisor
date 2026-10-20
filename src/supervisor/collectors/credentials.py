"""Issue the first ingress key of an agent for the Integrations page (WP38).

The same flow as ``python -m supervisor.gateway.ingress_auth issue <agent_id>`` (WP20): a new
secret, a key record in the key store with the same key id format. Rotation is not offered here
(it stays on the command line). The secret is returned to the caller ONCE; nothing here logs it,
and the console writes only the agent id and the key id to the audit log.

* store ``file``: the key file is written (mode 600) and the key is active at once;
* store ``env`` or ``secret_scope``: the server cannot write them. The result says which
  variable or secret to set; the secret is shown once, as the CLI does.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from supervisor.adapters.auth.agent_creds import (
    FileKeyStore,
    KeyStoreError,
    env_name,
    make_key_id,
    rotate_keys,
)
from supervisor.core.errors import SupervisorError
from supervisor.gateway.ingress_sign import AGENT_ID_RE, new_secret

ROTATE_CLI = "python -m supervisor.gateway.ingress_auth rotate {agent_id}"
_LOCK = threading.Lock()


class CollectorError(SupervisorError):
    """The credential cannot be issued (shown to the person as HTTP 400)."""


@dataclass(frozen=True)
class Issued:
    agent_id: str
    key_id: str
    secret: str = field(repr=False)  # never in a repr or a log line
    store: str
    written: bool  # True: the key store holds it now. False: the person must set it.
    manual_steps: tuple[str, ...] = ()


def issue_first_key(settings: Any, agent_id: str, now: datetime | None = None) -> Issued:
    """The first key for ``agent_id``. Refuses an agent that already has a key (use rotate)."""
    if not AGENT_ID_RE.match(agent_id or ""):
        raise CollectorError("agent id must match [A-Za-z0-9_.:@-]{1,128}")
    now = now or datetime.now(UTC)
    store_kind = settings.effective_ingress_key_store
    secret = new_secret()
    key_id = make_key_id(now)
    if store_kind != "file":
        steps = (
            (f"Set {env_name(agent_id)}=<secret> in the environment of the Supervisor server.",)
            if store_kind == "env"
            else (
                f"Put the secret in secret agent-{agent_id}-current of scope "
                f"{settings.ingress_secret_scope or 'FILL-ME-scope'}.",
            )
        )
        return Issued(agent_id, "pending", secret, store_kind, False, steps)
    path = settings.ingress_keys_file
    if path is None:
        raise CollectorError("no key file is configured (INGRESS_KEYS_FILE)")
    store = FileKeyStore(path)
    with _LOCK:  # two people pressing Add at once must not lose a key
        try:
            data = store.read_all()
            if data.get(agent_id):
                raise CollectorError(
                    f"{agent_id} already has a key; rotate it: "
                    + ROTATE_CLI.format(agent_id=agent_id)
                )
            data[agent_id] = rotate_keys(
                [], secret, now, timedelta(hours=settings.ingress_key_overlap_hours)
            )
            store.write_all(data)
        except KeyStoreError as exc:
            raise CollectorError(f"key file problem: {exc}") from exc
        except OSError as exc:
            raise CollectorError(f"key file cannot be written ({type(exc).__name__})") from exc
    return Issued(agent_id, data[agent_id][0].key_id or key_id, secret, "file", True)
