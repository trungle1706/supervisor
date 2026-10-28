"""Duties sweep job (WP-L3): one reminder task per system per week for duties due soon.

Run: python -m supervisor.jobs.duties_sweep
Also callable in-process (scheduler): ``run(ctx, settings)``; on by RISK_DUTIES with
RISK_DUTIES_SWEEP_S set to 300 or more (default 0 = off).

For every AI system with an open applying duty (``obligation_status``) that is due within 30
days, or past due, the job opens one task for the ISO week (template ``DUTY-DUE-<year>W<week>``,
owner role owner, not required), so the owner gets a reminder. The task id comes from the
system and the template, so a second run in the same week opens nothing. The job first moves the
due date of an open row to the effective date of its instrument when that date is still ahead.
Advisory only. Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.governance import duties_gap  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402
from supervisor.tasks.service import TaskService  # noqa: E402


def enabled(settings: Settings) -> bool:
    """Listed by the scheduler only when it can run."""
    return bool(duties_gap.enabled(settings) and int(settings.risk_duties_sweep_s) >= 300)


def run(ctx: MonitorContext, settings: Settings) -> dict[str, Any]:
    tasks = TaskService(ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence)
    return duties_gap.sweep(ctx.state, ctx.clock, tasks, settings)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="python -m supervisor.jobs.duties_sweep", description=__doc__.splitlines()[0]
    ).parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            if not duties_gap.enabled(settings):
                print("[SKIP] duties are off (RISK_DUTIES=1 turns them on)")  # noqa: T201
                return 0
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] duties_sweep: {exc}"))  # noqa: T201
        return 1
    print(ascii_line("[OK] duties_sweep: " + ", ".join(f"{k}={v}" for k, v in out.items())))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
