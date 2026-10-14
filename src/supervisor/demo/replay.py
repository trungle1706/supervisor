"""Scripted replay of the four demo incidents (``agents/redteam/demo_incidents.yaml``).

The agents' LLM output is fixed (MockChat scripts); the tool router, the GateHook and the
tracing are the real code paths. WP3 passes its gateway as ``gate=`` to test that every
incident is blocked or paused; without a gate the replay uses ``AllowAllHook`` and the
harmful actions go through (that is the "before Supervisor" picture).

    python -m supervisor.demo.replay                    # all four, allow-all gate, in memory
    python -m supervisor.demo.replay --incident DEMO-1
    python -m supervisor.demo.replay --store            # also append agent_event rows to the
                                                        # configured store (SQLite by default)
"""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.adapters.llm.mock import MockChat
from supervisor.core.ports import GateHook, TableStore
from supervisor_agents.common.gate import AllowAllHook
from supervisor_agents.common.runtime import RunResult
from supervisor_agents.common.tracing import AgentEventExporter, make_tracer_provider
from supervisor_agents.common.world import BankWorld

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_FILE = REPO_ROOT / "agents" / "redteam" / "demo_incidents.yaml"


@dataclass
class StepResult:
    agent: str
    caller_agent_id: str | None
    attack_step: bool
    run: RunResult


@dataclass
class IncidentResult:
    incident_id: str
    title: str
    expected_gate_action: str
    harmful_effect: str
    steps: list[StepResult] = field(default_factory=list)
    harmful_effects_recorded: int = 0

    @property
    def attack_stopped(self) -> bool:
        """True when the gate blocked or paused a tool call in an attack step."""
        return any(
            c.status in ("blocked", "paused")
            for s in self.steps
            if s.attack_step
            for c in s.run.tool_calls
        )

    @property
    def gate_actions(self) -> list[str]:
        return [str(c.decision.get("action")) for s in self.steps for c in s.run.tool_calls]


def load_demo_incidents(path: Path = DEMO_FILE) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return list(data["incidents"])


def replay(
    incident_ids: Sequence[str] | None = None,
    *,
    gate: GateHook | None = None,
    store: TableStore | None = None,
    world: BankWorld | None = None,
    env: str = "demo",
    path: Path = DEMO_FILE,
) -> list[IncidentResult]:
    """Drive the agents through the demo incidents. Returns one result per incident."""
    gate = gate or AllowAllHook()
    exporter = AgentEventExporter(store, env=env)
    provider = make_tracer_provider(exporter, service_name="supervisor-demo-replay")
    results: list[IncidentResult] = []
    shared = world
    for inc in load_demo_incidents(path):
        if incident_ids and inc["id"] not in incident_ids:
            continue
        w = shared if shared is not None else BankWorld.build()  # fresh world per incident
        chat = MockChat(seed=0, model_id="mock-replay")
        res = IncidentResult(
            inc["id"], inc["title"], inc.get("expected_gate_action", ""), inc["harmful_effect"]
        )
        before = len(getattr(w, inc["harmful_effect"]))
        for n, step in enumerate(inc["steps"], start=1):
            mod = importlib.import_module(f"supervisor_agents.{step['agent']}.agent")
            runtime = mod.build_agent(chat, w, gate=gate, tracer_provider=provider, env=env)
            key = f"{inc['id']}:{n}"
            chat.add_script(key, list(step["script"]))
            with chat.scenario(key):
                run = runtime.run(
                    step["task"],
                    context=dict(step.get("context") or {}, incident_id=inc["id"]),
                    caller_agent_id=step.get("caller_agent_id"),
                )
            res.steps.append(
                StepResult(
                    step["agent"], step.get("caller_agent_id"), bool(step.get("attack_step")), run
                )
            )
        res.harmful_effects_recorded = len(getattr(w, inc["harmful_effect"])) - before
        results.append(res)
    provider.shutdown()
    return results


def _summary(r: IncidentResult) -> str:
    verdict = "STOPPED" if r.attack_stopped else "EXECUTED"
    actions = ",".join(r.gate_actions) or "-"
    return (
        f"{r.incident_id} attack={verdict} expected_gate={r.expected_gate_action} "
        f"gate_actions=[{actions}] {r.harmful_effect}+{r.harmful_effects_recorded}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    from supervisor.bootstrap import bootstrap

    bootstrap()
    parser = argparse.ArgumentParser(prog="python -m supervisor.demo.replay")
    parser.add_argument("--incident", action="append", help="DEMO-1..DEMO-4 (repeatable)")
    parser.add_argument(
        "--store", action="store_true", help="append agent_event rows to the configured store"
    )
    args = parser.parse_args(argv)
    store: TableStore | None = None
    adapters = None
    if args.store:
        from supervisor.adapters.factory import build_adapters
        from supervisor.config import load_settings
        from supervisor.jobs import bootstrap_schema

        adapters = build_adapters(load_settings())
        bootstrap_schema.run(adapters.settings, adapters)
        store = adapters.tables
    try:
        results = replay(args.incident, store=store)
    finally:
        if adapters is not None:
            adapters.close()
    if not results:
        print("[FAIL] no incident matched")  # noqa: T201
        return 1
    print("[SKIP] no gateway attached: replay uses the allow-all gate hook")  # noqa: T201
    for r in results:
        print(f"[OK] {_summary(r)}")  # noqa: T201
    return 0


def describe(results: Sequence[IncidentResult]) -> list[Mapping[str, Any]]:
    """Plain dicts for tests and the console."""
    return [
        {
            "incident_id": r.incident_id,
            "attack_stopped": r.attack_stopped,
            "gate_actions": r.gate_actions,
            "harmful_effects_recorded": r.harmful_effects_recorded,
            "trace_ids": [s.run.trace_id for s in r.steps],
        }
        for r in results
    ]


if __name__ == "__main__":
    raise SystemExit(main())
