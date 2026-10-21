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


def build_registry(masker: Masker, *, judge: object | None = None) -> DetectorRegistry:
    """The catalogue from code: dlp_vn, injection_regex, judge_advisory (mock judge by default)."""
    from supervisor.core.detectors import DetectorRegistry
    from supervisor.detectors.dlp_vn import DlpVnDetector
    from supervisor.detectors.injection_regex import InjectionRegexDetector
    from supervisor.detectors.judge_advisory import JudgeAdvisoryDetector

    return DetectorRegistry(
        [
            DlpVnDetector(masker),
            InjectionRegexDetector(masker),
            JudgeAdvisoryDetector(masker, judge),  # type: ignore[arg-type]
        ]
    )
