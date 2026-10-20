"""Control status job (WP30): evidence status of every control for every agent, per window.

Run: python -m supervisor.jobs.control_status
Also callable in-process (scheduler): ``run(ctx, settings)``; on by CONTROLS_ENABLED.

For every active control in scope of an agent that is not RETIRED it asks the same facts the risk
register uses (gate rule hits, non-mock pack verdicts, monitor status of a supervised agent),
writes one ``control_status`` row (a status, a fixed reason code and integers) and, per agent, one
``control_status`` chain record with the compliance figure in basis points (docs/controls.md). A
second run in the same window writes nothing. The chain has one writer per lane: run the command
line only when the app is stopped, or let the app's scheduler run it.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.controls.service import ControlService  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402


def service_for(ctx: MonitorContext, settings: Settings) -> ControlService:
    return ControlService(ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence)


def run(
    ctx: MonitorContext, settings: Settings, service: ControlService | None = None
) -> dict[str, Any]:
    return (service or service_for(ctx, settings)).run_status()


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="python -m supervisor.jobs.control_status", description=__doc__.splitlines()[0]
    ).parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            if not settings.controls_enabled:
                print("[SKIP] control catalogue is off (CONTROLS_ENABLED=1 turns it on)")  # noqa: T201
                return 0
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] control_status: {exc}"))  # noqa: T201
        return 1
    print(ascii_line("[OK] control_status: " + ", ".join(f"{k}={v}" for k, v in out.items())))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
