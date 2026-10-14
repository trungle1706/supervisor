"""Scripted tasks: a prompt, the MockChat script that drives the agent, and the expected
outcome. Each agent ships 20 of them (``<agent>.tasks.TASKS``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from supervisor.adapters.llm.mock import MockChat
from supervisor_agents.common.runtime import AgentRuntime, RunResult
from supervisor_agents.common.world import BankWorld


def tool(name: str, **args: Any) -> dict[str, Any]:
    """One scripted LLM step that calls a tool."""
    return {"action": "tool", "tool": name, "args": args, "message": ""}


def final(message: str) -> dict[str, Any]:
    """One scripted LLM step that ends the run."""
    return {"action": "final", "tool": "", "args": {}, "message": message}


WorldCheck = Callable[[BankWorld], bool]


@dataclass(frozen=True)
class ScriptedTask:
    task_id: str
    prompt: str
    script: Sequence[Mapping[str, Any]]
    expected_status: str = "completed"
    expected_tools: Sequence[str] = ()
    expected_tool_statuses: Sequence[str] | None = None  # default: all "ok"
    expected_final_contains: str | None = None
    world_check: WorldCheck | None = None
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class TaskOutcome:
    task: ScriptedTask
    result: RunResult
    problems: list[str]

    @property
    def passed(self) -> bool:
        return not self.problems


def run_task(
    runtime: AgentRuntime, chat: MockChat, world: BankWorld, task: ScriptedTask
) -> TaskOutcome:
    chat.add_script(task.task_id, list(task.script))
    with chat.scenario(task.task_id):
        result = runtime.run(task.prompt, context=dict(task.context))
    problems: list[str] = []
    if result.status != task.expected_status:
        problems.append(f"status {result.status} != {task.expected_status}")
    if list(result.tool_sequence) != list(task.expected_tools):
        problems.append(f"tools {result.tool_sequence} != {list(task.expected_tools)}")
    statuses = [c.status for c in result.tool_calls]
    want = list(task.expected_tool_statuses or ["ok"] * len(task.expected_tools))
    if statuses != want:
        problems.append(f"tool statuses {statuses} != {want}")
    if task.expected_final_contains and task.expected_final_contains not in result.final_message:
        problems.append(f"final message lacks {task.expected_final_contains!r}")
    if task.world_check is not None and not task.world_check(world):
        problems.append("world check failed")
    return TaskOutcome(task, result, problems)
