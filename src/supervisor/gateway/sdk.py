"""Agent-side SDK: gate hooks (in-process and HTTP) and the ``supervised_tool`` decorator.

Fail closed: no gate, no call. ``check`` on a hook never raises.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from supervisor.core.ports import GateHook

F = TypeVar("F", bound=Callable[..., Any])

Transport = Callable[[str, dict[str, Any], float], Mapping[str, Any]]


class SupervisorBlocked(Exception):
    """The gate refused the call. ``decision`` holds the gate's answer."""

    def __init__(self, decision: Mapping[str, Any]) -> None:
        self.decision = dict(decision)
        rule = self.decision.get("rule_id")
        reason = self.decision.get("reason", "blocked")
        super().__init__(f"blocked by supervisor ({rule}): {reason}")


class SupervisorPaused(SupervisorBlocked):
    """The gate paused the agent (or the agent was already paused)."""


def _closed_decision(rule_id: str, reason: str, t0: float) -> dict[str, Any]:
    return {
        "allow": False,
        "action": "block",
        "rule_id": rule_id,
        "reason": reason,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


class InProcessGate:
    """GateHook that calls a ``Gateway`` in the same process."""

    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        t0 = time.perf_counter()
        try:
            return self.gateway.check(agent_id, agent_version, tool_name, args, context)
        except Exception:  # noqa: BLE001 - the hook must never raise
            return _closed_decision("GATE-ERROR", "gateway error: fail closed", t0)


def _default_transport(url: str, payload: dict[str, Any], timeout_s: float) -> Mapping[str, Any]:
    from supervisor.adapters.http_json import post_json

    return post_json(url, payload, timeout_s)


class HttpGate:
    """GateHook that POSTs to ``{base_url}/gate/check``; applies the fail mode locally."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 2.0,
        transport: Transport | None = None,
        fail_modes: Mapping[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.transport: Transport = transport or _default_transport
        self.fail_modes: dict[str, str] = dict(fail_modes or {})

    def _fallback(self, tool_name: str, t0: float) -> dict[str, Any]:
        latency = int((time.perf_counter() - t0) * 1000)
        if self.fail_modes.get(tool_name) == "read_only":
            return {
                "allow": True,
                "action": "alert",
                "rule_id": "GATE-UNREACHABLE",
                "reason": "gateway unreachable: fail open (read only)",
                "latency_ms": latency,
            }
        return _closed_decision("GATE-UNREACHABLE", "gateway unreachable: fail closed", t0)

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        t0 = time.perf_counter()
        payload = {
            "agent_id": agent_id,
            "agent_version": agent_version,
            "tool_name": tool_name,
            "args": dict(args),
            "context": dict(context) if context is not None else None,
        }
        try:
            result = self._call(payload)
            if not isinstance(result, Mapping) or not isinstance(result.get("allow"), bool):
                return self._fallback(tool_name, t0)
            out = dict(result)
            out["latency_ms"] = int(out.get("latency_ms") or 0)
            return out
        except Exception:  # noqa: BLE001 - timeouts and transport errors: fail mode
            return self._fallback(tool_name, t0)

    def _call(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        """Run the transport with a hard deadline, even if the transport ignores it."""
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                box["value"] = self.transport(
                    f"{self.base_url}/gate/check", payload, self.timeout_s
                )
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(self.timeout_s)
        if worker.is_alive():
            raise TimeoutError("gateway call timed out")
        if "error" in box:
            raise box["error"]
        return box["value"]  # type: ignore[no-any-return]


_default_gate: GateHook | None = None


def set_default_gate(gate: GateHook | None) -> None:
    global _default_gate
    _default_gate = gate


def get_default_gate() -> GateHook | None:
    return _default_gate


def _enforce(decision: Mapping[str, Any]) -> None:
    if decision.get("allow") is True:
        return
    reason = str(decision.get("reason", ""))
    if decision.get("action") == "pause" or "paused" in reason.lower():
        raise SupervisorPaused(decision)
    raise SupervisorBlocked(decision)


def supervised_tool(
    agent_id: str,
    agent_version: str,
    tool_name: str,
    risk_class: str,
    gate: GateHook | None = None,
) -> Callable[[F], F]:
    """Decorator: ask the gate before the tool runs; do not run it unless allowed."""

    def resolve() -> GateHook:
        g = gate or _default_gate
        if g is None:
            raise SupervisorBlocked(
                {
                    "allow": False,
                    "action": "block",
                    "rule_id": "GATE-MISSING",
                    "reason": "no gate configured: fail closed",
                }
            )
        return g

    def decorate(fn: F) -> F:
        sig = inspect.signature(fn)

        def bind(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                return dict(bound.arguments)
            except TypeError:
                return dict(kwargs)

        context = {"declared_risk_class": risk_class}

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                g = resolve()
                decision = await asyncio.to_thread(
                    g.check, agent_id, agent_version, tool_name, bind(args, kwargs), context
                )
                _enforce(decision)
                return await fn(*args, **kwargs)

            return awrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            g = resolve()
            decision = g.check(agent_id, agent_version, tool_name, bind(args, kwargs), context)
            _enforce(decision)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorate
