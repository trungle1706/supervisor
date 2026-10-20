"""Fillers and store on SQLite: exact graph, idempotent re-fill, stale handling, D33."""

from __future__ import annotations

import json
from pathlib import Path

from supervisor.inventory.fill import fill_from_manifests, fill_from_onboarding
from supervisor.inventory.graph import Graph
from supervisor.inventory.service import InventoryService
from tests.conftest import REPO_ROOT

MANIFEST = """\
id: pay
name: Pay agent
version: "1"
owner: Team A
risk_tier: high
model_family: acme
model_id: acme-1
tools:
  - name: send
    risk_class: money
  - name: look
    risk_class: read_only
"""
BASELINE = "policy_version: 1\ntools:\n  send: money\n  look: read_only\n"


def _mini(tmp_path: Path) -> tuple[Path, Path]:
    d = tmp_path / "agents" / "pay"
    d.mkdir(parents=True)
    (d / "manifest.yaml").write_text(MANIFEST, encoding="utf-8")
    b = tmp_path / "baseline.yaml"
    b.write_text(BASELINE, encoding="utf-8")
    return tmp_path / "agents", b


def _shape(g: Graph) -> tuple[set[tuple[str, str]], set[tuple[str, str, str, str]]]:
    nodes = {(n.kind, n.name) for n in g.nodes.values()}
    label = {nid: f"{n.kind}:{n.name}" for nid, n in g.nodes.items()}
    edges = {(label[e.src_id], e.kind, label[e.dst_id], e.source) for e in g.edges.values()}
    return nodes, edges


def test_manifest_graph_is_exact(tmp_path: Path) -> None:
    agents, baseline = _mini(tmp_path)
    g = fill_from_manifests(agents, baseline, {"pay": {"decision33_class": "high_risk"}}, tmp_path)
    nodes, edges = _shape(g)
    assert nodes == {
        ("system", "pay"),
        ("supplier", "team a"),
        ("model_endpoint", "acme-1"),
        ("model", "acme-1"),
        ("supplier", "acme"),
        ("tool", "pay/send"),
        ("tool", "pay/look"),
    }
    m = "manifest"
    assert edges == {
        ("system:pay", "owned_by", "supplier:team a", m),
        ("system:pay", "uses", "model_endpoint:acme-1", m),
        ("model_endpoint:acme-1", "serves", "model:acme-1", m),
        ("model:acme-1", "owned_by", "supplier:acme", m),
        ("system:pay", "uses", "tool:pay/send", m),
        ("system:pay", "uses", "tool:pay/look", m),
    }
    eff = g.effective_risk()
    pay = g.by_name("system", "pay")
    assert pay is not None and pay.own_risk == "high" and eff[pay.node_id] == "critical"
    assert pay.decision33_class == "high_risk"  # copied from the agent row, not inferred
    send = g.by_name("tool", "pay/send")
    assert send is not None
    assert send.evidence == [
        {"source": "manifest", "ref": "agents/pay/manifest.yaml:9"},
        {"source": "manifest", "ref": "baseline.yaml:3"},
    ]
    assert all(e.evidence_ref.count(":") == 1 for e in g.edges.values())  # file:line everywhere


def test_refill_is_idempotent_no_duplicates(svc: InventoryService, tmp_path: Path) -> None:
    agents, baseline = _mini(tmp_path)
    first = svc.fill_manifests(agents, baseline)
    n1 = len(svc.state.query("inventory_node"))
    e1 = len(svc.state.query("inventory_edge"))
    assert (n1, e1) == (7, 6) and first.nodes_new == 7 and first.edges_new == 6
    again = svc.fill_manifests(agents, baseline)
    assert (len(svc.state.query("inventory_node")), len(svc.state.query("inventory_edge"))) == (
        n1,
        e1,
    )
    assert again.nodes_new == again.edges_new == again.nodes_changed == again.edges_changed == 0
    versions = {r["node_id"]: r["row_version"] for r in svc.state.query("inventory_node")}
    svc.fill_manifests(agents, baseline)
    assert versions == {r["node_id"]: r["row_version"] for r in svc.state.query("inventory_node")}


def test_removed_tool_edge_goes_inactive(svc: InventoryService, tmp_path: Path) -> None:
    agents, baseline = _mini(tmp_path)
    svc.fill_manifests(agents, baseline)
    (agents / "pay" / "manifest.yaml").write_text(
        MANIFEST.replace("  - name: look\n    risk_class: read_only\n", ""), encoding="utf-8"
    )
    svc.fill_manifests(agents, baseline)
    view = svc.agent_view("pay")
    assert view is not None
    names = {n["name"] for n in view["nodes"]}
    assert "pay/look" not in names and "pay/send" in names


def test_agent_row_supplies_decision33_class(
    svc: InventoryService, adapters, tmp_path: Path
) -> None:
    from supervisor.core.canonical import format_ts  # noqa: F401

    agents, baseline = _mini(tmp_path)
    adapters.state.insert(
        "agent",
        {
            "agent_id": "pay",
            "name": "Pay agent",
            "owner_team": "Team A",
            "owner_user": "u@example.invalid",
            "risk_tier": "critical",
            "decision33_class": "high_risk",
            "host_type": "python_inprocess",
            "plug_point": "gate_hook",
            "model_family": "acme",
            "status": "active",
            "gate_state": "RUNNING",
            "created_at": adapters.clock.now(),
        },
    )
    svc.fill_manifests(agents, baseline)
    view = svc.agent_view("pay")
    assert view is not None
    root = next(n for n in view["nodes"] if n["node_id"] == view["root"])
    assert root["decision33_class"] == "high_risk" and root["own_risk"] == "critical"
    tools = [n for n in view["nodes"] if n["kind"] == "tool"]
    assert all(t["decision33_class"] is None for t in tools)  # never inferred downward


def test_manual_risk_survives_refill(svc: InventoryService, tmp_path: Path) -> None:
    agents, baseline = _mini(tmp_path)
    svc.fill_manifests(agents, baseline)
    g = svc.store.load_graph()
    send = g.by_name("tool", "pay/send")
    assert send is not None
    svc.store.set_manual_risk(send.node_id, "medium")
    svc.fill_manifests(agents, baseline)
    row = svc.state.get("inventory_node", {"node_id": send.node_id})
    assert row["own_risk"] == "medium" and row["risk_source"] == "manual"


def test_real_manifests_regression_baseline(svc: InventoryService) -> None:
    """Baseline counts for the three committed demo manifests (measured 2026-10-20)."""
    svc.fill_manifests()
    nodes = svc.state.query("inventory_node")
    edges = svc.state.query("inventory_edge")
    base = json.loads(
        (REPO_ROOT / "tests/fixtures/inventory/baseline_counts.json").read_text(encoding="utf-8")
    )["manifests"]
    by_kind: dict[str, int] = {}
    for n in nodes:
        by_kind[n["kind"]] = by_kind.get(n["kind"], 0) + 1
    assert by_kind == base["nodes_by_kind"]
    assert len(edges) == base["edges"]
    tree = svc.agent_view("payments")
    assert tree is not None
    eff = {n["name"]: n["effective_risk"] for n in tree["nodes"]}
    assert eff["payments"] == "critical" and eff["payments/ext_transfer_api"] == "critical"
    cs = svc.agent_view("customer_service")
    assert cs is not None
    assert {n["name"] for n in cs["nodes"] if n["kind"] == "tool"} >= {"customer_service/waive_fee"}


def test_onboarding_fragment_exact() -> None:
    inv = {
        "agent_id": "demo",
        "name": "Demo",
        "owner_team": "FILL-ME-owner-team",
        "declared_risk_tier": None,
        "tools": [
            {
                "name": "pay",
                "risk_class": "money",
                "risk_source": "manifest",
                "definition": {"file": "tools.py", "line": 7},
            }
        ],
        "model_endpoints": [
            {
                "name": "ep-1",
                "family": "meta",
                "source": "code",
                "evidence": {"file": "g.py", "line": 3},
            }
        ],
        "tables": [
            {
                "name": "loans",
                "direction": "write",
                "source": "code",
                "evidence": {"file": "t.py", "line": 9},
            }
        ],
    }
    g = fill_from_onboarding(inv)
    nodes, edges = _shape(g)
    assert nodes == {
        ("system", "demo"),
        ("tool", "demo/pay"),
        ("model_endpoint", "ep-1"),
        ("model", "ep-1"),
        ("supplier", "meta"),
        ("dataset", "loans"),
    }  # a FILL-ME owner team is not a supplier
    o = "onboarding"
    assert edges == {
        ("system:demo", "uses", "tool:demo/pay", o),
        ("system:demo", "uses", "model_endpoint:ep-1", o),
        ("model_endpoint:ep-1", "serves", "model:ep-1", o),
        ("model:ep-1", "owned_by", "supplier:meta", o),
        ("system:demo", "writes", "dataset:loans", o),
    }
    assert g.effective_risk()[g.by_name("system", "demo").node_id] == "critical"  # type: ignore[union-attr]
    refs = {e.evidence_ref for e in g.edges.values()}
    assert {"tools.py:7", "g.py:3", "t.py:9"} <= refs


def _agent_row(adapters, class_):
    return {
        "agent_id": "pay",
        "name": "Pay agent",
        "owner_team": "Team A",
        "owner_user": "u@example.invalid",
        "risk_tier": "critical",
        "decision33_class": class_,
        "host_type": "python_inprocess",
        "plug_point": "gate_hook",
        "model_family": "acme",
        "status": "active",
        "gate_state": "RUNNING",
        "created_at": adapters.clock.now(),
    }


def test_cleared_decision33_class_is_cleared_in_the_inventory(
    svc: InventoryService, adapters, tmp_path: Path
) -> None:
    """Review item 9: the node copies the current human value, an empty one included."""
    agents, baseline = _mini(tmp_path)
    adapters.state.insert("agent", _agent_row(adapters, "high_risk"))
    svc.fill_manifests(agents, baseline)
    assert svc.summary_for_agent("pay")["decision33_class"] == "high_risk"
    key = {"agent_id": "pay"}
    row = adapters.state.get("agent", key)
    adapters.state.update("agent", key, {"decision33_class": None}, row["row_version"])
    svc.fill_manifests(agents, baseline)
    assert svc.summary_for_agent("pay")["decision33_class"] is None
    row = adapters.state.get("agent", key)
    adapters.state.update("agent", key, {"decision33_class": "not_high_risk"}, row["row_version"])
    svc.fill_manifests(agents, baseline)
    assert svc.summary_for_agent("pay")["decision33_class"] == "not_high_risk"


def test_onboarding_never_sets_or_clears_decision33_class(
    svc: InventoryService, adapters, tmp_path: Path
) -> None:
    agents, baseline = _mini(tmp_path)
    adapters.state.insert("agent", _agent_row(adapters, "high_risk"))
    svc.fill_manifests(agents, baseline)
    svc.fill_onboarding({"agent_id": "pay", "name": "Pay agent"})
    assert svc.summary_for_agent("pay")["decision33_class"] == "high_risk"


def test_reserved_agent_ids_are_refused(svc: InventoryService, tmp_path: Path) -> None:
    from types import SimpleNamespace

    import pytest

    from supervisor.adapters.repo import LocalGitRepoReader
    from supervisor.core.errors import ReservedAgentIdError, SupervisorError, check_agent_id
    from supervisor.onboard.discover import discover
    from supervisor.wiring import register_agents

    assert issubclass(ReservedAgentIdError, SupervisorError)  # HTTP 400 through the app handler
    for bad in ("inventory", "Inventory", "app:payments", "APP:x"):
        with pytest.raises(ReservedAgentIdError, match="reserved"):
            check_agent_id(bad)
    assert check_agent_id("inventory_ops") == "inventory_ops"
    repo = tmp_path / "inventory"  # the folder name would become the agent id
    repo.mkdir()
    (repo / "tools.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    with pytest.raises(ReservedAgentIdError):
        discover(LocalGitRepoReader(repo))
    with pytest.raises(ReservedAgentIdError):
        discover(LocalGitRepoReader(repo), agent_id="app:x")
    with pytest.raises(ReservedAgentIdError):
        svc.fill_onboarding({"agent_id": "app:x"})
    rt = SimpleNamespace(
        adapters=SimpleNamespace(clock=svc.clock),
        policy=SimpleNamespace(doc=SimpleNamespace(agents={})),
    )
    with pytest.raises(ReservedAgentIdError):
        register_agents(rt, [SimpleNamespace(id="inventory")])  # type: ignore[arg-type]
