"""WP29: risk inheritance over the WP24 inventory graph (rubric: operational risk manager)."""

from __future__ import annotations

import random
from typing import Any

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Edge, Node, node_id_for
from supervisor.inventory.service import InventoryService
from supervisor.risk import inherit
from supervisor.risk.model import Thresholds, max_band
from supervisor.risk.service import RiskService

from .conftest import risk_data

TH = Thresholds()


def _g(*edges: tuple[str, str, str, str]) -> Graph:
    g = Graph()
    for sk, sn, dk, dn in edges:
        for k, n in ((sk, sn), (dk, dn)):
            g.add_node(Node(k, n, attrs={"role": "agent"} if k == "system" else {}))
        g.add_edge(Edge(node_id_for(sk, sn), node_id_for(dk, dn), "uses", "manual", "h"))
    return g


def _pt(rid: str, kind: str, name: str, score: int, status: str = "active") -> inherit.RiskPoint:
    return inherit.RiskPoint(rid, node_id_for(kind, name), None, status, score, score)


def test_shared_component_risk_reaches_every_agent() -> None:
    g = _g(("system", "a", "model_endpoint", "m"), ("system", "b", "model_endpoint", "m"))
    out = inherit.compute(g, [_pt("r1", "model_endpoint", "m", 20)], TH)
    assert out["a"].inherent_level == out["b"].inherent_level == "critical"
    assert [x["own"] for x in out["a"].reached] == [False]


def test_agent_level_is_the_max_over_the_graph() -> None:
    g = _g(("system", "a", "tool", "t1"), ("system", "a", "tool", "t2"))
    pts = [_pt("r1", "tool", "t1", 5), _pt("r2", "tool", "t2", 16), _pt("r3", "system", "a", 2)]
    out = inherit.compute(g, pts, TH)["a"]
    assert (out.inherent_level, out.inherent_score) == ("critical", 16)
    assert [x["risk_id"] for x in out.reached] == ["r1", "r2", "r3"]


def test_cycle_and_order_independence() -> None:
    edges = [
        ("system", "a", "tool", "t1"),
        ("tool", "t1", "tool", "t2"),
        ("tool", "t2", "tool", "t3"),
        ("tool", "t3", "tool", "t1"),
    ]
    pts = [_pt("r", "tool", "t3", 12)]
    base = inherit.compute(_g(*edges), pts, TH)["a"].inherent_level
    assert base == "high"
    rng = random.Random(7)
    for _ in range(10):
        rng.shuffle(edges)
        assert inherit.compute(_g(*edges), pts, TH)["a"].inherent_level == base


def test_agrees_with_the_walk_that_lists_the_risks() -> None:
    """Level from Graph.effective_risk (reused) equals the max over the reached list."""
    rng = random.Random(11)
    kinds = ["tool", "model_endpoint", "mcp_server", "dataset"]
    for _ in range(25):
        edges = [("system", "a", "tool", "n0"), ("system", "b", "tool", "n1")]
        names = [f"n{i}" for i in range(8)]
        for _e in range(12):
            edges.append(("tool", rng.choice(names), rng.choice(kinds), rng.choice(names)))
        g = _g(*edges)
        pts = [
            _pt(f"r{k}", "tool", rng.choice(names), rng.randint(1, 25))
            for k in range(rng.randint(0, 5))
        ]
        pts = [p for p in pts if p.anchor in g.nodes]
        for name, ar in inherit.compute(g, pts, TH).items():
            walked = max_band(*(TH.band(x["inherent_score"]) for x in ar.reached))
            assert ar.inherent_level == walked, (name, ar)


def test_gone_node_inactive_edge_draft_and_retired() -> None:
    g = _g(("system", "a", "tool", "t1"))
    g.nodes[node_id_for("tool", "t1")].status = "gone"
    assert inherit.compute(g, [_pt("r", "tool", "t1", 25)], TH)["a"].inherent_level is None
    g = _g(("system", "a", "tool", "t1"))
    for e in g.edges.values():
        e.active = False
    assert inherit.compute(g, [_pt("r", "tool", "t1", 25)], TH)["a"].inherent_level is None
    g = _g(("system", "a", "tool", "t1"))
    pts = [_pt("d", "tool", "t1", 25, "draft"), _pt("x", "tool", "t1", 25, "retired")]
    assert inherit.compute(g, pts, TH)["a"].inherent_level is None


def test_residual_level_differs_from_inherent() -> None:
    g = _g(("system", "a", "tool", "t1"))
    pt = inherit.RiskPoint("r", node_id_for("tool", "t1"), None, "active", 25, 4)
    out = inherit.compute(g, [pt], TH)["a"]
    assert (out.inherent_level, out.residual_level) == ("critical", "low")


def test_agent_without_a_node_keeps_its_own_risk() -> None:
    pt = inherit.RiskPoint("r", node_id_for("system", "ghost"), "ghost", "active", 12, 12)
    out = inherit.compute(Graph(), [pt], TH)
    assert out["ghost"].inherent_level == "high" and out["ghost"].reached[0]["own"] is True


# ---- on the real manifests and the 7-item workspace fixture ----------------------------------


def _shared(svc: RiskService, rid: str, kind: str, name: str, lik: int, imp: int) -> None:
    data: dict[str, Any] = risk_data(
        title=f"Risk on {name}",
        agent_id=None,
        node_id=node_id_for(kind, name),
        inherent_likelihood=lik,
        inherent_impact=imp,
        residual_likelihood=lik,
        residual_impact=imp,
    )
    svc.create(data, "t", risk_id=rid)


def test_workspace_7_inheritance_end_to_end(
    svc: RiskService, with_workspace: InventoryService
) -> None:
    """A risk on the shared model endpoint reaches the three managed agents; a risk on a tool
    reaches only its own agent; the unmanaged items are not agents and get no level."""
    _shared(svc, "R-EP", "model_endpoint", "qwen3:4b", 3, 4)
    _shared(svc, "R-TOOL", "tool", "payments/transfer", 2, 5)
    levels = svc.agent_levels()
    agents = ("payments", "credit_prequal", "customer_service")
    assert set(agents) <= set(levels)
    for a in agents:
        assert "R-EP" in [x["risk_id"] for x in levels[a].reached]
        assert levels[a].inherent_level == "high"  # 12
    assert "R-TOOL" in [x["risk_id"] for x in levels["payments"].reached]
    assert "R-TOOL" not in [x["risk_id"] for x in levels["credit_prequal"].reached]
    assert levels["payments"].inherent_score == 12
    listed = {r["risk_id"]: r for r in svc.list_risks()}
    assert listed["R-EP"]["agents"] == ["credit_prequal", "customer_service", "payments"]
    assert listed["R-TOOL"]["agents"] == ["payments"]
    # unmanaged workspace items (shadow AI) are not agents
    assert not {"hr-chat-assistant", "loan-bot-sandbox"} & set(levels)


def test_retiring_a_component_in_the_inventory_stops_inheritance(
    svc: RiskService, inventory: InventoryService
) -> None:
    nid = node_id_for("model_endpoint", "qwen3:4b")
    _shared(svc, "R-EP", "model_endpoint", "qwen3:4b", 3, 3)
    assert svc.agent_levels()["payments"].inherent_level == "medium"
    inventory.store.set_status(nid, "gone")
    assert "R-EP" not in [x["risk_id"] for x in svc.agent_levels()["payments"].reached]
