"""HTTP routes of the MCP server (WP-G6). Mounted only when ``MCP_SERVER_ENABLED=1``.

* ``POST /mcp`` (marker AGENT): streamable HTTP, JSON-RPC 2.0 (``initialize``, ``tools/list``,
  ``tools/call``, ``ping``). The credential is the WP20 HMAC signature of a connected app
  (``mcp_server/auth.py``): 401 or 403 with ``{"error": ...}`` and one audit row when refused;
  a JSON body that does not parse is HTTP 400 with a JSON-RPC parse error. An answer to a
  request is always HTTP 200 with a ``result`` or an ``error`` (never 500).
* ``GET /v1/mcp/apps`` (``mcp.apps``): the connected apps (no key hash).
* ``POST /v1/mcp/apps/{app_id}/approve`` and ``/block`` (``mcp.apps``): a signed-in admin.
* ``GET /v1/kpis`` (``console.view``): the governance KPIs in the scope of the caller, the same
  function as the Governance overview and the MCP tool ``kpis``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.audit import request_id_of
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import audited
from supervisor.core.errors import NotFoundError
from supervisor.gateway.mcp_proxy import error_response
from supervisor.governance import kpis as kpi_mod
from supervisor.governance.model import ensure_on
from supervisor.mcp_server import auth
from supervisor.mcp_server.apps import McpAppService
from supervisor.mcp_server.protocol import Caller
from supervisor.mcp_server.registry import INTERNAL_ERROR, INVALID_REQUEST, PARSE_ERROR
from supervisor.mcp_server.server import get_server

log = logging.getLogger("supervisor.mcp_server")

mcp_router = APIRouter(tags=["gate"])
admin_router = APIRouter(tags=["console"])
MAX_BODY = 262_144
MAX_BATCH = 50
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def _apps(ctx: ConsoleContext) -> McpAppService:
    return McpAppService(ctx.state, ctx.clock)


def _refuse(status: int, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    hdr = dict(headers or {})
    if status == 401:
        hdr["WWW-Authenticate"] = 'Bearer realm="supervisor"'
    return JSONResponse(status_code=status, content={"error": message}, headers=hdr or None)


def _handle(
    ctx: ConsoleContext, request_id: str, method: str, path: str, headers: Any, body: bytes
) -> tuple[int, Any]:
    """Blocking part of one request: authenticate, parse, dispatch. (status, JSON or None)."""
    apps = _apps(ctx)
    try:
        who = auth.authenticate(ctx, apps, method, path, headers, body)
    except auth.AuthFailure as fail:
        auth.audit_refusal(ctx, fail, path, body)
        return fail.status, {"error": fail.message}
    try:
        message = json.loads(body)
    except (ValueError, RecursionError):  # deep nesting is a parse error too
        return 400, error_response(None, PARSE_ERROR, "parse error")
    items = message if isinstance(message, list) else [message]
    if not items:
        return 400, error_response(None, INVALID_REQUEST, "empty batch")
    if len(items) > MAX_BATCH:
        return 400, error_response(None, INVALID_REQUEST, f"at most {MAX_BATCH} messages")
    caller = Caller(
        ctx=ctx,
        app=who.app,
        principal=who.principal,
        scopes=who.scopes,
        request_id=request_id,
        approved=who.approved,
    )
    server = get_server()
    out = [r for r in (server.handle(m, caller) for m in items) if r is not None]
    if not out:
        return 202, None
    return 200, out if isinstance(message, list) else out[0]


@mcp_router.post("/mcp")
async def mcp_endpoint(request: Request) -> Response:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY:
        return _refuse(413, "request body too large")
    body = await request.body()
    if len(body) > MAX_BODY:
        return _refuse(413, "request body too large")
    try:
        ctx = await run_in_threadpool(get_context)
        status, content = await run_in_threadpool(
            _handle,
            ctx,
            request_id_of(request),
            request.method,
            request.url.path,
            request.headers,
            body,
        )
    except Exception as exc:  # noqa: BLE001 - never a 500 with a trace
        log.error("mcp endpoint failed: %s", type(exc).__name__, exc_info=exc)
        return JSONResponse(
            status_code=400,
            content=error_response(None, INTERNAL_ERROR, f"server error: {type(exc).__name__}"),
        )
    if content is None:
        return Response(status_code=status)
    headers = {"WWW-Authenticate": 'Bearer realm="supervisor"'} if status == 401 else None
    return JSONResponse(status_code=status, content=content, headers=headers)


# ------------------------------------------------------------------------------ admin


def _person(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("deciding about a connected app needs a signed-in person")
    return str(me.user_id)


@admin_router.get("/v1/mcp/apps", dependencies=[Depends(needs("mcp.apps"))])
def list_apps(ctx: ConsoleContext = _CTX) -> Any:
    rows = _apps(ctx).list_apps()
    return {"count": len(rows), "apps": rows}


@admin_router.post("/v1/mcp/apps/{app_id}/approve", dependencies=[Depends(needs("mcp.apps"))])
@audited("mcp.apps")
async def approve_app(
    app_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    try:
        out = _apps(ctx).approve(app_id, _person(me))
    except NotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    request.state.audit_detail = "approve"
    return out


@admin_router.post("/v1/mcp/apps/{app_id}/block", dependencies=[Depends(needs("mcp.apps"))])
@audited("mcp.apps")
async def block_app(
    app_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    try:
        out = _apps(ctx).block(app_id, _person(me))
    except NotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    request.state.audit_detail = "block"
    return out


@admin_router.get("/v1/kpis", dependencies=[Depends(needs("console.view"))])
def get_kpis(ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    ensure_on(ctx.settings)
    return kpi_mod.compute(ctx, me)
