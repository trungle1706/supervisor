"""Drift job (ADR D09): baseline band per agent version; out-of-band windows open a case.

Run: python -m supervisor.jobs.drift
Also callable in-process (scheduler): ``run(ctx, settings)``.

Run it when the app is stopped, or let the app's scheduler run it (DRIFT_ENABLED=1):
the command line builds its own chain writer (single writer per lane).
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.bindings import BindingResolver  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.drift import DriftConfig, DriftMonitor  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402


def run(ctx: MonitorContext, settings: Settings) -> dict[str, Any]:
    resolver = BindingResolver.from_settings(settings)
    res = DriftMonitor(ctx, DriftConfig.from_settings(settings), resolver).run()
    return {
        "baselines_built": len(res.baselines_built),
        "windows_checked": res.windows_checked,
        "cases_opened": len(res.cases_opened),
        "collecting": len(res.collecting),
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m supervisor.jobs.drift").parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] drift: {exc}"))
        return 1
    print(ascii_line("[OK] drift: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
