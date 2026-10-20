"""Alert job (WP21): evaluate the rules in ``config/alerts.yaml`` over new signals.

Run: python -m supervisor.jobs.alerts
Also callable in-process (scheduler): ``run(ctx, settings)``; on by ALERTS_ENABLED.

Each run reads the signals since its cursor (plus the longest rule window, to fill the
counters), stores new alerts, sends them through their routes, adds absorbed repeats to the
open alert (``suppressed_count``) and retries routes that failed earlier. The cursor
(monitor ``alerts``, key ``cursor``) moves only after the alerts are stored, so a crash
repeats work but never loses an alert; alert ids are deterministic, so a repeat is a no-op.
The read stops ALERTS_LAG_S (default 30 s) before now: a watermark for entries that commit
after their timestamp.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from datetime import timedelta  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.alerts import AlertService, build_routes, evaluate, load_rules  # noqa: E402
from supervisor.alerts.signals import load_signals  # noqa: E402
from supervisor.config import Settings  # noqa: E402
from supervisor.core.canonical import format_ts  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext, as_dt, get_state, put_state  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402

MONITOR = "alerts"
FIRST_RUN_LOOKBACK_S = 900


def build_service(ctx: MonitorContext, settings: Settings) -> AlertService:
    from supervisor.adapters.integrations import load_integration_settings
    from supervisor.adapters.integrations.siem import build_siem_sink

    cfg = load_integration_settings(siem_enabled=settings.siem_enabled)
    sink = build_siem_sink(cfg, settings.data_dir, ctx.tables)
    routes = build_routes(
        settings, ctx.state, ctx.clock, siem_sink=sink, env=settings.supervisor_mode
    )
    return AlertService(ctx.state, ctx.clock, ctx.evidence, routes, env=settings.supervisor_mode)


def run(
    ctx: MonitorContext, settings: Settings, service: AlertService | None = None
) -> dict[str, Any]:
    ruleset = load_rules(settings.alerts_config)
    service = service or build_service(ctx, settings)
    redelivered = service.redeliver()
    now = ctx.clock.now()
    saved = get_state(ctx, MONITOR, "cursor")
    cursor = (as_dt(saved["ts"]), str(saved["sid"])) if saved else None
    if cursor is not None:
        ts_from = cursor[0] - timedelta(seconds=ruleset.max_window_s)
    else:
        ts_from = now - timedelta(seconds=max(ruleset.max_window_s, FIRST_RUN_LOOKBACK_S))
    # Watermark: only signals older than ALERTS_LAG_S are read, so an entry whose ts is
    # earlier than its commit (Delta latency, another lane committing first) is still ahead
    # of the cursor when it becomes visible. Entries later than the lag are still missed.
    upper = now - timedelta(seconds=settings.alerts_lag_s)
    signals = load_signals(ctx, ts_from, upper)
    result = evaluate(ruleset, signals, cursor=cursor, last_fired=service.last_fired())
    stored = 0
    for fired in result.fired:
        if service.raise_alert(fired) is not None:
            stored += 1
    for key, (count, last_ts) in sorted(result.suppressed_existing.items()):
        service.add_suppressed(key, count, last_ts)
    if result.cursor is not None:
        put_state(
            ctx, MONITOR, "cursor", {"ts": format_ts(result.cursor[0]), "sid": result.cursor[1]}
        )
    return {
        "signals": len(signals),
        "judged": result.judged,
        "alerts": stored,
        "suppressed": sum(n for n, _ in result.suppressed_existing.values())
        + sum(f.suppressed_count for f in result.fired),
        "policy_suppressed": result.policy_suppressed,
        "redelivered": redelivered,
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m supervisor.jobs.alerts").parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] alerts: {exc}"))
        return 1
    print(ascii_line("[OK] alerts: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
