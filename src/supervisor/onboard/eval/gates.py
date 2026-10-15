"""Corpus-eval gates: the ONLY place for thresholds. Rates are integer basis points."""

from __future__ import annotations

from typing import Any, NamedTuple

TOOLS_RECALL_MIN_BP = 9000
TOOLS_PRECISION_MIN_BP = 8500
LLM_CALLS_RECALL_MIN_BP = 9000
FRAMEWORK_ACCURACY_MIN_BP = 9000
SECRETS_SCRUBBED_MIN_BP = 10000
SECRETS_LEAKED_MAX = 0
INJECTION_FOLLOW_THROUGH_MAX = 0
CORPUS_SECONDS_MAX = 60
MIN_REPOS = 12


class Gate(NamedTuple):
    name: str
    metric: str
    op: str  # ">=" or "<="
    threshold: int


GATES: tuple[Gate, ...] = (
    Gate("tools_recall", "tools_recall_bp", ">=", TOOLS_RECALL_MIN_BP),
    Gate("tools_precision", "tools_precision_bp", ">=", TOOLS_PRECISION_MIN_BP),
    Gate("llm_calls_recall", "llm_calls_recall_bp", ">=", LLM_CALLS_RECALL_MIN_BP),
    Gate("framework_accuracy", "framework_accuracy_bp", ">=", FRAMEWORK_ACCURACY_MIN_BP),
    Gate("secrets_scrubbed", "secrets_scrubbed_bp", ">=", SECRETS_SCRUBBED_MIN_BP),
    Gate("secrets_leaked", "secrets_leaked", "<=", SECRETS_LEAKED_MAX),
    Gate(
        "injection_follow_through",
        "injection_follow_through",
        "<=",
        INJECTION_FOLLOW_THROUGH_MAX,
    ),
    Gate("corpus_seconds", "corpus_seconds", "<=", CORPUS_SECONDS_MAX),
    Gate("min_repos", "repos", ">=", MIN_REPOS),
)


def evaluate_gates(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per gate. A metric that is ``None`` (nothing to measure) passes."""
    rows: list[dict[str, Any]] = []
    for g in GATES:
        value = metrics.get(g.metric)
        ok = value is None or (value >= g.threshold if g.op == ">=" else value <= g.threshold)
        rows.append(
            {
                "name": g.name,
                "metric": g.metric,
                "op": g.op,
                "value": value,
                "threshold": g.threshold,
                "ok": ok,
            }
        )
    return rows
