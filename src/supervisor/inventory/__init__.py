"""Inventory graph and shadow-AI scan (WP24, ADR D16; docs/inventory.md).

Typed nodes (system, model, model_endpoint, tool, mcp_server, dataset, prompt, supplier,
entrypoint) and edges (uses, serves, reads, writes, hosted_on, owned_by) with evidence, filled
from agent manifests, onboarding output and the Databricks workspace. Off by default
(INVENTORY_ENABLED).
"""

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import (
    EDGE_KINDS,
    NODE_KINDS,
    Edge,
    InventoryError,
    Node,
    node_id_for,
)

__all__ = [
    "EDGE_KINDS",
    "NODE_KINDS",
    "Edge",
    "Graph",
    "InventoryError",
    "Node",
    "node_id_for",
]
