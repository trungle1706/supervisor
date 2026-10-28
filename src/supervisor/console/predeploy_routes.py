"""Pre-deploy assessment routes (WP-O3, ONBOARD_PREDEPLOY): the Pre-deploy panel of a candidate and
an agent and the JSON API. The routers are always mounted; with the flag off every route answers
HTTP 400 ``predeploy_off`` (nothing is read or written).

* ``POST /v1/predeploy/{node_id}/{n}``  start an assessment of intake attempt ``n``
                                         (``systems.edit``); 202 with the queued report
* ``GET  /v1/predeploy/{node_id}``      the newest report (``systems.view``)
* ``GET  /console/predeploy/{node_id}`` the panel (an htmx fragment; a full page without htmx);
                                         while a run is going it polls itself every 3 s
* ``POST /console/predeploy/{node_id}`` the **Run again** button: a new run for the newest
                                         attempt (``systems.edit``), htmx only

Every POST writes two ``console_action`` rows (``@audited``). A refusal is HTTP 400 with
``<code>: <text>``; see ``supervisor.onboard.predeploy``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import agent_detail
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import _call, _htmx_only, audited, message_html, render
from supervisor.onboard import intake, predeploy

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def service(ctx: ConsoleContext) -> predeploy.PredeployService:
    return predeploy.PredeployService(ctx.settings, ctx.state, ctx.clock, ctx=ctx)


def latest_attempt(ctx: ConsoleContext, node_id: str) -> int | None:
    """The newest stored intake attempt (status not ``failed``)."""
    ns = [
        int(r["n"])
        for r in ctx.state.query("intake_attempt", {"node_id": node_id})
        if r["status"] != "failed"
    ]
    return max(ns) if ns else None


def panel_data(ctx: ConsoleContext, me: AuthPrincipal, node_id: str) -> dict[str, Any]:
    """Template variables of the Pre-deploy panel (``_predeploy_panel.html``)."""
    on = bool(ctx.settings.onboard_predeploy)
    report = service(ctx).latest(node_id) if on else None
    latest = latest_attempt(ctx, node_id) if on else None
    return {
        "pd": {
            "node_id": node_id,
            "on": on,
            "report": report,
            "latest_attempt": latest,
            "newer_attempt": bool(report and latest is not None and latest > report["attempt_n"]),
            "can_edit": agent_detail.can(me, "systems.edit"),
        }
    }


def _start(ctx: ConsoleContext, node_id: str, n: int | None, by: str) -> dict[str, Any]:
    svc = service(ctx)
    if n is None:
        n = latest_attempt(ctx, node_id)
        if n is None:
            raise predeploy.PredeployError(
                "no_attempt", "there is no stored source; add one in the Source panel first"
            )
    return svc.start(node_id, n, by)


# ------------------------------------------------------------------------------- JSON API


@api_router.get("/predeploy/{node_id}", dependencies=[Depends(needs("systems.view"))])
def get_report(node_id: str, ctx: ConsoleContext = _CTX) -> Any:
    predeploy.require_on(ctx.settings)
    intake.check_node_id(node_id)
    return service(ctx).latest(node_id) or {"node_id": node_id, "status": "none", "verdict": "none"}


@api_router.post("/predeploy/{node_id}/{n}", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def post_start(
    node_id: str, n: int, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    predeploy.require_on(ctx.settings)
    intake.check_node_id(node_id)
    rep = await _call(_start, ctx, node_id, n, str(me.user_id))
    request.state.audit_detail = f"attempt={rep['attempt_n']} report={rep['report_id']}"
    return JSONResponse(status_code=202, content=rep)


# ------------------------------------------------------------------------------- console


@router.get(
    "/predeploy/{node_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def predeploy_panel(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    predeploy.require_on(ctx.settings)
    intake.check_node_id(node_id)
    data = await _call(panel_data, ctx, me, node_id)
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, "_predeploy_panel.html", **data)
    return render(request, ctx, me, "predeploy.html", section="candidates", **data)


@router.post(
    "/predeploy/{node_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def predeploy_again(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    predeploy.require_on(ctx.settings)
    intake.check_node_id(node_id)
    rep = await _call(_start, ctx, node_id, None, str(me.user_id))
    request.state.audit_detail = f"attempt={rep['attempt_n']} report={rep['report_id']}"
    data = await _call(panel_data, ctx, me, node_id)
    resp = render(request, ctx, me, "_predeploy_panel.html", **data)
    note = f"{node_id}: assessment of attempt {rep['attempt_n']} started"
    resp.body = resp.body + message_html(note, ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp
