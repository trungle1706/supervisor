"""Regulation graph routes (KBGRAPH_ENABLED, ``kbgraph.py``).

The routers are always mounted; with the flag off (or GOVERNANCE_ENABLED off) every route answers
HTTP 400 ``kbgraph_off`` and nothing is read.

* ``GET /console/regkb/graph``  the page (``regkb.view``): graph view and list view
* ``GET /v1/regkb/graph``       the same graph as JSON (``regkb.view``)

Query: ``instrument`` (id, ``all`` or empty = the one with most gaps), ``risk``, ``coverage``
(gap, partial, bank, closed), ``q`` (system or obligation), ``n`` (top systems: 10, 20, 40, 60),
``view`` (graph, list), ``sel`` (a selected node, ``sys:<id>``, ``obl:<id>`` or ``ins:<id>``).
Read only: no POST, no audit row. Not legal advice.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import kbgraph
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import _call, _lang, render
from supervisor.core import rbac

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
BANNER = "Not legal advice. Bank counsel must confirm."


def _page_data(ctx: ConsoleContext, me: AuthPrincipal, query: dict[str, str], lang: str) -> dict:
    from supervisor.governance import duties_gap as dg

    graph = kbgraph.load(ctx, me, query, lang)

    def href(**extra: str) -> str:
        params = {k: v for k, v in {**graph["params"], **extra, "lang": lang}.items() if v}
        return "/console/regkb/graph?" + urlencode(params)

    for node in graph["nodes"]:
        node["href"] = href(sel=node["id"])
    systems_on = bool(ctx.settings.console_systems_enabled) and rbac.allowed(
        me.roles, "systems.view"
    )
    sel = graph["selected"]
    return {
        "g": graph,
        "by_id": {n["id"]: n for n in graph["nodes"]},
        "sel": sel,
        "view": graph["params"].get("view", "graph"),
        "kg_risks": kbgraph.RISKS,
        "kg_states": kbgraph.STATES,
        "kg_n_choices": kbgraph.N_CHOICES,
        "kg_systems_on": systems_on,
        "kg_duties_tab": dg.enabled(ctx.settings),
        "kg_drafts_on": bool(ctx.settings.lawagent_enabled),
        "kg_q": graph["params"].get("q", ""),
        "kg_p": {
            "instrument": graph["params"].get("instrument", ""),
            "risk": graph["params"].get("risk", "all"),
            "coverage": graph["params"].get("coverage", "all"),
            "n": int(graph["params"].get("n") or graph["focus"]["n"]),
        },
        "kg_url_graph": href(view="", sel=""),
        "kg_url_list": href(view="list", sel=""),
        "kg_url_clear": href(sel=""),
        "kg_url_json": "/v1/regkb/graph"
        + ("?" + urlencode({k: v for k, v in graph["params"].items() if k != "view"})).rstrip("?"),
    }


@router.get(
    "/regkb/graph", response_class=HTMLResponse, dependencies=[Depends(needs("regkb.view"))]
)
async def graph_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    kbgraph.require_on(ctx.settings)
    data = await _call(_page_data, ctx, me, dict(request.query_params), _lang(request, ctx))
    return render(request, ctx, me, "regkb_graph.html", section="regkb_graph", **data)


@api_router.get("/regkb/graph", dependencies=[Depends(needs("regkb.view"))])
async def graph_json(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    kbgraph.require_on(ctx.settings)
    out = await _call(kbgraph.load, ctx, me, dict(request.query_params), "en")
    return {**out, "banner": BANNER}
