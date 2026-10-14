"""Judge sweep job: run the advisory judges (WP5) over new agent events (JUDGE_ENABLED=1).

Run: python -m supervisor.jobs.judge_sweep
Also callable in-process (scheduler): ``run(ctx, settings)``.

Judge advice opens a case (``case_type`` judge) or raises its severity; judges never
block or pause. Run it when the app is stopped, or let the app's scheduler run it.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402
from supervisor.monitors.sweeps import build_judge_sweep  # noqa: E402


def run(ctx: MonitorContext, settings: Settings, sweep: Any = None) -> dict[str, Any]:
    sweep = sweep or build_judge_sweep(ctx, settings)
    if sweep is None:
        return {"status": "skipped", "reason": "JUDGE_ENABLED is off"}
    res = sweep.run()
    return {
        "status": "ok",
        "events": res.events,
        "traces": res.traces,
        "cases_opened": len(res.cases_opened),
        "cases_raised": len(res.cases_raised),
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m supervisor.jobs.judge_sweep").parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] judge_sweep: {exc}"))
        return 1
    if out["status"] == "skipped":
        print(ascii_line(f"[SKIP] judge_sweep: {out['reason']}"))
        return 0
    print(ascii_line("[OK] judge_sweep: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
