"""JSON routes of the assignment rules and the Decision 33 classification (WP-G2).

Rules (docs/assignment-rules.md):
* ``GET  /v1/systems/{id}/assignments`` (systems.view): what the rules put on the system; ``?all=1``
  adds the rows that are switched off.
* ``GET  /v1/systems/{id}/obligations`` (systems.view): the obligations the rules assigned, as
  compliance matrix rows with source ``rule``.
* ``GET  /v1/systems/{id}/guardian-floor`` (systems.view): feature slugs the owner cannot switch
  off, each with the rule ids (for WP-S1).
* ``GET  /v1/systems/{id}/rules/explain`` (systems.view): the trace of every rule, ASCII lines.
* ``POST /v1/systems/{id}/assignments/run`` (systems.edit): run the rules now.

Classification (docs/decision33.md):
* ``GET   /v1/systems/{id}/classification`` (systems.view): the open draft and the applied one.
* ``POST  /v1/systems/{id}/classification`` (systems.edit): make a draft from the rules.
* ``PATCH /v1/systems/{id}/classification`` (systems.edit): a person edits answers.
* ``POST  /v1/systems/{id}/classification/apply`` (systems.edit): a person applies the draft.

Mounted by ``app.py`` with the other governance routes, only when GOVERNANCE_ENABLED=1. A system
outside the caller's scope answers 404. A bad input is HTTP 400 with the reason; never 500.
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
from supervisor.governance.classification import ClassificationService
from supervisor.governance.model import SystemsError, ensure_on
from supervisor.governance.routes import _actor, _body, _not_found, _service, _visible
from supervisor.governance.rules_service import RulesService

router = APIRouter(prefix="/v1/systems", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def _rules(ctx: ConsoleContext) -> RulesService:
    ensure_on(ctx.settings)
    svc: RulesService = ctx.rules
    return svc


def _classification(ctx: ConsoleContext) -> ClassificationService:
    ensure_on(ctx.settings)
    svc: ClassificationService = ctx.classification
    return svc


def _see(ctx: ConsoleContext, me: AuthPrincipal, system_id: str) -> str:
    return _visible(_service(ctx), me, system_id)


@router.get("/{system_id}/assignments", dependencies=[Depends(needs("systems.view"))])
def get_assignments(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _rules(ctx)
    try:
        sid = _see(ctx, me, system_id)
        every = request.query_params.get("all") in ("1", "true")
        rows = svc.assignments(sid, active_only=not every)
        return {"system_id": sid, "count": len(rows), "assignments": rows}
    except NotFoundError as exc:
        return _not_found(exc)


@router.get("/{system_id}/obligations", dependencies=[Depends(needs("systems.view"))])
def get_obligations(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _rules(ctx)
    try:
        sid = _see(ctx, me, system_id)
        rows = svc.obligations(sid)
        return {"system_id": sid, "count": len(rows), "obligations": rows}
    except NotFoundError as exc:
        return _not_found(exc)


@router.get("/{system_id}/guardian-floor", dependencies=[Depends(needs("systems.view"))])
def get_guardian_floor(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _rules(ctx)
    try:
        sid = _see(ctx, me, system_id)
        floor = svc.guardian_floor(sid)
        return {"system_id": sid, "count": len(floor), "floor": floor}
    except NotFoundError as exc:
        return _not_found(exc)


@router.get("/{system_id}/rules/explain", dependencies=[Depends(needs("systems.view"))])
def get_explain(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _rules(ctx)
    try:
        sid = _see(ctx, me, system_id)
        return {"system_id": sid, "lines": svc.explain(sid)}
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{system_id}/assignments/run", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def run_rules(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _rules(ctx)
    actor = _actor(me)
    try:
        return svc.run(_see(ctx, me, system_id), actor, "manual")
    except NotFoundError as exc:
        return _not_found(exc)


@router.get("/{system_id}/classification", dependencies=[Depends(needs("systems.view"))])
def get_classification(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _classification(ctx)
    try:
        return svc.get(_see(ctx, me, system_id))
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{system_id}/classification", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def draft_classification(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _classification(ctx)
    actor = _actor(me)
    try:
        out = svc.draft(_see(ctx, me, system_id), actor)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = "classification draft"
    return JSONResponse(status_code=201, content=out)


@router.patch("/{system_id}/classification", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def edit_classification(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _classification(ctx)
    actor = _actor(me)
    data = await _body(request)
    answers = data.get("answers", data)
    try:
        out = svc.edit(_see(ctx, me, system_id), actor, answers)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = "classification edit"
    return out


@router.post("/{system_id}/classification/apply", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def apply_classification(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _classification(ctx)
    _actor(me)
    data = await _body(request)
    confirm = data.get("confirm_ai_prefill", False)
    if not isinstance(confirm, bool):
        raise SystemsError("confirm_ai_prefill must be true or false")
    try:
        out = svc.apply(_see(ctx, me, system_id), me, confirm_ai_prefill=confirm)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = "classification apply"
    return out


@router.post("/{system_id}/risk-level/lower", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def lower_risk_level(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    """Lower the stored risk level with a written reason, by a person who is not the owner."""
    svc = _service(ctx)
    actor = _actor(me)
    data = await _body(request)
    try:
        out = svc.lower_risk_level(
            _visible(svc, me, system_id),
            str(data.get("level", "")),
            data.get("reason", ""),
            actor,
        )
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = "risk lower"
    return out
