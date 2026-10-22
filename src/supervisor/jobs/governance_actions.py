"""Governance action job (WP-G5): events to actions, incidents.

Run: python -m supervisor.jobs.governance_actions [--dry-run]
Also callable in-process (scheduler): ``run(ctx, settings)``; on by GOVERNANCE_ACTIONS_ENABLED
(and GOVERNANCE_ENABLED). Interval: SCHED_GOVERNANCE_S (default 60 s).

Each run reads the new events of every source (alerts, gate stops on money, credit and data
export tools, failed detectors, failing monitors, assurance NO-GO, chain verify failures, model
version changes, judge escalations), matches them to ``config/governance_actions.yaml`` and
runs the actions: create an incident, notify the owner, raise the risk level, move to
re-evaluation, create a review, fire a webhook event, reopen a control. An event is processed
once (a marker row per event); a repeat run does nothing. No action pauses or blocks an agent.

``--dry-run`` prints what would fire and writes nothing. The chain has one writer per lane: run
the command line only when the app is stopped, or let the app's scheduler run it.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.governance.actions import ActionRunner  # noqa: E402
from supervisor.governance.actions_model import load_rules  # noqa: E402
from supervisor.governance.incidents import IncidentService  # noqa: E402
from supervisor.governance.lifecycle import LifecycleService  # noqa: E402
from supervisor.governance.model import ensure_on  # noqa: E402
from supervisor.governance.reviews import ReviewService  # noqa: E402
from supervisor.governance.systems import SystemService  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402


def enabled(settings: Settings) -> bool:
    """The job is listed (and runs) only with both flags on."""
    return bool(settings.governance_actions_enabled and settings.governance_enabled)


def build_runner(ctx: MonitorContext, settings: Settings) -> ActionRunner:
    from supervisor.adapters.notify import InboxNotifier

    systems = SystemService(ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence)
    controls = None
    if settings.controls_enabled:
        from supervisor.controls.service import ControlService

        controls = ControlService(ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence)
    return ActionRunner(
        ctx,
        settings,
        load_rules(settings.governance_actions_config),
        systems=systems,
        lifecycle=LifecycleService(systems),
        reviews=ReviewService(systems),
        incidents=IncidentService(ctx.state, ctx.clock, settings, evidence=ctx.evidence),
        notifier=InboxNotifier(ctx.state, ctx.clock),
        controls=controls,
    )


def run(
    ctx: MonitorContext,
    settings: Settings,
    runner: ActionRunner | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    ensure_on(settings)
    res = (runner or build_runner(ctx, settings)).run(dry_run=dry_run)
    out: dict[str, Any] = res.as_dict()
    if dry_run:
        out["planned"] = res.planned
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.jobs.governance_actions")
    ap.add_argument("--dry-run", action="store_true", help="print what would fire; write nothing")
    args = ap.parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            if not enabled(settings):
                print(  # noqa: T201
                    "[SKIP] governance actions are off "
                    "(GOVERNANCE_ACTIONS_ENABLED=1 and GOVERNANCE_ENABLED=1 turn them on)"
                )
                return 0
            out = run(ctx, settings, dry_run=args.dry_run)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] governance_actions: {exc}"))  # noqa: T201
        return 1
    planned = out.pop("planned", None)
    if planned is not None:
        for p in planned:
            print(  # noqa: T201
                ascii_line(
                    f"[PLAN] {p['event']} {p['severity']} agent={p['agent_id']} "
                    f"system={p['system_id'] or '-'} ref={p['ref']} rules={','.join(p['rules'])} "
                    f"actions={','.join(p['actions'])}"
                )
            )
    tag = "[OK] governance_actions (dry run)" if args.dry_run else "[OK] governance_actions"
    print(ascii_line(f"{tag}: " + ", ".join(f"{k}={v}" for k, v in out.items())))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
