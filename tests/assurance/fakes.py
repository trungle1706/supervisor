"""Test doubles for the three assurance targets (shared by every tests/assurance file).

Each fake takes plain callables so a test can build a *good* target (must pass) and a
*bad* target (must fail) for the same pack. That is how we prove a runner measures
something and does not return a pass by construction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from supervisor.assurance.model import ModelDependency, RunContext, TargetReply
from tests.conftest import REPO_ROOT


def _echo(prompt: str, context: Sequence[str], sample: int) -> TargetReply:
    return TargetReply(text=context[0] if context else prompt, is_mock=True)


@dataclass
class FakeAgent:
    kind: Literal["agent"] = "agent"
    target_id: str = "fake_agent"
    is_mock: bool = True
    capabilities: frozenset[str] = frozenset(
        {"chat", "tools", "planned", "decide", "deps", "models", "tool_manifest"}
    )
    respond_fn: Callable[[str, Sequence[str], int], TargetReply] = _echo
    tool_fn: Callable[[str, str, Mapping[str, Any]], TargetReply] | None = None
    planned_fn: Callable[[str, Sequence[Mapping[str, Any]]], TargetReply] | None = None
    decide_fn: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
    deps: list[Path] = field(default_factory=lambda: [REPO_ROOT / "uv.lock"])
    models: list[ModelDependency] = field(default_factory=list)
    tools: Mapping[str, Any] = field(default_factory=lambda: {"tools": [], "mcp_servers": []})
    prompt: str = "You are a bank assistant. CANARY-SYS-7731"

    def respond(self, prompt: str, *, context: Sequence[str] = (), sample: int = 0) -> TargetReply:
        return self.respond_fn(prompt, context, sample)

    def run_with_tool_result(
        self, prompt: str, tool: str, injected_result: Mapping[str, Any]
    ) -> TargetReply:
        if self.tool_fn is None:
            return TargetReply(text="ok", is_mock=True)
        return self.tool_fn(prompt, tool, injected_result)

    def run_planned(self, prompt: str, planned_calls: Sequence[Mapping[str, Any]]) -> TargetReply:
        if self.planned_fn is None:
            return TargetReply(text="done", tool_calls=[dict(c) for c in planned_calls])
        return self.planned_fn(prompt, planned_calls)

    def decide(self, applicant: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.decide_fn is None:
            return {"approved": True, "limit_minor": 0, "reason": "fake"}
        return self.decide_fn(applicant)

    def dependency_files(self) -> list[Path]:
        return list(self.deps)

    def model_inventory(self) -> list[ModelDependency]:
        return list(self.models)

    def tool_manifest(self) -> Mapping[str, Any]:
        return self.tools

    def system_prompt(self) -> str:
        return self.prompt


@dataclass
class FakeTraces:
    rows: list[Mapping[str, Any]] = field(default_factory=list)
    kind: Literal["traces"] = "traces"
    target_id: str = "fake_agent"
    is_mock: bool = True
    store: Any = None

    def events(self) -> list[Mapping[str, Any]]:
        return list(self.rows)

    def tables(self) -> Any:
        return self.store


@dataclass
class FakeJudge:
    score_fn: Callable[[Sequence[Mapping[str, Any]]], Mapping[str, Any]]
    kind: Literal["judge"] = "judge"
    target_id: str = "judge:fake"
    is_mock: bool = True
    factory: Callable[[], Any] | None = None
    models: list[ModelDependency] = field(default_factory=list)

    def router_factory(self) -> Any:
        return self.factory

    def score(self, events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        return self.score_fn(events)

    def model_inventory(self) -> list[ModelDependency]:
        return list(self.models)

    def dependency_files(self) -> list[Path]:
        return [REPO_ROOT / "uv.lock"]


def ctx(target: Any, **kw: Any) -> RunContext:
    kw.setdefault("repo_root", REPO_ROOT)
    kw.setdefault("data_root", None)
    return RunContext(target=target, **kw)
