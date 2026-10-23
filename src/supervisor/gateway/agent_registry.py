"""Agent registry service (WP-P2): create or update the ``agent`` row from a manifest-shaped body.

Used by ``POST /v1/agents`` (AGENTS_API_ENABLED), and callable by the console Integrations "Add"
flow and ``demo seed-systems``. A new agent starts in SHADOW. An update changes only the
descriptive fields and never the gate state (that moves through ``/gate/agents/{id}/state``).
Every change is an ``agent_change`` chain record with ids and enums only: names, owners and
free text stay in the row.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError, NotFoundError, SupervisorError, check_agent_id
from supervisor.core.ports import Clock, EvidenceSink, StateStore

ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
RISK_TIERS = ("low", "medium", "high", "critical")
TEXT_FIELDS = ("name", "owner_team", "owner_user")
SLUG_FIELDS = ("host_type", "plug_point", "model_family")
SLUG_RE = re.compile(r"^[A-Za-z0-9_.:@/+-]{1,64}$")
MAX_TEXT = 200
ALLOWED = ("agent_id", "name", "owner_team", "owner_user", "risk_tier", *SLUG_FIELDS)
REQUIRED = ("agent_id", "name", "owner_team", "owner_user")


class AgentRegistryError(SupervisorError):
    """Bad registry input (HTTP 400 at a route)."""


def clean(body: Any) -> dict[str, str]:
    """Validate a manifest-shaped body; return only the known fields as strings."""
    if not isinstance(body, Mapping):
        raise AgentRegistryError("request body must be a JSON object")
    unknown = sorted(str(k) for k in body if k not in ALLOWED)
    if unknown:
        raise AgentRegistryError(f"unknown field(s): {', '.join(unknown)}")
    out: dict[str, str] = {}
    for key, value in body.items():
        if not isinstance(value, str):
            raise AgentRegistryError(f"{key} must be a string")
        out[key] = value.strip()
    missing = [k for k in REQUIRED if not out.get(k)]
    if missing:
        raise AgentRegistryError(f"missing field(s): {', '.join(missing)}")
    if not ID_RE.match(out["agent_id"]):
        raise AgentRegistryError("agent_id must match ^[A-Za-z0-9_.:@-]{1,128}$")
    try:
        check_agent_id(out["agent_id"])
    except SupervisorError as exc:
        raise AgentRegistryError(str(exc)) from None
    for key in TEXT_FIELDS:
        if len(out[key]) > MAX_TEXT:
            raise AgentRegistryError(f"{key} is longer than {MAX_TEXT} characters")
    if "risk_tier" in out and out["risk_tier"] not in RISK_TIERS:
        raise AgentRegistryError(f"risk_tier must be one of {', '.join(RISK_TIERS)}")
    for key in SLUG_FIELDS:
        if key in out and not SLUG_RE.match(out[key]):
            raise AgentRegistryError(f"{key} must match {SLUG_RE.pattern}")
    return out


class AgentRegistry:
    def __init__(
        self,
        state: StateStore,
        clock: Clock,
        evidence: EvidenceSink,
        *,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        self.state = state
        self.clock = clock
        self.evidence = evidence
        self.on_change = on_change  # called with the agent id (cache invalidation)

    def get(self, agent_id: str) -> dict[str, Any]:
        if not ID_RE.match(agent_id):
            raise AgentRegistryError("agent_id must match ^[A-Za-z0-9_.:@-]{1,128}$")
        row = self.state.get("agent", {"agent_id": agent_id})
        if row is None:
            raise NotFoundError(f"agent {agent_id} is not registered")
        return view(row)

    def register(self, body: Any, principal: str) -> tuple[dict[str, Any], bool]:
        """Create or update. Returns (agent view, created)."""
        data = clean(body)
        agent_id = data["agent_id"]
        now = self.clock.now()
        row = self.state.get("agent", {"agent_id": agent_id})
        if row is None:
            new = {
                "agent_id": agent_id,
                "name": data["name"],
                "owner_team": data["owner_team"],
                "owner_user": data["owner_user"],
                "risk_tier": data.get("risk_tier", "high"),
                "host_type": data.get("host_type", "python"),
                "plug_point": data.get("plug_point", "sdk"),
                "model_family": data.get("model_family", "unknown"),
                "status": "shadow",
                "gate_state": "SHADOW",
                "created_at": now,
            }
            try:
                current = self.state.insert("agent", new)
            except SupervisorError:
                raise AgentRegistryError(f"agent {agent_id} changed concurrently; retry") from None
            changed = sorted(k for k in new if k in ALLOWED and k != "agent_id")
            created = True
        else:
            if row["gate_state"] == "RETIRED":
                raise AgentRegistryError(f"agent {agent_id} is RETIRED; it cannot change")
            patch = {k: v for k, v in data.items() if k != "agent_id" and row.get(k) != v}
            changed = sorted(patch)
            created = False
            current = row
            if patch:
                try:
                    current = self.state.update(
                        "agent", {"agent_id": agent_id}, patch, int(row["row_version"])
                    )
                except ConcurrencyError:
                    raise AgentRegistryError(
                        f"agent {agent_id} changed concurrently; retry"
                    ) from None
        if self.on_change is not None:
            self.on_change(agent_id)
        if created or changed:
            self.evidence.record(
                "agent_change",
                agent_id,
                {
                    "agent_id": agent_id,
                    "action": "created" if created else "updated",
                    "changed_fields": changed,
                    "risk_tier": current["risk_tier"],
                    "host_type": current["host_type"],
                    "plug_point": current["plug_point"],
                    "model_family": current["model_family"],
                    "gate_state": current["gate_state"],
                    "principal": principal,
                    "ts": format_ts(now),
                },
            )
        return view(current), created


def view(row: Mapping[str, Any]) -> dict[str, Any]:
    ts = row.get("created_at")
    return {
        "agent_id": row["agent_id"],
        "name": row["name"],
        "owner_team": row["owner_team"],
        "owner_user": row["owner_user"],
        "risk_tier": row["risk_tier"],
        "host_type": row["host_type"],
        "plug_point": row["plug_point"],
        "model_family": row["model_family"],
        "status": row["status"],
        "gate_state": row["gate_state"],
        "created_at": format_ts(ts) if ts is not None else None,
        "row_version": int(row.get("row_version", 1)),
    }
