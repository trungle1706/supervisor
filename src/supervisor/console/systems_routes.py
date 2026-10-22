"""Systems pages routes (WP-G0): ``/console/systems``. Mounted by ``app.py`` only when
CONSOLE_SYSTEMS_ENABLED=1; the page also needs GOVERNANCE_ENABLED=1 (HTTP 400 with a message
when it is off). Minimal pages on the old navigation; the full governance pages come later."""

from __future__ import annotations

import functools
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console import systems_views, systems_wizard
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import (
    ConsoleInputError,
    _call,
    _check_id,
    _drawer_query,
    audited,
    form_or_plain,
    render,
)
from supervisor.governance.model import ensure_on
from supervisor.governance.systems import ALL

router = APIRouter(prefix="/console", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def _off(ctx: ConsoleContext) -> None:
    """HTTP 400 unless both CONSOLE_SYSTEMS_ENABLED and GOVERNANCE_ENABLED are on."""
    if not ctx.settings.console_systems_enabled:
        raise ConsoleInputError("The Systems page is off (CONSOLE_SYSTEMS_ENABLED=1 turns it on)")
    ensure_on(ctx.settings)


@router.get("/systems", response_class=HTMLResponse, dependencies=[Depends(needs("systems.view"))])
async def systems_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    query = dict(request.query_params)
    data: dict[str, Any] = await _call(systems_views.list_view, ctx, me, query)
    opened = query.get("drawer")
    if opened:  # no-JS fallback of the row drawer
        _check_id(opened, "system id")
        data["drawer"] = await _call(
            systems_views.drawer_view,
            ctx,
            me,
            opened,
            query.get("dtab") or "details",
            _drawer_query(query),
        )
    return render(request, ctx, me, "systems.html", section="systems", **data)


@router.get(
    "/systems/rows", response_class=HTMLResponse, dependencies=[Depends(needs("systems.view"))]
)
async def systems_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    data = await _call(systems_views.list_view, ctx, me, dict(request.query_params))
    return render(request, ctx, me, "_systems_list.html", **data)


# --- WP-UX4b --- register wizard. Declared before "/systems/{system_id}" so "new" is not an id.


def _wizard_off(ctx: ConsoleContext) -> None:
    """HTTP 400 unless the page flags are on and CONSOLE_NAV_V3 is on (the wizard is a v3 page)."""
    _off(ctx)
    if not ctx.settings.console_nav_v3:
        raise ConsoleInputError("The register wizard needs CONSOLE_NAV_V3=1")


def _person(me: AuthPrincipal) -> None:
    if me.kind != "user":
        raise PermissionDenied("registering an AI system needs a signed-in person")


@router.get(
    "/systems/new", response_class=HTMLResponse, dependencies=[Depends(needs("systems.edit"))]
)
async def system_new_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _wizard_off(ctx)
    _person(me)
    data = await _call(systems_wizard.form_view, ctx, me)
    return render(request, ctx, me, "system_new.html", section="systems", **data)


@router.post(
    "/systems/new/checks",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
async def system_new_checks(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Step 2: the preliminary checks. Read only; nothing is stored."""
    _wizard_off(ctx)
    _person(me)
    form, _ = await form_or_plain(request)
    d = await _call(systems_wizard.checks, ctx, me, form)
    return render(request, ctx, me, "system_new_result.html", section="systems", d=d)


@router.post("/systems/new", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def system_new_register(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Step 3: register the draft and open the initiation tasks. Applies nothing else."""
    _wizard_off(ctx)
    _person(me)
    form, plain = await form_or_plain(request)
    out = await _call(systems_wizard.register, ctx, me, form)
    request.state.audit_detail = "create"
    url = f"/console/systems/{out['system_id']}?tab=tasks"
    if out["tasks_missing"]:  # L3: the draft is stored; the tasks page says so and offers a retry
        url += "&intake=missing"
    if plain:
        return RedirectResponse(url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": url})


@router.post("/systems/{system_id}/intake-tasks", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def system_intake_tasks(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Open the initiation tasks of a system again (same ids: a repeat is a no-op)."""
    _wizard_off(ctx)
    _person(me)
    _check_id(system_id, "system id")
    await form_or_plain(request)
    await _call(systems_views.detail_view, ctx, me, system_id, "overview")  # scope check
    await _call(systems_wizard.open_tasks, ctx, system_id, str(me.user_id))
    request.state.audit_detail = "intake_tasks"
    url = f"/console/systems/{system_id}?tab=tasks"
    if request.headers.get("hx-request") == "true":
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@router.get(
    "/systems/{system_id}/drawer",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def system_drawer(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    _check_id(system_id, "system id")
    query = dict(request.query_params)
    data = await _call(
        systems_views.drawer_view,
        ctx,
        me,
        system_id,
        query.get("tab") or "details",
        _drawer_query(query),
    )
    return render(request, ctx, me, "_system_drawer.html", drawer=data)


@router.get(
    "/systems/{system_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def system_page(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    _check_id(system_id, "system id")
    tab = request.query_params.get("tab") or "overview"
    data = await _call(systems_views.detail_view, ctx, me, system_id, tab)
    if tab == "tasks" and request.query_params.get("intake") == "missing":  # WP-UX4b L3
        data["intake_missing"] = bool(await _call(systems_wizard.missing_tasks, ctx, system_id))
    return render(request, ctx, me, "system.html", section="systems", **data)


@router.post("/systems", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def systems_register(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    if me.kind != "user":
        raise PermissionDenied("registering an AI system needs a signed-in person")
    form, plain = await form_or_plain(request)
    draft = systems_views.draft_from_form(form, me)
    if ctx.systems.scope_for(me) is not ALL:
        draft["owner_user"] = str(me.user_id)
    out = await _call(functools.partial(ctx.systems.register, draft, str(me.user_id), for_user=me))
    request.state.audit_detail = "create"
    url = f"/console/systems/{out['system_id']}"
    if plain:
        return RedirectResponse(url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": url})
