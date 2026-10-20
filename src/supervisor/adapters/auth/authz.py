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

``needs(..., api=True)`` is for the agent-facing ``/gate`` check and read routes
(``/gate/check``, ``/gate/agents/{id}/state``, ``/gate/metrics`` and the ``/v1`` aliases): it
enforces only when ``API_RBAC_ENABLED=1`` (default off: the phase-1 behaviour is unchanged).

``needs(..., control=True)`` is for the ``/gate`` control routes (pause, resume, quarantine,
release and the ``/v1`` aliases). It ALWAYS enforces, whatever ``API_RBAC_ENABLED`` says, and
it needs an explicit identity: the ``dev_header`` adapter needs the ``X-Dev-User`` header
naming a user of the users file (no ``default_user``, no console cookie: a JSON API that
changes agent state must not act on an ambient credential); ``databricks_app`` needs valid SSO
headers. A missing or unknown identity, or a role without the permission, is HTTP 403. The
acting principal comes only from the ``Principal`` port; ``X-Forwarded-User`` is never read
by the route and a body ``principal`` is ignored.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from fastapi import Request

from supervisor.adapters.auth import AuthError, AuthPrincipal, current_principal, get_provider
from supervisor.adapters.auth.audit import (
    MUTATING,
    audit_active,
    request_id_of,
    snapshot_hash,
    target_of,
    write_action,
)
from supervisor.cases.service import PermissionDenied
from supervisor.config import Settings, get_settings
from supervisor.core import rbac
from supervisor.ops.logging_setup import set_principal_id

log = logging.getLogger("supervisor.authz")
_SAFE_ID = re.compile(r"[^A-Za-z0-9_.@+-]")

RBAC_ATTR = "rbac_permission"
RBAC_API_ATTR = "rbac_api"
RBAC_CONTROL_ATTR = "rbac_control"
DEV_HEADER = "x-dev-user"
DEV_HEADER_NAME = "X-Dev-User"


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
        if not audit_active(ctx.settings):
            return None
        return ctx.tables, ctx.state, ctx.clock
    if not audit_active(get_settings()):
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
    if not (
        path.startswith(("/console", "/v1/risks", "/v1/controls", "/v1/tasks"))  # WP29, WP30
        or rbac.normalise_path(path).startswith("/gate/")
    ):
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


def _claimed_id(request: Request) -> str:
    """The audit ``actor`` of a refused identity: ``unverified:<claimed id>`` where the claimed
    id is client text cut to [A-Za-z0-9_.@+-], 64 characters; else ``unverified:unknown``."""
    for name in ("x-dev-user", "x-forwarded-email", "x-forwarded-user"):
        value = _SAFE_ID.sub("", request.headers.get(name, "").strip())[:64]
        if value:
            return f"unverified:{value}"
    return "unverified:unknown"


def _audit_identity_failure(
    request: Request, permission: str | None = None, auth_method: str | None = None
) -> str:
    """One best-effort ``denied`` row (actor_kind ``unverified``) for a mutating call without a
    usable identity. Gate control routes derive the permission from the path."""
    if request.method not in MUTATING:
        return ""
    handles = _audit_handles(request)
    if handles is None:
        return ""
    tables, _state, clock = handles
    try:
        action = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        write_action(
            tables,
            clock,
            request_id=request_id_of(request),
            actor=None,
            actor_fallback=(
                _claimed_id(request),
                "unverified",
                auth_method or get_provider().name,
            ),
            permission=permission or f"agent.{action}",
            method=request.method,
            path=request.url.path,
            outcome="denied",
            detail="identity_unknown",
        )
    except Exception as exc:  # noqa: BLE001 - the denial itself must still be answered
        log.error("console_action write failed: %s", type(exc).__name__)
        return (
            f" (WARNING: the console audit record failed: {type(exc).__name__}; see the server log)"
        )
    return ""


def control_principal(request: Request) -> AuthPrincipal:
    """The explicitly authenticated person behind a gate control call, else ``PermissionDenied``
    (HTTP 403). Never uses ``default_user``, the dev cookie or ``X-Forwarded-User``."""
    provider = get_provider()
    headers = request.headers
    problem = ""
    me: AuthPrincipal | None = None
    if provider.name == "dev_header" and not headers.get(DEV_HEADER, "").strip():
        problem = f"identity required: send the {DEV_HEADER_NAME} header with a known user"
    else:
        try:
            # cookies are deliberately not passed: no ambient credential on a JSON API
            me, token = provider.resolve(headers, {})
        except AuthError as exc:
            problem = f"identity required: {exc}"
        else:
            if me.kind != "user":
                problem = "identity required: sign in as a person (no valid user identity found)"
                me = None
            else:
                request.state.principal = me
                request.state.user_token = token
                set_principal_id(me.user_id)
    if me is None:
        raise PermissionDenied(problem + _audit_identity_failure(request))
    return me


def needs(
    permission: str, *, api: bool = False, control: bool = False
) -> Callable[..., AuthPrincipal]:
    """FastAPI dependency factory: the caller must hold ``permission`` (see module doc)."""
    if "{" not in permission and permission not in rbac.PERMISSIONS:
        raise ValueError(f"unknown permission {permission!r}")
    if api and control:
        raise ValueError("api and control are exclusive")

    def dependency(request: Request) -> AuthPrincipal | None:
        if api and not runtime_settings().api_rbac_enabled:
            return None  # phase-1 behaviour: no identity lookup, no check
        perm = rbac.resolve_permission(permission, request.path_params)
        if control:
            me = control_principal(request)
        else:
            try:
                me = current_principal(request)
            except AuthError:
                # M4: an unknown / missing identity on a mutating route is audited (denied,
                # unverified). The answer stays the usual 400 message.
                if request.url.path.startswith("/console"):
                    shown = perm if perm in rbac.PERMISSIONS else permission
                    _audit_identity_failure(request, shown, get_provider().name)
                raise
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
    setattr(dependency, RBAC_CONTROL_ATTR, control)
    return dependency
