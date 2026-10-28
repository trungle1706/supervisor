"""Body of ``GET /healthz`` (WP-P3). Fast, secret-free, never raises.

Fields: ``status``, ``schema_ok`` (true / false / "unknown"), ``judge_sweep`` (enabled /
disabled), ``gate_timeout_s`` (the configured GATE_DECISION_TIMEOUT_S: a candidate's
SUPERVISOR_TIMEOUT_S must be larger), ``model_resource`` (ok / fail / unknown).

``model_resource`` is "unknown" unless HEALTHZ_MODEL_PROBE=1. With the flag on, one tiny call
goes to the configured LLM gateway in a background thread; the answer is cached for 60 s and
/healthz returns the cached value at once, so a slow gateway never slows the probe.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger("supervisor.ops.healthz")

PROBE_TTL_S = 60.0
PROBE_TIMEOUT_S = 5.0
_PROBE_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
_PROBE_MESSAGES = [{"role": "user", "content": 'Reply with the JSON {"ok": true}.'}]

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": None, "value": "unknown", "key": None, "busy": False}


def reset_probe_cache() -> None:
    with _lock:
        _cache.update(at=None, value="unknown", key=None, busy=False)


def _call_gateway(settings: Any) -> str:
    """One small call through the configured chat adapter. ok / fail / unknown (mock)."""
    from supervisor.adapters.factory import make_chat_model

    chat = make_chat_model(settings)
    try:
        if getattr(chat, "is_mock", False):
            return "unknown"  # no gateway behind a mock
        chat.complete_json(_PROBE_MESSAGES, _PROBE_SCHEMA, PROBE_TIMEOUT_S)
        return "ok"
    except Exception as exc:  # noqa: BLE001 - any failure means the resource is not usable
        log.warning("healthz model probe failed (%s)", type(exc).__name__)
        return "fail"
    finally:
        close = getattr(chat, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001, S110
                pass


def _refresh(settings: Any, probe: Callable[[Any], str], key: str) -> None:
    try:
        value = probe(settings)
        if value not in ("ok", "fail", "unknown"):
            value = "unknown"
    except Exception:  # noqa: BLE001
        value = "unknown"
    with _lock:
        _cache.update(at=time.monotonic(), value=value, key=key, busy=False)


def model_resource(
    settings: Any,
    probe: Callable[[Any], str] | None = None,
    *,
    background: bool = True,
) -> str:
    """Cached probe result. Off (default): "unknown", no call is made."""
    if not getattr(settings, "healthz_model_probe", False):
        return "unknown"
    key = f"{getattr(settings, 'llm_base_url', '')}|{getattr(settings, 'llm_model', '')}"
    with _lock:
        fresh = (
            _cache["at"] is not None
            and _cache["key"] == key
            and time.monotonic() - _cache["at"] < PROBE_TTL_S
        )
        value = str(_cache["value"]) if _cache["key"] == key else "unknown"
        if fresh or _cache["busy"]:
            return value
        _cache["busy"] = True
    fn = probe or _call_gateway
    if background:
        threading.Thread(
            target=_refresh, args=(settings, fn, key), name="healthz-model-probe", daemon=True
        ).start()
        return value
    _refresh(settings, fn, key)
    with _lock:
        return str(_cache["value"])


def judge_sweep_state(scheduler: Any) -> str:
    try:
        job = scheduler.jobs.get("judge_sweep") if scheduler is not None else None
        return "enabled" if job is not None and job.enabled else "disabled"
    except Exception:  # noqa: BLE001
        return "disabled"


def schema_ok_value() -> bool | str:
    try:
        from supervisor.ops import schema_selfcheck

        state = schema_selfcheck.get_state()
        return state.schema_ok if state is not None else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def body(
    settings: Any, scheduler: Any = None, probe: Callable[[Any], str] | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    try:
        out["schema_ok"] = schema_ok_value()
        out["judge_sweep"] = judge_sweep_state(scheduler)
        out["gate_timeout_s"] = float(settings.gate_decision_timeout_s)
        out["model_resource"] = model_resource(settings, probe)
    except Exception:  # noqa: BLE001 - /healthz never fails
        log.warning("healthz body incomplete", exc_info=True)
        out.setdefault("schema_ok", "unknown")
        out.setdefault("judge_sweep", "disabled")
        out.setdefault("model_resource", "unknown")
    return out
