"""Inventory run routes (W4, flag ``FACTORY_INVENTORY_RUN``): run one risk assessment agent over the
whole AI inventory and look at the result as a dashboard.

Always mounted; with the setting off every route answers HTTP 400 ``factory_inventory_off`` and
reads nothing. Starting and cancelling a run is ``factory.edit`` plus the group check of the
editor (like the simulation routes); reading is ``systems.view``. A run is a simulation: it never
promotes a version and never changes an assessment.

* ``GET  /console/factory/{id}/inventory``                          the runs and the start form
* ``POST /console/factory/{id}/inventory/run``                      start a run
* ``GET  /console/factory/{id}/inventory/{run}``                    progress, then the dashboard
* ``GET  /console/factory/{id}/inventory/{run}/progress``           the poll target of the bar
* ``POST /console/factory/{id}/inventory/{run}/cancel``             stop the run
* ``GET  /console/factory/{id}/inventory/{run}/system/{system}``    one system
* ``GET  /console/factory/{id}/inventory/{run}/export.csv``         the per-system results
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import factory_inventory_view as fiv
from supervisor.console import factory_view as fv
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import _call, audited, form, render
from supervisor.factory import inventory_run as inv
from supervisor.factory.store import FactoryError

router = APIRouter(prefix="/console", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
_SYSTEM_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_BASE = "/console/factory"


def _on(ctx: ConsoleContext) -> None:
    inv.require_on(ctx.settings)


def _redirect(url: str) -> Response:
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = url
    return resp


@router.get(
    "/factory/{agent_id}/inventory",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def inventory_list(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _on(ctx)
    data = await _call(fiv.list_data, ctx, me, agent_id)
    return render(request, ctx, me, "factory_inventory_list.html", section="", **data)


@router.post(
    "/factory/{agent_id}/inventory/run",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def inventory_start(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _on(ctx)
    f = await form(request)

    def work() -> dict[str, Any]:
        row = fv.load_row(ctx, agent_id, f.get("version", ""))
        who = fv.require_edit(me, row["owner_group"])
        return inv.start(fiv.env(ctx), agent_id, row["version"], who)

    run = await _call(work)
    request.state.audit_detail = f"inventory run {run['run_id']} queued"[:200]
    return _redirect(f"{_BASE}/{agent_id}/inventory/{run['run_id']}")


@router.get(
    "/factory/{agent_id}/inventory/{run_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def inventory_run_page(
    agent_id: str,
    run_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _on(ctx)
    data = await _call(fiv.run_data, ctx, me, agent_id, run_id, dict(request.query_params))
    return render(request, ctx, me, "factory_inventory_run.html", section="", **data)


@router.get(
    "/factory/{agent_id}/inventory/{run_id}/progress",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def inventory_progress(
    agent_id: str,
    run_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    """The poll target. While the run goes it answers the progress panel; when it has ended the
    browser is sent to the dashboard page."""
    _on(ctx)
    data = await _call(fiv.run_data, ctx, me, agent_id, run_id, {})
    if not data["run"]["active"] and request.headers.get("hx-request"):
        return _redirect(f"{_BASE}/{agent_id}/inventory/{run_id}")
    return render(request, ctx, me, "_factory_inventory_progress.html", **data)


@router.post(
    "/factory/{agent_id}/inventory/{run_id}/cancel",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def inventory_cancel(
    agent_id: str,
    run_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _on(ctx)
    await form(request)

    def work() -> dict[str, Any]:
        row = fv.load_row(ctx, agent_id)
        fv.require_edit(me, row["owner_group"])
        try:
            return inv.cancel(fiv.env(ctx), agent_id, run_id)
        except inv.InventoryError as exc:
            raise FactoryError(exc.code, str(exc).partition(": ")[2]) from None

    await _call(work)
    request.state.audit_detail = f"inventory run {run_id} cancel"[:200]
    data = await _call(fiv.run_data, ctx, me, agent_id, run_id, {})
    return render(request, ctx, me, "_factory_inventory_progress.html", **data)


@router.get(
    "/factory/{agent_id}/inventory/{run_id}/system/{system_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def inventory_system(
    agent_id: str,
    run_id: str,
    system_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _on(ctx)
    if not _SYSTEM_ID.match(system_id):
        raise FactoryError("bad_id", "this is not an AI system id")
    data = await _call(fiv.system_data, ctx, me, agent_id, run_id, system_id)
    return render(request, ctx, me, "factory_inventory_system.html", section="", **data)


@router.get(
    "/factory/{agent_id}/inventory/{run_id}/export.csv",
    dependencies=[Depends(needs("systems.view"))],
)
async def inventory_export(
    agent_id: str,
    run_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _on(ctx)

    def work() -> str:
        run = fiv.load_run(ctx, agent_id, run_id)
        if run["status"] in inv.ACTIVE:
            raise FactoryError("not_done", "the run has not finished")
        rows = inv.read_rows(inv.run_dir(ctx.settings.data_dir, agent_id, run_id))
        return inv.to_csv(run, rows)

    body = await _call(work)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="inventory-{agent_id}-{run_id}.csv"',
            "Cache-Control": "no-store",
        },
    )
