"""The demo runbook: seed -> 4 incidents -> tamper test -> reset, with [OK]/[FAIL] lines.

    python -m supervisor.cli demo                      # one full run
    python -m supervisor.cli demo --loop 20            # 20 runs, pass count + timings
    python -m supervisor.cli demo --replay             # recorded twins for model steps
    python -m supervisor.cli demo seed | seed-systems | inject N | tamper | reset | serve

Exit code 0 only when every step of every run matched the expected outcome.

Run 1 seeds a fresh demo data dir (default ``data/local/demo``) and takes the reset
snapshot. Every run ends with a reset to that snapshot and a check of the restored
store; run 2..N start from it, which proves the reset as well. ``--fresh-each`` seeds
again every run.

Honesty rules (CLAUDE.md, analysis 04): the gate block, the pause and the chain break are
always live. ``--replay`` only replaces a step that calls a model (the judge on DEMO-2,
onboarding when WP9 is present) when it fails or is not done after 20 s, and labels
every replayed line ``[REPLAY]``. Fixtures (scripted agent output, synthetic data, mock
judges) are labelled where they appear.
"""

from __future__ import annotations

import argparse
import importlib.util
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from supervisor.config import Settings
from supervisor.core.errors import SupervisorError
from supervisor.demo import fallback
from supervisor.demo.session import (
    Echo,
    ascii_line,
    build_session,
    default_echo,
    demo_settings,
    resolve_data_dir,
)

OPTIONAL_PACKAGES = (
    ("supervisor.onboard", "WP9 onboarding (run with --onboard)"),
    ("supervisor.monitors", "WP7 monitors (drift / fairness beat)"),
)


@dataclass
class RunReport:
    index: int
    lines: list[str] = field(default_factory=list)
    ok: bool = True
    replayed: list[str] = field(default_factory=list)
    seconds: float = 0.0
    step_seconds: dict[str, float] = field(default_factory=dict)


@dataclass
class LoopReport:
    runs: list[RunReport] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.runs if r.ok)

    @property
    def ok(self) -> bool:
        return bool(self.runs) and self.passed == len(self.runs)

    @property
    def total_seconds(self) -> float:
        return sum(r.seconds for r in self.runs)


def module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def optional_lines() -> list[str]:
    out = []
    for mod, what in OPTIONAL_PACKAGES:
        if module_present(mod):
            out.append(f"[SKIP] {what}: package {mod} present; not part of this runbook run")
        else:
            out.append(f"[SKIP] {what}: package {mod} not installed in this build")
    return out


def onboard_step(
    settings: Settings,
    echo: Echo,
    *,
    replay: bool,
    deadline_s: float,
    replay_dir: Path | None = None,
) -> tuple[bool, list[str], bool]:
    """Optional onboarding beat (WP9). Returns (ok, lines, replayed).

    Feature-detected: without ``supervisor.onboard.run.run_onboarding`` it is a [SKIP]."""
    step = "onboard-credit_prequal"
    lines: list[str] = []
    if not module_present("supervisor.onboard.run"):
        lines.append("[SKIP] onboard: supervisor.onboard is not in this build (WP9)")
        return True, lines, False

    def run() -> list[str]:
        from supervisor.adapters.llm.mock import MockChat
        from supervisor.config import REPO_ROOT
        from supervisor.onboard.run import run_onboarding

        out = Path(settings.data_dir) / "onboard" / "credit_prequal"
        got: list[str] = []
        run_onboarding(
            REPO_ROOT / "src" / "supervisor_agents" / "credit_prequal",
            out,
            settings=settings,
            chat=MockChat(model_id="mock-onboarding-v1"),
            echo=got.append,
        )
        return [*got, f"[OK] onboard artefacts in {out} (MOCK model)"]

    res = fallback.run_with_deadline(run, deadline_s)
    if res.ok:
        return True, list(res.value), False
    if replay:
        twin = fallback.load_twin(step, replay_dir)
        if twin is not None:
            lines.append(f"{fallback.REPLAY_TAG} onboard live run: {res.error}; using the twin")
            lines.extend(fallback.replay_lines(twin))
            return True, lines, True
    lines.append(f"[FAIL] onboard: {res.error}. Fallback: --replay (needs a recorded twin)")
    return False, lines, False


def run_once(
    settings: Settings,
    index: int = 1,
    *,
    echo: Echo = default_echo,
    seed_first: bool = True,
    replay: bool = False,
    deadline_s: float = fallback.DEFAULT_DEADLINE_S,
    onboard: bool = False,
    replay_dir: Path | None = None,
    record: bool = False,
) -> RunReport:
    """One full run. Never raises: an exception is a [FAIL] line."""
    from supervisor.demo import inject as inj
    from supervisor.demo import reset, seed, tamper

    rep = RunReport(index)
    t_run = time.perf_counter()

    def say(line: str) -> None:
        rep.lines.append(line)
        echo(line)

    def fail(text: str) -> None:
        rep.ok = False
        say(f"[FAIL] {text}")

    def timed(name: str, t0: float) -> None:
        rep.step_seconds[name] = round(time.perf_counter() - t0, 3)

    say(f"=== demo run {index}: data dir {settings.data_dir}")
    try:
        t0 = time.perf_counter()
        if seed_first or not reset.has_snapshot(Path(settings.data_dir)):
            s = seed.seed(settings, echo=say)
            if not s.ok:
                rep.ok = False
                return rep
        else:
            say("[OK] seed: starting from the reset snapshot of run 1")
        timed("seed", t0)
        for line in optional_lines():
            say(line)
        if onboard:
            t0 = time.perf_counter()
            ok, lines, replayed = onboard_step(
                settings, say, replay=replay, deadline_s=deadline_s, replay_dir=replay_dir
            )
            for line in lines:
                say(line)
            if replayed:
                rep.replayed.append("onboard-credit_prequal")
            if not ok:
                rep.ok = False
            timed("onboard", t0)

        session = build_session(settings)
        try:
            for n in (1, 2, 3, 4):
                t0 = time.perf_counter()
                r = inj.inject(
                    session,
                    n,
                    echo=lambda _line: None,
                    auto_resume=True,
                    replay=replay,
                    deadline_s=deadline_s,
                    replay_dir=replay_dir,
                )
                for line in r.lines:
                    say(line)
                rep.replayed.extend(r.replayed)
                if record and r.ok and n in (2,):
                    judge_lines = [ln for ln in r.lines if ln.startswith("[OK] judge")]
                    path = fallback.record_twin(
                        f"judge-{r.incident_id}",
                        judge_lines,
                        source="python -m supervisor.cli demo --record (MockJudge)",
                        replay_dir=replay_dir,
                    )
                    say(f"[OK] recorded twin {path}")
                timed(f"inject-{n}", t0)
                if not r.ok:
                    rep.ok = False
            t0 = time.perf_counter()
            tr = tamper.tamper(session, echo=lambda _line: None)
            for line in tr.lines:
                say(line)
            if not tr.ok:
                rep.ok = False
            timed("tamper", t0)
        finally:
            session.close()

        t0 = time.perf_counter()
        rr = reset.restore(settings, echo=lambda _line: None)
        for line in rr.lines:
            say(line)
        if not rr.ok:
            rep.ok = False
        timed("reset", t0)
    except SupervisorError as exc:
        fail(f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 - any crash is a deviation, reported as [FAIL]
        fail(f"unexpected {type(exc).__name__}: {exc}")
    rep.seconds = time.perf_counter() - t_run
    verdict = "PASS" if rep.ok else "FAIL"
    tag = "[OK]" if rep.ok else "[FAIL]"
    extra = f"; replayed: {', '.join(rep.replayed)}" if rep.replayed else ""
    say(f"{tag} demo run {index}: {verdict} in {rep.seconds:.2f} s{extra}")
    return rep


def run_loop(
    settings: Settings,
    loops: int = 1,
    *,
    echo: Echo = default_echo,
    fresh_each: bool = False,
    replay: bool = False,
    deadline_s: float = fallback.DEFAULT_DEADLINE_S,
    onboard: bool = False,
    replay_dir: Path | None = None,
    record: bool = False,
    quiet_after_first: bool = False,
) -> LoopReport:
    out = LoopReport()
    for i in range(1, loops + 1):
        sink = echo
        if quiet_after_first and i > 1:

            def sink(line: str) -> None:
                if line.startswith("[FAIL]") or line.startswith("[OK] demo run"):
                    echo(line)

        out.runs.append(
            run_once(
                settings,
                i,
                echo=sink,
                seed_first=(i == 1) or fresh_each,
                replay=replay,
                deadline_s=deadline_s,
                onboard=onboard,
                replay_dir=replay_dir,
                record=record and i == 1,
            )
        )
    if loops > 1:
        times = sorted(r.seconds for r in out.runs)
        tag = "[OK]" if out.ok else "[FAIL]"
        echo(
            f"{tag} demo loop: {out.passed}/{loops} runs passed; total {out.total_seconds:.1f} s, "
            f"per run min {times[0]:.2f} s, median {times[len(times) // 2]:.2f} s, "
            f"max {times[-1]:.2f} s"
        )
    return out


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m supervisor.cli demo",
        description="Supervisor demo harness (synthetic data, no network).",
    )
    p.add_argument(
        "step",
        nargs="?",
        default="run",
        choices=("run", "seed", "seed-systems", "inject", "tamper", "reset", "serve"),
        help="run = full runbook (default)",
    )
    p.add_argument("incident", nargs="?", help="inject: 1, 2, 3 or 4")
    p.add_argument("--data-dir", default=None, help="demo data dir (default data/local/demo)")
    p.add_argument("--loop", type=int, default=1, help="repeat the full run N times")
    p.add_argument("--fresh-each", action="store_true", help="seed again before every run")
    p.add_argument(
        "--replay",
        action="store_true",
        help="use recorded twins (data/fixtures/demo_replay) for model steps that fail",
    )
    p.add_argument(
        "--deadline", type=float, default=fallback.DEFAULT_DEADLINE_S, help=argparse.SUPPRESS
    )
    p.add_argument("--onboard", action="store_true", help="include the WP9 onboarding beat")
    p.add_argument("--record", action="store_true", help="re-record the replay twins")
    p.add_argument("--auto-resume", action="store_true", help="inject: two-person resume")
    p.add_argument("--snapshot", action="store_true", help="reset: take a new snapshot")
    p.add_argument("--quiet", action="store_true", help="loop: print run 1 in full only")
    p.add_argument(
        "--candidates-dir",
        default=None,
        help="seed-systems: folder with <name>/supervisor.manifest.yaml "
        "(default ~/supervisor-testbed/candidates)",
    )
    p.add_argument(
        "--no-snapshot",
        action="store_true",
        help="seed-systems: do not refresh the reset snapshot",
    )
    p.add_argument("--host", default="127.0.0.1", help="serve: bind address")
    p.add_argument("--port", type=int, default=8000, help="serve: port")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    echo = default_echo
    try:
        settings = demo_settings(resolve_data_dir(args.data_dir))
        if args.step == "run":
            if args.loop < 1:
                echo("[FAIL] --loop must be 1 or more")
                return 2
            report = run_loop(
                settings,
                args.loop,
                fresh_each=args.fresh_each,
                replay=args.replay,
                deadline_s=args.deadline,
                onboard=args.onboard,
                record=args.record,
                quiet_after_first=args.quiet,
            )
            return 0 if report.ok else 1
        if args.step == "seed":
            from supervisor.demo.seed import seed

            return 0 if seed(settings).ok else 1
        if args.step == "seed-systems":
            from supervisor.demo.seed_systems import seed_systems

            # Governance on for this step only: the systems service needs the flag.
            gov = demo_settings(
                resolve_data_dir(args.data_dir),
                governance_enabled=True,
                classifier_ai_prefill=False,
            )
            rep = seed_systems(gov, args.candidates_dir, echo=echo, snapshot=not args.no_snapshot)
            return 0 if rep.ok else 1
        if args.step == "inject":
            from supervisor.demo.inject import incident_id, inject

            if not args.incident:
                echo("[FAIL] which incident? python -m supervisor.cli demo inject 1")
                return 2
            try:
                incident_id(args.incident)
            except ValueError as exc:
                echo(f"[FAIL] {exc}")
                return 2
            session = build_session(settings)
            try:
                r = inject(session, args.incident, auto_resume=args.auto_resume, replay=args.replay)
            finally:
                session.close()
            return 0 if r.ok else 1
        if args.step == "tamper":
            from supervisor.demo.tamper import tamper

            session = build_session(settings)
            try:
                return 0 if tamper(session).ok else 1
            finally:
                session.close()
        if args.step == "reset":
            from supervisor.demo import reset

            if args.snapshot:
                reset.snapshot(settings)
                return 0
            return 0 if reset.restore(settings).ok else 1
        if args.step == "serve":
            from supervisor.demo.stage import serve

            return serve(settings, host=args.host, port=args.port, replay=args.replay)
    except SupervisorError as exc:
        echo(ascii_line(f"[FAIL] {exc}"))
        return 1
    return 2


if __name__ == "__main__":
    from supervisor.bootstrap import bootstrap

    bootstrap()
    raise SystemExit(main())
