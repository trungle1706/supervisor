"""JSON routes of the onboarding orchestrator (WP-F4, docs/orchestrator.md).

* ``POST /v1/systems/{id}/orchestrate`` (systems.edit): plan and start a run; 202 with the run row.
  A second POST while a run is queued or running answers 400 ``run_in_progress``. A system without
  an approved classification, a prohibited one and a not_system one answer 400 ``plan_blocked``.
* ``GET /v1/systems/{id}/orchestrate`` (systems.view): the newest run with its items (404 when the
  system has no run).
* ``GET /v1/orchestrate/{run_id}`` (systems.view): one run.
* ``GET /v1/orchestrate/{run_id}/reports/{dim}`` (systems.view): the stored ``assessment_report_v1``
  of one risk type.

Mounted by ``app.py`` when GOVERNANCE_ENABLED=1. While ONBOARD_ORCHESTRATOR is off every route
answers HTTP 400 ``orchestrator_off`` and reads no table. A system outside the caller's scope
answers 404. A POST writes two ``console_action`` rows. Never 500.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import audited
from supervisor.core.errors import NotFoundError
from supervisor.governance.routes import _actor, _not_found, _service, _visible
from supervisor.onboard import orchestrator as orch

router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def _scope(ctx: ConsoleContext, me: AuthPrincipal, system_id: str) -> str:
    orch.ensure_on(ctx.settings)
    return _visible(_service(ctx), me, system_id)


def audit_note(run: orch.OrchestratorRun) -> str:
    return f"orchestrate attempt={run.attempt_n} plan_sha={run.plan_hash[:12]}"


@router.post("/systems/{system_id}/orchestrate", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def post_orchestrate(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    orch.ensure_on(ctx.settings)
    actor = _actor(me)
    try:
        sid = _visible(_service(ctx), me, system_id)
    except NotFoundError as exc:
        return _not_found(exc)
    run = orch.start(ctx, sid, actor)
    request.state.audit_detail = audit_note(run)
    return JSONResponse(status_code=202, content=run.to_dict())


@router.get("/systems/{system_id}/orchestrate", dependencies=[Depends(needs("systems.view"))])
def get_orchestrate(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    try:
        sid = _scope(ctx, me, system_id)
    except NotFoundError as exc:
        return _not_found(exc)
    run = orch.latest(ctx, sid)
    if run is None:
        return JSONResponse(status_code=404, content={"error": f"no run for {sid} yet"})
    return run.to_dict()


def _run_in_scope(ctx: ConsoleContext, me: AuthPrincipal, run_id: str) -> orch.OrchestratorRun:
    orch.ensure_on(ctx.settings)
    run = orch.get(ctx, run_id) if len(run_id) <= 64 else None
    if run is None:
        raise NotFoundError(f"run {run_id[:64]} does not exist")
    _visible(_service(ctx), me, run.system_id)
    return run


@router.get("/orchestrate/{run_id}", dependencies=[Depends(needs("systems.view"))])
def get_run(run_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    try:
        return _run_in_scope(ctx, me, run_id).to_dict()
    except NotFoundError as exc:
        return _not_found(exc)


@router.get("/orchestrate/{run_id}/reports/{dim}", dependencies=[Depends(needs("systems.view"))])
def get_run_report(
    run_id: str, dim: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    try:
        run = _run_in_scope(ctx, me, run_id)
    except NotFoundError as exc:
        return _not_found(exc)
    path = orch.report_path(ctx.settings, run.system_id, run.attempt_n, dim)
    if path is None:
        return JSONResponse(status_code=404, content={"error": f"no report for {dim[:40]}"})
    return json.loads(path.read_text(encoding="utf-8"))
