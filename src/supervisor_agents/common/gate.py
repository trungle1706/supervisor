"""GateHook helpers for the agent tool router.

``AllowAllHook`` is the default when no gateway is attached (it decides nothing; the real
gate is WP3). ``safe_check`` wraps any hook so the router never crashes: if the hook
raises, money / credit / PII-export tools fail closed (block) and read-only tools fail
open with an alert, as the GateHook contract requires.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from supervisor.core.ports import GateHook
from supervisor_agents.common.manifest import FAIL_CLOSED_CLASSES

VALID_ACTIONS: frozenset[str] = frozenset({"allow", "log", "alert", "block", "pause"})

ALLOW: dict[str, Any] = {
    "allow": True,
    "action": "allow",
    "rule_id": None,
    "reason": "no gate attached",
    "latency_ms": 0,
}


class AllowAllHook:
    """Default hook: allows every call. Used only when no gateway is configured."""

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        return dict(ALLOW)


class RecordingHook:
    """Test helper: delegates to ``inner`` (default allow-all) and records every check."""

    def __init__(self, inner: GateHook | None = None) -> None:
        self.inner = inner or AllowAllHook()
        self.calls: list[dict[str, Any]] = []

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        decision = self.inner.check(agent_id, agent_version, tool_name, args, context)
        self.calls.append(
            {
                "agent_id": agent_id,
                "agent_version": agent_version,
                "tool_name": tool_name,
                "args": dict(args),
                "context": dict(context or {}),
                "decision": dict(decision),
            }
        )
        return decision


def safe_check(
    hook: GateHook,
    agent_id: str,
    agent_version: str,
    tool_name: str,
    args: Mapping[str, Any],
    context: Mapping[str, Any],
    risk_class: str | None,
) -> dict[str, Any]:
    start = time.monotonic()
    try:
        raw = dict(hook.check(agent_id, agent_version, tool_name, args, context))
    except Exception as exc:  # noqa: BLE001 - the router must never crash on the gate
        closed = risk_class is None or risk_class in FAIL_CLOSED_CLASSES
        return {
            "allow": not closed,
            "action": "block" if closed else "alert",
            "rule_id": "gate_hook_error",
            "reason": f"gate hook failed ({type(exc).__name__}); "
            + ("fail-closed" if closed else "fail-open"),
            "latency_ms": int((time.monotonic() - start) * 1000),
        }
    closed = risk_class is None or risk_class in FAIL_CLOSED_CLASSES
    action = raw.get("action")
    allow_raw = raw.get("allow")
    if action not in VALID_ACTIONS or not isinstance(allow_raw, bool):
        # Garbled decision: treat like a hook failure (fail-closed for money/credit/PII).
        return {
            "allow": not closed,
            "action": "block" if closed else "alert",
            "rule_id": "gate_hook_invalid",
            "reason": "gate hook returned an invalid decision; "
            + ("fail-closed" if closed else "fail-open"),
            "latency_ms": int((time.monotonic() - start) * 1000),
        }
    allow = allow_raw and action in ("allow", "log", "alert")
    return {
        "allow": allow,
        "action": action,
        "rule_id": raw.get("rule_id"),
        "reason": str(raw.get("reason", "")),
        "latency_ms": int(raw.get("latency_ms") or int((time.monotonic() - start) * 1000)),
    }
