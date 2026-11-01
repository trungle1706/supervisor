"""Red team test routes (W7, flag ``REDTEAM_TAB``): run the multi-turn red team on one AI system
before go-live, watch it run and read the report.

Always mounted; with the setting off every route answers HTTP 400 ``redteam_tab_off`` and reads
nothing. Starting and cancelling a run is ``systems.edit``; reading is ``systems.view`` (and the
system must be in the caller's scope). The sandbox agent is simulated; nothing here reaches a real
agent, a policy or the gate.

* ``GET  /console/redteam/panel/{system}``       the step panel / tab body (an htmx fragment)
* ``POST /console/redteam/{system}/run``         start a run (htmx), answers the live panel
* ``GET  /console/redteam/progress/{run}``       the poll target of the live panel
* ``POST /console/redteam/run/{run}/cancel``     stop after the current conversation
* ``GET  /console/redteam/run/{run}``            the live page (full screen)
* ``GET  /console/redteam/report/{run}``         the report (full page, printable)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import redteam_view as rv
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import _call, _htmx_only, audited, form, render
from supervisor.redteam import usecase as uc

router = APIRouter(prefix="/console/redteam", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
_BASE = "/console/redteam"


def _on(ctx: ConsoleContext) -> None:
    uc.require_on(ctx.settings)


def _redirect(url: str) -> Response:
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = url
    return resp


def _where(request: Request) -> str:
    return "tab" if request.query_params.get("where") == "tab" else "step"


@router.get(
    "/panel/{system_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def panel(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _on(ctx)
    where = _where(request)
    if request.headers.get("hx-request") != "true":
        return RedirectResponse(f"/console/systems/{system_id}?tab=redteam", status_code=303)
    data = await _call(rv.panel_data, ctx, me, system_id, where)
    return render(request, ctx, me, "_redteam_step_panel.html", **data)


@router.post(
    "/{system_id}/run",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def start(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _on(ctx)
    f = await form(request)
    where = _where(request)

    def work() -> dict[str, Any]:
        system = rv.system_of(ctx, me, system_id)
        if not rv.can_run(me, system):
            raise uc.RedteamError("bad_state", "This AI system is archived. Choose another system.")
        opts = uc.parse_options(f, ctx.settings)
        chat = rv.chat_of(ctx) if opts.attacker == "ai" else None
        got = uc.start(rv.run_env(ctx, chat), system, opts, str(getattr(me, "user_id", "")))
        return {**got, "system": system}

    got = await _call(work)
    request.state.audit_detail = f"red team run {got['run_id']} queued"[:200]
    data = await _call(rv.progress_data, ctx, me, got["run_id"])
    data["where"] = where
    return render(request, ctx, me, "_redteam_progress.html", **data)


@router.get(
    "/progress/{run_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def progress(
    run_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """The poll target. While the run goes it answers the live panel. When it has ended the
    step panel answers the finished panel, and the full page is sent to the report."""
    _on(ctx)
    where = request.query_params.get("where") or "run"
    data = await _call(rv.progress_data, ctx, me, run_id)
    if not data["pg"]["active"] and request.headers.get("hx-request") == "true":
        if where == "run":
            return _redirect(f"{_BASE}/report/{run_id}")
        pdata = await _call(rv.panel_data, ctx, me, data["rt"]["system_id"], where)
        return render(request, ctx, me, "_redteam_step_panel.html", **pdata)
    data["where"] = where
    return render(request, ctx, me, "_redteam_progress.html", **data)


@router.post(
    "/run/{run_id}/cancel",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def cancel(
    run_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _on(ctx)
    _htmx_only(request)
    where = request.query_params.get("where") or "run"

    def work() -> None:
        row_system = (uc.live(run_id).system_id if uc.live(run_id) else None) or uc.get_run(
            ctx.state, run_id
        )["system_id"]
        rv.system_of(ctx, me, row_system)
        uc.cancel(run_id)

    await _call(work)
    request.state.audit_detail = f"red team run {run_id} cancel"[:200]
    data = await _call(rv.progress_data, ctx, me, run_id)
    data["where"] = where
    return render(request, ctx, me, "_redteam_progress.html", **data)


@router.get(
    "/run/{run_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def run_page(
    run_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _on(ctx)
    data = await _call(rv.progress_data, ctx, me, run_id)
    if not data["pg"]["active"]:
        return RedirectResponse(f"{_BASE}/report/{run_id}", status_code=303)
    data["where"] = "run"
    return render(request, ctx, me, "redteam_run.html", section="systems", **data)


@router.get(
    "/report/{run_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def report(
    run_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _on(ctx)
    from supervisor.console.routes import _lang

    lang = _lang(request, ctx)
    data = await _call(rv.report_data, ctx, me, run_id, lang)
    if data["run"]["active"]:
        return RedirectResponse(f"{_BASE}/run/{run_id}", status_code=303)
    return render(request, ctx, me, "redteam_report.html", section="systems", **data)
