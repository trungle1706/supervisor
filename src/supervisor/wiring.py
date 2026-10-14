"""Composition root: Settings + adapters -> evidence chain + gateway (+ agent registry).

One place builds the running pieces and connects the work packages through the ports
in ``core/ports.py``:

    Settings -> build_adapters (SQLite / Delta)
             -> bootstrap schema (SQLite only; Delta tables come from the bootstrap notebook)
             -> policies/*.yaml validated and deployed to the ``rule`` table
             -> ChainWriter (WP6) = the EvidenceSink
             -> Gateway (WP3) on the deployed policy, recording into the chain

Used by the FastAPI app (startup), ``supervisor.gateway.wiring.get_gateway`` and the
demo replay (``python -m supervisor.demo.replay --gate``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import REPO_ROOT, Settings, load_settings
from supervisor.core.canonical import format_ts
from supervisor.evidence.chain import ChainWriter, build_chain_writer
from supervisor.gateway.engine import Gateway
from supervisor.gateway.facts import FactSource
from supervisor.gateway.policy import (
    Policy,
    StorePolicyProvider,
    deploy_with_retry,
    load_policy_dir,
)
from supervisor.gateway.state import STATUS_FOR_STATE

log = logging.getLogger("supervisor.wiring")

POLICY_DIR = REPO_ROOT / "policies"


class RegistrableAgent(Protocol):
    """What the registry needs from an agent manifest (``supervisor_agents`` manifests)."""

    id: str
    version: str

    def agent_row(self, now: Any) -> Any: ...

    def version_row(self, now: Any, prompt_hash: str | None = None) -> Any: ...


@dataclass
class Runtime:
    settings: Settings
    adapters: Adapters
    policy: Policy
    chain: ChainWriter
    gateway: Gateway
    owns_adapters: bool = True
    registered: list[str] = field(default_factory=list)

    def close(self) -> None:
        """Stop the gateway, seal the chain with a signed root, release the store."""
        try:
            self.gateway.close()
        finally:
            try:
                self.chain.close()
            finally:
                if self.owns_adapters:
                    self.adapters.close()


def build_runtime(
    settings: Settings | None = None,
    *,
    adapters: Adapters | None = None,
    policy_dir: Path | None = None,
    facts: FactSource | None = None,
    bootstrap: bool = True,
    git_sha: str | None = None,
    policy_refresh_s: float = 5.0,
    state_cache_ttl_s: float = 1.0,
) -> Runtime:
    """Build adapters, deploy the policy, build the chain writer and the gateway."""
    settings = settings or (adapters.settings if adapters else load_settings())
    owns = adapters is None
    adapters = adapters or build_adapters(settings)
    try:
        if bootstrap and adapters.executor.dialect == "sqlite":
            from supervisor.jobs import bootstrap_schema

            bootstrap_schema.run(settings, adapters)
        policy = load_policy_dir(policy_dir or POLICY_DIR)
        deploy_with_retry(policy, adapters.state, adapters.clock, git_sha)
        chain = build_chain_writer(settings, adapters.tables, adapters.clock)
    except BaseException:
        if owns:
            adapters.close()
        raise
    from supervisor_agents.common import tracing

    tracing.set_args_hash_key(
        settings.args_hash_key.get_secret_value() if settings.args_hash_key is not None else None
    )
    gateway = Gateway(
        StorePolicyProvider(adapters.state, refresh_s=policy_refresh_s),
        adapters.tables,
        adapters.state,
        chain,
        adapters.clock,
        facts=facts,
        args_hash_key=settings.args_hash_key.get_secret_value()
        if settings.args_hash_key is not None
        else None,
        env=settings.supervisor_mode,
        state_cache_ttl_s=state_cache_ttl_s,
        trust_body_principal=settings.supervisor_mode != "databricks_app",
    )
    return Runtime(settings, adapters, policy, chain, gateway, owns_adapters=owns)


def register_agents(
    runtime: Runtime,
    manifests: Iterable[RegistrableAgent],
    *,
    prompt_hashes: dict[str, str] | None = None,
) -> list[str]:
    """Registry rows for the agents (``agent`` + ``agent_version``), idempotent.

    The agent must be in the deployed policy (its ``agents`` section gives the initial
    gate state). Every new row is recorded on the evidence chain."""
    a = runtime.adapters
    now = a.clock.now()
    policy_agents = runtime.policy.doc.agents
    done: list[str] = []
    for m in manifests:
        if m.id not in policy_agents:
            raise ValueError(f"agent {m.id} is not in the deployed policy")
        initial = policy_agents[m.id].initial_state
        if a.state.get("agent", {"agent_id": m.id}) is None:
            row = m.agent_row(now).row()
            row.pop("row_version", None)
            row.pop("updated_at", None)
            row.update(gate_state=initial, status=STATUS_FOR_STATE[initial])
            a.state.insert("agent", row)
            runtime.gateway.states.invalidate(m.id)
            runtime.chain.record(
                "agent_registered",
                m.id,
                {
                    "agent_id": m.id,
                    "risk_tier": row["risk_tier"],
                    "model_family": row["model_family"],
                    "gate_state": initial,
                    "ts": format_ts(now),
                },
            )
        if not a.tables.query("agent_version", {"agent_id": m.id, "version": m.version}):
            v = m.version_row(now, (prompt_hashes or {}).get(m.id))
            a.tables.append("agent_version", [v])
            runtime.chain.record(
                "agent_version",
                f"{m.id}@{m.version}",
                {
                    "agent_id": m.id,
                    "version": m.version,
                    "tool_manifest_hash": v.tool_manifest_hash,
                    "prompt_hash": v.prompt_hash,
                    "model_family": v.model_family,
                    "ts": format_ts(now),
                },
            )
        done.append(m.id)
    runtime.registered = sorted(set(runtime.registered) | set(done))
    return done


__all__ = ["POLICY_DIR", "RegistrableAgent", "Runtime", "build_runtime", "register_agents"]
