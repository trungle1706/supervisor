"""Small helpers shared by gateway tests."""

from __future__ import annotations

from typing import Any

from supervisor.core.ports import GateHook


def call(gate: GateHook, agent: str, tool: str, **args: Any) -> dict[str, Any]:
    return dict(gate.check(agent, "1.0", tool, args, {"trace_id": "t-test"}))


def matched_ids(result: dict[str, Any]) -> list[str]:
    return [m["rule_id"] for m in result["matched_rules"]]
