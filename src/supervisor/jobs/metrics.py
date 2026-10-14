"""Oversight metrics job: daily ``oversight_metric`` rows per agent (docs/metrics.md).

Run: python -m supervisor.jobs.metrics [--date YYYY-MM-DD] [--eval-report PATH]
Also callable in-process (scheduler): ``run(ctx, settings)``.

Default: recompute yesterday and today (UTC). Run it when the app is stopped, or let
the app's scheduler run it (METRICS_ENABLED=1).
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import REPO_ROOT, Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402
from supervisor.monitors.oversight import OversightMetrics  # noqa: E402

EVAL_REPORT = REPO_ROOT / "data" / "golden" / "eval_report.json"


def run(
    ctx: MonitorContext,
    settings: Settings,
    *,
    days: list[date] | None = None,
    eval_report: Path | None = None,
) -> dict[str, Any]:
    rows = OversightMetrics(ctx, eval_report=eval_report or EVAL_REPORT).run(days=days)
    return {"rows": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.jobs.metrics")
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="one UTC day")
    ap.add_argument("--eval-report", type=Path, default=None, help="judge eval report JSON")
    args = ap.parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            out = run(
                ctx,
                settings,
                days=[args.date] if args.date else None,
                eval_report=args.eval_report.resolve() if args.eval_report else None,
            )
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] metrics: {exc}"))
        return 1
    print(ascii_line(f"[OK] metrics: {out['rows']} oversight_metric rows written"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
