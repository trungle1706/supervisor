"""Run packs against a target: validate runner output, apply thresholds, record results.

The engine, not the runner, decides pass or fail:

* a runner exception becomes status ``error`` (the run never crashes);
* runner output is validated (metrics int or None, details JSON-safe, no floats);
* fewer than ``pack.min_items`` items -> ``skip``; a runner skip -> ``skip``;
* thresholds per metric follow :class:`~supervisor.assurance.model.Threshold`;
  a pack with thresholds whose metrics are all ``None`` is ``skip`` ("metrics not
  computable"); a skipped pack is never ``ok``;
* pack status: ``fail`` if any metric fails, else ``warn`` if any warns, else ``ok``.

Outputs: ``eval_result`` rows (one ``eval_run`` row per run), one ``assurance_result``
evidence record per result (integers, strings and booleans only), and ``results.json`` +
``report.md`` in ``out_dir``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from supervisor.assurance.loader import PACKS_DIR, manifest_sha256, pack_path
from supervisor.assurance.model import (
    EvalPack,
    MetricStatusT,
    PackResult,
    RunContext,
    RunnerOutput,
    StatusT,
)
from supervisor.assurance.registry import resolve_runner
from supervisor.assurance.results import (
    RunSummary,
    count_statuses,
    dumps_results,
    summary_to_dict,
)
from supervisor.core.errors import SupervisorError
from supervisor.core.ports import Clock, EvidenceSink, TableStore
from supervisor.evidence.chain import check_no_floats

EVIDENCE_TYPE = "assurance_result"
MAX_REASON_CHARS = 240
MAX_DETAIL_DEPTH = 8


class EngineError(SupervisorError):
    """The engine cannot run (bad arguments), as opposed to a failing pack."""


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


# --------------------------------------------------------------------------- validation


def _json_safe(value: Any, path: str = "details", depth: int = 0) -> str | None:
    """None when ``value`` is JSON-safe without floats, else a problem text."""
    if depth > MAX_DETAIL_DEPTH:
        return f"{path}: nested too deep"
    if value is None or isinstance(value, bool | int | str):
        return None
    if isinstance(value, float):
        return f"{path}: float value {value!r} (use integers: bp, counts, ms)"
    if isinstance(value, list | tuple):
        for i, v in enumerate(value):
            err = _json_safe(v, f"{path}[{i}]", depth + 1)
            if err:
                return err
        return None
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                return f"{path}: key {k!r} is not a string"
            err = _json_safe(v, f"{path}.{k}", depth + 1)
            if err:
                return err
        return None
    return f"{path}: {type(value).__name__} is not JSON-safe"


def validate_output(pack: EvalPack, out: Any) -> str | None:
    """None when the runner output is acceptable, else the reason it is not."""
    if not isinstance(out, RunnerOutput):
        return f"runner returned {type(out).__name__}, not RunnerOutput"
    if out.status not in ("ok", "skip"):
        return f"runner status {out.status!r} is not ok or skip"
    known = {m.name for m in pack.metrics}
    for name, value in out.metrics.items():
        if name not in known:
            return f"metric {name!r} is not declared in the manifest"
        if value is not None and (type(value) is not int):
            return f"metric {name} is {type(value).__name__} {value!r}; only int or None"
    if type(out.n_items) is not int or out.n_items < 0:
        return f"n_items must be a non-negative int, got {out.n_items!r}"
    return _json_safe(out.details)


# --------------------------------------------------------------------------- thresholds


def metric_verdict(direction: str, value: int | None, go: int, no_go: int) -> MetricStatusT:
    """``pass`` / ``warn`` / ``fail`` / ``na`` for one metric (rules in model.Threshold)."""
    if value is None:
        return "na"
    if direction == "higher_better":
        if value >= go:
            return "pass"
        return "fail" if value < no_go else "warn"
    if value <= go:
        return "pass"
    return "fail" if value > no_go else "warn"


def apply_thresholds(
    pack: EvalPack, metrics: Mapping[str, int | None]
) -> tuple[dict[str, MetricStatusT], list[str], StatusT]:
    """(metric_status, reasons, status) for computed ``metrics``.

    Metrics without a threshold are ``na`` (informational). All thresholded metrics
    ``None`` -> status ``skip``."""
    ms: dict[str, MetricStatusT] = {}
    reasons: list[str] = []
    thresholded = 0
    computed = 0
    for spec in pack.metrics:
        value = metrics.get(spec.name)
        thr = pack.threshold(spec.name)
        if thr is None:
            ms[spec.name] = "na"
            continue
        thresholded += 1
        verdict = metric_verdict(spec.direction, value, thr.go, thr.no_go)
        ms[spec.name] = verdict
        if value is not None:
            computed += 1
        op_go = ">=" if spec.direction == "higher_better" else "<="
        if verdict == "fail":
            reasons.append(
                f"{spec.name}={value} misses no-go limit {thr.no_go} (go {op_go} {thr.go})"
            )
        elif verdict == "warn":
            reasons.append(f"{spec.name}={value} is in the warn band (go {op_go} {thr.go})")
        elif verdict == "na":
            reasons.append(f"{spec.name} not computable")
    if thresholded and computed == 0:
        return ms, ["metrics not computable"], "skip"
    if "fail" in ms.values():
        return ms, reasons, "fail"
    if "warn" in ms.values():
        return ms, reasons, "warn"
    return ms, reasons, "ok"


# --------------------------------------------------------------------------- one pack


def _short(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_REASON_CHARS else text[: MAX_REASON_CHARS - 3] + "..."


def _result(
    pack: EvalPack,
    run_id: str,
    target: Any,
    started: datetime,
    finished: datetime,
    status: StatusT,
    *,
    reasons: list[str],
    metrics: Mapping[str, int | None] | None = None,
    metric_status: Mapping[str, MetricStatusT] | None = None,
    out: RunnerOutput | None = None,
) -> PackResult:
    metrics = dict(metrics or {})
    return PackResult(
        run_id=run_id,
        pack_id=pack.id,
        pack_version=pack.version,
        dimension=pack.dimension,
        target_kind=target.kind,
        target_id=str(target.target_id),
        status=status,
        metrics={m.name: metrics.get(m.name) for m in pack.metrics} if metrics else {},
        metric_status=dict(metric_status or {}),
        reasons=reasons,
        n_items=out.n_items if out else 0,
        data_mode=str(out.data_mode) if out else "",
        dataset_id=out.dataset_id if out else "",
        dataset_sha256=out.dataset_sha256 if out else "",
        is_mock=bool((out.is_mock if out else False) or getattr(target, "is_mock", False)),
        launch_gate=pack.launch_gate,
        judge_gate=pack.judge_gate,
        started_at=started,
        finished_at=finished,
        details=dict(out.details) if out else {},
    )


def run_pack(
    pack: EvalPack,
    runner: Any,
    ctx: RunContext,
    run_id: str,
    clock: Clock,
) -> PackResult:
    """Run one pack on ``ctx.target``. Never raises for a runner problem."""
    target = ctx.target
    started = clock.now()
    try:
        out = runner.run(pack, ctx)
    except Exception as exc:  # noqa: BLE001 - one broken runner must not stop the run
        return _result(
            pack,
            run_id,
            target,
            started,
            clock.now(),
            "error",
            reasons=[_short(f"{type(exc).__name__}: {exc}")],
        )
    finished = clock.now()
    problem = validate_output(pack, out)
    if problem:
        return _result(
            pack,
            run_id,
            target,
            started,
            finished,
            "error",
            reasons=[_short(f"invalid runner output: {problem}")],
        )
    if out.status == "skip":
        return _result(
            pack,
            run_id,
            target,
            started,
            finished,
            "skip",
            reasons=[_short(out.skip_reason or "skipped by the runner")],
            metrics=out.metrics,
            out=out,
        )
    if out.n_items < pack.min_items:
        return _result(
            pack,
            run_id,
            target,
            started,
            finished,
            "skip",
            reasons=[f"too few items: {out.n_items} < {pack.min_items}"],
            metrics=out.metrics,
            out=out,
        )
    metric_status, reasons, status = apply_thresholds(pack, out.metrics)
    return _result(
        pack,
        run_id,
        target,
        started,
        finished,
        status,
        reasons=reasons,
        metrics=out.metrics,
        metric_status=metric_status,
        out=out,
    )


# --------------------------------------------------------------------------- records


def _threshold_map(pack: EvalPack) -> dict[str, dict[str, int]]:
    return {t.metric: {"go": t.go, "no_go": t.no_go} for t in pack.thresholds}


def summary_thresholds(pack: EvalPack) -> dict[str, dict[str, Any]]:
    """Thresholds for results.json and the report: go, no_go and the metric direction."""
    return {
        t.metric: {"go": t.go, "no_go": t.no_go, "direction": pack.metric(t.metric).direction}
        for t in pack.thresholds
    }


def evidence_payload(r: PackResult, pack: EvalPack, manifest_hash: str) -> dict[str, Any]:
    """The ``assurance_result`` chain payload: ints, strings, bools and nulls only."""
    return {
        "run_id": r.run_id,
        "pack_id": r.pack_id,
        "pack_version": r.pack_version,
        "manifest_sha256": manifest_hash,
        "dimension": r.dimension,
        "target_kind": r.target_kind,
        "target_id": r.target_id,
        "status": r.status,
        "metrics": dict(r.metrics),
        "metric_status": dict(r.metric_status),
        "thresholds": _threshold_map(pack),
        "n_items": r.n_items,
        "data_mode": r.data_mode,
        "dataset_id": r.dataset_id,
        "dataset_sha256": r.dataset_sha256,
        "is_mock": r.is_mock,
        "launch_gate": r.launch_gate,
        "judge_gate": r.judge_gate,
        "reasons": list(r.reasons),
    }


def result_row(r: PackResult, pack: EvalPack, manifest_hash: str) -> dict[str, Any]:
    return {
        "run_id": r.run_id,
        "ts": r.finished_at,
        "pack_id": r.pack_id,
        "pack_version": r.pack_version,
        "manifest_sha256": manifest_hash,
        "dimension": r.dimension,
        "target_kind": r.target_kind,
        "target_id": r.target_id,
        "status": r.status,
        "metrics": dict(r.metrics),
        "metric_status": dict(r.metric_status),
        "thresholds": _threshold_map(pack),
        "reasons": "; ".join(r.reasons),
        "n_items": r.n_items,
        "data_mode": r.data_mode,
        "dataset_id": r.dataset_id,
        "dataset_sha256": r.dataset_sha256,
        "is_mock": r.is_mock,
        "launch_gate": r.launch_gate,
        "judge_gate": r.judge_gate,
        "details": dict(r.details),
        "evidence_hash": r.evidence_hash or None,
    }


def _manifest_hash(pack: EvalPack, packs_dir: Path) -> str:
    """Hash of the manifest file; when the file is not on disk, of the parsed manifest."""
    path = pack_path(pack.id, packs_dir)
    if path.is_file():
        return manifest_sha256(path)
    import hashlib

    return hashlib.sha256(pack.model_dump_json().encode("utf-8")).hexdigest()


def new_run_id(clock: Clock | None = None) -> str:
    now = (clock or _SYSTEM).now()
    return f"run-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"


_SYSTEM = _SystemClock()


# --------------------------------------------------------------------------- public API


def execute(
    packs: Sequence[EvalPack],
    target: Any,
    ctx: RunContext,
    run_id: str,
    clock: Clock,
    overrides: Mapping[str, Any] | None = None,
    on_result: Callable[[PackResult, EvalPack], None] | None = None,
) -> list[PackResult]:
    """Run every pack that lists ``target.kind``; no storage. Used by run_packs/run_many."""
    results: list[PackResult] = []
    for pack in sorted(packs, key=lambda p: p.id):
        if target.kind not in pack.targets:
            continue
        try:
            runner = resolve_runner(pack, overrides)
        except SupervisorError as exc:
            now = clock.now()
            res = _result(pack, run_id, target, now, now, "error", reasons=[_short(str(exc))])
        else:
            res = run_pack(pack, runner, ctx, run_id, clock)
        results.append(res)
        if on_result is not None:
            on_result(res, pack)
    return results


def finish_run(
    packs: Sequence[EvalPack],
    results: list[PackResult],
    run_id: str,
    started: datetime,
    clock: Clock,
    *,
    target_spec: str = "",
    selector: str = "",
    tables: TableStore | None = None,
    sink: EvidenceSink | None = None,
    out_dir: Path | str | None = None,
    packs_dir: Path | str = PACKS_DIR,
    settings_digest: str | None = None,
    notes: Sequence[str] = (),
) -> RunSummary:
    """Record ``results`` (chain, tables) and write the files; return the summary."""
    by_id = {p.id: p for p in packs}
    hashes = {p.id: _manifest_hash(p, Path(packs_dir)) for p in packs}
    # (b) evidence first, so the entry hash goes into the row
    if sink is not None:
        for r in results:
            pack = by_id[r.pack_id]
            payload = evidence_payload(r, pack, hashes[r.pack_id])
            check_no_floats(payload)
            r.evidence_hash = sink.record(
                EVIDENCE_TYPE, f"{r.run_id}:{r.pack_id}:{r.target_id}", payload
            )
    finished = clock.now()
    counts = count_statuses(results)
    summary = RunSummary(
        run_id=run_id,
        results=results,
        counts=counts,
        started_at=started,
        finished_at=finished,
        target_spec=target_spec,
        selector=selector,
        is_mock=any(r.is_mock for r in results),
        out_dir=str(out_dir) if out_dir else None,
        notes=list(notes),
        thresholds={p.id: summary_thresholds(p) for p in packs},
    )
    # (a) tables
    if tables is not None:
        if results:
            tables.append(
                "eval_result", [result_row(r, by_id[r.pack_id], hashes[r.pack_id]) for r in results]
            )
        tables.append(
            "eval_run",
            [
                {
                    "run_id": run_id,
                    "started_at": started,
                    "finished_at": finished,
                    "target_spec": target_spec,
                    "selector": selector,
                    "packs_total": len(results),
                    "ok": counts["ok"],
                    "warn": counts["warn"],
                    "fail": counts["fail"],
                    "skip": counts["skip"],
                    "error": counts["error"],
                    "is_mock": summary.is_mock,
                    "settings_digest": settings_digest,
                    "out_dir": str(out_dir) if out_dir else None,
                }
            ],
        )
    # (c) files
    if out_dir is not None:
        from supervisor.assurance.report import render_markdown

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(dumps_results(summary_to_dict(summary)), encoding="utf-8")
        (out / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    return summary


def run_packs(
    packs: Sequence[EvalPack],
    target: Any,
    ctx: RunContext,
    *,
    run_id: str | None = None,
    tables: TableStore | None = None,
    sink: EvidenceSink | None = None,
    out_dir: Path | str | None = None,
    overrides: Mapping[str, Any] | None = None,
    clock: Clock | None = None,
    packs_dir: Path | str = PACKS_DIR,
    target_spec: str = "",
    selector: str = "",
    settings_digest: str | None = None,
) -> RunSummary:
    """Run ``packs`` on one ``target`` and record the results (see module docstring)."""
    clock = clock or _SYSTEM
    run_id = run_id or new_run_id(clock)
    if ctx.target is not target:
        ctx.target = target
    started = clock.now()
    results = execute(packs, target, ctx, run_id, clock, overrides)
    return finish_run(
        packs,
        results,
        run_id,
        started,
        clock,
        target_spec=target_spec or f"{target.kind}:{target.target_id}",
        selector=selector,
        tables=tables,
        sink=sink,
        out_dir=out_dir,
        packs_dir=packs_dir,
        settings_digest=settings_digest,
    )
