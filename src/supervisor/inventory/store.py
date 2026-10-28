"""Inventory store over the ``StateStore`` port (SQLite and Delta alike) (WP24, ADR D16).

``apply`` merges a graph fragment into ``inventory_node`` and ``inventory_edge`` and is
idempotent: ids are hashes, so a second identical apply changes nothing and adds no row. Writes
happen only for rows that changed (plus a daily ``last_seen`` refresh), because every state
write on Delta is one statement. Nothing here infers a Decision 33 class: only the manifest
filler sets one, copied from the human-set ``agent`` row.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from supervisor.core.errors import ConcurrencyError, NotFoundError
from supervisor.inventory.graph import Graph, _risk_src_rank
from supervisor.inventory.model import (
    NODE_KINDS,
    V2_NODE_KINDS,
    Edge,
    InventoryError,
    Node,
    check_risk,
)

log = logging.getLogger("supervisor.inventory")
LAST_SEEN_REFRESH = timedelta(days=1)


@dataclass
class ApplyResult:
    nodes_new: int = 0
    nodes_changed: int = 0
    nodes_same: int = 0
    nodes_gone: int = 0
    edges_new: int = 0
    edges_changed: int = 0
    edges_same: int = 0
    edges_dropped: int = 0  # an endpoint is not in the inventory
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "notes"} | {
            "notes": list(self.notes)
        }


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def node_from_row(r: dict[str, Any]) -> Node:
    n = Node(
        r["kind"],
        r["name"],
        display_name=r.get("display_name") or r["name"],
        status=r["status"],
        own_risk=r.get("own_risk"),
        risk_source=r.get("risk_source") or "none",
        decision33_class=r.get("decision33_class"),
        attrs=dict(_json(r.get("attrs"), {})),
        evidence=list(_json(r.get("evidence"), [])),
    )
    return n


def edge_from_row(r: dict[str, Any]) -> Edge:
    return Edge(
        r["src_id"],
        r["dst_id"],
        r["kind"],
        r["source"],
        r["evidence_ref"],
        active=_bool(r.get("active")),
    )


def _node_cols(n: Node) -> dict[str, Any]:
    return {
        "kind": n.kind,
        "name": n.name,
        "display_name": n.display_name,
        "status": n.status,
        "own_risk": n.own_risk,
        "risk_source": n.risk_source,
        "decision33_class": n.decision33_class,
        "attrs": dict(sorted(n.attrs.items())),
        "evidence": list(n.evidence),
    }


class InventoryStore:
    def __init__(self, state: Any, clock: Any) -> None:
        self.state = state
        self.clock = clock

    # ------------------------------------------------------------------ reads
    def load_graph(self) -> Graph:
        g = Graph()
        for r in self.state.query("inventory_node", order_by=("node_id",)):
            n = node_from_row(r)
            g.nodes[r["node_id"]] = n
        for r in self.state.query("inventory_edge", order_by=("edge_id",)):
            e = edge_from_row(r)
            g.edges[r["edge_id"]] = e
        return g

    def _rows(self, table: str, key: str) -> dict[str, dict[str, Any]]:
        return {r[key]: r for r in self.state.query(table)}

    # ------------------------------------------------------------------ writes
    def apply(
        self,
        fragment: Graph,
        *,
        source: str,
        stale_kinds: Iterable[str] | None = None,
        stale_any: bool = False,
        stale_edges: bool = False,
    ) -> ApplyResult:
        """Merge ``fragment`` (all of it came from ``source``).

        ``stale_kinds``: workspace kinds (attrs.workspace_kind) that were listed completely this
        time; a node of that kind whose only evidence is this source and that is missing from the
        fragment becomes ``gone``, and one with other evidence loses this source's evidence.
        ``stale_any``: the same for every node kind; use it only when the fragment is the
        complete output of ``source`` (all manifests): a retired agent then becomes ``gone``.
        ``stale_edges``: edges of this source that the fragment does not carry become inactive.
        """
        now = self.clock.now()
        res = ApplyResult()
        existing = self._rows("inventory_node", "node_id")
        for nid, node in sorted(fragment.nodes.items()):
            row = existing.get(nid)
            if row is None:
                self.state.insert(
                    "inventory_node",
                    {"node_id": nid, **_node_cols(node), "first_seen": now, "last_seen": now},
                )
                res.nodes_new += 1
                continue
            cur = node_from_row(row)
            merged = _merge(cur, node)
            same = _node_cols(merged) == _node_cols(cur)
            last = _as_dt(row.get("last_seen"))
            if same and last is not None and now - last < LAST_SEEN_REFRESH:
                res.nodes_same += 1
                continue
            self._update(
                "inventory_node", {"node_id": nid}, {**_node_cols(merged), "last_seen": now}
            )
            res.nodes_same += 1 if same else 0
            res.nodes_changed += 0 if same else 1
        if stale_kinds is not None or stale_any:
            kinds = None if stale_any else set(stale_kinds or ())
            res.nodes_gone += self._stale_nodes(fragment, existing, source, kinds, now)

        known = set(existing) | set(fragment.nodes)
        eexisting = self._rows("inventory_edge", "edge_id")
        for eid, edge in sorted(fragment.edges.items()):
            if edge.src_id not in known or edge.dst_id not in known:
                res.edges_dropped += 1
                continue
            row = eexisting.get(eid)
            if row is None:
                self.state.insert(
                    "inventory_edge",
                    {
                        "edge_id": eid,
                        "src_id": edge.src_id,
                        "dst_id": edge.dst_id,
                        "kind": edge.kind,
                        "source": edge.source,
                        "evidence_ref": edge.evidence_ref,
                        "active": True,
                        "first_seen": now,
                        "last_seen": now,
                    },
                )
                res.edges_new += 1
                continue
            last = _as_dt(row.get("last_seen"))
            if (
                _bool(row.get("active"))
                and row["evidence_ref"] == edge.evidence_ref
                and last is not None
                and now - last < LAST_SEEN_REFRESH
            ):
                res.edges_same += 1
                continue
            self._update(
                "inventory_edge",
                {"edge_id": eid},
                {"active": True, "evidence_ref": edge.evidence_ref, "last_seen": now},
            )
            res.edges_changed += 1
        if stale_edges:
            for eid, row in eexisting.items():
                if (
                    row["source"] == source
                    and eid not in fragment.edges
                    and _bool(row.get("active"))
                ):
                    self._update("inventory_edge", {"edge_id": eid}, {"active": False})
                    res.edges_changed += 1
        return res

    def _stale_nodes(
        self,
        fragment: Graph,
        existing: dict[str, dict[str, Any]],
        source: str,
        kinds: set[str] | None,
        now: datetime,
    ) -> int:
        gone = 0
        for nid, row in sorted(existing.items()):
            if nid in fragment.nodes:
                continue
            node = node_from_row(row)
            if kinds is not None and node.attrs.get("workspace_kind") not in kinds:
                continue
            kept = [e for e in node.evidence if e["source"] != source]
            if len(kept) == len(node.evidence):
                continue
            changes: dict[str, Any] = {"evidence": kept}
            if not kept:
                changes["status"] = "gone"
                gone += 1
            self._update("inventory_node", {"node_id": nid}, changes)
        return gone

    def _update(self, table: str, key: dict[str, Any], changes: dict[str, Any]) -> None:
        """Update with one retry on a concurrent writer (two Supervisor workers)."""
        for attempt in (0, 1):
            row = self.state.get(table, key)
            if row is None:
                raise NotFoundError(f"{table} {key} does not exist")
            try:
                self.state.update(table, key, changes, row["row_version"])
                return
            except ConcurrencyError:
                if attempt:
                    raise

    def deactivate_edges(self, src_id: str, source: str, keep: Iterable[str]) -> int:
        """Set ``active`` false on the edges of ``source`` that start at ``src_id`` and whose id is
        not in ``keep`` (one node's edges only; ``apply(stale_edges=True)`` is for a whole
        source)."""
        kept = set(keep)
        n = 0
        for row in self.state.query("inventory_edge", {"src_id": src_id, "source": source}):
            if row["edge_id"] not in kept and _bool(row.get("active")):
                self._update("inventory_edge", {"edge_id": row["edge_id"]}, {"active": False})
                n += 1
        return n

    def set_status(self, node_id: str, status: str) -> bool:
        row = self.state.get("inventory_node", {"node_id": node_id})
        if row is None or row["status"] == status:
            return False
        self._update("inventory_node", {"node_id": node_id}, {"status": status})
        return True

    def set_manual_risk(self, node_id: str, level: str | None) -> None:
        """A human sets the node's own risk (overrides manifest and onboarding)."""
        check_risk(level)
        row = self.state.get("inventory_node", {"node_id": node_id})
        if row is None:
            raise InventoryError(f"unknown node {node_id}")
        self._update(
            "inventory_node",
            {"node_id": node_id},
            {"own_risk": level, "risk_source": "manual" if level else "none"},
        )

    def counts(self) -> dict[str, Any]:
        rows = self.state.query("inventory_node")
        by_kind = {k: 0 for k in NODE_KINDS if k not in V2_NODE_KINDS}
        unmanaged = 0
        for r in rows:
            if r["status"] == "gone":
                continue
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
            unmanaged += 1 if r["status"] == "unmanaged" else 0
        return {"nodes": by_kind, "unmanaged": unmanaged}


def _as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _merge(cur: Node, new: Node) -> Node:
    """Stored node + fragment node. Evidence and attrs accumulate, the strongest risk source
    wins (a manual risk stays), a Decision 33 class is only ever copied from the human-set agent
    row (no filler infers one), and a node that
    was ``gone`` comes back with the fragment's status."""
    m = Node(
        cur.kind,
        cur.name,
        display_name=cur.display_name,
        status=cur.status,
        own_risk=cur.own_risk,
        risk_source=cur.risk_source,
        decision33_class=cur.decision33_class,
        attrs={**cur.attrs},
        evidence=list(cur.evidence),
    )
    for ev in new.evidence:
        m.add_evidence(ev["source"], ev["ref"])
    m.attrs.update(new.attrs)
    if new.own_risk is not None and _risk_src_rank(new.risk_source) >= _risk_src_rank(
        m.risk_source
    ):
        if m.risk_source != "manual":
            m.own_risk, m.risk_source = new.own_risk, new.risk_source
    if new.d33_copy:  # a copy of the human-set agent row, an empty value included
        m.decision33_class = new.decision33_class
    elif new.decision33_class and not m.decision33_class:
        m.decision33_class = new.decision33_class
    if m.status == "gone":
        m.status = new.status
    if new.display_name and m.display_name == m.name:
        m.display_name = new.display_name
    return m
