"""``GET /v1/analytics/tools``: the tool usage rollup as JSON (WP22).

For Databricks notebooks and dashboards that prefer the API to reading the Delta table
(``notebooks/tool_usage_analytics.py`` reads the table). Read only. Needs ``tools.view``
(any signed-in role, or a service principal). Off (HTTP 400 with a message) unless
``TOOL_ANALYTICS_ENABLED=1``. User errors are HTTP 400.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from supervisor.adapters.auth.authz import needs
from supervisor.analytics import tools, tools_suggest
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.tools_views import ToolsInputError, check_agent, check_days

router = APIRouter(prefix="/analytics", tags=["analytics"])

VIEWS = ("daily", "summary")


def _ctx() -> ConsoleContext:
    return get_context()


def _day_text(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for k in ("usage_date", "first_seen", "last_seen", "computed_at", "updated_at"):
        v = out.get(k)
        if v is not None and hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    return out


def _build(ctx: ConsoleContext, agent_id: str | None, days: int, view: str) -> dict[str, Any]:
    as_of = ctx.clock.now().astimezone(UTC).date()
    start, end = tools.window_bounds(as_of, days)
    rows = tools.load_daily(ctx.state, agent_id=agent_id, start=start, end=end)
    body: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "agent_id": agent_id,
        "view": view,
    }
    if view == "daily":
        body["rows"] = [_day_text(r) for r in rows]
        return body
    summary = tools.summarise(rows)
    body["rows"] = [_day_text(r) for r in summary]
    body["suggestions"] = [
        {k: v for k, v in _day_text_sug(s).items() if k != "manifest_tools"}
        for s in tools_suggest.build_all(
            ctx.state, ctx.settings, as_of=as_of, days=days, agent_id=agent_id, with_diff=False
        )
    ]
    return body


def _day_text_sug(s: dict[str, Any]) -> dict[str, Any]:
    out = dict(s)
    out["tools"] = [_day_text(e) for e in s["tools"]]
    out["undeclared"] = [_day_text(e) for e in s["undeclared"]]
    return out


@router.get("/tools", dependencies=[Depends(needs("tools.view"))])
async def tool_usage(
    request: Request, agent_id: str | None = None, days: str | None = None, view: str = "daily"
) -> JSONResponse:
    ctx = _ctx()
    if not ctx.settings.tool_analytics_enabled:
        return JSONResponse(
            status_code=400,
            content={"error": "tool analytics is off (TOOL_ANALYTICS_ENABLED=1 turns it on)"},
        )
    try:
        agent = check_agent(agent_id)
        n = check_days(days, ctx.settings)
        if view not in VIEWS:
            raise ToolsInputError(f"view must be one of: {', '.join(VIEWS)}")
        body = await run_in_threadpool(_build, ctx, agent, n, view)
    except (ToolsInputError, tools.AnalyticsError) as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return JSONResponse(content=body)
