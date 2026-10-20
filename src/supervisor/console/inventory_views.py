"""Read model of the Inventory page (WP24): per-agent ASCII tree, unmanaged table, counts."""

from __future__ import annotations

import re
from typing import Any

from supervisor.console.listing import paginate, parse_int, parse_sort, query_string, sort_rows
from supervisor.inventory.api import InventoryInputError
from supervisor.inventory.service import InventoryService

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
UNMANAGED_COLUMNS = ("kind", "display_name", "case_id")  # WP-UX2: sortable, paged table
UNMANAGED_PAGE = 10


def unmanaged_view(
    items: list[dict[str, Any]], query: Any, agent: str | None = None
) -> dict[str, Any]:
    """Sort and page the unmanaged items (WP-UX2). Unknown column: default sort; bad page:
    ListingError (HTTP 400)."""
    col, direction = parse_sort(query.get("sort"), query.get("dir"), UNMANAGED_COLUMNS, "kind")
    rows = sort_rows(items, col, direction)
    pg = paginate(rows, parse_int(query.get("page"), "page", 1), UNMANAGED_PAGE)
    base = {"agent": agent or ""}
    return {
        "um_page": pg,
        "um_sort_col": col,
        "um_sort_dir": direction,
        "um_base_qs": query_string(base),
        "um_list_qs": query_string({**base, "sort": col, "dir": direction}),
    }


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
