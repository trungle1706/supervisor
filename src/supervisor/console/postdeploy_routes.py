"""Post-deploy assessment routes (WP-O5, ``ONBOARD_POSTDEPLOY``): the Post-deploy panel of an agent
and a candidate, and the JSON API. The routers are always mounted; with the flag off every route
answers HTTP 400 ``postdeploy_off`` (nothing is read or written).

* ``GET /console/postdeploy/{node_id}``  the panel (an htmx fragment; a full page without htmx),
                                          ``systems.view``; optional ``?days=`` (1 to 90, default 7)
* ``GET /v1/postdeploy/{node_id}``       the same data as JSON (``systems.view``): the assessment,
                                          the newest pre-deploy report and the agent log

Both routes only read. See ``supervisor.onboard.postdeploy`` for the figures and
``supervisor.onboard.agent_log`` for the log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import agent_detail
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import _call, render
from supervisor.onboard import agent_log, intake, postdeploy
from supervisor.onboard.predeploy import PredeployService

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)

# The agent log reads as a story: plan, read, found, suggest. Each step sits in one phase.
PHASE = {
    "scan": "plan",
    "intake": "read",
    "facts": "read",
    "predeploy": "found",
    "attach": "found",
    "postdeploy": "found",
    "duties": "suggest",
    "state": "suggest",
}
PHASES = ("plan", "read", "found", "suggest")
ITEMS_SHOWN = 10  # pre-deploy items that need a look (fail, question)


def _predeploy_side(ctx: ConsoleContext, node_id: str) -> dict[str, Any] | None:
    """The newest pre-deploy report as a view (``None`` when the flag is off or no report)."""
    if not ctx.settings.onboard_predeploy:
        return None
    return PredeployService(ctx.settings, ctx.state, ctx.clock, ctx=ctx).latest(node_id)


def _log_rows(ctx: ConsoleContext, node_id: str) -> list[dict[str, Any]]:
    out = []
    for r in agent_log.rows(ctx, node_id):
        out.append({**r, "phase": PHASE.get(r["step"], "found")})
    return out


def data_of(ctx: ConsoleContext, node_id: str, days: Any = None) -> dict[str, Any]:
    """The assessment, the pre-deploy report and the agent log of one node."""
    n = postdeploy.parse_days(days)
    return {
        "node_id": node_id,
        "assessment": postdeploy.assess(ctx, node_id, n),
        "predeploy": _predeploy_side(ctx, node_id),
        "agent_log": _log_rows(ctx, node_id),
    }


def panel_data(
    ctx: ConsoleContext, me: AuthPrincipal, node_id: str, days: Any = None
) -> dict[str, Any]:
    """Template variables of the Post-deploy panel (``_postdeploy_panel.html``)."""
    d = data_of(ctx, node_id, days)
    pd = d["predeploy"]
    attention = (
        [i for i in pd["items"] if i["status"] in ("fail", "question")][:ITEMS_SHOWN] if pd else []
    )
    return {
        "px": {
            **d,
            "attention": attention,
            "phases": PHASES,
            "predeploy_on": bool(ctx.settings.onboard_predeploy),
            "can_edit": agent_detail.can(me, "systems.edit"),
        }
    }


# ------------------------------------------------------------------------------- JSON API


@api_router.get("/postdeploy/{node_id}", dependencies=[Depends(needs("systems.view"))])
async def get_postdeploy(node_id: str, request: Request, ctx: ConsoleContext = _CTX) -> Any:
    postdeploy.require_on(ctx.settings)
    intake.check_node_id(node_id)
    return await _call(data_of, ctx, node_id, request.query_params.get("days"))


# ------------------------------------------------------------------------------- console


@router.get(
    "/postdeploy/{node_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def postdeploy_panel(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    postdeploy.require_on(ctx.settings)
    intake.check_node_id(node_id)
    data = await _call(panel_data, ctx, me, node_id, request.query_params.get("days"))
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, "_postdeploy_panel.html", **data)
    return render(request, ctx, me, "postdeploy.html", section="candidates", **data)
