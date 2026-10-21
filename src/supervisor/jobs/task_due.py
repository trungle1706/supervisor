"""Task due job (WP30): close tasks whose evidence is there, open a case for overdue ones.

Run: python -m supervisor.jobs.task_due [--no-cases]
Also callable in-process (scheduler): ``run(ctx, settings, cases)``; on by CONTROLS_ENABLED.

Two steps, both deterministic (no judge, rule R1):

1. ``sync``: a template task whose evidence is a control that shows "working" for the agent, or a
   real (non-mock) assurance pack that passed, is marked done by the system.
2. ``run_due``: every REQUIRED task past its due time that has no case yet gets one case
   (source ``task``, severity low, medium at level high or critical). A case for a task has no
   incident clock: it is an internal flag, not an incident. A second run opens none again.

The standalone command writes to the evidence chain, so run it only when the app is stopped; the
app calls ``run`` with its own case service instead.
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
from supervisor.monitors.jobctx import ascii_line  # noqa: E402
from supervisor.tasks.service import TaskService  # noqa: E402


def service_for(ctx: MonitorContext, settings: Settings) -> TaskService:
    return TaskService(ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence)


def run(
    ctx: MonitorContext,
    settings: Settings,
    cases: Any = None,
    service: TaskService | None = None,
) -> dict[str, Any]:
    svc = service or service_for(ctx, settings)
    out: dict[str, Any] = {}
    out.update(svc.sync())
    out.update(svc.run_due(cases))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m supervisor.jobs.task_due", description=__doc__.splitlines()[0]
    )
    ap.add_argument("--no-cases", action="store_true", help="count overdue tasks, open no case")
    args = ap.parse_args(argv)
    from supervisor.cases import build_case_service
    from supervisor.config import load_settings
    from supervisor.jobs import bootstrap_schema
    from supervisor.monitors.common import MonitorContext as _Ctx
    from supervisor.wiring import build_runtime

    try:
        settings = load_settings()
        if not settings.controls_enabled:
            print("[SKIP] task list is off (CONTROLS_ENABLED=1 turns it on)")  # noqa: T201
            return 0
        runtime = build_runtime(settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] runtime: {exc}"))  # noqa: T201
        return 1
    try:
        if runtime.adapters.executor.dialect == "sqlite":
            bootstrap_schema.run(settings, runtime.adapters)
        ctx = _Ctx.from_adapters(runtime.adapters, runtime.chain)
        cases = None if args.no_cases else build_case_service(runtime)
        out = run(ctx, settings, cases)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] task_due: {exc}"))  # noqa: T201
        return 1
    finally:
        runtime.close()
    print(ascii_line("[OK] task_due: " + ", ".join(f"{k}={v}" for k, v in out.items())))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
