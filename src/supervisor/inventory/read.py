"""Small read API for other modules (WP24): the compliance advisor and the launch report.

    from supervisor.inventory.read import inventory_for_agent
    info = inventory_for_agent(adapters, "payments")   # None when the inventory is off

``found`` is False when the agent is not in the inventory. Read only; never raises for a missing
table (an old store without the WP24 tables answers ``None``).
"""

from __future__ import annotations

from typing import Any

from supervisor.inventory.service import InventoryService


def inventory_for_agent(adapters: Any, agent_id: str) -> dict[str, Any] | None:
    """What the agent resolves to: own and effective risk, Decision 33 class (human-set), and
    its links (model endpoint, tools, datasets, MCP servers, hosting) with source and evidence.
    ``None`` when ``INVENTORY_ENABLED`` is off or the tables do not exist."""
    if not adapters.settings.inventory_enabled:
        return None
    try:
        return InventoryService.from_adapters(adapters).summary_for_agent(agent_id)
    except Exception:  # noqa: BLE001 - an advisor must not fail because the inventory is missing
        return None
