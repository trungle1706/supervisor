"""Risk inheritance over the inventory graph (WP29, ADR D26).

A risk sits on one inventory node: the agent's own ``system`` node, or a shared component (a
model, model endpoint, tool, MCP server, dataset). It applies to every agent that reaches that
node along active ``uses`` edges, and an agent's register level is the maximum band over all
the risks it reaches.

The graph code is the WP24 code and is not copied: this module builds a *copy* of the inventory
graph whose nodes carry the band of the risks attached to them as ``own_risk`` (the four band
names are the four inventory levels), then calls ``Graph.effective_risk()`` (iterative Tarjan,
cycle safe, independent of insertion order). The list of which risks reach an agent comes from a
plain reverse walk over the same edges (``reach``). A test asserts the two agree.

Rules:

* Only ``active`` risks count. ``draft`` and ``retired`` risks are listed but not propagated.
* A node whose status is ``gone`` (retired in the inventory) holds no risk and passes none up.
* An edge that is not active passes nothing (``Graph`` already skips it).
* Two scores are carried: inherent (what the risk is worth with no control) and residual (what
  is left after the evidence rule). The agent level is given for both.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from supervisor.inventory.graph import INHERIT_EDGE, Graph
from supervisor.inventory.model import Node, canonical_name, node_id_for
from supervisor.risk.model import Thresholds, max_band


@dataclass(frozen=True)
class RiskPoint:
    """What the inheritance code needs to know about one risk."""

    risk_id: str
    anchor: str  # inventory node id the risk sits on (the agent's system node for an agent risk)
    agent_id: str | None  # the agent the risk was written for (canonical), if any
    status: str
    inherent_score: int
    residual_score: int


@dataclass
class AgentRisk:
    agent_id: str
    inherent_level: str | None = None
    residual_level: str | None = None
    inherent_score: int = 0  # max over reached risks (0 = none)
    residual_score: int = 0
    reached: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "inherent_level": self.inherent_level,
            "residual_level": self.residual_level,
            "inherent_score": self.inherent_score,
            "residual_score": self.residual_score,
            "reached": list(self.reached),
        }


def anchor_for(agent_id: str | None, node_id: str | None) -> str:
    """The anchor a risk row resolves to: its node id, else the agent's system node id."""
    if node_id:
        return node_id
    if agent_id:
        return node_id_for("system", agent_id)
    raise ValueError("a risk needs an agent_id or a node_id")


def agent_nodes(g: Graph) -> dict[str, Node]:
    """agent id (canonical) -> its system node, for nodes that are agents and not gone."""
    return {
        n.name: n
        for n in g.nodes.values()
        if n.kind == "system" and n.attrs.get("role") == "agent" and n.status != "gone"
    }


def reach(g: Graph, node_id: str) -> set[str]:
    """Node ids that can reach ``node_id`` along active ``uses`` edges (itself included).
    Iterative, cycle safe."""
    seen = {node_id}
    todo = [node_id]
    while todo:
        cur = todo.pop()
        for e in g.in_edges(cur, (INHERIT_EDGE,)):
            if e.src_id not in seen and e.src_id in g.nodes:
                seen.add(e.src_id)
                todo.append(e.src_id)
    return seen


def _banded_copy(g: Graph, band_by_node: Mapping[str, str | None]) -> Graph:
    """A copy of ``g`` where ``own_risk`` is the band of the register risks on the node."""
    out = Graph()
    for nid, n in g.nodes.items():
        band = None if n.status == "gone" else band_by_node.get(nid)
        out.nodes[nid] = dataclasses.replace(
            n, own_risk=band, risk_source="manual" if band else "none"
        )
    out.edges = dict(g.edges)
    return out


def compute(
    g: Graph,
    risks: Iterable[RiskPoint],
    th: Thresholds,
    *,
    known_agents: Iterable[str] = (),
) -> dict[str, AgentRisk]:
    """Register level of every agent in the graph (and of ``known_agents`` that are not in it).

    An agent-anchored risk whose agent has no system node in the graph still counts for that
    agent (the inventory may be off or not filled); it just cannot be passed to others.
    """
    active = [r for r in risks if r.status == "active"]
    nodes_of_agent = agent_nodes(g)
    inh_band: dict[str, str | None] = {}
    res_band: dict[str, str | None] = {}
    by_anchor: dict[str, list[RiskPoint]] = {}
    for r in active:
        by_anchor.setdefault(r.anchor, []).append(r)
    for nid, rs in by_anchor.items():
        inh_band[nid] = max_band(*(th.band(r.inherent_score) for r in rs))
        res_band[nid] = max_band(*(th.band(r.residual_score) for r in rs))
    eff_inh = _banded_copy(g, inh_band).effective_risk()
    eff_res = _banded_copy(g, res_band).effective_risk()

    out: dict[str, AgentRisk] = {}
    for name, node in sorted(nodes_of_agent.items()):
        ar = AgentRisk(name, eff_inh.get(node.node_id), eff_res.get(node.node_id))
        below = _downstream(g, node.node_id)
        for r in sorted(active, key=lambda x: x.risk_id):
            held = g.nodes.get(r.anchor)
            if held is not None and held.status != "gone" and r.anchor in below:
                ar.reached.append(_reached(r, g, node.node_id))
        _fill_scores(ar)
        out[name] = ar
    # An agent risk whose agent has no node in the graph (inventory off or not filled yet) still
    # counts for that agent; it cannot be passed to anyone else.
    loose: dict[str, list[RiskPoint]] = {}
    for r in active:
        if r.anchor not in g.nodes and r.agent_id:
            loose.setdefault(canonical_name(r.agent_id), []).append(r)
    for name in sorted(set(loose) | {canonical_name(a) for a in known_agents}):
        if name in out:
            continue
        ar = AgentRisk(name)
        for r in sorted(loose.get(name, []), key=lambda x: x.risk_id):
            ar.reached.append(_reached(r, g, None))
        ar.inherent_level = max_band(*(th.band(x["inherent_score"]) for x in ar.reached))
        ar.residual_level = max_band(*(th.band(x["residual_score"]) for x in ar.reached))
        _fill_scores(ar)
        out[name] = ar
    return out


def _fill_scores(ar: AgentRisk) -> None:
    ar.inherent_score = max((x["inherent_score"] for x in ar.reached), default=0)
    ar.residual_score = max((x["residual_score"] for x in ar.reached), default=0)


def _downstream(g: Graph, node_id: str) -> set[str]:
    """Node ids reachable from ``node_id`` along active ``uses`` edges (itself included)."""
    seen = {node_id}
    todo = [node_id]
    while todo:
        cur = todo.pop()
        for e in g.out_edges(cur, (INHERIT_EDGE,)):
            if e.dst_id not in seen and e.dst_id in g.nodes:
                seen.add(e.dst_id)
                todo.append(e.dst_id)
    return seen


def _reached(r: RiskPoint, g: Graph, agent_node_id: str | None) -> dict[str, Any]:
    node = g.nodes.get(r.anchor)
    return {
        "risk_id": r.risk_id,
        "via": f"{node.kind}:{node.display_name}" if node else r.anchor,
        "own": agent_node_id is None or r.anchor == agent_node_id,
        "inherent_score": r.inherent_score,
        "residual_score": r.residual_score,
    }


def agents_reached_by(g: Graph, anchor: str, agent_id: str | None = None) -> list[str]:
    """Agent ids affected by a risk on ``anchor``: every agent node that reaches it. A risk
    written for an agent that has no node in the graph affects that agent only."""
    node = g.nodes.get(anchor)
    if node is None:
        return [canonical_name(agent_id)] if agent_id else []
    if node.status == "gone":
        return []
    up = reach(g, anchor)
    return sorted(name for name, n in agent_nodes(g).items() if n.node_id in up)
