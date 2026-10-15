"""Authorisation dependency (WP18): ``needs("case.assign")`` on every non-public route.

The role matrix is ``supervisor.core.rbac``. ``needs`` resolves the caller with
``current_principal`` (an unknown or missing user is still an ``AuthError``, HTTP 400), then
checks the permission:

* A person (``kind == "user"``) needs a role that holds the permission.
* A service principal or the system identity keeps its phase-1 treatment: it may open the
  read-only views in ``rbac.NON_USER_OK`` (so background readers are not locked out) and
  nothing else. Every action needs a signed-in person, as before.
* A denial raises ``PermissionDenied``; ``supervisor.app`` answers it with HTTP 403 (a user
  error, never 5xx). A denied POST is written to ``console_action`` first.

``needs(..., api=True)`` is for the ``/gate/*`` human routes: it enforces only when
``API_RBAC_ENABLED=1`` (default off: the phase-1 behaviour of those routes is unchanged).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import Request

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.audit import (
    MUTATING,
    request_id_of,
    snapshot_hash,
    target_of,
    write_action,
)
from supervisor.cases.service import PermissionDenied
from supervisor.config import Settings, get_settings
from supervisor.core import rbac

log = logging.getLogger("supervisor.authz")

RBAC_ATTR = "rbac_permission"
RBAC_API_ATTR = "rbac_api"


def runtime_settings() -> Settings:
    """Settings of the running console context if there is one, else the process settings."""
    from supervisor.console.context import peek_context

    ctx = peek_context()
    return ctx.settings if ctx is not None else get_settings()


def _audit_handles(request: Request) -> tuple[Any, Any, Any] | None:
    """(tables, state, clock) to write the audit row with, or None when audit is off or no
    runtime is up."""
    from supervisor.console.context import peek_context

    ctx = peek_context()
    if ctx is not None:
        if not ctx.settings.console_audit_enabled:
            return None
        return ctx.tables, ctx.state, ctx.clock
    if not get_settings().console_audit_enabled:
        return None
    try:
        from supervisor.gateway import wiring

        gw = wiring.get_gateway()
        return gw.tables, gw.states.state, gw.clock
    except Exception as exc:  # noqa: BLE001 - audit is best effort here
        log.error("console_action audit unavailable: %s", type(exc).__name__)
        return None


def _audit_denied(request: Request, me: AuthPrincipal, permission: str, detail: str) -> str:
    """Write the ``denied`` row; return a warning suffix when the write fails."""
    if request.method not in MUTATING:
        return ""
    path = request.url.path
    if not (path.startswith("/console") or rbac.normalise_path(path).startswith("/gate/")):
        return ""
    handles = _audit_handles(request)
    if handles is None:
        return ""
    tables, state, clock = handles
    try:
        route = request.scope.get("route")
        template = getattr(route, "path", None) or path
        kind, tid = target_of(template if "{" in template else path, request.path_params)
        h = snapshot_hash(state, kind, tid)
        write_action(
            tables,
            clock,
            request_id=request_id_of(request),
            actor=me,
            permission=permission,
            method=request.method,
            path=path,
            outcome="denied",
            target_kind=kind,
            target_id=tid,
            before_hash=h,
            after_hash=h,
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001 - the denial itself must still be answered
        log.error("console_action write failed: %s", type(exc).__name__)
        return (
            f" (WARNING: the console audit record failed: {type(exc).__name__}; see the server log)"
        )
    return ""


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def needs(permission: str, *, api: bool = False) -> Callable[..., AuthPrincipal]:
    """FastAPI dependency factory: the caller must hold ``permission`` (see module doc)."""
    if "{" not in permission and permission not in rbac.PERMISSIONS:
        raise ValueError(f"unknown permission {permission!r}")

    def dependency(request: Request) -> AuthPrincipal | None:
        if api and not runtime_settings().api_rbac_enabled:
            return None  # phase-1 behaviour: no identity lookup, no check
        me = current_principal(request)
        perm = rbac.resolve_permission(permission, request.path_params)
        if perm not in rbac.PERMISSIONS:
            return me  # e.g. an unknown agent action: the route answers it with a 400
        if me.kind != "user":
            if perm in rbac.NON_USER_OK:
                return me
            msg = f"{perm} needs a signed-in person, not a {me.kind}"
        elif rbac.allowed(me.roles, perm):
            return me
        else:
            msg = (
                f"{me.user_id} cannot {_lower_first(rbac.PERMISSIONS[perm][1])}: "
                f"needs role {' or '.join(rbac.roles_for(perm))}"
            )
        warn = _audit_denied(request, me, perm, "permission_denied")
        raise PermissionDenied(msg + warn)

    setattr(dependency, RBAC_ATTR, permission)
    setattr(dependency, RBAC_API_ATTR, api)
    return dependency
