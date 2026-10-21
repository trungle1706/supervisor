"""Register a gate-only agent in the inventory on its first decision (WP41, D19 / D28).

An agent that only calls the gate (a collector, no onboarding run, no manifest in ``agents/``)
never reached the inventory, so the Agent page, the coverage-gap check and the control evidence
had no node to point at. With ``INVENTORY_ENABLED=1`` the gate calls :meth:`GateRegistrar.register`
once per agent and process, in the background, after the first decision of an agent that the
policy knows. The node is the same ``system`` node a manifest makes (``attrs.role = agent``) with
the evidence source ``gate``; a manifest or an onboarding run later adds its own evidence to it.

Nothing here reads or stores a payload: the agent id (checked against the policy by the caller)
is the only input.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Node
from supervisor.inventory.store import InventoryStore

log = logging.getLogger(__name__)

SOURCE = "gate"
EVIDENCE_REF = "first_gate_decision"


class GateRegistrar:
    def __init__(self, state: Any, clock: Any) -> None:
        self.store = InventoryStore(state, clock)
        self._done: set[str] = set()
        self._lock = threading.Lock()

    def seen(self, agent_id: str) -> bool:
        with self._lock:
            return agent_id in self._done

    def register(self, agent_id: str) -> bool:
        """Upsert the agent node. True when this call wrote (or refreshed) it. Never raises."""
        with self._lock:
            if agent_id in self._done:
                return False
            self._done.add(agent_id)
        try:
            node = Node(
                "system",
                agent_id,
                display_name=agent_id,
                attrs={"role": "agent", "registered_by": SOURCE},
            )
            node.add_evidence(SOURCE, EVIDENCE_REF)
            g = Graph()
            g.add_node(node)
            self.store.apply(g, source=SOURCE)
            return True
        except Exception as exc:  # noqa: BLE001 - the inventory must never break the gate
            with self._lock:
                self._done.discard(agent_id)  # try again on the next decision
            log.warning("inventory: gate registration failed: %s", type(exc).__name__)
            return False
