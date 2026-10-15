"""Read models for the Assurance screen (WP17): ``eval_run`` and ``eval_result`` rows.

Read only. Rows are plain dicts; integers and strings only (the tables hold no floats).
"""

from __future__ import annotations

import re
from typing import Any

from supervisor.core.errors import SupervisorError

RUN_LIMIT = 50
_RUN_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
STATUS_PILL = {"ok": "ok", "warn": "warn", "fail": "bad", "error": "bad", "skip": "neutral"}


class AssuranceInputError(SupervisorError):
    """Bad run id or unknown run (HTTP 400)."""


def check_run_id(run_id: str) -> str:
    if not _RUN_ID.match(run_id or ""):
        raise AssuranceInputError("invalid run id")
    return run_id


def runs(tables: Any, limit: int = RUN_LIMIT) -> list[dict[str, Any]]:
    """Newest runs first."""
    rows = tables.query("eval_run", order_by=("-started_at",), limit=limit)
    return [dict(r) for r in rows]


def _metric_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    thr = row.get("thresholds") or {}
    status = row.get("metric_status") or {}
    out = []
    for name, value in sorted((row.get("metrics") or {}).items()):
        t = thr.get(name) or {}
        go, no_go = t.get("go"), t.get("no_go")
        op = "-" if go is None or no_go is None else (">=" if go >= no_go else "<=")
        out.append(
            {
                "name": name,
                "value": value,
                "status": status.get(name, "na"),
                "go": go,
                "no_go": no_go,
                "op": op,
            }
        )
    return out


def run_detail(tables: Any, run_id: str) -> dict[str, Any]:
    """One run: its summary row and the per-pack results (pack, then target)."""
    check_run_id(run_id)
    found = tables.query("eval_run", {"run_id": run_id}, limit=1)
    rows = tables.query("eval_result", {"run_id": run_id}, order_by=("pack_id", "target_id"))
    if not found and not rows:
        raise AssuranceInputError(f"no assurance run {run_id!r}")
    results = []
    for r in rows:
        d = dict(r)
        reasons = d.get("reasons") or ""
        d["reason_list"] = [x for x in str(reasons).split("; ") if x]
        d["metric_rows"] = _metric_rows(d)
        d["pill"] = STATUS_PILL.get(str(d.get("status")), "neutral")
        d["record_ref"] = f"{d['run_id']}:{d['pack_id']}:{d['target_id']}"
        d["evidence_hash"] = d.get("evidence_hash") or ""
        results.append(d)
    return {"run": dict(found[0]) if found else None, "run_id": run_id, "results": results}
