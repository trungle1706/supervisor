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
from supervisor.core.errors import check_agent_id
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


def resolve_policy_dir(settings: Settings, explicit: Path | None = None) -> Path:
    """An explicit folder (tests, CLI), else ``POLICY_DIR`` (D13), else ``<repo>/policies``."""
    return explicit or settings.policy_dir or POLICY_DIR


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
        policy = load_policy_dir(resolve_policy_dir(settings, policy_dir))
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
    try:
        if facts is None:  # D13: FACT_SOURCE (default none)
            from supervisor.adapters.facts import make_fact_source

            facts = make_fact_source(settings)
        gateway = _make_gateway(
            settings,
            adapters,
            chain,
            facts,
            policy_refresh_s,
            state_cache_ttl_s,
            detector_gate=make_detector_gate(settings, policy),
            session_gate=make_session_gate(settings, adapters, chain),
        )
    except BaseException:
        chain.close(seal=False)
        if owns:
            adapters.close()
        raise
    return Runtime(settings, adapters, policy, chain, gateway, owns_adapters=owns)


def _make_gateway(
    settings: Settings,
    adapters: Adapters,
    chain: ChainWriter,
    facts: FactSource | None,
    policy_refresh_s: float,
    state_cache_ttl_s: float,
    detector_gate: Any = None,
    session_gate: Any = None,
) -> Gateway:
    provider = StorePolicyProvider(adapters.state, refresh_s=policy_refresh_s)
    if detector_gate is not None:  # F11: the same check on every reload
        provider.validator = detector_gate.check_policy
        provider.on_accept = lambda p: detector_gate.audit_policy(p, chain)  # WP41
    return Gateway(
        provider,
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
        require_caller_id=settings.require_caller_id,  # WP7, ADR D10 (default off)
        # WP24b inline redaction (default off). The gate's masker keeps amounts in the text:
        # redaction must not change a value the rules or the tool need.
        masker=_redaction_masker(settings) if settings.inline_redaction_enabled else None,
        inline_redaction=settings.inline_redaction_enabled,
        redact_tools=settings.inline_redaction_tool_set,
        detector_gate=detector_gate,  # WP37 (default off)
        session_gate=session_gate,  # WP27 (default off)
        agent_registrar=_agent_registrar(settings, adapters),  # WP41 (INVENTORY_ENABLED)
    )


def _agent_registrar(settings: Settings, adapters: Adapters) -> Any:
    """WP41 (D19): the callable that puts a gate-only agent into the inventory, or None when
    INVENTORY_ENABLED is off."""
    if not settings.inventory_enabled:
        return None
    from supervisor.inventory.gate_register import GateRegistrar

    return GateRegistrar(adapters.state, adapters.clock).register


def make_session_gate(settings: Settings, adapters: Adapters, evidence: Any) -> Any:
    """WP27: the session monitor's gate hook, or None when SESSION_MONITOR_ENABLED is off."""
    if not settings.session_monitor_enabled:
        return None
    from supervisor.gateway.session_gate import SessionGate
    from supervisor.monitors.common import MonitorContext

    return SessionGate(
        settings,
        MonitorContext.from_adapters(adapters, evidence),
        key=settings.args_hash_key.get_secret_value()
        if settings.args_hash_key is not None
        else None,
    )


def make_detector_gate(settings: Settings, policy: Policy) -> Any:
    """WP37: the detector gate (catalogue, ``config/detectors.yaml``, per-agent overrides of the
    policy file), or None when DETECTORS_ENABLED is off. A bad config or a bad agent override is
    a startup error, never a silent default."""
    if not settings.detectors_enabled:
        return None
    from supervisor.core.errors import ConfigError
    from supervisor.detectors import build_registry
    from supervisor.detectors.config import ResolvedDetectors, load_config
    from supervisor.gateway.detector_gate import DetectorGate

    masker = _redaction_masker(settings)
    if masker is None:  # MASKER_KIND=none: the detectors still need a masker (R2)
        from supervisor.adapters.masking.vn_regex import VnRegexMasker

        key, key_id = settings.mask_key
        masker = VnRegexMasker(key, key_id)
    registry = build_registry(masker, judge=_advisory_judge(settings, masker))
    try:
        resolved = ResolvedDetectors(
            load_config(settings.detectors_config),
            registry,
            scan_budget_bytes=settings.detectors_scan_budget_bytes,
        )
    except ConfigError as exc:  # one ASCII line naming the setting, no chained traceback
        msg = f"DETECTORS_CONFIG={settings.detectors_config}: {exc}"
        raise ConfigError(msg.encode("ascii", "backslashreplace").decode("ascii")) from None
    gate = DetectorGate(registry, resolved)
    problems = gate.check_policy(policy)
    if problems:
        msg = "detector overrides in the policy are invalid: " + "; ".join(problems)
        raise ConfigError(msg.encode("ascii", "backslashreplace").decode("ascii"))
    return gate


def _advisory_judge(settings: Settings, masker: Any) -> Any:
    """Tier 1 judge for ``judge_advisory``: the configured one, else None (the mock, labelled)."""
    if not settings.judge_t1_model or settings.llm_mock:
        return None
    try:
        from supervisor.judge.router import JudgeRouter
        from supervisor.judge.tier1 import Tier1Judge

        router = JudgeRouter.from_settings(settings)
        return Tier1Judge(
            router.t1,
            masker,
            timeout_s=float(settings.judge_timeout_s),
            max_retries=settings.judge_max_retries,
            max_input_chars=settings.judge_max_input_chars,
        )
    except Exception as exc:  # noqa: BLE001 - judge_advisory then runs on the labelled mock
        log.warning("judge_advisory: judge not available (%s); using the mock", type(exc).__name__)
        return None


def _redaction_masker(settings: Settings) -> Any:
    from supervisor.adapters.factory import make_masker

    return make_masker(settings.model_copy(update={"mask_amounts": False}))


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
        check_agent_id(m.id)
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


__all__ = [
    "POLICY_DIR",
    "RegistrableAgent",
    "Runtime",
    "build_runtime",
    "register_agents",
    "resolve_policy_dir",
]
