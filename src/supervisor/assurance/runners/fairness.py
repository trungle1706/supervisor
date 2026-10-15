"""Bias and fairness pack runners (WP17, dimension bias_fairness).

Thin re-export module; the code lives in ``fairness_common`` (shared helpers),
``fairness_qa`` (BBQ, WinoBias), ``fairness_text`` (BOLD, CrowS-Pairs, StereoSet) and
``fairness_decisions`` (group metrics, four-fifths rule, counterfactual probes).
"""

from __future__ import annotations

from supervisor.assurance.runners.fairness_decisions import (
    CounterfactualRunner,
    FairnessMetricsRunner,
    FourFifthsRunner,
)
from supervisor.assurance.runners.fairness_qa import BbqRunner, WinoBiasRunner
from supervisor.assurance.runners.fairness_text import (
    BoldRunner,
    CrowsPairsRunner,
    StereoSetRunner,
)

__all__ = [
    "BbqRunner",
    "BoldRunner",
    "CounterfactualRunner",
    "CrowsPairsRunner",
    "FairnessMetricsRunner",
    "FourFifthsRunner",
    "StereoSetRunner",
    "WinoBiasRunner",
]
