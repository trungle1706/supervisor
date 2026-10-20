"""SIEM export job (WP21): send new evidence-chain events to the configured sink.

Run: python -m supervisor.jobs.siem [--replay-dead-letter]
Also callable in-process (scheduler): ``run(ctx, settings)``; on by SIEM_ENABLED.

Sink and format come from SIEM_SINK / SIEM_FORMAT (docs/siem.md). The cursor of each chain
lane lives in ``monitor_state`` (monitor ``siem``) and moves only after the sink accepted the
batch, so a restart does not send an event twice.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.adapters.integrations import load_integration_settings  # noqa: E402
from supervisor.adapters.integrations.siem import (  # noqa: E402
    ChainEventFeed,
    WebhookSiemSink,
    build_siem_sink,
)
from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402


def run(ctx: MonitorContext, settings: Settings, *, replay: bool = False) -> dict[str, Any]:
    cfg = load_integration_settings(siem_enabled=settings.siem_enabled)
    sink = build_siem_sink(cfg, settings.data_dir, ctx.tables)
    if sink is None:
        return {"enabled": False, "sent": 0}
    out: dict[str, Any] = {"enabled": True, "sink": cfg.siem_sink, "format": cfg.siem_format}
    if replay and isinstance(sink, WebhookSiemSink):
        sent, failing = sink.replay_dead_letter()
        out.update(replayed=sent, still_failing=failing)
    out["sent"] = ChainEventFeed(ctx.tables, sink, ctx.state).poll()
    if isinstance(sink, WebhookSiemSink):
        out["dead_lettered"] = sink.dead_lettered
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.jobs.siem")
    ap.add_argument("--replay-dead-letter", action="store_true", help="resend parked batches")
    args = ap.parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            out = run(ctx, settings, replay=args.replay_dead_letter)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] siem: {exc}"))
        return 1
    if not out["enabled"]:
        print("[SKIP] siem: SIEM_ENABLED is off")
        return 0
    print(ascii_line("[OK] siem: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
