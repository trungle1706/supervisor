"""Routes of the MCP tool lock (WP26, ADR D24): ``/v1/mcp/tools/...``.

Human routes (role matrix, permissions ``mcp.tools.*``):

* ``GET  /v1/mcp/tools``            list tools of one server or all (``view``)
* ``GET  /v1/mcp/tools/diff``       locked against observed definition (``view``)
* ``POST /v1/mcp/tools/propose``    first approval (``propose``: an operator may)
* ``POST /v1/mcp/tools/approve``    approval; the second DIFFERENT person locks it (``approve``)

Machine routes (agent ingress, WP20 signing when INGRESS_AUTH_ENABLED=1), called by
``python -m supervisor.gateway.mcp_http`` when it runs away from the database:

* ``POST /v1/mcp/tools/observe``    a ``tools/list`` result in, the lock view out
* ``POST /v1/mcp/tools/blocked``    a refused tools/call, for the chain

All of it is off (HTTP 400 with a message) unless MCP_HTTP_ENABLED=1. The acting person is the
authenticated principal, never a body field.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from supervisor.adapters.auth import AuthPrincipal
from supervisor.adapters.auth.authz import needs
from supervisor.console.context import ConsoleContext, get_context
from supervisor.core.errors import SupervisorError
from supervisor.gateway import mcp_lock
from supervisor.gateway.ingress_auth import ingress_gate
from supervisor.gateway.mcp_lock_service import ToolLockError, ToolLockService, inventory_hook

router = APIRouter(prefix="/v1/mcp/tools", tags=["console"])
_CTX = Depends(get_context)
_PROPOSER = Depends(needs("mcp.tools.propose", control=True))
_APPROVER = Depends(needs("mcp.tools.approve", control=True))
_ID = r"^[A-Za-z0-9_.:@-]{1,128}$"


class McpOff(SupervisorError):
    """MCP_HTTP_ENABLED is off (HTTP 400)."""


def service_for(ctx: ConsoleContext) -> ToolLockService:
    if not ctx.settings.mcp_http_enabled:
        raise McpOff("The MCP gateway is off (MCP_HTTP_ENABLED=1 turns it on)")
    svc = getattr(ctx, "_mcp_lock", None)
    if svc is None:
        hook = inventory_hook(ctx.state, ctx.clock) if ctx.settings.inventory_enabled else None
        svc = ToolLockService(
            ctx.state, ctx.runtime.chain, ctx.clock, ctx.cases, on_new_server=hook
        )
        ctx._mcp_lock = svc  # type: ignore[attr-defined]
    return svc  # type: ignore[no-any-return]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_id: str = Field(pattern=_ID)
    tool: str = Field(min_length=1, max_length=512)
    observed_hash: str = Field(min_length=12, max_length=64, pattern=r"^[0-9a-fA-F]+$")


class ObserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(pattern=_ID)
    server_id: str = Field(pattern=_ID)
    tools: list[dict[str, Any]] = Field(max_length=mcp_lock.MAX_TOOLS)
    trust_on_first_use_by: str | None = Field(default=None, max_length=128)


class BlockedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(pattern=_ID)
    server_id: str = Field(pattern=_ID)
    tool: str = Field(min_length=1, max_length=512)
    rule_id: str = Field(max_length=64)


@router.get("", dependencies=[Depends(needs("mcp.tools.view"))])
def list_tools(server_id: str | None = Query(default=None), ctx: ConsoleContext = _CTX) -> Any:
    svc = service_for(ctx)
    return {"servers": svc.servers(), "tools": svc.list_tools(server_id)}


@router.get("/diff", dependencies=[Depends(needs("mcp.tools.view"))])
def tool_diff(server_id: str, tool: str, ctx: ConsoleContext = _CTX) -> Any:
    return service_for(ctx).diff(server_id, tool)


@router.post("/propose")
async def propose(
    body: ReviewRequest,
    me: AuthPrincipal = _PROPOSER,
    ctx: ConsoleContext = _CTX,
) -> Any:
    svc = service_for(ctx)
    return await run_in_threadpool(
        svc.propose, body.server_id, body.tool, me.user_id, body.observed_hash
    )


@router.post("/approve")
async def approve(
    body: ReviewRequest,
    me: AuthPrincipal = _APPROVER,
    ctx: ConsoleContext = _CTX,
) -> Any:
    svc = service_for(ctx)
    return await run_in_threadpool(
        svc.approve, body.server_id, body.tool, me.user_id, body.observed_hash
    )


@router.post("/observe", dependencies=[Depends(ingress_gate)])
async def observe(body: ObserveRequest, ctx: ConsoleContext = _CTX) -> Any:
    svc = service_for(ctx)
    try:
        tools = mcp_lock.parse_tools({"tools": body.tools})
    except mcp_lock.ToolListError as exc:
        raise ToolLockError(str(exc)) from None
    return await run_in_threadpool(
        lambda: svc.observe(
            body.server_id, body.agent_id, tools, tofu_by=body.trust_on_first_use_by
        )
    )


@router.post("/blocked", dependencies=[Depends(ingress_gate)])
async def blocked(body: BlockedRequest, ctx: ConsoleContext = _CTX) -> JSONResponse:
    svc = service_for(ctx)
    await run_in_threadpool(
        svc.report_block, body.server_id, body.tool, body.agent_id, body.rule_id
    )
    return JSONResponse(content={"ok": True})
