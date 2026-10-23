"""Session monitor job (WP27, ADR D29): replay stored gate decisions, apply the session rules.

Run: python -m supervisor.jobs.session_monitor
Also callable in-process (scheduler): ``run(ctx, settings)``; ``SESSION_MONITOR_ENABLED=1`` and
``SCHED_SESSION_S`` (default 300 s).

The in-request path (gate hook) does the same work call by call; this batch path is the safety net
(restart, second replica, missed call) and lifts session pauses whose cool-down ran out.
Run it from the command line only when the app is stopped (single chain writer per lane).
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.gateway.policy import load_policy_dirs  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402
from supervisor.monitors.session_batch import SessionMonitor  # noqa: E402
from supervisor.wiring import resolve_policy_dirs  # noqa: E402


def run(ctx: MonitorContext, settings: Settings) -> dict[str, Any]:
    policy = load_policy_dirs(resolve_policy_dirs(settings))
    res = SessionMonitor(ctx, settings, policy).run()
    return {
        "sessions": res.sessions,
        "assessed": res.assessed,
        "cases_opened": len(res.cases_opened),
        "pauses_set": len(res.pauses_set),
        "pauses_expired": len(res.expired),
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="python -m supervisor.jobs.session_monitor",
        description="Score sessions from stored gate decisions; open cases; lift expired pauses.",
    ).parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            if not settings.session_monitor_enabled:
                print("[SKIP] session_monitor: SESSION_MONITOR_ENABLED is off")
                return 0
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] session_monitor: {exc}"))
        return 1
    print(ascii_line("[OK] session_monitor: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
