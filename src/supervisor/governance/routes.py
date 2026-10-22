"""JSON routes of the AI system entity (WP-G0): ``/v1/systems/...``.

* ``GET /v1/systems`` (systems.view): the systems in the caller's scope; filters status,
  owner_team, lifecycle_stage, risk, system_type, q.
* ``POST /v1/systems`` (systems.edit): register (status draft); body = the intake fields.
* ``GET /v1/systems/{id}`` (systems.view): one system with team, components and effective risk.
* ``PATCH /v1/systems/{id}`` (systems.edit): change fields; optional ``row_version``.
* ``POST /v1/systems/{id}/team`` (systems.edit): body user_id, team_role (add or change).
* ``DELETE /v1/systems/{id}/team/{user}`` (systems.edit): remove a member.
* ``POST /v1/systems/{id}/links`` (systems.edit): body ref_kind (agent | node), ref_id, role.
* ``DELETE /v1/systems/{id}/links/{component_id}`` (systems.edit): remove a link.
* ``POST /v1/systems/{id}/archive`` (systems.edit): archive.

WP-G1 (same router, same flag):

* ``GET|POST /v1/systems/{id}/approvals`` (systems.view | systems.edit): stage approvals; body of
  the POST: ``to_stage``.
* ``POST /v1/systems/{id}/approvals/{aid}/decide`` (systems.approve): body ``decision``
  (approve | reject), ``reason`` (needed for reject).
* ``POST /v1/systems/{id}/stage`` (systems.edit): body ``to_stage``.
* ``GET|POST /v1/systems/{id}/reviews`` (systems.view | systems.review), ``PATCH .../{rid}``,
  ``POST .../{rid}/complete``, ``POST .../{rid}/reopen`` (body ``reason``).

Mounted by ``app.py`` only when GOVERNANCE_ENABLED=1 (nothing is mounted otherwise). A person
with a scoped role (``SCOPED_ROLES``) sees and changes only the systems in their scope; a system
outside it answers 404, like a system that does not exist. Every write makes two
``console_action`` audit rows and a ``system_change`` chain record. A bad input is HTTP 400 with
the reason; never 500.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import audited
from supervisor.core.errors import NotFoundError
from supervisor.governance.model import SystemsError, check_system_id, check_user, ensure_on
from supervisor.governance.systems import ALL, SystemService

router = APIRouter(prefix="/v1/systems", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
MAX_BODY = 64_000


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise SystemsError("request body is too large")
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise SystemsError("request body must be JSON") from None
    if not isinstance(data, dict):
        raise SystemsError("request body must be a JSON object")
    return data


def _service(ctx: ConsoleContext) -> SystemService:
    ensure_on(ctx.settings)
    svc: SystemService = ctx.systems
    return svc


def _not_found(exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": str(exc)})


def _actor(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("changing an AI system needs a signed-in person")
    return str(me.user_id)


def _visible(svc: SystemService, me: AuthPrincipal, system_id: str) -> str:
    """The id, if the system exists and is in the caller's scope; else NotFoundError (the same
    answer for both, so a scoped person cannot probe for names)."""
    check_system_id(system_id)
    if system_id not in svc.scope_for(me):
        raise NotFoundError(f"AI system {system_id} does not exist")
    return system_id


@router.get("", dependencies=[Depends(needs("systems.view"))])
def list_systems(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _service(ctx)
    rows = svc.list_systems(svc.scope_for(me), dict(request.query_params))
    return {"count": len(rows), "systems": rows}


@router.post("", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def register_system(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    data = await _body(request)
    data.setdefault("owner_user", actor)
    if svc.scope_for(me) is not ALL and data.get("owner_user") != actor:
        raise SystemsError("you can register a system only with yourself as owner_user")
    out = svc.register(data, actor, for_user=me)
    request.state.audit_detail = "create"
    return JSONResponse(status_code=201, content=out)


@router.get("/{system_id}", dependencies=[Depends(needs("systems.view"))])
def get_system(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _service(ctx)
    try:
        return svc.get(_visible(svc, me, system_id))
    except NotFoundError as exc:
        return _not_found(exc)


@router.patch("/{system_id}", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def update_system(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    data = await _body(request)
    version = data.pop("row_version", None)
    if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
        raise SystemsError("row_version must be a whole number")
    try:
        return svc.update_fields(_visible(svc, me, system_id), data, actor, version, for_user=me)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{system_id}/team", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def add_member(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    data = await _body(request)
    try:
        return svc.add_member(
            _visible(svc, me, system_id),
            check_user(data.get("user_id")),
            str(data.get("team_role", "")),
            actor,
        )
    except NotFoundError as exc:
        return _not_found(exc)


@router.delete("/{system_id}/team/{user}", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def remove_member(
    system_id: str,
    user: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    try:
        return svc.remove_member(_visible(svc, me, system_id), check_user(user), actor)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{system_id}/links", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def add_link(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    data = await _body(request)
    try:
        return svc.link(
            _visible(svc, me, system_id),
            str(data.get("ref_kind", "")),
            data.get("ref_id", ""),
            actor,
            role=str(data.get("role", "component_of")),
            evidence_ref=data.get("evidence_ref", "") or "",
            for_user=me,
        )
    except NotFoundError as exc:
        return _not_found(exc)


@router.delete("/{system_id}/links/{component_id}", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def remove_link(
    system_id: str,
    component_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    try:
        return svc.unlink(_visible(svc, me, system_id), component_id, actor)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{system_id}/archive", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def archive_system(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    try:
        return svc.archive(_visible(svc, me, system_id), actor)
    except NotFoundError as exc:
        return _not_found(exc)


# ---------------------------------------------------------------------- WP-G1


def _lifecycle(ctx: ConsoleContext) -> Any:
    ensure_on(ctx.settings)
    return ctx.lifecycle


def _reviews(ctx: ConsoleContext) -> Any:
    ensure_on(ctx.settings)
    return ctx.reviews


@router.get("/{system_id}/approvals", dependencies=[Depends(needs("systems.view"))])
def list_approvals(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _service(ctx)
    try:
        sid = _visible(svc, me, system_id)
        return {"system_id": sid, "approvals": _lifecycle(ctx).approvals(sid)}
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{system_id}/approvals", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def request_approval(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    data = await _body(request)
    try:
        out = _lifecycle(ctx).request(
            _visible(svc, me, system_id), str(data.get("to_stage", "")), actor
        )
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = "approval_request"
    return JSONResponse(status_code=201, content=out)


@router.post(
    "/{system_id}/approvals/{approval_id}/decide", dependencies=[Depends(needs("systems.approve"))]
)
@audited("systems.approve")
async def decide_approval(
    system_id: str,
    approval_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    svc = _service(ctx)
    _actor(me)
    data = await _body(request)
    try:
        out = _lifecycle(ctx).decide(
            _visible(svc, me, system_id),
            approval_id,
            str(data.get("decision", "")),
            me,
            data.get("reason"),
        )
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"approval_{out['status']}"
    return out


@router.post("/{system_id}/stage", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def move_stage(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    data = await _body(request)
    try:
        out = _lifecycle(ctx).move(
            _visible(svc, me, system_id), str(data.get("to_stage", "")), actor
        )
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = "stage_move"
    return out


@router.get("/{system_id}/reviews", dependencies=[Depends(needs("systems.view"))])
def list_reviews(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _service(ctx)
    try:
        sid = _visible(svc, me, system_id)
        rows = _reviews(ctx).list_reviews(sid)
        return {"system_id": sid, "count": len(rows), "reviews": rows}
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{system_id}/reviews", dependencies=[Depends(needs("systems.review"))])
@audited("systems.review")
async def create_review(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    data = await _body(request)
    try:
        out = _reviews(ctx).create(_visible(svc, me, system_id), data, actor)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = "review_create"
    return JSONResponse(status_code=201, content=out)


@router.patch("/{system_id}/reviews/{review_id}", dependencies=[Depends(needs("systems.review"))])
@audited("systems.review")
async def update_review(
    system_id: str,
    review_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    svc = _service(ctx)
    actor = _actor(me)
    data = await _body(request)
    version = data.pop("row_version", None)
    if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
        raise SystemsError("row_version must be a whole number")
    try:
        return _reviews(ctx).update(_visible(svc, me, system_id), review_id, data, actor, version)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post(
    "/{system_id}/reviews/{review_id}/complete", dependencies=[Depends(needs("systems.review"))]
)
@audited("systems.review")
async def complete_review(
    system_id: str,
    review_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    svc = _service(ctx)
    _actor(me)
    try:
        return _reviews(ctx).complete(_visible(svc, me, system_id), review_id, me)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post(
    "/{system_id}/reviews/{review_id}/reopen", dependencies=[Depends(needs("systems.review"))]
)
@audited("systems.review")
async def reopen_review(
    system_id: str,
    review_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    svc = _service(ctx)
    _actor(me)
    data = await _body(request)
    try:
        return _reviews(ctx).reopen(_visible(svc, me, system_id), review_id, me, data.get("reason"))
    except NotFoundError as exc:
        return _not_found(exc)
