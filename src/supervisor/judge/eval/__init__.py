"""Judge eval harness: ``python -m supervisor.judge.eval --model mock``.

See ``datasets.py`` for the four sets and the held-out rule, ``harness.py`` for metrics.
"""

from __future__ import annotations

from supervisor.judge.eval.datasets import EvalItem, build_eval_sets, heldout_digest
from supervisor.judge.eval.harness import ascii_table, cohen_kappa_bp, run_eval

__all__ = [
    "EvalItem",
    "ascii_table",
    "build_eval_sets",
    "cohen_kappa_bp",
    "heldout_digest",
    "run_eval",
]
