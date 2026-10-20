"""The process-wide Gateway used by the FastAPI routes.

The gateway is built by the composition root ``supervisor.wiring.build_runtime``:
adapters from Settings, ``policies/*.yaml`` deployed to the ``rule`` table
(``StorePolicyProvider`` enforces what the table holds), and the WP6 ``ChainWriter``
as the EvidenceSink. The app builds it at startup (``install_runtime``); routes build
it on first use if startup could not (for example the store was briefly unavailable).

``build_gateway(evidence=...)`` keeps the older path with a caller-supplied sink
(tests and embedding). ``BufferedEvidenceSink`` remains for that path only.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from supervisor.config import REPO_ROOT, Settings
from supervisor.core.canonical import canonical_bytes
from supervisor.core.ports import EvidenceSink
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StorePolicyProvider, deploy_with_retry, load_policy_dir

if TYPE_CHECKING:
    from supervisor.wiring import Runtime

log = logging.getLogger("supervisor.gateway")

POLICY_DIR = REPO_ROOT / "policies"


class BufferedEvidenceSink:
    """In-memory sink for callers that pass no chain writer. Keeps the last N records."""

    def __init__(self, keep: int = 10_000) -> None:
        self.keep = keep
        self.entries: list[tuple[str, str, dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._warned = False

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        data = canonical_bytes({"type": record_type, "ref": record_ref, "payload": payload})
        with self._lock:
            if not self._warned:
                log.warning("gate evidence goes to an in-memory buffer, not the chain")
                self._warned = True
            self.entries.append((record_type, record_ref, dict(payload)))
            del self.entries[: -self.keep]
        return hashlib.sha256(data).hexdigest()


_lock = threading.RLock()
_gateway: Gateway | None = None
_runtime: Runtime | None = None


def build_gateway(
    settings: Settings | None = None,
    *,
    evidence: EvidenceSink | None = None,
    policy_dir: Path | None = None,
) -> Gateway:
    """Gateway with the WP6 chain writer (default) or with the given evidence sink."""
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings

    if evidence is None:
        return install_runtime(settings, policy_dir=policy_dir).gateway
    settings = settings or load_settings()
    adapters = build_adapters(settings)
    if adapters.executor.dialect == "sqlite":
        from supervisor.jobs import bootstrap_schema

        bootstrap_schema.run(settings, adapters)
    from supervisor.adapters.facts import make_fact_source
    from supervisor.wiring import make_detector_gate, make_session_gate, resolve_policy_dir

    policy = load_policy_dir(resolve_policy_dir(settings, policy_dir))
    deploy_with_retry(policy, adapters.state, adapters.clock)
    return Gateway(
        StorePolicyProvider(adapters.state, refresh_s=5.0),
        adapters.tables,
        adapters.state,
        evidence,
        adapters.clock,
        facts=make_fact_source(settings),  # D13: FACT_SOURCE (default none)
        env=settings.supervisor_mode,
        detector_gate=make_detector_gate(settings, policy),  # WP37 (default off)
        session_gate=make_session_gate(settings, adapters, evidence),  # WP27 (default off)
    )


def install_runtime(settings: Settings | None = None, *, policy_dir: Path | None = None) -> Runtime:
    """Build the runtime (chain + gateway) once per process and install its gateway."""
    global _gateway, _runtime
    from supervisor.wiring import build_runtime

    with _lock:
        if _runtime is None:
            _runtime = build_runtime(settings, policy_dir=policy_dir)
        if _gateway is None:  # a gateway installed with set_gateway() stays in place
            _gateway = _runtime.gateway
        return _runtime


def shutdown_runtime() -> None:
    """Close the installed runtime (seals the chain with a signed root)."""
    global _gateway, _runtime
    with _lock:
        rt, _runtime = _runtime, None
        if rt is not None and _gateway is rt.gateway:
            _gateway = None
    if rt is not None:
        rt.close()


def get_gateway() -> Gateway:
    """The process-wide gateway (built on first use)."""
    global _gateway
    with _lock:
        if _gateway is None:
            _gateway = install_runtime().gateway
        return _gateway


def peek_gateway() -> Gateway | None:
    """The installed gateway, or None. Never builds one (WP20 ingress audit and metrics)."""
    with _lock:
        return _gateway


def set_gateway(gateway: Gateway | None) -> None:
    """Install a gateway (tests, or embedding with another evidence sink)."""
    global _gateway
    with _lock:
        _gateway = gateway


def set_evidence_sink(sink: EvidenceSink) -> None:
    """Point the running gateway (and its state machine) at another sink."""
    gw = get_gateway()
    gw.evidence = sink
    gw.states.evidence = sink
