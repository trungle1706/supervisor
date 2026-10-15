"""Run the analyser over the corpus and score it."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.onboard.eval.gates import CORPUS_SECONDS_MAX, evaluate_gates
from supervisor.onboard.eval.labels import load_labels
from supervisor.onboard.eval.metrics import aggregate, gate_metrics, score_repo
from supervisor.onboard.eval.predict import predict_repo


@dataclass
class EvalResult:
    corpus: str
    repos: list[dict[str, Any]]
    fields: dict[str, dict[str, Any]]
    metrics: dict[str, Any]
    gates: list[dict[str, Any]]  # includes the timing gate (in memory only)
    elapsed_s: float = 0.0
    latency_ok: bool = True
    all_gates_ok: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def run_eval(
    corpus_dir: str | Path, labels_path: str | Path, repos: Sequence[str] | None = None
) -> EvalResult:
    """Evaluate the repos (default: all labelled ones) in sorted order. No network.

    Raises ValueError for unknown repo names or a labelled repo without a folder.
    """
    started = time.monotonic()
    root = Path(corpus_dir)
    labels = load_labels(labels_path)
    names = sorted(set(repos) if repos else labels.repos)
    for n in names:
        if n not in labels.repos:
            raise ValueError(f"repo has no labels: {n}")
        if not (root / n).is_dir():
            raise ValueError(f"repo folder missing: {n}")
    total: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for n in names:
        counts, misses, wrong = score_repo(predict_repo(root / n), labels.repos[n])
        total.update(counts)
        rows.append(
            {
                "name": n,
                "misses": dict(sorted(misses.items())),
                "wrong": dict(sorted(wrong.items())),
                "secrets_leaked": counts["secrets.leaked"],
                "injection_follow_through": bool(counts["injections.follow_through"]),
            }
        )
    fields = aggregate(total)
    metrics = gate_metrics(fields, len(names))
    elapsed = time.monotonic() - started
    metrics["corpus_seconds"] = int(elapsed + 0.999)
    gates = evaluate_gates(metrics)
    latency_ok = elapsed <= CORPUS_SECONDS_MAX
    return EvalResult(
        corpus=root.name,
        repos=rows,
        fields=fields,
        metrics=metrics,
        gates=gates,
        elapsed_s=elapsed,
        latency_ok=latency_ok,
        all_gates_ok=all(g["ok"] for g in gates),
    )
