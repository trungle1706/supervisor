"""Task sizing of an agent that is linked to an AI system (WP-G1, docs/governance.md).

For an agent with at least one active link to a system that is not archived, the band that sizes
its task list is the effective risk level of the system (the higher one when it is linked to
several), mapped to the task scale: ``prohibited`` is the top level (``critical`` in
``config/tasks.yaml``). The Decision 33 floor still applies (``tasks.model.effective_level``
takes the higher of band and floor). A system whose level is still ``unspecified`` gives the
initiation set only (``initiation_only``), until a person sets the level.

An agent that is not linked keeps the computation of WP30 (the caller does not come here).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from supervisor.governance.model import max_level
from supervisor.governance.systems import SystemService, _on

# System level -> task level. ``unspecified`` sizes as low (the Decision 33 floor decides) and
# restricts the set to initiation (``LinkedSizing.initiation_only``).
SYSTEM_TO_TASK: dict[str, str] = {
    "unspecified": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "prohibited": "critical",
}


@dataclass(frozen=True)
class LinkedSizing:
    band: str  # on the task scale (low, medium, high, critical)
    system_level: str  # on the system scale
    system_ids: tuple[str, ...]
    initiation_only: bool


def linked_systems(state: Any, agent_id: str) -> list[str]:
    """Ids of the systems (not archived) the agent is linked to, sorted."""
    ids: set[str] = set()
    for c in state.query("system_component", {"ref_kind": "agent"}):
        if _on(c["active"]) and str(c["ref_id"]).lower() == agent_id.lower():
            ids.add(str(c["system_id"]))
    out = []
    for sid in sorted(ids):
        row = state.get("ai_system", {"system_id": sid})
        if row is not None and row["status"] != "archived":
            out.append(sid)
    return out


def linked_sizing(
    state: Any, tables: Any, clock: Any, settings: Any, agent_id: str
) -> LinkedSizing | None:
    """The sizing of the agent from its systems, or None when it is not linked to any."""
    ids = linked_systems(state, agent_id)
    if not ids:
        return None
    svc = SystemService(state, tables, clock, settings)
    level = max_level(*(svc.effective_risk_level(sid).level for sid in ids))
    return LinkedSizing(SYSTEM_TO_TASK[level], level, tuple(ids), level == "unspecified")
