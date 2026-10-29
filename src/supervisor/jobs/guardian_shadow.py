"""Guardian shadow job (WP-G3): the daily upkeep of the guardian factory.

Run: python -m supervisor.jobs.guardian_shadow
Also callable in-process (scheduler): ``run(ctx, settings)``; listed when GUARDIAN_FACTORY and
DETECTORS_ENABLED are on (``SCHED_GUARDIAN_SHADOW_S``, default 86400).

* removes every expired allow-list entry (an expired entry is ignored by the guardian at once; this
  job takes it out of the definition and writes a ``guardian_def_event`` row, action
  ``allow_expired``);
* writes one ``guardian_shadow_day`` chain record per closed shadow day (counts only).
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.guardian_factory.promotion import Promotion  # noqa: E402
from supervisor.guardian_factory.store import GuardianDefStore  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402


def enabled(settings: Settings) -> bool:
    return bool(settings.guardian_factory and settings.detectors_enabled)


def run(ctx: MonitorContext, settings: Settings) -> dict[str, Any]:
    store = GuardianDefStore(ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence)
    promo = Promotion(store)
    return {"allow_expired": promo.expire_allow_entries(), "days_closed": promo.close_days()}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="python -m supervisor.jobs.guardian_shadow", description=__doc__.splitlines()[0]
    ).parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            if not enabled(settings):
                print("[SKIP] the guardian factory is off (GUARDIAN_FACTORY=1 turns it on)")  # noqa: T201
                return 0
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] guardian_shadow: {exc}"))  # noqa: T201
        return 1
    print(ascii_line("[OK] guardian_shadow: " + ", ".join(f"{k}={v}" for k, v in out.items())))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
