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
from supervisor.console import systems_views
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


# --- WP-G2: Rules and Classification tabs (docs/assignment-rules.md, docs/decision33.md) -------
def _done(request: Request, plain: bool, system_id: str, tab: str) -> Response:
    lang = request.query_params.get("lang") or ""
    url = f"/console/systems/{system_id}?tab={tab}" + (f"&lang={lang}" if lang else "")
    if plain:
        return RedirectResponse(url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": url})


def _person(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("this action needs a signed-in person")
    return str(me.user_id)


@router.post("/systems/{system_id}/rules/run", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def system_rules_run(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    actor = _person(me)
    _, plain = await form_or_plain(request)
    seen = await _call(systems_views.detail_view, ctx, me, system_id, "overview")
    sid = seen["s"]["system_id"]
    await _call(functools.partial(ctx.rules.run, sid, actor, "manual"))
    request.state.audit_detail = "rules run"
    return _done(request, plain, sid, "rules")


@router.post(
    "/systems/{system_id}/classification/{step}", dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def system_classification_step(
    system_id: str,
    step: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _off(ctx)
    actor = _person(me)
    if step not in ("draft", "answers", "apply"):
        raise ConsoleInputError("unknown classification step")
    form, plain = await form_or_plain(request)
    seen = await _call(systems_views.detail_view, ctx, me, system_id, "overview")
    sid = seen["s"]["system_id"]
    svc = ctx.classification
    if step == "draft":
        await _call(functools.partial(svc.draft, sid, actor))
    elif step == "answers":
        current = (await _call(svc.get, sid))["draft"]
        if current is None:
            raise ConsoleInputError("there is no draft to edit; make one first")
        changes = systems_views.classification_changes(form, current)
        if changes:
            await _call(functools.partial(svc.edit, sid, actor, changes))
    else:
        confirm = form.get("confirm_ai_prefill", "") in ("1", "true", "on")
        await _call(functools.partial(svc.apply, sid, me, confirm_ai_prefill=confirm))
    request.state.audit_detail = f"classification {step}"
    return _done(request, plain, sid, "classification")
