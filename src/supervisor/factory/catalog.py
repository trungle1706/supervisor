"""The factory store as the orchestrator's agent catalogue (WP-F3, flag ``AGENT_FACTORY_GATE``).

``onboard.orchestrator`` asks an ``AgentCatalog`` which live agent assesses a risk type. This
adapter answers from ``FactoryStore.live_agent_for``: only a version in state ``live`` (so one that
passed the gate and the approvals) is returned. A dimension without one keeps the rule proposal
(with ORCH_RUN_DRAFT_AGENTS, demo only, the newest draft of the type instead). The orchestrator
runs it through ``RoutingRunner`` and ``factory.runtime.run_agent``.
"""

from __future__ import annotations

from typing import Any

from supervisor.factory.store import FactoryStore
from supervisor.onboard.orchestrator import LiveAgent


class FactoryCatalog:
    """``run_drafts`` (setting ORCH_RUN_DRAFT_AGENTS, demo only, default off): a risk type with no
    live version gets its newest DRAFT version, as a ``LiveAgent`` of kind ``draft`` whose version
    ends in ``-draft``. Off, a draft is never returned."""

    def __init__(self, store: FactoryStore, run_drafts: bool = False) -> None:
        self.store = store
        self.run_drafts = run_drafts

    def live_agent(self, dimension_id: str) -> LiveAgent | None:
        row = self.store.live_agent_for(dimension_id)
        if row is not None:
            return LiveAgent(str(row["id"]), str(row["version"]), dict(row["definition"]))
        if not self.run_drafts:
            return None
        draft = self.store.draft_agent_for(dimension_id)
        if draft is None:
            return None
        return LiveAgent(
            str(draft["id"]), f"{draft['version']}-draft", dict(draft["definition"]), "draft"
        )


def for_console(ctx: Any) -> FactoryCatalog | None:
    """The catalogue of a console context, or ``None`` while the gate flag is off (the
    orchestrator then uses its default and no factory table is read)."""
    from supervisor.factory import gate, registry

    if not gate.enabled(ctx.settings):
        return None
    store = FactoryStore(
        ctx.state, ctx.tables, ctx.clock, registry.load_tools(), registry.load_groups()
    )
    return FactoryCatalog(store, bool(getattr(ctx.settings, "orch_run_draft_agents", False)))
