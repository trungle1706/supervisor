"""JSON routes of the eight risk types per AI system (WP-C2, docs/risk-dimensions.md).

* ``GET /v1/systems/{id}/risk-dimensions`` (systems.view): the eight rows with definition,
  status, evidence pointers, threshold and the rule proposal. The first read makes the rows.
* ``POST /v1/systems/{id}/risk-dimensions`` (systems.edit): body ``dimension_id`` and either
  ``status`` (not_started | in_progress | pass | fail | not_applicable) with optional
  ``evidence`` (list of pointers), ``note``, ``threshold``, ``valid_until``, ``report_ref``, or
  ``confirm_proposal: true`` to store the rule proposal.
* ``POST /v1/systems/{id}/risk-dimensions/{dim}/waive`` (systems.approve): body ``reason`` (20
  characters or more). The owner of the system gets HTTP 400 ``owner_cannot_waive``.
* ``GET /v1/risk-dimensions/summary`` (systems.view): counts per type and status over the
  systems in the caller's scope (for the portfolio views).

Mounted by ``app.py`` when GOVERNANCE_ENABLED=1. While RISK_DIMENSIONS is off every route
answers HTTP 400 ``risk_dimensions_off`` and reads no table. A system outside the caller's scope
answers 404. Every write makes two ``console_action`` audit rows (with ``before>after``) and a
``risk_dimension_status`` chain record. Never 500.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import systems_riskdim as srd
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import audited
from supervisor.core.errors import NotFoundError
from supervisor.governance import risk_dimensions as rd
from supervisor.governance.routes import _actor, _body, _not_found, _service, _visible

router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def _system(ctx: ConsoleContext, me: AuthPrincipal, system_id: str) -> dict[str, Any]:
    rd.ensure_on(ctx.settings)
    svc = _service(ctx)
    return dict(svc.get(_visible(svc, me, system_id)))


@router.get("/systems/{system_id}/risk-dimensions", dependencies=[Depends(needs("systems.view"))])
def get_risk_dimensions(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    try:
        return rd.view(rd.Env.from_console(ctx), _system(ctx, me, system_id))
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/systems/{system_id}/risk-dimensions", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def post_risk_dimension(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    rd.ensure_on(ctx.settings)
    actor = _actor(me)
    data = await _body(request)
    try:
        system = _system(ctx, me, system_id)
    except NotFoundError as exc:
        return _not_found(exc)
    env = rd.Env.from_console(ctx)
    dim = str(data.get("dimension_id") or "")
    if data.get("confirm_proposal") is True:
        out = rd.confirm_proposal(env, actor, system, dim)
    else:
        out = rd.set_status(
            env,
            actor,
            system,
            dim,
            data.get("status"),
            evidence=data.get("evidence"),
            note=data.get("note"),
            threshold=data.get("threshold"),
            valid_until=data.get("valid_until"),
            report_ref=data.get("report_ref"),
        )
    request.state.audit_detail = srd.audit_note(out, str(data.get("note") or "") or None)
    return out


@router.post(
    "/systems/{system_id}/risk-dimensions/{dim}/waive",
    dependencies=[Depends(needs("systems.approve"))],
)
@audited("systems.approve")
async def waive_risk_dimension(
    system_id: str,
    dim: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    rd.ensure_on(ctx.settings)
    actor = _actor(me)
    data = await _body(request)
    try:
        system = _system(ctx, me, system_id)
    except NotFoundError as exc:
        return _not_found(exc)
    out = rd.waive(rd.Env.from_console(ctx), actor, system, dim, data.get("reason"))
    request.state.audit_detail = srd.audit_note(out, str(data.get("reason") or "") or None)
    return out


@router.get("/risk-dimensions/summary", dependencies=[Depends(needs("systems.view"))])
def risk_dimensions_summary(ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    rd.ensure_on(ctx.settings)
    svc = _service(ctx)
    rows = svc.list_systems(svc.scope_for(me), {})
    ids = [str(r["system_id"]) for r in rows if r.get("status") != "archived"]
    return rd.summary(rd.Env.from_console(ctx), ids)
