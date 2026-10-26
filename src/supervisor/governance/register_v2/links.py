"""Where a "Register" link points (WP-N4a): the six-step workflow while CONSOLE_REGISTER_V2 is on
(with GOVERNANCE_ENABLED and CONSOLE_SYSTEMS_ENABLED it needs), else the old wizard. Ids are
URL-encoded. The query holds no language: the template adds it."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


def v2_on(settings: Any) -> bool:
    return bool(
        getattr(settings, "console_register_v2", False)
        and getattr(settings, "governance_enabled", False)
        and getattr(settings, "console_systems_enabled", False)
    )


def candidate_href(settings: Any, node_id: str) -> str:
    base = "/console/register/new" if v2_on(settings) else "/console/systems/new"
    return f"{base}?from={quote(str(node_id), safe='')}"


def agent_href(settings: Any, agent_id: str) -> str:
    base = "/console/register/new" if v2_on(settings) else "/console/systems/new"
    return f"{base}?agent={quote(str(agent_id), safe='')}"
