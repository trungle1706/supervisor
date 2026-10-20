"""In-memory inventory graph: merge, risk inheritance, subgraph, ASCII tree (WP24, ADR D16).

Risk inheritance rule: the effective risk of a node = max(own risk, effective risk of every
node it points to along an active ``uses`` edge). Cycles are handled by strongly connected
components: all nodes of one cycle share the same effective level (the max over the cycle
and everything reachable from it). The result does not depend on insertion order.
The Decision 33 class is never part of this computation and is never inferred.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from supervisor.inventory.model import RISK_RANK, Edge, Node, max_risk

INHERIT_EDGE = "uses"
TREE_EDGES = ("uses", "serves", "reads", "writes", "hosted_on", "owned_by")
MAX_TREE_NODES = 500


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}

    # ------------------------------------------------------------------ build
    def add_node(self, node: Node) -> str:
        """Add or merge. Evidence and attrs accumulate; the non-null own risk with the
        strongest source wins (manual > manifest > onboarding > none); for two claims from
        sources of the same strength the higher level wins, so the order does not matter."""
        nid = node.node_id
        cur = self.nodes.get(nid)
        if cur is None:
            self.nodes[nid] = node
            return nid
        for ev in node.evidence:
            cur.add_evidence(ev["source"], ev["ref"])
        cur.attrs.update(node.attrs)
        new_src, cur_src = _risk_src_rank(node.risk_source), _risk_src_rank(cur.risk_source)
        if node.own_risk is not None and (
            new_src > cur_src
            or (new_src == cur_src and RISK_RANK[node.own_risk] > RISK_RANK[cur.own_risk])
        ):
            cur.own_risk, cur.risk_source = node.own_risk, node.risk_source
        if node.decision33_class and not cur.decision33_class:
            cur.decision33_class = node.decision33_class
        return nid

    def add_edge(self, edge: Edge) -> str:
        """One edge per (src, kind, dst, source). When two fragments carry the same edge with
        different evidence (a model shared by two agents), the smallest reference wins, so the
        result does not depend on the order of the fills."""
        cur = self.edges.get(edge.edge_id)
        if cur is None or edge.evidence_ref < cur.evidence_ref:
            self.edges[edge.edge_id] = edge
        return edge.edge_id

    def link(self, src: Node, kind: str, dst: Node, source: str, ref: str) -> None:
        self.add_edge(Edge(src.node_id, dst.node_id, kind, source, ref))

    def merge(self, other: Graph) -> None:
        for n in other.nodes.values():
            self.add_node(n)
        for e in other.edges.values():
            self.add_edge(e)

    # ------------------------------------------------------------------ reads
    def out_edges(self, node_id: str, kinds: Iterable[str] | None = None) -> list[Edge]:
        ks = set(kinds) if kinds is not None else None
        out = [
            e
            for e in self.edges.values()
            if e.src_id == node_id and e.active and (ks is None or e.kind in ks)
        ]
        return sorted(out, key=lambda e: (e.kind, self._sort_name(e.dst_id), e.source))

    def in_edges(self, node_id: str, kinds: Iterable[str] | None = None) -> list[Edge]:
        ks = set(kinds) if kinds is not None else None
        return sorted(
            (
                e
                for e in self.edges.values()
                if e.dst_id == node_id and e.active and (ks is None or e.kind in ks)
            ),
            key=lambda e: (e.kind, e.src_id, e.source),
        )

    def _sort_name(self, node_id: str) -> tuple[str, str]:
        n = self.nodes.get(node_id)
        return (n.kind, n.name) if n else ("~", node_id)

    def by_name(self, kind: str, name: str) -> Node | None:
        from supervisor.inventory.model import node_id_for

        return self.nodes.get(node_id_for(kind, name))

    # ------------------------------------------------------------------ risk
    def effective_risk(self) -> dict[str, str | None]:
        """Effective level of every node (see module docstring). Deterministic, iterative
        Tarjan so a deep or cyclic graph cannot hit the recursion limit."""
        succ: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for e in self.edges.values():
            if e.active and e.kind == INHERIT_EDGE and e.src_id in succ and e.dst_id in succ:
                succ[e.src_id].append(e.dst_id)
        for nid in succ:
            succ[nid] = sorted(set(succ[nid]))

        comp_of: dict[str, int] = {}
        comps: list[list[str]] = []
        index: dict[str, int] = {}
        low: dict[str, int] = {}
        on_stack: set[str] = set()
        stack: list[str] = []
        counter = 0
        for root in sorted(succ):
            if root in index:
                continue
            work: list[tuple[str, Iterator[str]]] = [(root, iter(succ[root]))]
            index[root] = low[root] = counter
            counter += 1
            stack.append(root)
            on_stack.add(root)
            while work:
                v, it = work[-1]
                advanced = False
                for w in it:
                    if w not in index:
                        index[w] = low[w] = counter
                        counter += 1
                        stack.append(w)
                        on_stack.add(w)
                        work.append((w, iter(succ[w])))
                        advanced = True
                        break
                    if w in on_stack:
                        low[v] = min(low[v], index[w])
                if advanced:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[v])
                if low[v] == index[v]:
                    members = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        comp_of[w] = len(comps)
                        members.append(w)
                        if w == v:
                            break
                    comps.append(sorted(members))
        # Tarjan emits components in reverse topological order: successors come first.
        comp_level: list[str | None] = []
        for ci, members in enumerate(comps):
            level = max_risk(*(self.nodes[m].own_risk for m in members))
            for m in members:
                for w in succ[m]:
                    if comp_of[w] != ci:
                        level = max_risk(level, comp_level[comp_of[w]])
            comp_level.append(level)
        return {nid: comp_level[comp_of[nid]] for nid in self.nodes}

    # ------------------------------------------------------------------ subgraph
    def subgraph(self, root_id: str) -> dict[str, Any]:
        """Reachable nodes and edges from ``root_id`` along active edges (cycle safe)."""
        if root_id not in self.nodes:
            return {"root": root_id, "nodes": [], "edges": []}
        seen = {root_id}
        order = [root_id]
        i = 0
        while i < len(order) and len(order) < MAX_TREE_NODES:
            for e in self.out_edges(order[i], TREE_EDGES):
                if e.dst_id in self.nodes and e.dst_id not in seen:
                    seen.add(e.dst_id)
                    order.append(e.dst_id)
            i += 1
        eff = self.effective_risk()
        nodes = [self.node_dict(self.nodes[n], eff) for n in order]
        edges = [
            edge_dict(e)
            for e in sorted(self.edges.values(), key=lambda x: x.edge_id)
            if e.active and e.src_id in seen and e.dst_id in seen
        ]
        return {"root": root_id, "nodes": nodes, "edges": edges}

    def node_dict(self, n: Node, eff: dict[str, str | None] | None = None) -> dict[str, Any]:
        eff = eff if eff is not None else self.effective_risk()
        return {
            "node_id": n.node_id,
            "kind": n.kind,
            "name": n.name,
            "display_name": n.display_name,
            "status": n.status,
            "own_risk": n.own_risk,
            "effective_risk": eff.get(n.node_id),
            "risk_source": n.risk_source,
            "decision33_class": n.decision33_class,
            "attrs": dict(sorted(n.attrs.items())),
            "evidence": list(n.evidence),
        }

    def ascii_tree(self, root_id: str) -> str:
        """Indented ASCII tree from ``root_id``. A node reached again is marked ``(seen)``."""
        root = self.nodes.get(root_id)
        if root is None:
            return ""
        eff = self.effective_risk()
        lines: list[str] = [_label(root, eff.get(root_id), None, None)]
        printed = {root_id}

        def walk(nid: str, prefix: str) -> None:
            kids = [e for e in self.out_edges(nid, TREE_EDGES) if e.dst_id in self.nodes]
            for i, e in enumerate(kids):
                last = i == len(kids) - 1
                child = self.nodes[e.dst_id]
                again = e.dst_id in printed
                lines.append(
                    prefix
                    + ("`-- " if last else "|-- ")
                    + _label(child, eff.get(e.dst_id), e, "(seen)" if again else None)
                )
                if not again and len(printed) < MAX_TREE_NODES:
                    printed.add(e.dst_id)
                    walk(e.dst_id, prefix + ("    " if last else "|   "))

        walk(root_id, "")
        return "\n".join(lines)


def _risk_src_rank(src: str) -> int:
    return {"none": 0, "onboarding": 1, "manifest": 2, "manual": 3}.get(src, 0)


def edge_dict(e: Edge) -> dict[str, Any]:
    return {
        "edge_id": e.edge_id,
        "src_id": e.src_id,
        "dst_id": e.dst_id,
        "kind": e.kind,
        "source": e.source,
        "evidence_ref": e.evidence_ref,
    }


def _label(n: Node, eff: str | None, e: Edge | None, note: str | None) -> str:
    head = f"[{e.kind}] " if e is not None else ""
    risk = f" risk={eff or '-'}"
    if eff != n.own_risk:
        risk += f" (own {n.own_risk or '-'})"
    ref = ""
    if e is not None and e.evidence_ref:
        ref = f"  <{e.source}: {e.evidence_ref}>"
    flag = f" !{n.status}" if n.status not in ("active",) else ""
    return f"{head}{n.kind}:{n.display_name}{risk}{flag}{ref}" + (f" {note}" if note else "")


def risk_rank(level: str | None) -> int:
    return RISK_RANK[level]
