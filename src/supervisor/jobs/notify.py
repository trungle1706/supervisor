"""Notify job (WP21): send the queued webhook notices.

Run: python -m supervisor.jobs.notify
Also callable in-process (scheduler): ``run(ctx, settings)``; on when NOTIFY_WEBHOOK_ENABLED is
set and NOTIFY_WEBHOOK_URL is filled.

Case actions and other console requests only queue a ``webhook:<channel>`` notice; this job
sends them (3 attempts, back-off, idempotency key = notice id, dead-letter file) so a dead
webhook never slows a request.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.adapters.integrations import is_placeholder  # noqa: E402
from supervisor.adapters.notify import WebhookNotifier, build_notifier  # noqa: E402
from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402


def enabled(settings: Settings) -> bool:
    return bool(settings.notify_webhook_enabled) and not is_placeholder(settings.notify_webhook_url)


def run(ctx: MonitorContext, settings: Settings) -> dict[str, Any]:
    if not enabled(settings):
        return {"enabled": False, "sent": 0, "dead_letter": 0}
    notifier, _ = build_notifier(settings, ctx.state, ctx.clock)
    hook = next((t for t in notifier.targets if isinstance(t, WebhookNotifier)), None)
    if hook is None:
        return {"enabled": False, "sent": 0, "dead_letter": 0}
    return {"enabled": True, **hook.drain()}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m supervisor.jobs.notify").parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] notify: {exc}"))
        return 1
    if not out["enabled"]:
        print("[SKIP] notify: the webhook is off (NOTIFY_WEBHOOK_ENABLED and a URL)")
        return 0
    print(ascii_line("[OK] notify: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
