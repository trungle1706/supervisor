"""Scripted replay of the four demo incidents (``agents/redteam/demo_incidents.yaml``).

The agents' LLM output is fixed (MockChat scripts); the tool router, the GateHook and the
tracing are the real code paths. WP3 passes its gateway as ``gate=`` to test that every
incident is blocked or paused; without a gate the replay uses ``AllowAllHook`` and the
harmful actions go through (that is the "before Supervisor" picture).

    python -m supervisor.demo.replay                    # all four, allow-all gate, in memory
    python -m supervisor.demo.replay --incident DEMO-1
    python -m supervisor.demo.replay --store            # also append agent_event rows to the
                                                        # configured store (SQLite by default)
    python -m supervisor.demo.replay --gate             # M1: the real gateway on the
                                                        # configured store, evidence on the chain

``--gate`` builds the runtime with ``supervisor.wiring.build_runtime`` (policy from
``policies/``, ChainWriter on the store, Gateway with a fact source over the demo
BankWorld), registers the three agents and their versions, replays the incidents and
prints one ``[OK] DEMO-n STOPPED by <rule> action=<block|pause>`` line per incident and
the chain head. An agent paused by a rule is resumed between incidents by the normal
two-person resume (owner + reviewer), recorded on the chain. Exit 1 if any attack
executes or stops with another action than the incident file expects.
"""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.adapters.llm.mock import MockChat
from supervisor.config import Settings
from supervisor.core.canonical import sha256_hex
from supervisor.core.ports import GateHook, TableStore
from supervisor.gateway.facts import MappingFactSource
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
    def first_stop(self) -> tuple[str, str] | None:
        """(rule_id, action) of the first blocked or paused call in an attack step."""
        for s in self.steps:
            if not s.attack_step:
                continue
            for c in s.run.tool_calls:
                if c.status in ("blocked", "paused"):
                    return str(c.decision.get("rule_id")), str(c.decision.get("action"))
        return None

    @property
    def stop_fail_mode(self) -> str | None:
        """fail_mode of the first stop: None for a real rule match, "closed" for a rule error."""
        for s in self.steps:
            if not s.attack_step:
                continue
            for c in s.run.tool_calls:
                if c.status in ("blocked", "paused"):
                    return c.decision.get("fail_mode")
        return None

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
    after_incident: Callable[[IncidentResult], None] | None = None,
) -> list[IncidentResult]:
    """Drive the agents through the demo incidents. Returns one result per incident.

    ``after_incident`` runs after each incident (the gated replay resumes paused agents)."""
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
        if after_incident is not None:
            after_incident(res)
    provider.shutdown()
    return results


def _summary(r: IncidentResult) -> str:
    verdict = "STOPPED" if r.attack_stopped else "EXECUTED"
    actions = ",".join(r.gate_actions) or "-"
    return (
        f"{r.incident_id} attack={verdict} expected_gate={r.expected_gate_action} "
        f"gate_actions=[{actions}] {r.harmful_effect}+{r.harmful_effects_recorded}"
    )


# --------------------------------------------------------------------------- gated (M1)

AGENT_IDS = ("customer_service", "credit_prequal", "payments")
DEMO_REVIEWER = "reviewer.an"  # synthetic reviewer id from policies/baseline.yaml


def world_facts(world: BankWorld) -> MappingFactSource:
    """Gateway fact source over the demo world (stands in for the loan origination system)."""

    def application(key: str) -> Mapping[str, Any] | None:
        app = world.applications.get(key)
        if app is None:
            return None
        return {
            "documents_complete": bool(app.documents_complete),
            "customer_id": app.customer_id,
        }

    return MappingFactSource({"application": application})


@dataclass
class GatedReport:
    results: list[IncidentResult]
    expected: dict[str, str]
    lines: list[str]
    chain_head: str | None
    lanes: dict[str, int]
    registered: list[str]

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(
            r.attack_stopped
            and (r.first_stop or ("", ""))[1] == self.expected[r.incident_id]
            and r.stop_fail_mode is None  # a genuine rule match, not a fail-closed error
            for r in self.results
        )


def run_gated(
    settings: Settings | None = None,
    *,
    adapters: Any = None,
    incident_ids: Sequence[str] | None = None,
    path: Path = DEMO_FILE,
) -> GatedReport:
    """M1 replay: real gateway, real policy, evidence on the chain of the configured store."""
    from supervisor.wiring import build_runtime, register_agents
    from supervisor_agents.common.manifest import load_manifest
    from supervisor_agents.common.runtime import default_system_prompt

    world = BankWorld.build()
    runtime = build_runtime(
        settings, adapters=adapters, facts=world_facts(world), policy_refresh_s=0.0
    )
    lines: list[str] = []
    try:
        manifests = [load_manifest(a) for a in AGENT_IDS]
        register_agents(
            runtime,
            manifests,
            prompt_hashes={m.id: sha256_hex(default_system_prompt(m)) for m in manifests},
        )
        lines.append(
            "[OK] registered agents: " + ", ".join(f"{m.id}@{m.version}" for m in manifests)
        )
        states = runtime.gateway.states

        expected = {
            inc["id"]: str(inc.get("expected_gate_action", "")) for inc in load_demo_incidents(path)
        }

        def after_incident(res: IncidentResult) -> None:
            stop = res.first_stop
            if stop is None:
                lines.append(
                    f"[FAIL] {res.incident_id} EXECUTED "
                    f"gate_actions=[{','.join(res.gate_actions)}] "
                    f"{res.harmful_effect}+{res.harmful_effects_recorded}"
                )
            elif res.stop_fail_mode is not None:
                lines.append(
                    f"[FAIL] {res.incident_id} STOPPED by {stop[0]} only by a rule error "
                    f"(fail_mode={res.stop_fail_mode}), not by a rule match"
                )
            elif stop[1] != expected[res.incident_id]:
                lines.append(
                    f"[FAIL] {res.incident_id} STOPPED by {stop[0]} action={stop[1]} "
                    f"(expected action={expected[res.incident_id]})"
                )
            else:
                lines.append(f"[OK] {res.incident_id} STOPPED by {stop[0]} action={stop[1]}")
            # A rule paused an agent: the normal two-person resume (owner + reviewer).
            for agent_id in AGENT_IDS:
                if states.get_state(agent_id) != "PAUSED":
                    continue
                row = runtime.adapters.state.get("agent", {"agent_id": agent_id})
                reason = f"demo replay: {res.incident_id} reviewed"
                states.resume(agent_id, row["owner_user"], reason)
                states.resume(agent_id, DEMO_REVIEWER, reason)
                lines.append(
                    f"       {agent_id} resumed (demo auto-approval, two-person: "
                    f"owner + {DEMO_REVIEWER})"
                )

        results = replay(
            incident_ids,
            gate=runtime.gateway,
            store=runtime.adapters.tables,
            world=world,
            path=path,
            after_incident=after_incident,
        )
        runtime.gateway.drain()
        # Gate blocks/pauses become cases here, so a fresh database shows cases without the
        # console (the console queue GET does not write).
        from supervisor.cases import build_case_service
        from supervisor.jobs import case_intake

        opened = case_intake.run(build_case_service(runtime))
        lines.append(f"[OK] cases opened: {len(set(opened))}")
        runtime.chain.commit_root()
        heads = runtime.chain.heads()
        root = heads.get("root")
        head = root.entry_hash if root is not None else None
        lanes = {k: v.seq + 1 for k, v in sorted(heads.items())}
        lines.append(f"[OK] chain head {head} (root seq {root.seq if root else '-'}, signed)")
        registered = list(runtime.registered)
    finally:
        runtime.close()
    return GatedReport(results, expected, lines, head, lanes, registered)


def main(argv: Sequence[str] | None = None) -> int:
    from supervisor.bootstrap import bootstrap

    bootstrap()
    parser = argparse.ArgumentParser(prog="python -m supervisor.demo.replay")
    parser.add_argument("--incident", action="append", help="DEMO-1..DEMO-4 (repeatable)")
    parser.add_argument(
        "--store", action="store_true", help="append agent_event rows to the configured store"
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="run behind the real gateway; evidence on the chain of the configured store",
    )
    args = parser.parse_args(argv)
    if args.gate:
        from supervisor.config import load_settings

        report = run_gated(load_settings(), incident_ids=args.incident)
        for line in report.lines:
            print(line)  # noqa: T201
        if not report.results:
            print("[FAIL] no incident matched")  # noqa: T201
        return 0 if report.ok else 1
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
