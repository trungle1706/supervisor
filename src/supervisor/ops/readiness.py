"""Readiness probe logic (WP18). ``readiness(...)`` returns a body that never carries secrets,
hostnames, paths or exception messages: only check names and short fixed states."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("supervisor.ops")


def _store_ok(runtime: Any) -> bool:
    try:
        # One cheap read through the state port; any answer (even None) means reachable.
        runtime.adapters.state.query("agent", limit=1)
        return True
    except Exception:  # noqa: BLE001 - the body must not carry the message
        log.warning("readiness: store check failed", exc_info=True)
        return False


def _signer_ok(runtime: Any) -> bool:
    signer = getattr(getattr(runtime, "chain", None), "signer", None)
    return bool(signer is not None and getattr(signer, "key_id", None))


def _scheduler_state(settings: Any, scheduler: Any) -> str:
    if scheduler is None:
        return "not-leader" if getattr(settings, "scheduler_on", False) else "off"
    return "running" if scheduler.running else "not-leader"


def readiness(settings: Any, runtime: Any | None, scheduler: Any | None = None) -> dict[str, Any]:
    """{"ready": bool, "checks": {...}, "failed": [names]}.

    The scheduler state (running / off / not-leader) is informational: it never fails the probe.
    """
    checks: dict[str, Any] = {"runtime": runtime is not None}
    checks["store"] = _store_ok(runtime) if runtime is not None else False
    checks["signer"] = _signer_ok(runtime) if runtime is not None else False
    checks["scheduler"] = _scheduler_state(settings, scheduler)
    failed = [k for k in ("runtime", "store", "signer") if checks[k] is not True]
    return {"ready": not failed, "checks": checks, "failed": failed}
