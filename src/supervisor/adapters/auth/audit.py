"""Console action audit (WP18): one append-only ``console_action`` row per mutating action.

Who (actor, kind, auth method, roles), what (permission, method, path), which target, the
outcome (``ok`` | ``denied`` | ``error``), the SHA-256 of the canonical target row before and
after, and a request id. ``detail`` is a short fixed note (an error class name or a denial
code): never PII and never text a user typed.

A failed audit write never turns into a 5xx: the caller logs it and shows a WARNING.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

from supervisor.core.canonical import sha256_hex

log = logging.getLogger("supervisor.audit")

TARGET_KINDS = ("case", "agent", "notice", "export", "job", "session")
# path parameter name -> target kind (the first one present on the route wins)
_PARAM_KIND = {
    "case_id": "case",
    "agent_id": "agent",
    "notice_id": "notice",
    "name": "export",
}
# route template -> target kind when the route has no id parameter
_TEMPLATE_KIND = {
    "/console/onboard/start": "job",
    "/console/dev/user": "session",
    "/console/export": "export",
    "/console/chain/export": "export",
}
_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class _Clock(Protocol):
    def now(self) -> Any: ...


class Actor(Protocol):
    user_id: str
    kind: str
    auth_method: str
    roles: frozenset[str]


def row_hash(row: Any) -> str | None:
    """SHA-256 of the canonical JSON of one row (or of a list of rows); None for no row."""
    if row is None or row == []:
        return None
    try:
        return sha256_hex(row)
    except Exception as exc:  # noqa: BLE001 - a hash problem must not block the action
        log.error("console_action hash failed: %s", type(exc).__name__)
        return None


def target_of(template: str, path_params: Mapping[str, str]) -> tuple[str | None, str | None]:
    """(target_kind, target_id) from the route template and its path parameters."""
    for param, kind in _PARAM_KIND.items():
        if param in path_params:
            value = str(path_params[param])
            return kind, value if _ID.match(value) else None
    return _TEMPLATE_KIND.get(template), None


def snapshot_hash(state: Any, kind: str | None, target_id: str | None) -> str | None:
    """Hash of the target's row(s) now: cases row; agent row + active gate_control rows;
    notice row. None when the target has no row (or no kind)."""
    if kind is None or target_id is None:
        return None
    if kind == "case":
        return row_hash(state.get("cases", {"case_id": target_id}))
    if kind == "notice":
        return row_hash(state.get("notice", {"notice_id": target_id}))
    if kind == "agent":
        agent = state.get("agent", {"agent_id": target_id})
        controls = [
            c
            for c in state.query("gate_control", {"agent_id": target_id})
            if c.get("status") in ("active", "pending")
        ]
        controls.sort(key=lambda c: str(c.get("control_id")))
        if agent is None and not controls:
            return None
        return row_hash({"agent": agent, "gate_control": controls})
    return None


def write_action(
    tables: Any,
    clock: _Clock,
    *,
    request_id: str | None,
    actor: Actor | None,
    permission: str,
    method: str,
    path: str,
    outcome: str,
    target_kind: str | None = None,
    target_id: str | None = None,
    before_hash: str | None = None,
    after_hash: str | None = None,
    detail: str | None = None,
    actor_fallback: tuple[str, str, str] | None = None,
) -> str:
    """Append one ``console_action`` row; returns the action id. Raises on a store error
    (the caller decides how to warn). ``actor_fallback`` = (id, kind, auth_method) is used
    when there is no ``AuthPrincipal`` (a gate caller known only by a header)."""
    if actor is not None:
        who = (actor.user_id, actor.kind, actor.auth_method)
        roles = sorted(actor.roles)
    else:
        who = actor_fallback or ("unknown", "unknown", "none")
        roles = []
    action_id = uuid.uuid4().hex
    tables.append(
        "console_action",
        [
            {
                "action_id": action_id,
                "ts": clock.now(),
                "request_id": request_id or uuid.uuid4().hex,
                "actor": who[0][:256],
                "actor_kind": who[1],
                "auth_method": who[2],
                "roles": roles,
                "permission": permission,
                "method": method,
                "path": path[:512],
                "target_kind": target_kind,
                "target_id": target_id,
                "outcome": outcome,
                "before_hash": before_hash,
                "after_hash": after_hash,
                "detail": (detail or None) and detail[:200],
            }
        ],
    )
    return action_id


def request_id_of(request: Any) -> str:
    """The id W2's middleware put on ``request.state``, else a fresh one (kept on the request
    so every row of one request shares it)."""
    rid = getattr(request.state, "request_id", None)
    if not rid:
        rid = uuid.uuid4().hex
        try:
            request.state.request_id = rid
        except Exception:  # noqa: BLE001, S110 - state is optional
            pass
    return str(rid)
