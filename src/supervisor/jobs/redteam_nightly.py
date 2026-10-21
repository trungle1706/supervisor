"""Nightly multi-turn red team (WP28): run the pack on the sandbox agents, write the chain.

Run: python -m supervisor.jobs.redteam_nightly [--trials N] [--out DIR] [--agent ID] [--force]
Also callable in-process (scheduler job ``redteam_nightly``, REDTEAM_NIGHTLY_ENABLED=1,
interval SCHED_REDTEAM_S, default one day): ``run(ctx, settings)``.

For each demo agent (payments, customer_service, credit_prequal) it builds a private sandbox,
runs the pack ``multiturn_redteam_vi`` with ``REDTEAM_NIGHTLY_TRIALS`` trials per objective
(default 50), and records the results like any assurance run: one ``eval_result`` row and one
``assurance_result`` chain record per agent, plus an ``eval_run`` row. Traces of every
conversation (per-turn gate decision, rule ids, oracle flag, monitor counters) go to the output
folder for WP27. The 7-day trend is written next to them.

The agent side is a labelled mock; nothing here can change an agent, a policy or the gate. The
standalone command opens the chain, so run it only when the app is stopped (single-writer rule);
the app's scheduler passes the app's own chain writer.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.assurance.engine import execute, finish_run, new_run_id  # noqa: E402
from supervisor.assurance.loader import PACKS_DIR, load_packs  # noqa: E402
from supervisor.assurance.model import RunContext  # noqa: E402
from supervisor.assurance.targets import DemoAgentTarget  # noqa: E402
from supervisor.config import REPO_ROOT, Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402
from supervisor.redteam.multiturn.model import AGENTS  # noqa: E402
from supervisor.redteam.multiturn.trend import pack_trend, render_trend  # noqa: E402

PACK_ID = "multiturn_redteam_vi"


def enabled(settings: Settings) -> bool:
    return bool(settings.redteam_nightly_enabled)


def run(
    ctx: MonitorContext,
    settings: Settings,
    *,
    trials: int | None = None,
    out_dir: Path | None = None,
    agents: tuple[str, ...] = AGENTS,
    attacker: Any = None,
) -> dict[str, Any]:
    """Run the nightly campaign and record it. Returns a small JSON-safe summary."""
    pack = next(p for p in load_packs(PACKS_DIR) if p.id == PACK_ID)
    clock = ctx.clock
    run_id = new_run_id(clock)
    out = out_dir or (Path(settings.data_dir) / "redteam_nightly" / run_id)
    out.mkdir(parents=True, exist_ok=True)
    n_trials = trials or settings.redteam_nightly_trials
    if attacker is None:
        # The nightly job is always offline. The LLM attacker is a manual, capped run
        # (python -m supervisor.redteam.multiturn run --attacker llm), never a schedule.
        from supervisor.redteam.multiturn.attacker import TemplateAttacker

        attacker = TemplateAttacker()
    started = clock.now()
    results = []
    for agent in agents:
        target = DemoAgentTarget(agent, out / "work", settings=settings)
        try:
            rctx = RunContext(
                target=target,
                repo_root=REPO_ROOT,
                data_root=settings.assurance_data_dir,
                data_mode="auto",
                extras={
                    "out_dir": str(out),
                    "redteam_trials": n_trials,
                    "redteam_attacker": attacker,
                    "redteam_langs": settings.redteam_langs,
                },
            )
            results += execute([pack], target, rctx, run_id, clock)
        finally:
            target.close()
    summary = finish_run(
        [pack],
        results,
        run_id,
        started,
        clock,
        target_spec="redteam_nightly:" + ",".join(agents),
        selector=PACK_ID,
        tables=ctx.tables,
        sink=ctx.evidence,
        out_dir=out,
        packs_dir=PACKS_DIR,
    )
    shutil.rmtree(out / "work", ignore_errors=True)  # throw-away sandbox stores
    trend = pack_trend(ctx.tables, PACK_ID, now=clock.now())
    (out / "trend.md").write_text(render_trend(trend), encoding="utf-8")
    return {
        "enabled": True,
        "run_id": run_id,
        "out_dir": str(out),
        "trials": n_trials,
        "counts": dict(summary.counts),
        "agents": {
            r.target_id: {
                "status": r.status,
                "gate_catch_bp": r.metrics.get("gate_catch_bp"),
                "unexpected_escape_count": r.metrics.get("unexpected_escape_count"),
                "known_gap_open_count": r.metrics.get("known_gap_open_count"),
                "conversations": r.metrics.get("conversations"),
            }
            for r in results
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m supervisor.jobs.redteam_nightly",
        description="Nightly multi-turn Vietnamese red team (WP28).",
    )
    ap.add_argument(
        "--trials", type=int, help="trials per objective (default REDTEAM_NIGHTLY_TRIALS)"
    )
    ap.add_argument(
        "--out", type=Path, help="output folder (default <data dir>/redteam_nightly/<run>)"
    )
    ap.add_argument("--agent", action="append", choices=AGENTS, help="limit to these agents")
    ap.add_argument(
        "--force", action="store_true", help="run even when REDTEAM_NIGHTLY_ENABLED is off"
    )
    args = ap.parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            if not enabled(settings) and not args.force:
                print(
                    "[SKIP] redteam_nightly: REDTEAM_NIGHTLY_ENABLED is off (--force runs it once)"
                )  # noqa: T201
                return 0
            out = run(
                ctx,
                settings,
                trials=args.trials,
                out_dir=args.out,
                agents=tuple(args.agent or AGENTS),
            )
    except (SupervisorError, OSError, ValueError) as exc:
        print(ascii_line(f"[FAIL] redteam_nightly: {type(exc).__name__}: {exc}"))  # noqa: T201
        return 1
    print(  # noqa: T201
        ascii_line(
            f"[OK] redteam_nightly: run={out['run_id']} trials={out['trials']} "
            f"counts={out['counts']} out={out['out_dir']} [MOCK agent]"
        )
    )
    for agent, m in out["agents"].items():
        print(ascii_line(f"  {agent}: {m}"))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
