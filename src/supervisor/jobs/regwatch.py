"""Regulation watcher job (WP-W1): ask vbpl.vn about the stored instruments, write a report and a
signed update package.

Run: python -m supervisor.jobs.regwatch
Also callable in-process (scheduler): ``run(ctx, settings)``; on by REGWATCH_ENABLED=1 with
REGWATCH_INTERVAL_S (default 86400, at least 3600). Laptop mode only: the Databricks App has no
internet, so the scheduler refuses the job there with a log line.

Files go to ``DATA_DIR/regwatch/`` (``watch-<date>.json``, ``.md``, ``update-package-<date>.zip``,
new texts under ``sources/<id>/incoming/<date>/``). One ``regwatch_run`` row and one
``regwatch_run`` chain record (counts and hashes only). Nothing is applied to RegKB.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402

log = logging.getLogger(__name__)
TABLE = "regwatch_run"
MAX_ERROR = 300


def out_dir(settings: Settings) -> Path:
    return Path(settings.data_dir).resolve() / "regwatch"


def refused_reason(settings: Settings) -> str | None:
    """Why the job cannot run here, or None when it can."""
    if not settings.regwatch_enabled:
        return "REGWATCH_ENABLED is off"
    if settings.supervisor_mode == "databricks_app":
        return "the Databricks App has no internet; run the watcher on the dev host or a laptop"
    return None


def enabled(settings: Settings) -> bool:
    """Listed by the scheduler only when it can run. A refusal in App mode is logged."""
    reason = refused_reason(settings)
    if reason and settings.regwatch_enabled:
        log.warning("regwatch job refused: %s", reason)
    return reason is None


def run(
    ctx: MonitorContext, settings: Settings, fetcher: Any = None, signer: Any = None
) -> dict[str, Any]:
    from supervisor.regkb import watch

    reason = refused_reason(settings)
    if reason:
        raise SupervisorError(f"regwatch_off: {reason}")
    now = datetime.now(UTC)
    run_id = watch.new_run_id(now)
    row = ctx.state.insert(
        TABLE,
        {
            "run_id": run_id,
            "started_at": now,
            "status": "running",
            "instruments_checked": 0,
            "changes_found": 0,
        },
    )
    target = out_dir(settings)
    try:
        signer = signer or getattr(ctx.evidence, "signer", None)
        if signer is None:
            from supervisor.evidence.signer import build_signer

            signer = build_signer(settings)
        done = watch.run_and_package(
            fetcher or watch.ToolFetcher(),
            target,
            signer,
            sources_root=target / "sources",
            now=now,
        )
    except Exception as exc:  # noqa: BLE001 - record the failure, then let the scheduler log it
        msg = f"{type(exc).__name__}: {exc}"[:MAX_ERROR]
        ctx.state.update(
            TABLE,
            {"run_id": run_id},
            {"status": "error", "finished_at": datetime.now(UTC), "error": msg},
            int(row["row_version"]),
        )
        raise
    report = done["report"]
    summary = report["summary"]
    ctx.state.update(
        TABLE,
        {"run_id": run_id},
        {
            "status": report["status"],
            "finished_at": datetime.now(UTC),
            "instruments_checked": int(summary["instruments_checked"]),
            "changes_found": int(summary["changes_found"]),
            "report_sha256": done["report_sha256"],
            "package_sha256": done["package_sha256"],
        },
        int(row["row_version"]),
    )
    ctx.evidence.record(
        "regwatch_run",
        run_id,
        {
            "run_id": run_id,
            "status": str(report["status"]),
            "instruments_checked": int(summary["instruments_checked"]),
            "changes_found": int(summary["changes_found"]),
            "new_candidates": int(summary["new_candidates"]),
            "incoming_files": int(summary["incoming_files"]),
            "errors": int(summary["errors"]),
            "report_sha256": done["report_sha256"],
            "package_sha256": done["package_sha256"],
        },
    )
    return {
        "run_id": run_id,
        "status": report["status"],
        "instruments_checked": int(summary["instruments_checked"]),
        "changes_found": int(summary["changes_found"]),
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="python -m supervisor.jobs.regwatch", description=__doc__.splitlines()[0]
    ).parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            reason = refused_reason(settings)
            if reason:
                print(ascii_line(f"[SKIP] regwatch: {reason}"))  # noqa: T201
                return 0
            result = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] regwatch: {exc}"))  # noqa: T201
        return 1
    print(ascii_line("[OK] regwatch: " + ", ".join(f"{k}={v}" for k, v in result.items())))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
