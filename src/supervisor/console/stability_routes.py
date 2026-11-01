"""Stability tab routes (W8, setting ``STABILITY_TAB``).

Always mounted; with the setting off every route answers HTTP 400 and reads nothing. Both routes
only read: the tab never pauses, resumes or changes anything.

* ``GET /console/systems/{system_id}/stability``  the tab as a page (the same content as
  ``/console/systems/{id}?tab=stability``), ``systems.view``
* ``GET /console/systems/{system_id}/stability/panel``  the refresh fragment that the page asks
  for every 10 seconds while it is live; query ``view`` (hour, day, week), ``agent``, ``live``
  (``0`` pauses the refresh)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import stability_view as sv
from supervisor.console import systems_views
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import _call, render

router = APIRouter(prefix="/console", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def panel_vars(
    ctx: ConsoleContext, me: AuthPrincipal, system_id: str, query: Any
) -> dict[str, Any]:
    sv.require_on(ctx.settings)
    system = systems_views._need_visible(ctx, me, system_id)  # noqa: SLF001 - same visibility rule
    return {"s": system, **sv.page_data(ctx, system, dict(query))}


@router.get(
    "/systems/{system_id}/stability/panel",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def stability_panel(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    data = await _call(panel_vars, ctx, me, system_id, request.query_params)
    return render(request, ctx, me, "_stability_panel.html", **data)


@router.get(
    "/systems/{system_id}/stability",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def stability_page(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    sv.require_on(ctx.settings)
    lang = request.query_params.get("lang")
    suffix = f"&lang={lang}" if lang in ("en", "vi") else ""
    return RedirectResponse(f"/console/systems/{system_id}?tab=stability{suffix}", status_code=303)
