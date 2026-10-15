"""Run summary, results.json (de)serialisation and reads of stored results.

``results.json`` is canonical JSON (``supervisor.core.canonical``): sorted keys, integers
only, RFC 3339 UTC timestamps. ``latest_results`` reads the newest ``eval_result`` row of
each pack for one target (what Launch, the judge gate and the console look at).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from supervisor.assurance.model import PackResult
from supervisor.core.canonical import canonical_json, format_ts
from supervisor.core.errors import SupervisorError

RESULTS_FORMAT = "supervisor-assurance-results"
RESULTS_VERSION = 1
STATUSES = ("ok", "warn", "fail", "skip", "error")


class ResultsError(SupervisorError):
    """results.json is missing, unreadable or not an assurance results file."""


@dataclass
class RunSummary:
    run_id: str
    results: list[PackResult]
    counts: dict[str, int]
    started_at: datetime
    finished_at: datetime
    target_spec: str = ""
    selector: str = ""
    is_mock: bool = False
    out_dir: str | None = None
    notes: list[str] = field(default_factory=list)
    # pack id -> metric -> {go, no_go, direction} (the manifest thresholds that applied)
    thresholds: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    @property
    def targets(self) -> list[tuple[str, str]]:
        """(target_kind, target_id) pairs in first-seen order."""
        seen: dict[tuple[str, str], None] = {}
        for r in self.results:
            seen.setdefault((r.target_kind, r.target_id), None)
        return list(seen)

    @property
    def failed(self) -> bool:
        """True when any result is ``fail`` or ``error`` (CLI exit code 1)."""
        return bool(self.counts.get("fail", 0) or self.counts.get("error", 0))


def count_statuses(results: Iterable[PackResult]) -> dict[str, int]:
    counts = dict.fromkeys(STATUSES, 0)
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


def result_to_dict(r: PackResult) -> dict[str, Any]:
    return {
        "run_id": r.run_id,
        "pack_id": r.pack_id,
        "pack_version": r.pack_version,
        "dimension": r.dimension,
        "target_kind": r.target_kind,
        "target_id": r.target_id,
        "status": r.status,
        "metrics": dict(r.metrics),
        "metric_status": dict(r.metric_status),
        "reasons": list(r.reasons),
        "n_items": r.n_items,
        "data_mode": r.data_mode,
        "dataset_id": r.dataset_id,
        "dataset_sha256": r.dataset_sha256,
        "is_mock": r.is_mock,
        "launch_gate": r.launch_gate,
        "judge_gate": r.judge_gate,
        "started_at": format_ts(r.started_at),
        "finished_at": format_ts(r.finished_at),
        "details": dict(r.details),
        "evidence_hash": r.evidence_hash,
    }


def summary_to_dict(s: RunSummary) -> dict[str, Any]:
    """Plain dict for results.json."""
    rows = []
    for r in s.results:
        d = result_to_dict(r)
        d["thresholds"] = {k: dict(v) for k, v in s.thresholds.get(r.pack_id, {}).items()}
        rows.append(d)
    return {
        "format": RESULTS_FORMAT,
        "version": RESULTS_VERSION,
        "run_id": s.run_id,
        "started_at": format_ts(s.started_at),
        "finished_at": format_ts(s.finished_at),
        "target_spec": s.target_spec,
        "selector": s.selector,
        "is_mock": s.is_mock,
        "counts": dict(s.counts),
        "notes": list(s.notes),
        "results": rows,
    }


def dumps_results(data: Mapping[str, Any]) -> str:
    """Canonical JSON when possible, plain sorted JSON otherwise (never floats here)."""
    try:
        return canonical_json(data) + "\n"
    except (TypeError, ValueError):
        return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str) + "\n"


def _ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ResultsError(f"bad timestamp {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def result_from_dict(d: Mapping[str, Any]) -> PackResult:
    try:
        return PackResult(
            run_id=str(d["run_id"]),
            pack_id=str(d["pack_id"]),
            pack_version=int(d["pack_version"]),
            dimension=str(d["dimension"]),
            target_kind=d["target_kind"],
            target_id=str(d["target_id"]),
            status=d["status"],
            metrics=dict(d.get("metrics") or {}),
            metric_status=dict(d.get("metric_status") or {}),
            reasons=[str(x) for x in d.get("reasons") or []],
            n_items=int(d.get("n_items") or 0),
            data_mode=str(d.get("data_mode") or ""),
            dataset_id=str(d.get("dataset_id") or ""),
            dataset_sha256=str(d.get("dataset_sha256") or ""),
            is_mock=bool(d.get("is_mock")),
            launch_gate=d.get("launch_gate", "advisory"),
            judge_gate=bool(d.get("judge_gate")),
            started_at=_ts(d["started_at"]),
            finished_at=_ts(d["finished_at"]),
            details=dict(d.get("details") or {}),
            evidence_hash=str(d.get("evidence_hash") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ResultsError(f"bad result row: {type(exc).__name__}: {exc}") from exc


def load_results_json(path: Path | str) -> dict[str, Any]:
    """Read a results.json (or a folder that holds one). Returns the plain dict."""
    p = Path(path)
    if p.is_dir():
        p = p / "results.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ResultsError(f"cannot read {p}: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise ResultsError(f"{p} is not valid JSON") from exc
    if not isinstance(data, dict) or data.get("format") != RESULTS_FORMAT:
        raise ResultsError(f"{p} is not an assurance results file")
    return data


def summary_from_dict(data: Mapping[str, Any]) -> RunSummary:
    results = [result_from_dict(r) for r in data.get("results") or []]
    thresholds = {
        str(r["pack_id"]): {k: dict(v) for k, v in r["thresholds"].items()}
        for r in data.get("results") or []
        if r.get("thresholds")
    }
    return RunSummary(
        run_id=str(data.get("run_id") or ""),
        results=results,
        counts=dict(data.get("counts") or count_statuses(results)),
        started_at=_ts(data["started_at"]),
        finished_at=_ts(data["finished_at"]),
        target_spec=str(data.get("target_spec") or ""),
        selector=str(data.get("selector") or ""),
        is_mock=bool(data.get("is_mock")),
        notes=[str(x) for x in data.get("notes") or []],
        thresholds=thresholds,
    )


def summary_from_store(tables: Any, run_id: str) -> RunSummary:
    """Rebuild a run summary from the ``eval_run`` and ``eval_result`` rows of ``run_id``."""
    runs = tables.query("eval_run", {"run_id": run_id}, limit=1)
    rows = tables.query("eval_result", {"run_id": run_id}, order_by=["pack_id", "target_id"])
    if not runs and not rows:
        raise ResultsError(f"no stored results for run id {run_id!r}")
    results: list[PackResult] = []
    thresholds: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        ts = _ts(row["ts"])
        d = dict(row)
        d["reasons"] = [x for x in str(row.get("reasons") or "").split("; ") if x]
        d["started_at"] = d["finished_at"] = ts
        d["evidence_hash"] = row.get("evidence_hash") or ""
        results.append(result_from_dict(d))
        thresholds[str(row["pack_id"])] = {
            m: {**t, "direction": "higher_better" if t["go"] >= t["no_go"] else "lower_better"}
            for m, t in (row.get("thresholds") or {}).items()
        }
    run = runs[0] if runs else {}
    first = min((r.started_at for r in results), default=datetime.now(UTC))
    return RunSummary(
        run_id=run_id,
        results=results,
        counts=count_statuses(results),
        started_at=_ts(run["started_at"]) if run else first,
        finished_at=_ts(run["finished_at"]) if run else first,
        target_spec=str(run.get("target_spec") or ""),
        selector=str(run.get("selector") or ""),
        is_mock=bool(run.get("is_mock")) if run else any(r.is_mock for r in results),
        out_dir=run.get("out_dir") if run else None,
        thresholds=thresholds,
    )


def latest_results(
    tables: Any,
    target_kind: str,
    target_id: str,
    pack_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Newest ``eval_result`` row per pack for one target (rows as dicts)."""
    rows = tables.query(
        "eval_result",
        {"target_kind": target_kind, "target_id": target_id},
        order_by=["-ts"],
    )
    wanted = set(pack_ids) if pack_ids is not None else None
    newest: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = str(row["pack_id"])
        if wanted is not None and pid not in wanted:
            continue
        if pid not in newest:
            newest[pid] = dict(row)
    return [newest[k] for k in sorted(newest)]
