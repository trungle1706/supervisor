"""Console routes of the smart guardian panel (WP-G4, ``SMART_GUARDIAN``).

* ``GET  /console/systems/{id}/guardian-proposal`` (systems.view): the panel fragment.
* ``POST /console/systems/{id}/guardian-proposal`` (systems.edit): make a proposal.
* ``POST .../guardian-proposal/accept`` (systems.edit): the ticked lines (fields ``sel_<line id>``).
* ``POST .../guardian-proposal/reject`` (systems.edit): field ``reason``, 20 characters or more.

All answer HTTP 400 ``smart_guardian_off`` while the flag is off. A POST needs HTMX (or a plain
form from this site, which is redirected to the Guardians tab) and writes two ``console_action``
rows. "Run pre-deploy now" is the existing ``POST /console/predeploy/{node}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import smart_guardian_view as view
from supervisor.console import systems_views
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.i18n import translator
from supervisor.console.routes import (
    _call,
    _check_id,
    _lang,
    audited,
    form_or_plain,
    message_html,
    render,
)
from supervisor.console.systems_routes import _done, _off
from supervisor.onboard import smart_guardian as sg

console_router = APIRouter(prefix="/console", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
TAB = "guardians"


async def _panel(
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
    system: dict[str, Any],
    note: str | None,
) -> Response:
    data = await _call(view.panel_data, ctx, me, system)
    resp = render(request, ctx, me, "_smart_guardian_panel.html", s=system, **data)
    if note:
        msg = translator(_lang(request, ctx), ux5=bool(ctx.settings.console_ux5))(note)
        resp.body = resp.body + message_html(msg, ok=True, oob=True).encode()
        resp.headers["content-length"] = str(len(resp.body))
    return resp


async def _gate(ctx: ConsoleContext, me: AuthPrincipal, system_id: str) -> dict[str, Any]:
    _off(ctx)
    sg.ensure_on(ctx.settings)
    _check_id(system_id, "system id")
    system: dict[str, Any] = await _call(systems_views._need_visible, ctx, me, system_id)
    return system


@console_router.get(
    "/systems/{system_id}/guardian-proposal",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def proposal_panel(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    system = await _gate(ctx, me, system_id)
    return await _panel(request, ctx, me, system, None)


@console_router.post(
    "/systems/{system_id}/guardian-proposal",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def proposal_make(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    system = await _gate(ctx, me, system_id)
    _, plain = await form_or_plain(request)
    _, note = await _call(view.do_create, ctx, me, system)
    request.state.audit_detail = note
    if plain:
        return _done(request, True, system["system_id"], TAB)
    return await _panel(request, ctx, me, system, "sgd_ok_proposed")


@console_router.post(
    "/systems/{system_id}/guardian-proposal/accept",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def proposal_accept(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    system = await _gate(ctx, me, system_id)
    form, plain = await form_or_plain(request)
    _, note = await _call(view.do_accept, ctx, me, system, form)
    request.state.audit_detail = note
    if plain:
        return _done(request, True, system["system_id"], TAB)
    system = await _call(systems_views._need_visible, ctx, me, system_id)
    return await _panel(request, ctx, me, system, "sgd_ok_accepted")


@console_router.post(
    "/systems/{system_id}/guardian-proposal/reject",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def proposal_reject(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    system = await _gate(ctx, me, system_id)
    form, plain = await form_or_plain(request)
    _, note = await _call(view.do_reject, ctx, me, system, form)
    request.state.audit_detail = note
    if plain:
        return _done(request, True, system["system_id"], TAB)
    return await _panel(request, ctx, me, system, "sgd_ok_rejected")
