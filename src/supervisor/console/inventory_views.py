"""Read model of the Inventory page (WP24): per-agent ASCII tree, unmanaged table, counts."""

from __future__ import annotations

import re
from typing import Any

from supervisor.inventory.api import InventoryInputError
from supervisor.inventory.service import InventoryService

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def page(ctx: Any, agent: str | None) -> dict[str, Any]:
    svc = InventoryService.from_adapters(ctx.runtime.adapters)
    g = svc.store.load_graph()
    agents = sorted(
        n.name
        for n in g.nodes.values()
        if n.kind == "system" and n.attrs.get("role") == "agent" and n.status != "gone"
    )
    if agent:
        if not _ID.match(agent):
            raise InventoryInputError("invalid agent id")
        if agent not in agents:
            raise InventoryInputError(f"agent {agent} is not in the inventory")
    chosen = agent or (agents[0] if agents else "")
    view = svc.agent_view(chosen) if chosen else None
    rows = []
    if view:
        rows = [
            {
                "kind": n["kind"],
                "name": n["display_name"],
                "status": n["status"],
                "own_risk": n["own_risk"],
                "effective_risk": n["effective_risk"],
                "evidence": "; ".join(f"{e['source']}: {e['ref']}" for e in n["evidence"][:3]),
            }
            for n in view["nodes"]
        ]
    return {
        "agents": agents,
        "agent": chosen,
        "tree": view["tree"] if view else "",
        "node_rows": rows,
        "unmanaged": svc.unmanaged(),
        "counts": svc.counts(),
    }
