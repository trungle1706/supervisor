"""Read-only JSON routes of the inventory (WP24): ``/v1/inventory/unmanaged`` and
``/v1/inventory/{agent_id}``. Permission ``inventory.view`` (every role, including viewer).
Off unless INVENTORY_ENABLED=1: HTTP 400 with a message, like the other flag-gated pages."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from supervisor.adapters.auth.authz import needs
from supervisor.console.context import ConsoleContext, get_context
from supervisor.core.errors import SupervisorError
from supervisor.inventory.service import InventoryService

router = APIRouter(prefix="/v1/inventory", tags=["console"])
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_CTX = Depends(get_context)


class InventoryInputError(SupervisorError):
    """Bad input (HTTP 400)."""


class InventoryOff(InventoryInputError):
    """INVENTORY_ENABLED is off (HTTP 400)."""


def service_for(ctx: ConsoleContext) -> InventoryService:
    if not ctx.settings.inventory_enabled:
        raise InventoryOff(
            "The inventory is off (INVENTORY_ENABLED=1 turns it on); "
            "python -m supervisor.jobs.inventory fills it"
        )
    return InventoryService.from_adapters(ctx.runtime.adapters)


@router.get("/unmanaged", dependencies=[Depends(needs("inventory.view"))])
def unmanaged(ctx: ConsoleContext = _CTX) -> dict[str, Any]:
    """Databricks Apps and serving endpoints seen in the workspace that no Supervisor
    manifest or agent covers (and that are not on the allow-list)."""
    items = service_for(ctx).unmanaged()
    return {"count": len(items), "items": items}


@router.get("/{agent_id}", dependencies=[Depends(needs("inventory.view"))])
def agent_inventory(agent_id: str, ctx: ConsoleContext = _CTX) -> Any:
    """One agent's subgraph: nodes, edges (with evidence), effective risk, ASCII tree."""
    svc = service_for(ctx)
    if not _ID.match(agent_id):
        raise InventoryInputError("invalid agent id")
    view = svc.agent_view(agent_id)
    if view is None:
        return JSONResponse(
            status_code=404, content={"error": f"agent {agent_id} is not in the inventory"}
        )
    return view
