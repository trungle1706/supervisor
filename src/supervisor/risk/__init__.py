"""Risk register (WP29, ADR D26; docs/risk-register.md).

Risks are first-class records linked to the inventory graph (WP24), to compliance matrix rows, to
gate rules, assurance packs and monitors. A rule hit at runtime is counted as evidence that a
control works, and the residual score follows the facts. Off by default (RISK_REGISTER_ENABLED).
"""

from supervisor.risk.model import (
    BANDS,
    CATEGORIES,
    LINK_KINDS,
    STATUSES,
    TREATMENTS,
    RiskConfig,
    RiskError,
    Thresholds,
    band_of,
    score_of,
)

__all__ = [
    "BANDS",
    "CATEGORIES",
    "LINK_KINDS",
    "STATUSES",
    "TREATMENTS",
    "RiskConfig",
    "RiskError",
    "Thresholds",
    "band_of",
    "score_of",
]
