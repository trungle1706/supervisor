"""Facts card routes (WP-O2, ONBOARD_FACTS): the Facts panel of a candidate and an agent and the
JSON API. The routers are always mounted; with the flag off every route answers HTTP 400 with the
flag name (nothing is read or written).

* ``GET  /v1/facts/{node_id}``      the card of the newest built attempt (``systems.view``)
* ``POST /v1/facts/{node_id}/{n}``  build the facts of intake attempt ``n`` (``systems.edit``); 201
* ``GET  /console/facts/{node_id}`` the Facts panel (an htmx fragment; a full page without htmx)
* ``POST /console/facts/{node_id}`` the **Re-read** button: build again for the newest attempt
                                     (``systems.edit``), htmx only

Every POST writes two ``console_action`` rows (``@audited``). A refusal is HTTP 400 with
``<code>: <text>``; see ``supervisor.onboard.facts``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import agent_detail
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import _call, _htmx_only, audited, message_html, render
from supervisor.onboard import facts, intake

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def service(ctx: ConsoleContext) -> facts.FactsService:
    return facts.FactsService(ctx.settings, ctx.state, ctx.clock)


def panel_data(ctx: ConsoleContext, me: AuthPrincipal, node_id: str) -> dict[str, Any]:
    """Template variables of the Facts panel (``_facts_panel.html``)."""
    on = bool(ctx.settings.onboard_facts)
    card = service(ctx).card(node_id) if on else {}
    return {
        "fk": {
            "node_id": node_id,
            "on": on,
            "card": card,
            "can_edit": agent_detail.can(me, "systems.edit"),
        }
    }


def _build(ctx: ConsoleContext, node_id: str, n: int | None) -> dict[str, Any]:
    svc = service(ctx)
    if n is None:
        n = svc.latest_attempt(node_id)
        if n is None:
            raise facts.FactsError(
                "no_attempt", "there is no stored source; add one in the Source panel first"
            )
    return svc.build(node_id, n)


def _public(card: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in card.items() if k != "rows"}


# ------------------------------------------------------------------------------- JSON API


@api_router.get("/facts/{node_id}", dependencies=[Depends(needs("systems.view"))])
def get_card(node_id: str, ctx: ConsoleContext = _CTX) -> Any:
    facts.require_on(ctx.settings)
    return _public(service(ctx).card(node_id))


@api_router.post("/facts/{node_id}/{n}", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def post_build(
    node_id: str, n: int, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    facts.require_on(ctx.settings)
    intake.check_node_id(node_id)
    card = await _call(_build, ctx, node_id, n)
    request.state.audit_detail = f"attempt={card['attempt_n']} facts={card['total']}"
    return JSONResponse(status_code=201, content=_public(card))


# ------------------------------------------------------------------------------- console


@router.get(
    "/facts/{node_id}", response_class=HTMLResponse, dependencies=[Depends(needs("systems.view"))]
)
async def facts_panel(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    facts.require_on(ctx.settings)
    intake.check_node_id(node_id)
    data = await _call(panel_data, ctx, me, node_id)
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, "_facts_panel.html", **data)
    return render(request, ctx, me, "facts.html", section="candidates", **data)


@router.post(
    "/facts/{node_id}", response_class=HTMLResponse, dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def facts_reread(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    facts.require_on(ctx.settings)
    intake.check_node_id(node_id)
    card = await _call(_build, ctx, node_id, None)
    request.state.audit_detail = f"attempt={card['attempt_n']} facts={card['total']}"
    data = await _call(panel_data, ctx, me, node_id)
    resp = render(request, ctx, me, "_facts_panel.html", **data)
    note = f"{node_id}: {card['total']} fact(s) from attempt {card['attempt_n']}"
    resp.body = resp.body + message_html(note, ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp
