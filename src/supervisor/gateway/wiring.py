"""Build the process-wide Gateway from Settings (used by the FastAPI routes).

* Adapters come from ``supervisor.adapters.factory`` (SQLite on the laptop, Delta on Databricks).
* Policy: ``policies/*.yaml`` is loaded, validated and deployed to the ``rule`` table
  (idempotent); the gateway then enforces what the table holds (``StorePolicyProvider``).
* EvidenceSink: WP6 provides the chain writer. Until it is wired with
  ``set_evidence_sink`` (or ``build_gateway(evidence=...)``), ``BufferedEvidenceSink``
  keeps the records in memory and logs a warning once. It never drops the gate decision.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT, Settings
from supervisor.core.canonical import canonical_bytes
from supervisor.core.ports import EvidenceSink
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StorePolicyProvider, deploy_with_retry, load_policy_dir

log = logging.getLogger("supervisor.gateway")

POLICY_DIR = REPO_ROOT / "policies"


class BufferedEvidenceSink:
    """Placeholder sink until the WP6 chain writer is wired. Keeps the last N records."""

    def __init__(self, keep: int = 10_000) -> None:
        self.keep = keep
        self.entries: list[tuple[str, str, dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._warned = False

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        data = canonical_bytes({"type": record_type, "ref": record_ref, "payload": payload})
        with self._lock:
            if not self._warned:
                log.warning("evidence chain writer (WP6) not wired; buffering gate evidence")
                self._warned = True
            self.entries.append((record_type, record_ref, dict(payload)))
            del self.entries[: -self.keep]
        return hashlib.sha256(data).hexdigest()


_lock = threading.Lock()
_gateway: Gateway | None = None


def build_gateway(
    settings: Settings | None = None,
    *,
    evidence: EvidenceSink | None = None,
    policy_dir: Path | None = None,
) -> Gateway:
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings

    settings = settings or load_settings()
    adapters = build_adapters(settings)
    if adapters.executor.dialect == "sqlite":
        from supervisor.jobs import bootstrap_schema

        bootstrap_schema.run(settings, adapters)
    policy = load_policy_dir(policy_dir or POLICY_DIR)
    deploy_with_retry(policy, adapters.state, adapters.clock)
    return Gateway(
        StorePolicyProvider(adapters.state, refresh_s=5.0),
        adapters.tables,
        adapters.state,
        evidence or BufferedEvidenceSink(),
        adapters.clock,
        env=settings.supervisor_mode,
    )


def get_gateway() -> Gateway:
    """The process-wide gateway (built on first use)."""
    global _gateway
    with _lock:
        if _gateway is None:
            _gateway = build_gateway()
        return _gateway


def set_gateway(gateway: Gateway | None) -> None:
    """Install a gateway (tests, or the app wiring a WP6 evidence sink)."""
    global _gateway
    with _lock:
        _gateway = gateway


def set_evidence_sink(sink: EvidenceSink) -> None:
    """Point the running gateway (and its state machine) at a new sink (WP6 hook)."""
    gw = get_gateway()
    gw.evidence = sink
    gw.states.evidence = sink
