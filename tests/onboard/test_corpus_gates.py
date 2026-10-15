"""WP16 gates: Discover + Understand measured on the labelled corpus (data/corpus).

Thresholds come only from ``supervisor.onboard.eval.gates`` (WP15 reuses them).
"""

from __future__ import annotations

import pytest

from supervisor.onboard.eval import gates
from supervisor.onboard.eval.labels import check_labels, load_labels
from supervisor.onboard.eval.runner import EvalResult, run_eval
from tests.conftest import REPO_ROOT

CORPUS = REPO_ROOT / "data" / "corpus" / "repos"
LABELS = REPO_ROOT / "data" / "corpus" / "labels.yaml"


@pytest.fixture(scope="module")
def result() -> EvalResult:
    return run_eval(CORPUS, LABELS)


def test_labels_match_the_corpus() -> None:
    labels = load_labels(LABELS)
    assert check_labels(CORPUS, labels) == []
    assert len(labels.repos) >= gates.MIN_REPOS
    on_disk = {p.name for p in CORPUS.iterdir() if p.is_dir()}
    assert on_disk == set(labels.repos), "every corpus repo has labels and vice versa"


def test_tools_gates(result: EvalResult) -> None:
    m = result.metrics
    assert m["tools_recall_bp"] >= gates.TOOLS_RECALL_MIN_BP
    assert m["tools_precision_bp"] >= gates.TOOLS_PRECISION_MIN_BP


def test_llm_calls_gate(result: EvalResult) -> None:
    assert result.metrics["llm_calls_recall_bp"] >= gates.LLM_CALLS_RECALL_MIN_BP


def test_framework_gate(result: EvalResult) -> None:
    assert result.metrics["framework_accuracy_bp"] >= gates.FRAMEWORK_ACCURACY_MIN_BP


def test_secrets_gates(result: EvalResult) -> None:
    assert result.metrics["secrets_scrubbed_bp"] >= gates.SECRETS_SCRUBBED_MIN_BP
    assert result.metrics["secrets_leaked"] <= gates.SECRETS_LEAKED_MAX


def test_injection_gate(result: EvalResult) -> None:
    assert result.metrics["injection_follow_through"] <= gates.INJECTION_FOLLOW_THROUGH_MAX


def test_latency_and_all_gates(result: EvalResult) -> None:
    assert result.elapsed_s <= gates.CORPUS_SECONDS_MAX
    failed = [g for g in gates.evaluate_gates(result.metrics) if not g["ok"]]
    assert failed == []
    assert result.all_gates_ok
