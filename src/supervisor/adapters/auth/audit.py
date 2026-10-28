"""Console action audit (WP18): one append-only ``console_action`` row per mutating action.

Who (actor, kind, auth method, roles), what (permission, method, path), which target, the
outcome (``attempted`` | ``ok`` | ``denied`` | ``error``), the SHA-256 of the canonical target
row before and after, and a request id. ``detail`` is a short fixed note (an error class name
or a denial code): never PII and never text a user typed.

Two rows per mutating action (M4), sharing one request id: ``attempted`` is written BEFORE the
side effect (``write_attempt``); if that write fails the action is not done (``AuditUnavailable``,
HTTP 400). The outcome row (``write_outcome``) is written after; if it fails the result is
returned with a WARNING and an ERROR log (the ``attempted`` row already proves the try). A denial
(403) and a refused identity need no ``attempted`` row: they have no side effect.
Auditing may be switched off (``CONSOLE_AUDIT_ENABLED=0``) only when ``SUPERVISOR_MODE=dev``.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

from supervisor.core.canonical import sha256_hex
from supervisor.core.errors import SupervisorError

log = logging.getLogger("supervisor.audit")

TARGET_KINDS = (
    "case",
    "agent",
    "notice",
    "export",
    "job",
    "session",
    "alert",
    "risk",
    "control",
    "task",
    "system",  # WP-G0
    "incident",  # WP-G5
    "mcp_app",  # WP-G6
    "node",  # WP-O1: an inventory node or agent whose source is taken in
    "regkb_draft",  # WP-L1
)
# path parameter name -> target kind (the first one present on the route wins)
_PARAM_KIND = {
    "case_id": "case",
    "agent_id": "agent",
    "notice_id": "notice",
    "alert_id": "alert",
    "risk_id": "risk",  # WP29
    "control_id": "control",  # WP30
    "task_id": "task",  # WP30
    "system_id": "system",  # WP-G0
    "incident_id": "incident",  # WP-G5
    "app_id": "mcp_app",  # WP-G6
    "node_id": "node",  # WP-O1
    "draft_id": "regkb_draft",  # WP-L1
    "name": "export",
}
# route template -> target kind when the route has no id parameter
_TEMPLATE_KIND = {
    "/console/onboard/start": "job",
    "/console/dev/user": "session",
    "/console/export": "export",
    "/console/chain/export": "export",
    "/v1/risks": "risk",  # WP29: create (the new id is in the detail note)
    "/v1/controls": "control",  # WP30: create
    "/v1/tasks": "task",  # WP30: add a custom task
    "/v1/systems": "system",  # WP-G0: register
    "/v1/agents": "agent",  # WP-P2: register (the agent id is in the body)
    "/console/systems": "system",  # WP-G0: register (form)
    "/console/systems/new": "system",  # WP-UX4b: register wizard, step 3
}
_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AuditUnavailable(SupervisorError):
    """The ``attempted`` audit row could not be written: the action was not done."""


def audit_active(settings: Any) -> bool:
    """Audit is on, unless the flag is off AND the mode is ``dev`` (the only mode that may skip)."""
    return bool(settings.console_audit_enabled) or settings.supervisor_mode != "dev"


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
    if kind == "alert":
        return row_hash(state.get("alert", {"alert_id": target_id}))
    if kind == "risk":  # WP29: the risk row and its links
        risk = state.get("risk", {"risk_id": target_id})
        if risk is None:
            return None
        links = sorted(
            (
                f"{r['kind']}:{r['target']}"
                for r in state.query("risk_link", {"risk_id": target_id})
                if r.get("active")
            ),
        )
        return row_hash({"risk": risk, "links": links})
    if kind == "control":  # WP30: the control row and its map
        control = state.get("control", {"control_id": target_id})
        if control is None:
            return None
        maps = sorted(
            f"{r['kind']}:{r['target']}"
            for r in state.query("control_map", {"control_id": target_id})
            if r.get("active")
        )
        return row_hash({"control": control, "map": maps})
    if kind == "task":  # WP30
        return row_hash(state.get("task", {"task_id": target_id}))
    if kind == "system":  # WP-G0: the system row, its team and its links
        system = state.get("ai_system", {"system_id": target_id})
        if system is None:
            return None
        team = sorted(
            f"{r['user_id']}:{r['team_role']}"
            for r in state.query("system_team", {"system_id": target_id})
            if r.get("active")
        )
        links = sorted(
            r["component_id"]
            for r in state.query("system_component", {"system_id": target_id})
            if r.get("active")
        )
        # WP-L3: the duty rows of the system (a close, waive or re-evaluate changes the hash; a
        # system without duty rows hashes as before)
        try:
            duties = sorted(
                f"{r['status_id']}:{r['row_version']}"
                for r in state.query("obligation_status", {"system_id": target_id})
            )
        except Exception:  # noqa: BLE001 - a store before WP-L2 has no such table
            duties = []
        if duties:
            return row_hash({"system": system, "team": team, "links": links, "duties": duties})
        return row_hash({"system": system, "team": team, "links": links})
    if kind == "incident":  # WP-G5
        return row_hash(state.get("incident", {"incident_id": target_id}))
    if kind == "regkb_draft":  # WP-L1
        return row_hash(state.get("regkb_draft", {"draft_id": target_id}))
    if kind == "mcp_app":  # WP-G6: the app row without its key hash
        app = state.get("mcp_app", {"app_id": target_id})
        if app is None:
            return None
        return row_hash({k: v for k, v in dict(app).items() if k != "key_hash"})
    if kind == "node":  # WP-O1: the intake attempts of the node (the n+1 row changes the hash)
        parts = sorted(
            f"{r['n']}:{r['sha256']}:{r['status']}"
            for r in state.query("intake_attempt", {"node_id": target_id})
        )
        # WP-O2: the active fact rows of the node (a build changes the hash; no facts = as before)
        parts += sorted(
            f"facts:{r['attempt_n']}:{r['fact_id']}:{r['row_version']}"
            for r in state.query("onboard_facts", {"node_id": target_id})
        )
        return row_hash(parts)
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


def write_attempt(tables: Any, clock: _Clock, **kw: Any) -> str:
    """Row 1: ``attempted``, before the side effect. ``AuditUnavailable`` on a store error."""
    kw.pop("outcome", None)
    kw["after_hash"] = None
    try:
        return write_action(tables, clock, outcome="attempted", **kw)
    except Exception as exc:  # noqa: BLE001 - any store error blocks the action
        log.error("console_action attempt write failed: %s", type(exc).__name__)
        raise AuditUnavailable("audit store unavailable; the action was not done") from exc


def write_outcome(tables: Any, clock: _Clock, **kw: Any) -> str | None:
    """Row 2: the outcome, after the side effect. Returns a WARNING text when the write fails."""
    try:
        write_action(tables, clock, **kw)
    except Exception as exc:  # noqa: BLE001 - never a 5xx because of the audit
        log.error("console_action write failed: %s", type(exc).__name__)
        return f"WARNING: the console audit record failed: {type(exc).__name__}; see the server log"
    return None


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
