"""Multi-agent pattern job (ADR D10): split payment across callers over gateway events.

Run: python -m supervisor.jobs.multiagent
Also callable in-process (scheduler): ``run(ctx, settings)``.

Run it when the app is stopped, or let the app's scheduler run it (MULTIAGENT_ENABLED=1).
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
from supervisor.monitors.multiagent import MultiAgentMonitor, SplitPaymentConfig  # noqa: E402


def run(ctx: MonitorContext, settings: Settings) -> dict[str, Any]:
    res = MultiAgentMonitor(ctx, SplitPaymentConfig.from_settings(settings)).run()
    return {
        "events_scanned": res.events_scanned,
        "findings": len(res.findings),
        "cases_opened": len(res.cases_opened),
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m supervisor.jobs.multiagent").parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] multiagent: {exc}"))
        return 1
    print(ascii_line("[OK] multiagent: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
