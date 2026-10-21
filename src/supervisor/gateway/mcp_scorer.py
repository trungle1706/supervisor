"""WP25 classifier score in the MCP tool lock (integration wave 2; WP26 hook, WP25 adapter).

``install(settings)`` registers ``score_tool_description`` with
``mcp_lock.register_description_scorer`` only when the classifier is switched on: the same
switch as the detector, ``DETECTORS_ENABLED=1`` and ``detectors.injection_classifier.enabled:
true`` in ``DETECTORS_CONFIG`` (shipped ``false``). Otherwise the scorer is cleared and
``scan.score_bp`` stays empty, as before.

The score is REPORT ONLY (R1): it is stored as ``scan.score_bp`` and changes neither
``suspicious`` nor the lock. One deterministic exception, the reviewers' recommendation (WP25
review question 6, WP26 integration note): when the model weights are refused (SHA-256 not equal
to the model card, ``ModelIntegrityError``) the scorer raises ``mcp_lock.ScorerRefused``. The scan
then records the finding ``scorer_refused``; the tool is held for two-person review (also on
trust-on-first-use) and a high review case opens. That is a registration hold on a fact (the
weights did not verify), not a classifier verdict on a call.
"""

from __future__ import annotations

import logging
from typing import Any

from supervisor.gateway import mcp_lock

log = logging.getLogger("supervisor.mcp_scorer")

SLUG = "injection_classifier"


def classifier_enabled(settings: Any) -> bool:
    """True when DETECTORS_ENABLED is on and the classifier entry of DETECTORS_CONFIG says
    ``enabled: true``. A config that cannot be read counts as off (the detector start-up check
    reports it)."""
    if not getattr(settings, "detectors_enabled", False):
        return False
    from supervisor.detectors.config import ConfigError, load_config

    try:
        entry = load_config(settings.detectors_config).detectors.get(SLUG)
    except (ConfigError, OSError, ValueError):
        return False
    return bool(entry is not None and entry.enabled)


def score(text: str) -> int:
    """``score_tool_description`` with the refused-weights case mapped to ``ScorerRefused``."""
    from supervisor.detectors.injection_classifier import score_tool_description
    from supervisor.detectors.injection_classifier.model import ModelIntegrityError

    try:
        return score_tool_description(text)
    except ModelIntegrityError as exc:
        raise mcp_lock.ScorerRefused("classifier weights refused") from exc


def install(settings: Any) -> bool:
    """Register (or clear) the scorer for this process. Returns True when it is registered."""
    on = classifier_enabled(settings)
    mcp_lock.register_description_scorer(score if on else None)
    if on:
        log.info("mcp tool lock: injection classifier score registered (report only)")
    return on
