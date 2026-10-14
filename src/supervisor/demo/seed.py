"""Seed a fresh demo data dir: schema, policy, three agents, a synthetic normal day.

    python -m supervisor.cli demo seed [--data-dir DIR]

Steps (all real code paths; only the agents' LLM output is scripted):

1. wipe the demo data dir (only when it carries the ``.supervisor-demo`` marker or is
   empty) and create a fresh SQLite store (``bootstrap_schema``);
2. deploy ``policies/*.yaml`` to the ``rule`` table;
3. register customer_service, credit_prequal and payments (registry + evidence chain);
4. run the agents' scripted everyday tasks (WP2 ``TASKS``) behind the real gateway, so
   the console has allowed traffic, coverage and chain entries before the incidents.
   [FIXTURE] The task scripts are fixed MockChat outputs over synthetic Vietnamese data;
   every gate decision on them is real;
5. close the runtime (signed root) and take the reset snapshot.

A normal day must stay quiet: every decision allowed, no case. Anything else is a
deviation and fails the seed.
"""

from __future__ import annotations

import importlib
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from supervisor.config import Settings
from supervisor.core.canonical import sha256_hex
from supervisor.core.errors import SupervisorError
from supervisor.demo.session import (
    MARKER,
    Echo,
    build_session,
    default_echo,
    is_demo_dir,
    mark_demo_dir,
)

AGENT_IDS = ("customer_service", "credit_prequal", "payments")

# Scripted tasks that ask for more than the policy allows (the gate stops them; see
# tests/e2e/test_benign_tasks_gated.py). They are not part of a quiet normal day.
NOT_IN_NORMAL_DAY = frozenset({"cs-10", "cs-11", "cp-15", "pay-19"})


class SeedError(SupervisorError):
    """The demo data dir cannot be seeded."""


@dataclass
class SeedReport:
    lines: list[str] = field(default_factory=list)
    ok: bool = True
    tasks: int = 0
    decisions: int = 0
    seconds: float = 0.0

    def fail(self, text: str) -> None:
        self.ok = False
        self.lines.append(f"[FAIL] {text}")


def wipe(data_dir: Path) -> None:
    """Delete the demo data dir. Refuses a non-empty directory without the marker."""
    data_dir = Path(data_dir)
    if data_dir.exists():
        if not data_dir.is_dir():
            raise SeedError(f"demo data dir is a file: {data_dir}")
        if any(data_dir.iterdir()) and not is_demo_dir(data_dir):
            raise SeedError(
                f"refusing to wipe {data_dir}: it is not empty and has no {MARKER} marker. "
                "Pick another --data-dir (default data/local/demo)."
            )
        try:
            shutil.rmtree(data_dir)
        except OSError as exc:
            raise SeedError(
                f"cannot delete {data_dir} ({exc}). Stop the server that uses it first."
            ) from exc
    mark_demo_dir(data_dir)


def seed(settings: Settings, echo: Echo = default_echo, *, snapshot: bool = True) -> SeedReport:
    """Fresh store + policy + agents + normal day + snapshot. Never raises for a deviation;
    raises ``SeedError`` when the data dir cannot be used."""
    from supervisor.adapters.llm.mock import MockChat
    from supervisor.demo import reset
    from supervisor.wiring import register_agents
    from supervisor_agents.common.manifest import load_manifest
    from supervisor_agents.common.runtime import default_system_prompt
    from supervisor_agents.common.tasks import run_task
    from supervisor_agents.common.tracing import AgentEventExporter, make_tracer_provider

    t0 = time.perf_counter()
    rep = SeedReport()

    def say(line: str) -> None:
        rep.lines.append(line)
        echo(line)

    data_dir = Path(settings.data_dir)
    wipe(data_dir)
    session = build_session(settings)
    try:
        rt = session.runtime
        say(f"[OK] seed: fresh SQLite store {settings.sqlite_path}")
        say(
            f"[OK] policy deployed: {len(rt.policy.doc.rules)} rules, "
            f"hash {rt.policy.policy_hash[:16]}..."
        )
        manifests = [load_manifest(a) for a in AGENT_IDS]
        register_agents(
            rt,
            manifests,
            prompt_hashes={m.id: sha256_hex(default_system_prompt(m)) for m in manifests},
        )
        say("[OK] agents registered: " + ", ".join(f"{m.id}@{m.version}" for m in manifests))

        exporter = AgentEventExporter(rt.adapters.tables, env="demo")
        provider = make_tracer_provider(exporter, service_name="supervisor-demo-seed")
        chat = MockChat(seed=1, model_id="mock-agent-script")
        stopped: list[str] = []
        problems: list[str] = []
        for agent_id in AGENT_IDS:
            mod = importlib.import_module(f"supervisor_agents.{agent_id}.agent")
            tasks = importlib.import_module(f"supervisor_agents.{agent_id}.tasks").TASKS
            agent = mod.build_agent(
                chat, session.world, gate=rt.gateway, tracer_provider=provider, env="demo"
            )
            for task in tasks:
                if task.task_id in NOT_IN_NORMAL_DAY:
                    continue
                out = run_task(agent, chat, session.world, task)
                rep.tasks += 1
                rep.decisions += len(out.result.tool_calls)
                denied = [c for c in out.result.tool_calls if not c.decision.get("allow")]
                if denied:
                    stopped.append(f"{task.task_id}:{denied[0].decision.get('rule_id')}")
                elif not out.passed:
                    problems.append(f"{task.task_id}: {'; '.join(out.problems)}")
        provider.shutdown()
        rt.gateway.drain()
        touched = session.cases.sync_gate_cases()
        if stopped or problems or touched:
            rep.fail(
                f"normal day was not quiet: stopped={stopped} problems={problems} "
                f"cases={sorted(set(touched))}"
            )
        else:
            say(
                f"[OK] normal day: {rep.tasks} scripted tasks, {rep.decisions} gate "
                "decisions, all allowed, 0 cases"
            )
            say(
                "       [FIXTURE] agent LLM output is scripted (MockChat) over synthetic "
                "Vietnamese data; the gate decisions are real"
            )
    finally:
        session.close()  # seals the chain with a signed root
    if rep.ok and snapshot:
        facts = reset.snapshot(settings, echo=lambda _line: None)
        say(
            f"[OK] reset snapshot taken (chain entries {facts['chain_entries']}, "
            f"root {str(facts['root_head'])[:16]}...)"
        )
    rep.seconds = time.perf_counter() - t0
    for line in rep.lines:
        if line.startswith("[FAIL]"):
            echo(line)
    return rep


__all__ = ["AGENT_IDS", "NOT_IN_NORMAL_DAY", "SeedError", "SeedReport", "seed", "wipe"]
