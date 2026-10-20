"""A fake gate for the adapter tests. Records every call and answers from a script."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

ALLOW: dict[str, Any] = {"allow": True, "action": "allow", "rule_id": None, "reason": "allowed"}
BLOCK: dict[str, Any] = {
    "allow": False,
    "action": "block",
    "rule_id": "PAY-06",
    "reason": "A transfer amount must be a positive integer",
    "status": "block",
}
PAUSE: dict[str, Any] = {
    "allow": False,
    "action": "pause",
    "rule_id": "PAY-07",
    "reason": "agent paused",
    "status": "pause",
}


def transform(args: dict[str, Any] | None = None, output: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args is not None:
        payload["args"] = args
    if output is not None:
        payload["output"] = output
    return {
        "allow": True,
        "action": "allow",
        "rule_id": None,
        "reason": "allowed",
        "status": "transform",
        "transformed_payload": payload,
    }


class FakeGate:
    """``answer`` is a dict, or a function ``(call) -> dict`` (call = the recorded call)."""

    def __init__(self, answer: Mapping[str, Any] | Callable[[dict], Mapping[str, Any]] = ALLOW):
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
        *,
        direction: str = "input",
        correlation_id: str | None = None,
    ) -> Mapping[str, Any]:
        call = {
            "agent_id": agent_id,
            "agent_version": agent_version,
            "tool_name": tool_name,
            "args": dict(args),
            "context": dict(context or {}),
            "direction": direction,
            "correlation_id": correlation_id,
        }
        self.calls.append(call)
        return self.answer(call) if callable(self.answer) else dict(self.answer)


class OldGate:
    """A GateHook of the old shape: no direction, no correlation id."""

    def __init__(self, answer: Mapping[str, Any] = ALLOW) -> None:
        self.answer = answer
        self.calls: list[tuple[Any, ...]] = []

    def check(self, agent_id, agent_version, tool_name, args, context=None):  # type: ignore[no-untyped-def]
        self.calls.append((agent_id, agent_version, tool_name, dict(args), context))
        return dict(self.answer)


class DownGate:
    """A gate that is unreachable: the SDK answer for an outage."""

    def __init__(self, rule_id: str = "GATE-UNREACHABLE", allow: bool = False) -> None:
        self.rule_id = rule_id
        self.allow = allow
        self.calls = 0

    def check(self, *a: Any, **k: Any) -> Mapping[str, Any]:
        self.calls += 1
        return {
            "allow": self.allow,
            "action": "alert" if self.allow else "block",
            "rule_id": self.rule_id,
            "reason": "gateway unreachable",
        }


class RaisingGate:
    def check(self, *a: Any, **k: Any) -> Mapping[str, Any]:
        raise RuntimeError("boom")
