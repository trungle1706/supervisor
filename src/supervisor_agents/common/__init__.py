"""Shared runtime for the demo agents: manifest, tool loop, gate hook, tracing, world."""

from __future__ import annotations

from typing import Any

from opentelemetry.sdk.trace import TracerProvider

from supervisor.core.ports import ChatModel, GateHook
from supervisor_agents.common.manifest import load_manifest
from supervisor_agents.common.runtime import AgentRuntime, ToolRegistry


def build_runtime(
    agent_id: str,
    tools: ToolRegistry,
    chat: ChatModel,
    *,
    gate: GateHook | None = None,
    tracer_provider: TracerProvider | None = None,
    env: str = "dev",
    **kwargs: Any,
) -> AgentRuntime:
    return AgentRuntime(
        load_manifest(agent_id),
        tools,
        chat,
        gate=gate,
        tracer_provider=tracer_provider,
        env=env,
        **kwargs,
    )
