"""Injection classifier detector, Vietnamese and English (WP25, ADR D27).

``score_tool_description`` is the adapter for the tool-locking gateway (WP26,
``mcp_lock.register_description_scorer``). Everything else is imported lazily from the submodules
(``detector``, ``model``, ``features``, ``units``, ``validation``).
"""

from __future__ import annotations

from supervisor.detectors.injection_classifier.detector import (
    MODEL_VERSION,
    InjectionClassifierDetector,
    score_tool_description,
)

__all__ = ["MODEL_VERSION", "InjectionClassifierDetector", "score_tool_description"]
