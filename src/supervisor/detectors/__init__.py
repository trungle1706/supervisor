"""Detector implementations and the default catalogue (WP37, ADR D23, docs/detectors.md).

The contract (``Detector``, ``Finding``, ``DetectorRegistry``) lives in
``supervisor.core.detectors``. This package holds the detectors the product ships, the config
loader (``config/detectors.yaml``) and the evaluation harness
(``python -m supervisor.detectors.harness``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supervisor.core.detectors import DetectorRegistry
    from supervisor.core.ports import Masker

__all__ = ["build_registry"]


def build_registry(
    masker: Masker, *, judge: object | None = None, guard: object | None = None
) -> DetectorRegistry:
    """The catalogue from code: dlp_vn, injection_regex, injection_classifier (WP25), judge_advisory
    (mock judge by default), guard_model (WP-D3; ``guard`` is its port, with None the detector
    reports ``execution_failed`` until ``set_port`` is called)."""
    from supervisor.core.detectors import DetectorRegistry
    from supervisor.detectors.dlp_vn import DlpVnDetector
    from supervisor.detectors.guard_model import GuardModelDetector  # WP-D3
    from supervisor.detectors.injection_classifier.detector import InjectionClassifierDetector
    from supervisor.detectors.injection_regex import InjectionRegexDetector
    from supervisor.detectors.judge_advisory import JudgeAdvisoryDetector
    from supervisor.detectors.judge_moderation import JudgeModerationDetector  # WP-D4
    from supervisor.detectors.memo_masker import MemoMasker

    masker = MemoMasker(masker)  # WP41: three detectors mask the same long text once
    return DetectorRegistry(
        [
            DlpVnDetector(masker),
            InjectionRegexDetector(masker),
            InjectionClassifierDetector(masker),  # WP25: weights load on first use
            JudgeAdvisoryDetector(masker, judge),  # type: ignore[arg-type]
            JudgeModerationDetector(masker, judge),  # type: ignore[arg-type]  # WP-D4
            GuardModelDetector(masker, guard),  # type: ignore[arg-type]  # WP-D3
        ]
    )
