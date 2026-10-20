"""Model, ids and risk inheritance (pure, no store)."""

from __future__ import annotations

import random

import pytest

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Edge, InventoryError, Node, max_risk, node_id_for


def _g(nodes: dict[str, str | None], edges: list[tuple[str, str]]) -> tuple[Graph, dict[str, str]]:
    g = Graph()
    ids = {}
    for name, risk in nodes.items():
        n = Node("tool", name, own_risk=risk, risk_source="manifest" if risk else "none")
        ids[name] = g.add_node(n)
    for a, b in edges:
        g.add_edge(Edge(ids[a], ids[b], "uses", "manifest", f"{a}->{b}"))
    return g, ids


def test_node_id_is_deterministic_and_canonical() -> None:
    a = node_id_for("tool", "  Payments/Transfer ")
    assert a == node_id_for("tool", "payments/transfer")
    assert a.startswith("inv_") and len(a) == 20
    assert a != node_id_for("model", "payments/transfer")  # kind is part of the hash
    with pytest.raises(InventoryError):
        node_id_for("tool", "  ")
    with pytest.raises(InventoryError):
        node_id_for("widget", "x")


def test_max_risk_order_and_none() -> None:
    assert max_risk(None, None) is None
    assert max_risk("low", None, "high", "medium") == "high"
    with pytest.raises(InventoryError):
        Node("tool", "x", own_risk="extreme")


def test_inheritance_chain_takes_max_of_children() -> None:
    g, ids = _g(
        {"agent": "medium", "tool_a": "low", "tool_b": "critical", "ep": None},
        [("agent", "tool_a"), ("agent", "tool_b"), ("agent", "ep")],
    )
    eff = g.effective_risk()
    assert eff[ids["agent"]] == "critical"  # inherited from tool_b
    assert eff[ids["tool_a"]] == "low" and eff[ids["ep"]] is None


def test_own_risk_higher_than_children_stays() -> None:
    g, ids = _g({"agent": "critical", "t": "low"}, [("agent", "t")])
    assert g.effective_risk()[ids["agent"]] == "critical"


def test_only_uses_edges_inherit() -> None:
    g, ids = _g({"a": "low", "d": "critical"}, [])
    g.add_edge(Edge(ids["a"], ids["d"], "reads", "manifest", "x"))
    assert g.effective_risk()[ids["a"]] == "low"


def test_inactive_edge_does_not_inherit() -> None:
    g, ids = _g({"a": "low", "b": "critical"}, [("a", "b")])
    for e in g.edges.values():
        e.active = False
    assert g.effective_risk()[ids["a"]] == "low"


def test_cycle_terminates_and_members_share_the_level() -> None:
    # a -> b -> c -> a, c is critical, d hangs off a (low), e is reached from d only
    g, ids = _g(
        {"a": "low", "b": None, "c": "critical", "d": "medium", "e": None},
        [("a", "b"), ("b", "c"), ("c", "a"), ("a", "d")],
    )
    eff = g.effective_risk()
    assert {eff[ids[x]] for x in "abc"} == {"critical"}
    assert eff[ids["d"]] == "medium" and eff[ids["e"]] is None


def test_self_loop_and_two_cycle() -> None:
    g, ids = _g({"a": "high", "b": "low"}, [("a", "a"), ("a", "b"), ("b", "a")])
    eff = g.effective_risk()
    assert eff[ids["a"]] == eff[ids["b"]] == "high"


def test_order_independent() -> None:
    nodes = {f"n{i}": r for i, r in enumerate([None, "low", "high", None, "medium", "critical"])}
    edges = [("n0", "n1"), ("n1", "n2"), ("n2", "n0"), ("n3", "n4"), ("n4", "n5"), ("n0", "n3")]
    base_g, base_ids = _g(nodes, edges)
    base = {k: base_g.effective_risk()[v] for k, v in base_ids.items()}
    rnd = random.Random(7)
    for _ in range(10):
        items = list(nodes.items())
        rnd.shuffle(items)
        es = list(edges)
        rnd.shuffle(es)
        g, ids = _g(dict(items), es)
        assert {k: g.effective_risk()[v] for k, v in ids.items()} == base


def test_deep_chain_does_not_recurse() -> None:
    n = 3000
    nodes = {f"t{i}": ("critical" if i == n - 1 else None) for i in range(n)}
    g, ids = _g(nodes, [(f"t{i}", f"t{i + 1}") for i in range(n - 1)])
    assert g.effective_risk()[ids["t0"]] == "critical"


def test_decision33_class_is_never_inferred() -> None:
    g, ids = _g({"a": "critical", "b": "critical"}, [("a", "b")])
    g.nodes[ids["a"]].decision33_class = "high_risk"  # a human set this one
    assert g.nodes[ids["b"]].decision33_class is None
    g.effective_risk()
    assert g.nodes[ids["b"]].decision33_class is None  # nothing passes it up or down
    assert g.nodes[ids["a"]].decision33_class == "high_risk"


def test_ascii_tree_marks_cycles_and_is_stable() -> None:
    g, ids = _g({"a": "low", "b": "high"}, [("a", "b"), ("b", "a")])
    tree = g.ascii_tree(ids["a"])
    assert "(seen)" in tree and tree == g.ascii_tree(ids["a"])
    assert tree.splitlines()[0].startswith("tool:a risk=high (own low)")
