"""Inventory graph model (WP24, ADR D16): node and edge types, deterministic ids, risk order.

Pure Python. No SQL, no web, no Databricks imports.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

NODE_KINDS: tuple[str, ...] = (
    "system",  # an agent, or a Databricks App seen in the workspace
    "model",
    "model_endpoint",
    "tool",
    "mcp_server",
    "dataset",  # table or file
    "prompt",
    "supplier",  # model vendor, or an owner team (attrs.party)
    "entrypoint",  # an HTTP route of an agent app (WP1b-B); never a tool
    # WP-G3 scan sources v2 (workspace_scan only; names, never workspace ids or URLs)
    "genie_space",
    "job",  # a Databricks job whose config names an LLM serving endpoint
    "vector_index",
    "uc_function",  # a Unity Catalog function (an agent tool)
)
EDGE_KINDS: tuple[str, ...] = ("uses", "serves", "reads", "writes", "hosted_on", "owned_by")
# "gate": a gate-only agent registered on its first decision (WP41, gate_register.py)
SOURCES: tuple[str, ...] = ("manifest", "onboarding", "workspace_scan", "manual", "gate")
STATUSES: tuple[str, ...] = ("active", "unmanaged", "allowlisted", "gone")
RISK_SOURCES: tuple[str, ...] = ("none", "manifest", "onboarding", "manual")

# Risk levels in order. None (unspecified) ranks below "low".
RISK_LEVELS: tuple[str, ...] = ("low", "medium", "high", "critical")
RISK_RANK: dict[str | None, int] = {None: 0, **{lv: i + 1 for i, lv in enumerate(RISK_LEVELS)}}

# Tool risk class (manifest, policies/baseline.yaml) -> own risk level of the tool node.
TOOL_CLASS_RISK: dict[str, str] = {
    "read_only": "low",
    "pii_export": "high",
    "credit": "high",
    "money": "critical",
}

MAX_EVIDENCE = 20
_WS = re.compile(r"\s+")


class InventoryError(ValueError):
    """Bad input to the inventory (HTTP 400 when it reaches a route)."""


def canonical_name(name: str) -> str:
    """Trim, collapse whitespace, lower-case. The hash input for a node id."""
    return _WS.sub(" ", str(name).strip()).lower()


def node_id_for(kind: str, name: str) -> str:
    """Deterministic node id: ``inv_`` + 16 hex of sha256(kind NUL canonical name)."""
    if kind not in NODE_KINDS:
        raise InventoryError(f"unknown node kind {kind!r}")
    canon = canonical_name(name)
    if not canon:
        raise InventoryError("node name is empty")
    digest = hashlib.sha256(f"{kind}\x00{canon}".encode()).hexdigest()
    return f"inv_{digest[:16]}"


def edge_id_for(src_id: str, kind: str, dst_id: str, source: str) -> str:
    digest = hashlib.sha256(f"{src_id}\x00{kind}\x00{dst_id}\x00{source}".encode()).hexdigest()
    return f"ive_{digest[:16]}"


def max_risk(*levels: str | None) -> str | None:
    best: str | None = None
    for lv in levels:
        if RISK_RANK[lv] > RISK_RANK[best]:
            best = lv
    return best


def check_risk(level: str | None) -> str | None:
    if level is not None and level not in RISK_RANK:
        raise InventoryError(f"risk level must be one of {', '.join(RISK_LEVELS)}")
    return level


@dataclass
class Node:
    kind: str
    name: str  # canonical (lower-case); display_name keeps the original spelling
    display_name: str = ""
    status: str = "active"
    own_risk: str | None = None
    risk_source: str = "none"
    decision33_class: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, str]] = field(default_factory=list)
    # Not stored. True when decision33_class is a copy of the human-set agent row: the store then
    # copies the value as it is, including an empty one (a cleared class is cleared here too).
    d33_copy: bool = False

    def __post_init__(self) -> None:
        self.display_name = self.display_name or str(self.name).strip()
        self.name = canonical_name(self.name)
        self.own_risk = check_risk(self.own_risk)

    @property
    def node_id(self) -> str:
        return node_id_for(self.kind, self.name)

    def add_evidence(self, source: str, ref: str) -> None:
        item = {"source": source, "ref": ref}
        if item not in self.evidence and len(self.evidence) < MAX_EVIDENCE:
            self.evidence.append(item)
            self.evidence.sort(key=lambda e: (e["source"], e["ref"]))

    @property
    def sources(self) -> list[str]:
        return sorted({e["source"] for e in self.evidence})


@dataclass
class Edge:
    src_id: str
    dst_id: str
    kind: str
    source: str
    evidence_ref: str
    active: bool = True

    def __post_init__(self) -> None:
        if self.kind not in EDGE_KINDS:
            raise InventoryError(f"unknown edge kind {self.kind!r}")
        if self.source not in SOURCES:
            raise InventoryError(f"unknown edge source {self.source!r}")

    @property
    def edge_id(self) -> str:
        return edge_id_for(self.src_id, self.kind, self.dst_id, self.source)
