"""JSON routes of the smart guardian (WP-G4, docs/smart-guardian.md).

* ``GET /v1/systems/{id}/guardian-proposal`` (systems.view): the open proposal, else the newest one
  (404 when the system has none yet).
* ``POST /v1/systems/{id}/guardian-proposal`` (systems.edit): compute and store a proposal; an open
  one with other content is superseded. 201 with the row.
* ``POST .../guardian-proposal/accept`` (systems.edit): body ``{"lines": [line ids], "note": ""}``.
  Writes the bindings through ``GuardianService`` (the floor and the off-request rule stay).
* ``POST .../guardian-proposal/reject`` (systems.edit): body ``{"reason": "..."}``, 20 characters
  or more.

Mounted by ``app.py`` inside the GOVERNANCE_ENABLED block. While SMART_GUARDIAN is off every route
answers HTTP 400 ``smart_guardian_off`` and reads no table. A system outside the caller's scope
answers 404. Every POST writes two ``console_action`` rows. Never 500.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import audited
from supervisor.core.errors import NotFoundError
from supervisor.governance.routes import _actor, _body, _not_found, _service, _visible
from supervisor.onboard import smart_guardian as sg

router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def _scope(ctx: ConsoleContext, me: AuthPrincipal, system_id: str) -> str:
    sg.ensure_on(ctx.settings)
    return _visible(_service(ctx), me, system_id)


@router.get("/systems/{system_id}/guardian-proposal", dependencies=[Depends(needs("systems.view"))])
def get_proposal(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    try:
        sid = _scope(ctx, me, system_id)
    except NotFoundError as exc:
        return _not_found(exc)
    row = sg.current(ctx, sid)
    if row is None:
        return JSONResponse(status_code=404, content={"error": f"no proposal for {sid} yet"})
    return row


@router.post(
    "/systems/{system_id}/guardian-proposal", dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def post_proposal(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    sg.ensure_on(ctx.settings)
    actor = _actor(me)
    try:
        sid = _visible(_service(ctx), me, system_id)
    except NotFoundError as exc:
        return _not_found(exc)
    row = sg.create(ctx, sid, actor)
    request.state.audit_detail = f"proposal={row['proposal_id']} attempt={row['attempt_n']}"
    return JSONResponse(status_code=201, content=row)


@router.post(
    "/systems/{system_id}/guardian-proposal/accept", dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def post_accept(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    sg.ensure_on(ctx.settings)
    actor = _actor(me)
    try:
        sid = _visible(_service(ctx), me, system_id)
    except NotFoundError as exc:
        return _not_found(exc)
    body = await _body(request)
    row = sg.accept(
        ctx, sid, actor, body.get("lines"), body.get("note"), proposal_id=body.get("proposal_id")
    )
    n = len(row["proposal"].get("decision", {}).get("accepted", []))
    request.state.audit_detail = f"accept proposal={row['proposal_id']} lines={n}"
    return row


@router.post(
    "/systems/{system_id}/guardian-proposal/reject", dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def post_reject(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    sg.ensure_on(ctx.settings)
    actor = _actor(me)
    try:
        sid = _visible(_service(ctx), me, system_id)
    except NotFoundError as exc:
        return _not_found(exc)
    body = await _body(request)
    row = sg.reject(ctx, sid, actor, body.get("reason"), proposal_id=body.get("proposal_id"))
    request.state.audit_detail = f"reject proposal={row['proposal_id']}"
    return row
