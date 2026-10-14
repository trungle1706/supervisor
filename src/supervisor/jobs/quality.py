"""Quality job: sampled groundedness / guideline scores of customer replies (advisory).

Run: python -m supervisor.jobs.quality
Also callable in-process (scheduler): ``run(ctx, settings)``. Needs QUALITY_ENABLED=1.
Uses the Tier 1 judge model (JUDGE_T1_MODEL; empty = mock, labelled mock).
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
from supervisor.monitors.sweeps import build_quality_sweep  # noqa: E402


def run(ctx: MonitorContext, settings: Settings, sweep: Any = None) -> dict[str, Any]:
    sweep = sweep or build_quality_sweep(ctx, settings)
    if sweep is None:
        return {"status": "skipped", "reason": "QUALITY_ENABLED is off"}
    res = sweep.run()
    return {"status": "ok", "events": res.events, "scored": res.traces}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m supervisor.jobs.quality").parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] quality: {exc}"))
        return 1
    if out["status"] == "skipped":
        print(ascii_line(f"[SKIP] quality: {out['reason']}"))
        return 0
    print(ascii_line("[OK] quality: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
