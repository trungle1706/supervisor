"""Incidents tab routes (WP-G5): ``/console/incidents``. Mounted by ``app.py`` only when
GOVERNANCE_ACTIONS_ENABLED=1; the page also needs GOVERNANCE_ENABLED=1 (HTTP 400 with a message
when it is off). The tab sits on Cases & alerts. An incident is moved on and closed by a person
with ``incidents.transition``; nothing here creates one."""

from __future__ import annotations

import functools
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console import incidents_views
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import (
    _call,
    _check_id,
    _list_after_write,
    _version,
    audited,
    form,
    render,
)
from supervisor.governance.incident_routes import ensure_actions_on

router = APIRouter(prefix="/console", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


@router.get(
    "/incidents", response_class=HTMLResponse, dependencies=[Depends(needs("incidents.view"))]
)
async def incidents_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    ensure_actions_on(ctx.settings)
    query = dict(request.query_params)
    data: dict[str, Any] = await _call(incidents_views.list_view, ctx, me, query)
    opened = query.get("drawer")
    if opened:  # no-JS fallback of the row drawer
        _check_id(opened, "incident id")
        data["drawer"] = await _call(incidents_views.drawer_view, ctx, me, opened)
    return render(request, ctx, me, "incidents.html", section="incidents", **data)


@router.get(
    "/incidents/rows",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("incidents.view"))],
)
async def incidents_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    ensure_actions_on(ctx.settings)
    data = await _call(incidents_views.list_view, ctx, me, dict(request.query_params))
    return render(request, ctx, me, "_incidents_list.html", **data)


@router.get(
    "/incidents/{incident_id}/drawer",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("incidents.view"))],
)
async def incident_drawer(
    incident_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    ensure_actions_on(ctx.settings)
    _check_id(incident_id, "incident id")
    data = await _call(incidents_views.drawer_view, ctx, me, incident_id)
    return render(request, ctx, me, "_incident_drawer.html", drawer=data)


@router.post(
    "/incidents/{incident_id}/transition",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("incidents.transition"))],
)
@audited("incidents.transition")
async def incident_transition(
    incident_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    ensure_actions_on(ctx.settings)
    _check_id(incident_id, "incident id")
    d = await form(request)
    if me.kind != "user":
        raise PermissionDenied("moving an incident needs a signed-in person")
    out = await _call(
        functools.partial(
            ctx.incidents.transition,
            incident_id,
            d.get("status", ""),
            me,
            root_cause=d.get("root_cause") or None,
            affected_scope=d.get("affected_scope") or None,
            expected_version=_version(d),
            me_scope=me,
        )
    )
    request.state.audit_detail = f"incident_{out['status']}"
    data = await _call(
        _list_after_write, incidents_views.list_view, ctx, me, query=dict(request.query_params)
    )
    return render(request, ctx, me, "_incidents_list.html", **data)
