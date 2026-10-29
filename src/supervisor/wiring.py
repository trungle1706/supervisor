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

import hashlib
import hmac
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
    load_policy_dirs,
)
from supervisor.gateway.state import STATUS_FOR_STATE

log = logging.getLogger("supervisor.wiring")

POLICY_DIR = REPO_ROOT / "policies"


def resolve_policy_dir(settings: Settings, explicit: Path | None = None) -> Path:
    """An explicit folder (tests, CLI), else ``POLICY_DIR`` (D13), else ``<repo>/policies``."""
    return explicit or settings.policy_dir or POLICY_DIR


def resolve_policy_dirs(settings: Settings, explicit: Path | None = None) -> list[Path]:
    """WP-P2: every policy folder in load order. An explicit folder wins and is alone; else
    POLICY_DIR (one or several folders); else ``<repo>/policies``."""
    if explicit is not None:
        return [explicit]
    return list(settings.policy_dirs) or [POLICY_DIR]


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


def _chain_tables(adapters: Adapters) -> Any:
    """WP-P5: the evidence chain always writes as the App service principal, never as a
    forwarded user, so it gets its own SP-only executor when the adapter has the switch."""
    sp_only = getattr(adapters.executor, "sp_only", None)
    if sp_only is None:
        return adapters.tables
    from supervisor.adapters.sql.store import SqlTableStore

    return SqlTableStore(sp_only(), adapters.model)


GATEWAY_UNAVAILABLE = "gateway unavailable: the App service principal has no SQL grant yet"


class _Unavailable:
    """WP-P5: stands in for the gateway and the chain when the SP cannot build the runtime."""

    def close(self, *args: Any, **kwargs: Any) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        from supervisor.core.errors import GatewayUnavailable

        raise GatewayUnavailable(GATEWAY_UNAVAILABLE)


class _UnavailableGateway(_Unavailable):
    """Read models ask ``gateway.states`` and fall back when it answers 400-class errors."""

    @property
    def states(self) -> Any:
        return _Unavailable()


class _UnavailableChain(_Unavailable):
    """No writer: reads of the in-memory heads answer empty, every write answers 400."""

    def heads(self) -> dict[str, Any]:
        return {}


def build_degraded_runtime(settings: Settings) -> Runtime:
    """WP-P5 (SQL_USER_TOKEN_FORWARD only): a runtime with adapters but no gateway and no chain,
    so the console can render reads as the signed-in user. Gate and chain paths answer 400."""
    from supervisor.adapters.auth.user_token import without_forwarded_token
    from supervisor.adapters.factory import build_adapters

    with without_forwarded_token():
        adapters = build_adapters(settings)
    return Runtime(
        settings,
        adapters,
        None,  # type: ignore[arg-type]
        _UnavailableChain(),  # type: ignore[arg-type]
        _UnavailableGateway(),  # type: ignore[arg-type]
    )


def build_runtime(*args: Any, **kwargs: Any) -> Runtime:
    """Build the runtime. WP-P5: always as the App service principal, even when called inside a
    request that carries a forwarded user token (lazy retry): policy deploy and chain-writer
    init must never run as a user."""
    from supervisor.adapters.auth.user_token import without_forwarded_token

    with without_forwarded_token():
        return _build_runtime(*args, **kwargs)


def _build_runtime(
    settings: Settings | None = None,
    *,
    adapters: Adapters | None = None,
    policy_dir: Path | None = None,
    facts: FactSource | None = None,
    bootstrap: bool = True,
    git_sha: str | None = None,
    policy_refresh_s: float | None = None,
    state_cache_ttl_s: float | None = None,
) -> Runtime:
    """Build adapters, deploy the policy, build the chain writer and the gateway. The two
    cache periods default to the settings (POLICY_REFRESH_S, STATE_CACHE_TTL_S); a test may
    pass 0 to read the store on every call."""
    settings = settings or (adapters.settings if adapters else load_settings())
    if policy_refresh_s is None:
        policy_refresh_s = settings.policy_refresh_s
    if state_cache_ttl_s is None:
        state_cache_ttl_s = settings.state_cache_ttl_s
    owns = adapters is None
    adapters = adapters or build_adapters(settings)
    try:
        if bootstrap and adapters.executor.dialect == "sqlite":
            from supervisor.jobs import bootstrap_schema

            bootstrap_schema.run(settings, adapters)
        policy = load_policy_dirs(resolve_policy_dirs(settings, policy_dir))  # WP-P2
        deploy_with_retry(policy, adapters.state, adapters.clock, git_sha)
        chain = build_chain_writer(settings, _chain_tables(adapters), adapters.clock)
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
            detector_gate=make_detector_gate(settings, policy, adapters.state),
            session_gate=make_session_gate(settings, adapters, chain),
        )
    except BaseException:
        chain.close(seal=False)
        if owns:
            adapters.close()
        raise
    gateway.policy_dirs = tuple(resolve_policy_dirs(settings, policy_dir))  # WP-P2 (reload)
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
        timeout_s=settings.gate_decision_timeout_s,  # WP-P6: 2 s locally, more on Databricks
        record_async=settings.gate_record_async,
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


def make_detector_gate(settings: Settings, policy: Policy, state: Any = None) -> Any:
    """WP37: the detector gate (catalogue, ``config/detectors.yaml``, per-agent overrides of the
    policy file), or None when DETECTORS_ENABLED is off. A bad config or a bad agent override is
    a startup error, never a silent default."""
    if not settings.detectors_enabled:
        if settings.document_intake_enabled:
            log.warning(
                "DOCUMENT_INTAKE_ENABLED=1 has no effect without DETECTORS_ENABLED=1; "
                "context.documents is refused"
            )
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
    dlp = resolved.cfg.detectors.get("dlp_vn")  # WP-P2
    if (
        dlp is not None
        and dlp.enabled
        and dlp.settings.get("mode", "transform") == "transform"
        and not settings.inline_redaction_enabled
    ):
        log.warning(
            "dlp_vn is in transform mode but INLINE_REDACTION_ENABLED is off: the gate returns "
            "masked arguments, and an SDK or collector applies them only when it runs with "
            "INLINE_REDACTION_ENABLED=1"
        )
    _wire_guard_model(settings, registry, resolved, policy, state)  # WP-D3
    gate = DetectorGate(registry, resolved)
    # WP-D1: document and URL intake (None unless DOCUMENT_INTAKE_ENABLED=1)
    gate.intake = make_intake(settings)
    gate.dry_fetch = bool(settings.playground_url_fetch)
    # WP-S1: per-system guardian bindings (None unless both flags are on)
    from supervisor.governance.guardians import make_narrower

    gate.narrow = make_narrower(settings, state)
    from supervisor.detectors.overrides import make_source

    gate.overrides = make_source(settings, state)  # WP-B1 (None unless SMART_GUARDIAN)
    _wire_guardian_factory(settings, gate, registry, state)  # WP-G3 (default off)
    problems = gate.check_policy(policy)
    if problems:
        msg = "detector overrides in the policy are invalid: " + "; ".join(problems)
        raise ConfigError(msg.encode("ascii", "backslashreplace").decode("ascii"))
    return gate


def _wire_guardian_factory(settings: Settings, gate: Any, registry: Any, state: Any) -> None:
    """WP-G3: live guardians (GUARDIAN_FACTORY) and the shadow runner (also GUARDIAN_SHADOW).
    Both stay None when the flag is off: the gate then runs the code it ran before."""
    if state is None or not getattr(settings, "guardian_factory", False):
        return
    from supervisor.guardian_factory import shadow as gshadow
    from supervisor.guardian_factory.attach import LiveGuardians

    chat = gmasker = None
    if settings.llm_base_url and not settings.llm_mock:
        from supervisor.adapters.factory import make_chat_model, make_masker

        chat = make_chat_model(settings)
        gmasker = make_masker(settings)
    gate.attach = LiveGuardians(state, settings, registry, chat=chat, masker=gmasker)
    if gshadow.enabled(settings):
        gate.shadow = gshadow.ShadowRunner(
            state, settings, registry=registry, chat=chat, masker=gmasker
        )


def make_intake(settings: Settings) -> Any:
    """WP-D1: the reader of ``context.documents``, or None when DOCUMENT_INTAKE_ENABLED is off.
    The URL fetcher exists only with URL_FETCH_ENABLED=1 and a non-empty URL_FETCH_ALLOWLIST;
    without it a document given by URL is reported as unread (``url_fetch_disabled``)."""
    if not settings.document_intake_enabled:
        return None
    from supervisor.adapters.fetch import Fetcher
    from supervisor.detectors.intake import IntakeService

    domains = settings.url_fetch_domains
    fetcher = Fetcher(domains) if settings.url_fetch_enabled and domains else None
    key = settings.mask_key[0]  # documents and URLs are digested with the keyed mask hash

    def digest(data: bytes) -> str:
        return hmac.new(key, b"doc:" + data, hashlib.sha256).hexdigest()

    return IntakeService(fetcher, digest=digest)


def _guard_wanted(resolved: Any, policy: Policy) -> bool:
    """True when the ``guard_model`` entry is enabled in the file or a per-agent override of the
    policy enables it."""
    entry = resolved.cfg.detectors.get("guard_model")
    if entry is None:
        return False
    if entry.enabled:
        return True
    for agent_id in policy.doc.agents:
        override = policy.agent_detectors(agent_id)
        if override is not None and "guard_model" in override.enable:
            return True
    return False


def _wire_guard_model(
    settings: Settings, registry: Any, resolved: Any, policy: Policy, state: Any
) -> None:
    """WP-D3: give the ``guard_model`` detector its model, only when the detector is switched on
    (the entry is enabled, or a per-agent override enables it). Off, or absent from
    ``config/detectors.yaml``: nothing is built and nothing can fail at start-up; a bad setting is
    then only a ``[SKIP]`` line in the log. On, a bad setting (remote URL, family clash with an
    agent) is a start-up ``ConfigError``, never an error at call time."""
    if "guard_model" not in registry:
        return
    from supervisor.adapters.guard import make_guard_model
    from supervisor.adapters.guard.factory import check_remote
    from supervisor.core.errors import ConfigError

    if not _guard_wanted(resolved, policy):
        url = settings.guard_model_url.strip()
        if url:
            try:
                check_remote(settings, url, "GUARD_MODEL_URL")
            except ConfigError as exc:
                log.warning("[SKIP] guard_model is off and its setting is not usable: %s", exc)
        return
    try:
        port = make_guard_model(settings, state=state)
    except ConfigError as exc:
        msg = f"guard_model: {exc}"
        raise ConfigError(msg.encode("ascii", "backslashreplace").decode("ascii")) from None
    registry.get("guard_model").set_port(port)


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
    "resolve_policy_dirs",
]
