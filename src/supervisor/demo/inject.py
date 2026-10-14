"""Inject one demo incident (1..4) through the real agents and the real gateway.

    python -m supervisor.cli demo inject 1 [--data-dir DIR] [--auto-resume] [--replay]

What is real and what is scripted:

* [FIXTURE] the agent's LLM output (``agents/redteam/demo_incidents.yaml``, MockChat):
  an injection payload does not reliably trigger a model on stage, so the harmful tool
  call is replayed as the agent's output;
* real: the tool router, the gateway rule that blocks or pauses the call, the pause of
  the agent (read back from the store), the evidence chain, the case that the console
  case service opens (the same ``CaseService`` the console uses);
* the judge (DEMO-2 only) is advisory. With no judge model configured it is the
  deterministic MockJudge, labelled ``MOCK`` here and in the console. With ``--replay``
  a judge call that fails or takes more than 20 s is replaced by its recorded twin,
  labelled ``[REPLAY]`` on every line.

Paused agents stay paused (resume in the console: owner + reviewer). ``--auto-resume``
does the same two-person resume from the command line (the runbook uses it between
incidents) and says so.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.demo import fallback
from supervisor.demo.session import DemoSession, Echo, default_echo

INCIDENTS = {1: "DEMO-1", 2: "DEMO-2", 3: "DEMO-3", 4: "DEMO-4"}
JUDGE_INCIDENTS = frozenset({"DEMO-2"})  # the judge beat of the demo (advisory)
DEMO_REVIEWER = "reviewer.an"  # synthetic reviewer id in policies/baseline.yaml


@dataclass
class InjectReport:
    incident_id: str
    lines: list[str] = field(default_factory=list)
    ok: bool = True
    replayed: list[str] = field(default_factory=list)
    case_ids: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def fail(self, text: str) -> None:
        self.ok = False
        self.lines.append(f"[FAIL] {text}")


def incident_id(n: int | str) -> str:
    if isinstance(n, str) and n.upper().startswith("DEMO-"):
        n = n.split("-", 1)[1]
    try:
        return INCIDENTS[int(n)]
    except (KeyError, ValueError):
        raise ValueError(f"unknown incident {n!r}: use 1, 2, 3 or 4") from None


def _incident(inc_id: str) -> dict[str, Any]:
    from supervisor.demo.replay import load_demo_incidents

    for inc in load_demo_incidents():
        if inc["id"] == inc_id:
            return inc
    raise ValueError(f"{inc_id} is not in agents/redteam/demo_incidents.yaml")


def _gate_state(session: DemoSession, agent_id: str) -> str | None:
    row = session.state.get("agent", {"agent_id": agent_id})
    return None if row is None else str(row["gate_state"])


def inject(
    session: DemoSession,
    n: int | str,
    *,
    echo: Echo = default_echo,
    auto_resume: bool = False,
    replay: bool = False,
    deadline_s: float = fallback.DEFAULT_DEADLINE_S,
    replay_dir: Path | None = None,
) -> InjectReport:
    """Run one incident on an open demo session. Never raises for a deviation."""
    from supervisor.demo.replay import replay as run_replay

    t0 = time.perf_counter()
    inc_id = incident_id(n)
    inc = _incident(inc_id)
    rep = InjectReport(inc_id)
    expected = str(inc.get("expected_gate_action", ""))
    agents = sorted({s["agent"] for s in inc["steps"]})

    def say(line: str) -> None:
        rep.lines.append(line)
        echo(line)

    def fail(text: str) -> None:
        rep.fail(text)
        echo(rep.lines[-1])

    say(f"== {inc_id}: {inc['title']}")
    say("       [FIXTURE] agent LLM output is scripted (MockChat); gate, pause, chain are live")
    for agent_id in agents:
        state = _gate_state(session, agent_id)
        if state is None:
            fail(f"{agent_id} is not registered. Fix: python -m supervisor.cli demo seed")
            return rep
        if state != "RUNNING":
            fail(
                f"{agent_id} is {state}; the incident would be stopped by that state, not "
                "by its rule. Fix: resume it in the console (owner + reviewer), press r in "
                "demo serve, or add --auto-resume"
            )
            return rep

    cases_before = {c["case_id"] for c in session.cases.list_cases()}
    results = run_replay(
        [inc_id], gate=session.gateway, store=session.tables, world=session.world, env="demo"
    )
    session.gateway.drain()
    if not results:
        fail(f"{inc_id}: no result from the replay")
        return rep
    res = results[0]
    stop = res.first_stop
    if stop is None:
        fail(
            f"{inc_id} attack EXECUTED: gate actions [{','.join(res.gate_actions)}] "
            f"{res.harmful_effect}+{res.harmful_effects_recorded}"
        )
        return rep
    rule_id, action = stop
    if res.stop_fail_mode is not None:
        fail(
            f"{inc_id} stopped by {rule_id} only through a rule error "
            f"(fail_mode={res.stop_fail_mode}), not a rule match"
        )
        return rep
    if action != expected:
        fail(f"{inc_id} stopped by {rule_id} action={action}, expected action={expected}")
        return rep
    attack_agent = next(s.agent for s in res.steps if s.attack_step)
    verb = "PAUSED" if action == "pause" else "BLOCKED"
    say(f"[OK] gate {verb} {attack_agent} tool call: rule {rule_id} (real rule match)")
    say(f"       harm recorded: {res.harmful_effect} +{res.harmful_effects_recorded}")

    if action == "pause":
        state = _gate_state(session, attack_agent)
        if state != "PAUSED":
            fail(f"{attack_agent} gate_state is {state} after a pause rule, expected PAUSED")
            return rep
        say(f"[OK] {attack_agent} gate_state=PAUSED (read back from the store)")
        say("       console: Agents page /console/agents shows PAUSED; resume needs two people")

    if inc_id in JUDGE_INCIDENTS:
        trace_ids = [s.run.trace_id for s in res.steps if s.attack_step]
        _judge_step(session, inc_id, trace_ids, rep, say, fail, replay, deadline_s, replay_dir)

    touched = session.cases.sync_gate_cases()
    new_cases = [c for c in session.cases.list_cases() if c["case_id"] not in cases_before] or [
        session.cases.get(cid) for cid in dict.fromkeys(touched)
    ]
    if not new_cases:
        fail(f"{inc_id}: no case opened or joined for the {action}")
        return rep
    for c in new_cases:
        rep.case_ids.append(c["case_id"])
        say(
            f"[OK] case {c['case_id']} {c['severity']} {c['status']} agent={c['agent_id']}: "
            f"{c['summary'][:90]}"
        )
        say(f"       console: Queue /console/ and Case /console/cases/{c['case_id']}")

    if auto_resume:
        for agent_id in agents:
            if _gate_state(session, agent_id) != "PAUSED":
                continue
            owner = session.state.get("agent", {"agent_id": agent_id})["owner_user"]
            reason = f"demo runbook: {inc_id} reviewed"
            session.gateway.states.resume(agent_id, owner, reason)
            session.gateway.states.resume(agent_id, DEMO_REVIEWER, reason)
            if _gate_state(session, agent_id) != "RUNNING":
                fail(f"{agent_id}: two-person resume did not return it to RUNNING")
                return rep
            say(
                f"[OK] {agent_id} resumed by two people (owner + {DEMO_REVIEWER}); "
                "[DEMO] auto-approval from the runbook, recorded on the chain"
            )
    rep.seconds = time.perf_counter() - t0
    return rep


def _judge_step(
    session: DemoSession,
    inc_id: str,
    trace_ids: Sequence[str],
    rep: InjectReport,
    say: Any,
    fail: Any,
    replay: bool,
    deadline_s: float,
    replay_dir: Path | None,
) -> None:
    """Advisory judge on the attack trace. Opens or raises a case; never touches the gate."""
    step = f"judge-{inc_id}"

    def run() -> list[str]:
        from supervisor.judge.service import JudgeService

        judge = JudgeService.from_settings(
            session.settings,
            session.runtime.adapters.clock,
            masker=session.cases.masker,
            tables=session.tables,
            evidence=session.runtime.chain,
            state=session.state,
            force=True,  # the demo shows the judge beat; JUDGE_ENABLED stays off for serve
            case_sink=session.cases.open_from_case_request,
        )
        assert judge is not None
        lines: list[str] = []
        for trace_id in trace_ids:
            out = judge.evaluate_trace_id(trace_id)
            for call in (out.t1, out.t2):
                if call is None:
                    continue
                tag = "MOCK" if call.is_mock else "model"
                score = "-" if call.suspicion_bp is None else f"{call.suspicion_bp} bp"
                lines.append(
                    f"[OK] judge tier {call.tier} ({tag} {call.model_id}): suspicion {score}, "
                    f"label {call.label or '-'} (advisory)"
                )
            lines.append(
                f"[OK] judge outcome: {out.final_action} ({out.final_label}); "
                f"{len(out.case_requests)} case request(s) to the case service; "
                "the judge never calls the gate"
            )
        return lines

    got = fallback.run_with_deadline(run, deadline_s)
    if got.ok:
        for line in got.value:
            say(line)
        return
    reason = got.error or "failed"
    if not replay:
        fail(f"judge step {step}: {reason}. Fallback: rerun with --replay")
        return
    twin = fallback.load_twin(step, replay_dir)
    if twin is None:
        fail(f"judge step {step}: {reason}; no recorded twin in {fallback.REPLAY_DIR}")
        return
    say(f"{fallback.REPLAY_TAG} judge step {step} live call: {reason}; switching to replay")
    for line in fallback.replay_lines(twin):
        say(line)
    rep.replayed.append(step)


__all__ = ["INCIDENTS", "JUDGE_INCIDENTS", "InjectReport", "incident_id", "inject"]
