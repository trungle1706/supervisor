"""Fairness job: slice approval and block rates on configured attributes (config/fairness.yaml).

Run: python -m supervisor.jobs.fairness [--config PATH] [--method auto|fairlearn|python]
Also callable in-process (scheduler): ``run(ctx, settings)``.

Fairlearn is used when the ``monitors`` extra is installed; the pure-Python path gives
the same integers. Cells under n = 30 are suppressed. Run it when the app is stopped, or
let the app's scheduler run it (FAIRNESS_ENABLED=1).
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.fairness import (  # noqa: E402
    FairnessConfig,
    FairnessMonitor,
    build_source,
)
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402


def run(
    ctx: MonitorContext,
    settings: Settings,
    *,
    config_path: Path | None = None,
    method: str = "auto",
) -> dict[str, Any]:
    cfg = FairnessConfig.load(config_path or settings.fairness_config)
    source = build_source(ctx, cfg, settings.mask_key[0])
    if source is None:
        return {"status": "skipped", "reason": "attribute_source is none"}
    res = FairnessMonitor(ctx, cfg, source, method=method).run()
    return {
        "status": "ok",
        "agents": len(res.reports),
        "method": ",".join(sorted({r.method for r in res.reports.values()})) or "-",
        "max_gap_bp": max((r.max_approval_gap_bp or 0 for r in res.reports.values()), default=0),
        "cases_opened": len(res.cases_opened),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.jobs.fairness")
    ap.add_argument("--config", type=Path, default=None, help="default: FAIRNESS_CONFIG")
    ap.add_argument("--method", choices=("auto", "fairlearn", "python"), default="auto")
    args = ap.parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            out = run(
                ctx,
                settings,
                config_path=args.config.resolve() if args.config else None,
                method=args.method,
            )
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] fairness: {exc}"))
        return 1
    if out["status"] == "skipped":
        print(ascii_line(f"[SKIP] fairness: {out['reason']}"))
        return 0
    print(ascii_line("[OK] fairness: " + ", ".join(f"{k}={v}" for k, v in out.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
