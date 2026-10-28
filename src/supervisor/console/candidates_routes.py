"""Candidate triage routes (WP-N1): ``/console/candidates`` (the Candidates tab, a full page and an
htmx partial plus a row drawer) and ``GET /v1/candidates`` (JSON). Mounted by ``app.py`` only
when CONSOLE_OVERVIEW_V4=1. The pages also need CONSOLE_NAV_V3=1 and INVENTORY_ENABLED=1; each
answers HTTP 400 with the flag name when one is off. Read only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import overview_v4
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import ConsoleInputError, _call, _check_id, render
from supervisor.governance.register_v2 import links as rl
from supervisor.inventory.api import InventoryInputError

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def _off(ctx: ConsoleContext, *, page: bool = True) -> None:
    if not ctx.settings.console_overview_v4:
        raise ConsoleInputError("Candidates are off (CONSOLE_OVERVIEW_V4=1 turns them on)")
    if page and not ctx.settings.console_nav_v3:
        raise ConsoleInputError("The Candidates page needs CONSOLE_NAV_V3=1")
    if not ctx.settings.inventory_enabled:
        raise ConsoleInputError(
            "The inventory is off (INVENTORY_ENABLED=1 turns it on); "
            "python -m supervisor.jobs.inventory fills it"
        )


def _page_data(ctx: ConsoleContext, query: Any, src: str) -> dict[str, Any]:
    rows = overview_v4.load_candidates(ctx) or []
    top = src == "top"
    data = overview_v4.candidates_view(
        rows,
        query,
        size=overview_v4.CAND_PAGE_TOP if top else overview_v4.CAND_PAGE_FULL,
        with_filters=not top,
    )
    data["cand_url"] = "/console/" if top else "/console/candidates"
    data["cand_src"] = "top" if top else ""
    data["cand_register"] = bool(
        ctx.settings.console_systems_enabled and ctx.settings.console_nav_v3
    )
    data["cand_reg_base"] = _reg_base(ctx)
    return data


def _reg_base(ctx: ConsoleContext) -> str:
    """Where Register goes: the six-step workflow while it is on, else the old wizard."""
    return rl.candidate_href(ctx.settings, "x").split("?", 1)[0]


def _drawer_data(ctx: ConsoleContext, node_id: str) -> dict[str, Any]:
    _check_id(node_id, "candidate id")
    data = overview_v4.drawer_view(overview_v4.load_candidates(ctx) or [], node_id)
    data["register"] = bool(ctx.settings.console_systems_enabled and ctx.settings.console_nav_v3)
    data["reg_base"] = _reg_base(ctx)
    data["intake"] = bool(ctx.settings.onboard_intake)  # WP-O1: the Source panel
    data["facts"] = bool(ctx.settings.onboard_facts)  # WP-O2: the Facts panel
    data["predeploy"] = bool(ctx.settings.onboard_predeploy)  # WP-O3: the Pre-deploy panel
    data["attach"] = bool(ctx.settings.onboard_attach_view)  # WP-O4: the Attach panel
    data["postdeploy"] = bool(ctx.settings.onboard_postdeploy)  # WP-O5: the Post-deploy panel
    return data


@router.get(
    "/candidates", response_class=HTMLResponse, dependencies=[Depends(needs("inventory.view"))]
)
async def candidates_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    data = await _call(_page_data, ctx, request.query_params, "")
    opened = request.query_params.get("drawer")
    if opened:  # no-JS fallback of the row drawer
        data["drawer"] = await _call(_drawer_data, ctx, opened)
        data["drawer_open"] = True
    return render(request, ctx, me, "candidates.html", section="candidates", **data)


@router.get(
    "/candidates/rows", response_class=HTMLResponse, dependencies=[Depends(needs("inventory.view"))]
)
async def candidates_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    src = "top" if request.query_params.get("src") == "top" else ""
    data = await _call(_page_data, ctx, request.query_params, src)
    return render(request, ctx, me, "_cand_rows.html", **data)


@router.get(
    "/candidates/{node_id}/drawer",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("inventory.view"))],
)
async def candidate_drawer(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    data = await _call(_drawer_data, ctx, node_id)
    return render(request, ctx, me, "_cand_drawer.html", drawer=data)


@api_router.get("/candidates", dependencies=[Depends(needs("inventory.view"))])
def candidates_api(request: Request, ctx: ConsoleContext = _CTX) -> dict[str, Any]:
    """The triage rows (best score first). Filters: ``kind``, ``signal``, ``band``."""
    try:
        _off(ctx, page=False)
    except ConsoleInputError as exc:
        raise InventoryInputError(str(exc)) from exc
    rows = overview_v4.load_candidates(ctx) or []
    return overview_v4.api_rows(rows, request.query_params)
