"""Agent registry routes (WP-P2): ``POST /v1/agents`` and ``GET /v1/agents/{agent_id}``.

Mounted by ``app.py`` only when AGENTS_API_ENABLED=1 (nothing is mounted otherwise).

* ``POST /v1/agents`` (``agents.edit``: owner, reviewer, admin): create or update the registry row
  from a manifest-shaped body (agent_id, name, owner_team, owner_user, risk_tier, host_type,
  plug_point, model_family). A new agent starts in SHADOW; an update never moves the gate state.
  201 on create, 200 on update, 400 with a message on bad input.
* ``GET /v1/agents/{agent_id}`` (``console.view``): the registry row, 404 when not registered.

Every write makes two ``console_action`` audit rows and an ``agent_change`` chain record (ids and
enums only).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import audited
from supervisor.core.errors import NotFoundError
from supervisor.gateway.agent_registry import AgentRegistry, AgentRegistryError

router = APIRouter(prefix="/v1/agents", tags=["agents"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
MAX_BODY = 16_000


def registry_of(ctx: ConsoleContext) -> AgentRegistry:
    """The registry service on the running store and chain (also used by the seed command)."""
    return AgentRegistry(
        ctx.state, ctx.clock, ctx.runtime.chain, on_change=ctx.runtime.gateway.states.invalidate
    )


async def _body(request: Request) -> Any:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise AgentRegistryError("request body is too large")
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise AgentRegistryError("request body must be JSON") from None


@router.post("", dependencies=[Depends(needs("agents.edit"))])
@audited("agents.edit")
async def register_agent(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    if me.kind != "user":
        raise PermissionDenied("changing the agent registry needs a signed-in person")
    body = await _body(request)
    out, created = registry_of(ctx).register(body, str(me.user_id))
    request.state.audit_detail = "create" if created else "update"
    return JSONResponse(status_code=201 if created else 200, content=out)


@router.get("/{agent_id}", dependencies=[Depends(needs("console.view"))])
def get_agent(agent_id: str, ctx: ConsoleContext = _CTX) -> Any:
    try:
        return registry_of(ctx).get(agent_id)
    except NotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
