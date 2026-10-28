"""Duty evidence sweep job (WP-L4): close the full-coverage duties whose controls all work.

Run: python -m supervisor.jobs.duty_evidence_sweep
Also callable in-process (scheduler): ``run(ctx, settings)``; on by REGULATOR_PACK (and RISK_DUTIES)
with DUTY_EVIDENCE_SWEEP_S set to 300 or more (default 0 = off).

For every AI system (not archived) with an open applying duty of coverage ``full``, the job reads
the live evidence counts of the mapped Supervisor controls (window DUTY_EVIDENCE_WINDOW_DAYS,
default 30). When every mapped control has at least DUTY_EVIDENCE_MIN_ROWS rows, the duty is
closed with the control ids as the closing control (actor ``system``). Duties with coverage
partial or none are never closed here. A second run closes nothing new.
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
from supervisor.governance import duty_evidence  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402


def enabled(settings: Settings) -> bool:
    """Listed by the scheduler only when it can run."""
    return duty_evidence.sweep_enabled(settings)


def run(ctx: MonitorContext, settings: Settings) -> dict[str, Any]:
    return duty_evidence.sweep(duty_evidence.Env.from_job(ctx, settings))


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="python -m supervisor.jobs.duty_evidence_sweep", description=__doc__.splitlines()[0]
    ).parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            if not duty_evidence.enabled(settings):
                print("[SKIP] the regulator pack is off (REGULATOR_PACK=1 turns it on)")  # noqa: T201
                return 0
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] duty_evidence_sweep: {exc}"))  # noqa: T201
        return 1
    print(ascii_line("[OK] duty_evidence_sweep: " + ", ".join(f"{k}={v}" for k, v in out.items())))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
