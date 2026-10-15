"""Retention job (PDPL storage limitation, ADR D13): null personal-data columns after their TTL.

Run: python -m supervisor.jobs.retention        (needs RETENTION_ENABLED=1)
Also callable in-process (scheduler): ``run(settings, adapters, chain=app_writer)``.

Classes come from ``retention:`` in schema/model.yaml:
``raw`` (RETENTION_RAW_DAYS), ``masked`` (RETENTION_MASKED_DAYS),
``notice`` (RETENTION_NOTICE_DAYS).
Rows are never deleted. Only the listed columns are set to NULL ('' when NOT NULL) on rows whose
``ts`` is older than now minus the class days. Digest columns and the chain tables are not touched.
RETENTION_DRY_RUN=1 counts only. On Delta (appendOnly) the append-only tables are report-only.
Each run writes one ``retention_run`` evidence entry (counts and cutoffs, integers only) when a
chain writer is given.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from datetime import timedelta  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.adapters.factory import Adapters, build_adapters  # noqa: E402
from supervisor.config import Settings, load_settings  # noqa: E402
from supervisor.core.canonical import format_ts  # noqa: E402
from supervisor.core.errors import AppendOnlyError, SupervisorError  # noqa: E402
from supervisor.core.ports import EvidenceSink  # noqa: E402

RECORD_TYPE = "retention_run"
DELTA_REASON = "Delta appendOnly: needs bank decision (see ADR D13)"
TRIGGER_HINT = (
    "an old append-only trigger blocks the UPDATE; refresh it with "
    "python -m supervisor.jobs.bootstrap_schema"
)


def class_days(settings: Settings) -> dict[str, int]:
    return {
        "raw": int(settings.retention_raw_days),
        "masked": int(settings.retention_masked_days),
        "notice": int(settings.retention_notice_days),
    }


def run(
    settings: Settings | None = None,
    adapters: Adapters | None = None,
    *,
    chain: EvidenceSink | None = None,
) -> dict[str, Any]:
    """Apply (or count) retention. Returns {status, ...}; status is ok, skipped or failed."""
    settings = settings or load_settings()
    if not settings.retention_enabled:
        return {"status": "skipped", "reason": "RETENTION_ENABLED=0", "items": []}
    adapters = adapters or build_adapters(settings)
    tables, model = adapters.tables, adapters.model
    now = adapters.clock.now()
    days = class_days(settings)
    delta = adapters.executor.dialect == "databricks"
    dry = bool(settings.retention_dry_run)
    items: list[dict[str, Any]] = []
    failed: list[str] = []
    for t in model.tables.values():
        for klass, cols in t.retention:
            cutoff = now - timedelta(days=days[klass])
            item: dict[str, Any] = {
                "table": t.name,
                "class": klass,
                "columns": list(cols),
                "cutoff": format_ts(cutoff),
                "due": 0,
                "redacted": 0,
                "mode": "apply",
            }
            items.append(item)
            try:
                item["due"] = tables.count_due(t.name, cols, "ts", cutoff)
                if dry:
                    item["mode"] = "dry_run"
                elif delta and t.append_only:
                    item["mode"] = "report_only"
                    item["reason"] = DELTA_REASON
                else:
                    item["redacted"] = tables.redact_columns(t.name, cols, "ts", cutoff, now=now)
            except AppendOnlyError as exc:
                item["mode"] = "failed"
                item["reason"] = f"{t.name}: {TRIGGER_HINT} ({str(exc)[:120]})"
                failed.append(item["reason"])
            except SupervisorError as exc:
                item["mode"] = "failed"
                item["reason"] = f"{t.name}: {str(exc)[:200]}"
                failed.append(item["reason"])
    result: dict[str, Any] = {
        "status": "failed" if failed else "ok",
        "dry_run": dry,
        "items": items,
        "failed": failed,
    }
    if chain is not None and not failed:
        payload = {
            "dry_run": dry,
            "classes": {
                k: {
                    "days": days[k],
                    "tables": {
                        i["table"]: {
                            "cutoff": i["cutoff"],
                            "due": i["due"],
                            "redacted": i["redacted"],
                            "mode": i["mode"],
                        }
                        for i in items
                        if i["class"] == k
                    },
                }
                for k in days
            },
        }
        result["entry_hash"] = chain.record(RECORD_TYPE, f"{RECORD_TYPE}:{format_ts(now)}", payload)
    return result


def _ascii(line: str) -> str:
    return line.encode("ascii", "backslashreplace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m supervisor.jobs.retention").parse_args(argv)
    settings = load_settings()
    if not settings.retention_enabled:
        print("[SKIP] RETENTION_ENABLED=0")
        return 0
    adapters = build_adapters(settings)
    writer = None
    try:
        from supervisor.evidence.chain import build_chain_writer

        try:
            # single-writer rule: do not run this while the app (which owns the chain) runs
            writer = build_chain_writer(settings, adapters.tables, adapters.clock)
        except SupervisorError as exc:
            print(_ascii(f"[SKIP] no evidence entry: {exc}"))
        result = run(settings, adapters, chain=writer)
    except SupervisorError as exc:
        print(_ascii(f"[FAIL] {exc}"))
        return 1
    finally:
        if writer is not None:
            writer.close(seal=False)
        adapters.close()
    for i in result["items"]:
        tag = {"failed": "[FAIL]", "report_only": "[SKIP]", "dry_run": "[SKIP]"}.get(
            i["mode"], "[OK]  "
        )
        note = f" ({i['reason']})" if i.get("reason") else ""
        print(
            _ascii(
                f"{tag} {i['table']} {i['class']}: due {i['due']}, redacted {i['redacted']}, "
                f"cutoff {i['cutoff']}, mode {i['mode']}{note}"
            )
        )
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
