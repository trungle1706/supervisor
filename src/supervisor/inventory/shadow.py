"""Shadow-AI check (WP24, ADR D16).

A Databricks App or a Model Serving endpoint seen in the workspace is *managed* when Supervisor
knows it: an agent (manifest or onboarding evidence) is named like the app, declares it, is
``hosted_on`` it, or ``uses`` the endpoint. Otherwise it is *allowlisted* (listed in
``config/inventory_allowlist.yaml`` or this app itself) or *unmanaged*. An unmanaged node opens
one low-severity case through the case service; the case service dedupes on
(``inventory``, node id), so a node is reported once however often the scan runs.

Deterministic. No model decides anything here (rule R1).
"""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import canonical_name

log = logging.getLogger("supervisor.inventory")

CASE_AGENT_ID = "inventory"  # one evidence lane for all shadow-AI cases
SOURCE_KIND = "inventory"
SHADOW_SEVERITY = "low"
ALLOWLIST_KEYS = ("apps", "serving_endpoints")


@dataclass
class Allowlist:
    apps: list[str] = field(default_factory=list)
    serving_endpoints: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None) -> Allowlist:
        if path is None or not Path(path).exists():
            return cls()
        try:
            doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            log.warning("inventory: allow-list is not valid YAML; ignored")
            return cls()
        out = cls()
        if not isinstance(doc, Mapping):
            log.warning("inventory: allow-list is not a mapping; ignored")
            return out
        for key in ALLOWLIST_KEYS:
            items = doc.get(key) or []
            if isinstance(items, str):  # "apps: bi-portal" is one name, not five letters
                items = [items]
            elif not isinstance(items, list):
                items = []
            setattr(
                out,
                key,
                [canonical_name(x) for x in items if isinstance(x, str) and "FILL-ME" not in x],
            )
        return out

    def matches(self, workspace_kind: str, name: str) -> bool:
        patterns = self.apps if workspace_kind == "app" else self.serving_endpoints
        n = canonical_name(name)
        return any(fnmatch.fnmatchcase(n, p) for p in patterns)


@dataclass
class ShadowResult:
    active: list[str] = field(default_factory=list)  # node ids
    allowlisted: list[str] = field(default_factory=list)
    unmanaged: list[str] = field(default_factory=list)
    cases: dict[str, str] = field(default_factory=dict)  # node id -> case id

    def as_dict(self) -> dict[str, Any]:
        return {
            "managed": len(self.active),
            "allowlisted": len(self.allowlisted),
            "unmanaged": len(self.unmanaged),
            "cases_opened_or_found": len(self.cases),
        }


def _norm(name: str) -> str:
    return canonical_name(name).replace("-", "_")


def classify(graph: Graph, allow: Allowlist, *, self_app: str = "") -> dict[str, str]:
    """node id -> ``active`` | ``allowlisted`` | ``unmanaged`` for every live workspace app
    and serving endpoint (nodes with workspace_scan evidence)."""
    agents = {
        nid: n
        for nid, n in graph.nodes.items()
        if n.kind == "system"
        and n.attrs.get("role") == "agent"
        and any(e["source"] in ("manifest", "onboarding") for e in n.evidence)
        and n.status != "gone"
    }
    agent_keys = {_norm(n.name) for n in agents.values()}
    out: dict[str, str] = {}
    for nid, n in sorted(graph.nodes.items()):
        wk = n.attrs.get("workspace_kind")
        if wk not in ("app", "serving_endpoint") or n.status == "gone":
            continue
        if not any(e["source"] == "workspace_scan" for e in n.evidence):
            continue  # declared by a manifest but not seen in the workspace now
        raw = n.name.removeprefix("app:")
        if self_app and _norm(raw) == _norm(self_app):
            out[nid] = "allowlisted"
        elif wk == "app" and (
            _norm(raw) in agent_keys
            or any(e.src_id in agents for e in graph.in_edges(nid, ("hosted_on",)))
        ):
            out[nid] = "active"
        elif wk == "serving_endpoint" and any(
            e.src_id in agents for e in graph.in_edges(nid, ("uses",))
        ):
            out[nid] = "active"
        elif allow.matches(wk, raw):
            out[nid] = "allowlisted"
        else:
            out[nid] = "unmanaged"
    return out


def case_summary(node: Mapping[str, Any]) -> str:
    kind = "Databricks App" if node["kind"] == "system" else "serving endpoint"
    return (
        f"Shadow AI: {kind} '{node['display_name']}' runs in the workspace but no Supervisor "
        f"manifest or agent row covers it. Register it (onboarding) or add it to "
        f"config/inventory_allowlist.yaml if it is not an AI agent."
    )
