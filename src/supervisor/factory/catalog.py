"""The factory store as the orchestrator's agent catalogue (WP-F3, flag ``AGENT_FACTORY_GATE``).

``onboard.orchestrator`` asks an ``AgentCatalog`` which live agent assesses a risk type. This
adapter answers from ``FactoryStore.live_agent_for``: only a version in state ``live`` (so one that
passed the gate and the approvals) is ever returned. A dimension without one keeps the rule
proposal. The orchestrator runs it through ``RoutingRunner`` and ``factory.runtime.run_agent``.
"""

from __future__ import annotations

from typing import Any

from supervisor.factory.store import FactoryStore
from supervisor.onboard.orchestrator import LiveAgent


class FactoryCatalog:
    def __init__(self, store: FactoryStore) -> None:
        self.store = store

    def live_agent(self, dimension_id: str) -> LiveAgent | None:
        row = self.store.live_agent_for(dimension_id)
        if row is None:
            return None
        return LiveAgent(str(row["id"]), str(row["version"]), dict(row["definition"]))


def for_console(ctx: Any) -> FactoryCatalog | None:
    """The catalogue of a console context, or ``None`` while the gate flag is off (the
    orchestrator then uses its default and no factory table is read)."""
    from supervisor.factory import gate, registry

    if not gate.enabled(ctx.settings):
        return None
    store = FactoryStore(
        ctx.state, ctx.tables, ctx.clock, registry.load_tools(), registry.load_groups()
    )
    return FactoryCatalog(store)
