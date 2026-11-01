# ruff: noqa: E501
"""Showcase scenario for the Stability tab (W8): normal traffic, then a shift (a drift case).

    python -m supervisor.demo.showcase drift prepare  [--system SYS] [--agent ID]
    python -m supervisor.demo.showcase drift baseline [--windows N] [--seed S]
    python -m supervisor.demo.showcase drift shift    [--windows N] [--live] [--seed S]
    python -m supervisor.demo.showcase drift run      (baseline and shift in one go, in the past)
    python -m supervisor.demo.showcase drift status

The presenter sees the Stability tab go from Stable, to Watch, to Unstable, with a drift case open.

* ``prepare``   adds the agent to the registry when it is not there (the same helper as the
  journeys), links it to the AI system, and moves it SHADOW to RUNNING with two persons.
* ``baseline``  sends normal traffic (``--windows`` windows, default 9) and runs the drift check.
  The first 7 windows build the normal range; the next ones are inside it: Stable.
* ``shift``     sends the changed traffic (default 5 windows): larger payments, one tool used far
  more, more blocked calls with an injection text, one pause per window. ``--live`` sends it in
  real time so the lines move on the page; without it the windows are written in the past, ending
  now.
* ``run``       baseline then shift, both in the past (a quick way to fill a fresh store).

Every call goes through the REAL gate of this process (``gateway.check``): the rules decide, the
detectors report, the gate writes its own rows. No ``agent_event`` or metric row is ever inserted
here. Only the clock differs in the past modes: the gate is built with a stepped clock so that
the rows it writes carry a time in the past (a demo clock, not a changed row). The drift check is
the product's own ``DriftMonitor``; a case opens by the product's own rule (M windows in a row).

The window length is ``DRIFT_WINDOW_S`` (the product setting, at least 60). For the demo run the
command with ``DRIFT_WINDOW_S=60 DRIFT_SETTLE_S=5``; with the default one-day window nothing can
happen in minutes and the command says so. Needs ``SHOWCASE_ENABLED=1``. Synthetic data only.
ASCII output."""

from __future__ import annotations

import argparse
import datetime as dt
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from supervisor.demo import showcase_journeys as sj
from supervisor.demo import showcase_traffic as st

CID = "payment-ops-copilot"
SYSTEM_NAME = "payment-ops-copilot"
MIN_DEMO_WINDOW_S = 10
MAX_DEMO_WINDOW_S = 3600
BASELINE_WINDOWS = 9  # 7 build the normal range, 2 are checked against it
SHORT_SHIFT_WINDOWS = 4  # with a window under a minute
SHIFT_WINDOWS = 5  # the 3 breaches in a row that open a case, and a little more
LIVE_DRIFT_EVERY_S = 5


@dataclass(frozen=True)
class Profile:
    """One window of traffic: how many calls of each tool and what happens to the transfers."""

    name: str
    reconcile: int
    add_payee: int
    transfer: int
    t_paused: int  # transfers above the pause line (the agent is paused, then resumed)
    t_blocked: int  # transfers above the block line, with an injection text
    allowed: tuple[int, ...]  # amounts of the transfers that pass (minor units = VND)
    paused: tuple[int, ...]
    blocked: tuple[int, ...]

    @property
    def total(self) -> int:
        return self.reconcile + self.add_payee + self.transfer


NORMAL = Profile(
    "normal",
    reconcile=24,
    add_payee=6,
    transfer=30,
    t_paused=0,
    t_blocked=0,
    allowed=(1_000_000, 2_500_000, 5_000_000, 8_000_000, 12_000_000),
    paused=(25_000_000,),
    blocked=(120_000_000, 150_000_000),
)
SHIFT = Profile(
    "shift",
    reconcile=6,
    add_payee=6,
    transfer=48,
    t_paused=2,
    t_blocked=8,
    allowed=(15_000_000, 16_500_000, 18_000_000, 19_000_000, 19_900_000),
    paused=(30_000_000, 45_000_000, 60_000_000),
    blocked=(150_000_000, 180_000_000, 250_000_000),
)


# ----------------------------------------------------------------------------- the calls


def plan_window(p: Profile, rng: random.Random) -> list[tuple[str, str, int]]:
    """The (tool, outcome, amount) of every call of one window. The counts and the set of amounts
    are exact (the amounts cycle through the profile), only the order is shuffled by the seed, so
    a quiet window looks like the one before it and a run is repeatable."""
    plan: list[tuple[str, str]] = [("reconcile", "allowed")] * p.reconcile
    plan += [("add_payee", "masked")] * p.add_payee
    plan += [("transfer", "paused")] * p.t_paused
    plan += [("transfer", "blocked")] * p.t_blocked
    plan += [("transfer", "allowed")] * (p.transfer - p.t_paused - p.t_blocked)
    rng.shuffle(plan)
    pools = {"allowed": p.allowed, "paused": p.paused, "blocked": p.blocked}
    used = dict.fromkeys(pools, 0)
    out: list[tuple[str, str, int]] = []
    for tool, outcome in plan:
        amount = 0
        if tool == "transfer":
            pool = pools[outcome]
            amount = pool[used[outcome] % len(pool)]
            used[outcome] += 1
        out.append((tool, outcome, amount))
    return out


def build(tool: str, outcome: str, amount: int, rng: random.Random, n: int) -> st.Call:
    """One synthetic call. Ids carry ``n`` so the per-account counters never trip by accident."""
    acct, cust = f"ACC{n:07d}", f"CUS{n:07d}"
    if tool == "reconcile":
        return "reconcile", {"statement_id": f"STM{n:07d}", "period": "2026-10"}
    if tool == "add_payee":
        return "add_payee", {
            "customer_id": cust,
            "payee_name": rng.choice(st.FIRST),
            "account_number": st.account(rng),
            "phone": st.phone(rng),
            "cccd": st.cccd(rng),
        }
    args: dict[str, Any] = {
        "amount_minor": amount,
        "from_account_id": acct,
        "payee_id": f"PAY{n:07d}",
    }
    if outcome == "blocked":
        args["memo"] = rng.choice(st.INJECTIONS)
    return "transfer", args


# ----------------------------------------------------------------------------- the rig


def open_rig(settings: Any, clock: Any | None) -> sj.Rig:
    """The rig of the showcase, with a stepped clock for the past modes (None = the real clock)."""
    from supervisor.adapters.factory import build_adapters
    from supervisor.console.context import build_context
    from supervisor.jobs import bootstrap_schema
    from supervisor.wiring import build_runtime

    adapters = build_adapters(settings, clock=clock)
    if adapters.executor.dialect == "sqlite":
        bootstrap_schema.run(settings, adapters)
    runtime = build_runtime(settings, adapters=adapters, policy_refresh_s=0.0)
    ctx = build_context(runtime)

    def close() -> None:
        try:
            retry_chain(runtime.close)  # the seal may meet the console's own chain writes
        except Exception as exc:  # noqa: BLE001 - the demo data is written; do not fail the run
            print(f"[SKIP] chain seal not written: {type(exc).__name__}", flush=True)
        adapters.close()

    return sj.Rig(settings, adapters, runtime, ctx, None, close)


def prepare(rig: sj.Rig, system_id: str, say: Callable[[str], None]) -> None:
    """The agent in the registry, linked to the system, RUNNING."""
    from supervisor.demo.seed_systems import Manifest, _ensure_agent

    cand = sj.CANDIDATES[CID]
    m = Manifest(
        system={"owner_team": cand.owner_team, "owner_user": cand.owner_user},
        agent_id=CID,
        agent_name=cand.title,
        model_family=cand.model_family,
        plug_point=cand.plug_point,
        tools=cand.tools,
        path=Path(CID),
    )
    say(
        f"[OK] agent {CID} registered (gate SHADOW)"
        if _ensure_agent(rig.runtime, m)
        else f"[OK] agent {CID} already registered"
    )
    if system_id:
        if rig.ctx.state.get("ai_system", {"system_id": system_id}) is None:
            raise sj.ShowcaseError(f"no_system: {system_id} does not exist")
        if not rig.ctx.state.query("system_component", {"system_id": system_id, "ref_id": CID}):
            rig.ctx.systems.link(system_id, "agent", CID, sj.DECIDER, for_user=sj.me())
            say(f"[OK] agent linked to {system_id}")
        else:
            say(f"[OK] agent already linked to {system_id}")
    row = rig.ctx.state.get("agent", {"agent_id": CID})
    if row["gate_state"] == "SHADOW":
        states = rig.runtime.gateway.states
        for who, why in (
            (sj.DECIDER, "showcase: shadow run looked clean"),
            (sj.APPROVER, "approved"),
        ):
            states.change_mode(
                CID, "RUNNING", who, why, auth_method="dev_header", actor_kind="user"
            )
        say(
            f"[OK] agent {CID}: SHADOW -> RUNNING (asked by {sj.DECIDER}, approved by {sj.APPROVER})"
        )
    say(f"[OK] gate state: {rig.ctx.state.get('agent', {'agent_id': CID})['gate_state']}")


def drift_config(settings: Any) -> Any:
    from supervisor.monitors.drift import DriftConfig

    return DriftConfig.from_settings(settings)


def run_drift(rig: sj.Rig, settings: Any, now: dt.datetime) -> Any:
    """The product's own drift check, with ``now`` as its time."""
    from supervisor.monitors.bindings import BindingResolver
    from supervisor.monitors.common import MonitorContext
    from supervisor.monitors.drift import DriftMonitor

    ctx = MonitorContext.from_adapters(rig.adapters, rig.runtime.chain)
    resolver = BindingResolver.from_settings(settings, ctx.state)
    return DriftMonitor(ctx, drift_config(settings), resolver).run(now)


# ----------------------------------------------------------------------------- the traffic


def resume(rig: sj.Rig) -> bool:
    """The two-person resume by the synthetic owner and reviewer. Each step is retried on its own
    when the console wrote the chain in between; an approval that is already there is kept."""
    from supervisor.gateway.state import TransitionError

    row = rig.ctx.state.get("agent", {"agent_id": CID})
    if row is None or row["gate_state"] != "PAUSED":
        return False
    for who in (str(row["owner_user"]), sj.DECIDER):
        try:
            retry_chain(
                lambda who=who: rig.runtime.gateway.states.resume(
                    CID, who, "showcase drift: resume after pause"
                )
            )
        except TransitionError as exc:
            if "already approved" not in str(exc):
                raise
    return True


def retry_chain(fn: Callable[[], Any]) -> Any:
    """Run ``fn``; when another process wrote the chain in between (the console of the demo does
    its own writes), the writer forgets its head, so one more try succeeds."""
    from supervisor.evidence.chain import ChainConflictError

    try:
        return fn()
    except ChainConflictError:
        return fn()


@dataclass
class Sent:
    calls: int = 0
    stopped: int = 0
    resumes: int = 0
    next_n: int = 1


def send_window(
    rig: sj.Rig,
    p: Profile,
    rng: random.Random,
    sent: Sent,
    *,
    on_call: Callable[[], None],
) -> None:
    """One window of calls through the gate. A pause is resumed by the synthetic owner and
    reviewer (the rule of the product stays as it is)."""
    gate = rig.runtime.gateway.check
    for tool, outcome, amount in plan_window(p, rng):
        name, args = build(tool, outcome, amount, rng, sent.next_n)
        sent.next_n += 1
        res = gate(CID, "1", name, args, {"source": sj.TAG})
        sent.calls += 1
        if st.kind_of(res) in ("blocked", "paused"):
            sent.stopped += 1
        if st.agent_paused(res) and resume(rig):
            sent.resumes += 1
        on_call()


def window_start(now: dt.datetime, window_s: int) -> dt.datetime:
    from supervisor.monitors.common import floor_window

    return floor_window(now, window_s)


def last_event_ts(rig: sj.Rig) -> dt.datetime | None:
    rows = rig.adapters.tables.query("agent_event", {"agent_id": CID}, order_by=("-ts",), limit=1)
    if not rows:
        return None
    from supervisor.monitors.common import as_dt

    return as_dt(rows[0]["ts"])


def past_phase(
    settings: Any,
    phases: list[tuple[Profile, int]],
    *,
    seed: int,
    system_id: str,
    say: Callable[[str], None],
) -> Sent:
    """Write the phases in the past, ending at the last whole window before now, then run the
    drift check once at the end."""
    from supervisor.adapters.clock import FixedClock

    window_s = int(settings.drift_window_s)
    total_windows = sum(n for _, n in phases)
    now = dt.datetime.now(dt.UTC)
    end = window_start(now, window_s)
    start = end - dt.timedelta(seconds=window_s * total_windows)
    clock = FixedClock(start)
    rig = open_rig(settings, clock)
    try:
        prepare(rig, system_id, say)
        last = last_event_ts(rig)
        if last is not None and last >= start:
            raise sj.ShowcaseError(
                "traffic_exists: the agent already has calls in that period; "
                "use --live for the shift, or start with a fresh copy of the data"
            )
        rng = random.Random(seed)  # noqa: S311 - synthetic traffic, not a secret
        sent = Sent()
        for profile, n in phases:
            gap = window_s / profile.total

            def on_call(gap: float = gap) -> None:
                clock.advance(gap)  # the next call is one gap later; a window ends on its edge

            for _ in range(n):
                send_window(rig, profile, rng, sent, on_call=on_call)
            say(
                f"[OK] {profile.name}: {n} windows of {window_s} s written "
                f"(calls so far {sent.calls})"
            )
        settle = int(getattr(settings, "drift_settle_s", 600))
        drift_now = max(clock.now(), end) + dt.timedelta(seconds=settle + 1)
        clock.advance(max(0.0, (drift_now - clock.now()).total_seconds()))
        res = retry_chain(lambda: run_drift(rig, settings, drift_now))
        say(
            f"[OK] drift check: baselines {len(res.baselines_built)}, windows {res.windows_checked}, "
            f"cases opened {len(res.cases_opened)}"
        )
        return sent
    finally:
        rig.close()


def live_phase(
    settings: Any,
    profile: Profile,
    windows: int,
    *,
    seed: int,
    system_id: str,
    say: Callable[[str], None],
    sleep: Callable[[float], None] = time.sleep,
) -> Sent:
    """Send ``windows`` windows of calls in real time at a steady rate and run the drift check as
    each real window edge passes (plus the settle time). The rate is ``profile.total`` calls per
    window, so every drift window gets the same number of calls, whatever the first one is. The
    start waits for the next edge only when that is a short wait (less than half a window)."""
    window_s = int(settings.drift_window_s)
    settle = int(getattr(settings, "drift_settle_s", 600))
    rig = open_rig(settings, None)
    try:
        prepare(rig, system_id, say)
        rng = random.Random(seed)  # noqa: S311 - synthetic traffic, not a secret
        sent = Sent()
        pace = window_s / profile.total
        now = dt.datetime.now(dt.UTC)
        edge = window_start(now, window_s) + dt.timedelta(seconds=window_s)
        wait = (edge - now).total_seconds()
        if wait < window_s / 2:
            say(f"[OK] waiting {wait:.0f} s for the next window edge")
            sleep(max(0.0, wait))
            now = dt.datetime.now(dt.UTC)
        say(f"[OK] sending {windows} windows of {window_s} s ({profile.total} calls each)")
        first_edge = window_start(dt.datetime.now(dt.UTC), window_s) + dt.timedelta(
            seconds=window_s
        )
        check_at = [first_edge + dt.timedelta(seconds=settle + 1)]
        clock = {"t0": time.monotonic(), "k": 0}

        def check_due() -> None:
            t = dt.datetime.now(dt.UTC)
            while check_at and check_at[0] <= t:
                check_at[0] += dt.timedelta(seconds=window_s)
                at = t
                try:
                    res = retry_chain(lambda at=at: run_drift(rig, settings, at))
                except Exception as exc:  # noqa: BLE001 - the next window checks again
                    say(f"[SKIP] drift check failed: {type(exc).__name__}")
                    continue
                say(
                    f"     drift check: windows {res.windows_checked}, cases opened {len(res.cases_opened)}"
                )

        def on_call() -> None:
            clock["k"] += 1  # a steady rate: the next call is due one pace after the last was due
            sleep(max(0.0, clock["t0"] + clock["k"] * pace - time.monotonic()))
            check_due()

        for w in range(windows):
            send_window(rig, profile, rng, sent, on_call=on_call)
            say(
                f"[OK] window {w + 1} of {windows} sent ({sent.calls} calls, {sent.stopped} stopped)"
            )
        end_edge = window_start(dt.datetime.now(dt.UTC), window_s) + dt.timedelta(seconds=window_s)
        last_check = end_edge + dt.timedelta(seconds=settle + 1)
        while check_at and check_at[0] <= last_check:
            wait = (check_at[0] - dt.datetime.now(dt.UTC)).total_seconds()
            sleep(max(0.0, wait))
            check_due()
        return sent
    finally:
        rig.close()


# ----------------------------------------------------------------------------- status


def status_lines(settings: Any) -> list[str]:
    rig = open_rig(settings, None)
    try:
        state = rig.ctx.state
        out = []
        agent = state.get("agent", {"agent_id": CID})
        out.append(f"agent {CID}: {agent['gate_state'] if agent else 'not registered'}")
        bands = state.query("policy_baseline", {"agent_id": CID})
        out.append(f"normal range: {len(bands)} measures")
        for b in sorted(bands, key=lambda r: r["metric"]):
            out.append(
                f"     {b['metric']:24} {b['band_low']:>12} .. {b['band_high']:<12} "
                f"streak {b['breach_streak']}"
            )
        cases = [
            c for c in state.query("cases", {"agent_id": CID}) if c.get("case_type") == "drift"
        ]
        out.append(
            f"drift cases: {len(cases)} ({sum(1 for c in cases if c['status'] != 'closed')} open)"
        )
        return out
    finally:
        rig.close()


# ----------------------------------------------------------------------------- command line


def shift_windows(settings: Any) -> int:
    """How many shifted windows: four short ones are enough to show Unstable on a short window."""
    return SHIFT_WINDOWS if int(settings.drift_window_s) >= 60 else SHORT_SHIFT_WINDOWS


def check_window(settings: Any) -> str:
    w = int(settings.drift_window_s)
    if w > MAX_DEMO_WINDOW_S or w < MIN_DEMO_WINDOW_S:
        return (
            f"drift_window_off: DRIFT_WINDOW_S is {w} s. For this demo set DRIFT_WINDOW_S=10 and "
            "DRIFT_SETTLE_S=2 in the environment of this command"
        )
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="showcase drift", description="Stability tab demo scenario")
    ap.add_argument("action", choices=("prepare", "baseline", "shift", "run", "status"))
    ap.add_argument("--system", default="", help="AI system id to link the agent to")
    ap.add_argument("--windows", type=int, default=0, help="number of windows (default per phase)")
    ap.add_argument("--live", action="store_true", help="send the shift in real time")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    from supervisor.config import load_settings

    def say(text: str) -> None:
        print(text, flush=True)

    try:
        settings = load_settings()
        if not sj.enabled(settings):
            raise sj.ShowcaseError(
                "showcase_off: the showcase is off (SHOWCASE_ENABLED=1 turns it on)"
            )
        if args.action == "status":
            for line in status_lines(settings):
                say(line)
            return 0
        if args.action == "prepare":
            rig = open_rig(settings, None)
            try:
                prepare(rig, args.system, say)
            finally:
                rig.close()
            return 0
        problem = check_window(settings)
        if problem:
            raise sj.ShowcaseError(problem)
        if args.windows < 0:
            raise sj.ShowcaseError("windows_bad: --windows must be 0 or more")
        if args.action == "baseline":
            sent = past_phase(
                settings,
                [(NORMAL, args.windows or BASELINE_WINDOWS)],
                seed=args.seed,
                system_id=args.system,
                say=say,
            )
        elif args.action == "run":
            sent = past_phase(
                settings,
                [(NORMAL, BASELINE_WINDOWS), (SHIFT, args.windows or shift_windows(settings))],
                seed=args.seed,
                system_id=args.system,
                say=say,
            )
        elif args.live:
            sent = live_phase(
                settings,
                SHIFT,
                args.windows or shift_windows(settings),
                seed=args.seed + 1,
                system_id=args.system,
                say=say,
            )
        else:
            sent = past_phase(
                settings,
                [(SHIFT, args.windows or shift_windows(settings))],
                seed=args.seed + 1,
                system_id=args.system,
                say=say,
            )
        say(
            f"[OK] {sent.calls} calls through the gate, {sent.stopped} stopped, {sent.resumes} resumes"
        )
        say(
            f"     open: {sj.DEFAULT_CONSOLE}/console/systems/{args.system or '<system id>'}?tab=stability"
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - one clean line
        say(f"[FAIL] {type(exc).__name__}: {exc}")
        return 2 if isinstance(exc, sj.ShowcaseError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
