"""Governance shared core (WP-G0; docs/governance.md).

The AI system entity: the unit of governance. People are scoped to the systems they are on;
agents and inventory nodes are linked to a system as components. Off by default
(GOVERNANCE_ENABLED).
"""

from supervisor.governance.model import (
    LINK_ROLES,
    RISK_LEVELS,
    TEAM_ROLES,
    SystemsError,
)

__all__ = ["LINK_ROLES", "RISK_LEVELS", "TEAM_ROLES", "SystemsError"]
