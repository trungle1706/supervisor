"""WP24 review fixes: registry-only agents, retired manifests, allow-list shapes."""

from __future__ import annotations

from pathlib import Path

from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.inventory.fill import fill_from_manifests
from supervisor.inventory.service import InventoryService
from supervisor.inventory.shadow import Allowlist
from tests.inventory.test_fill_store import MANIFEST, _mini


def _agent_row(agent_id: str, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "agent_id": agent_id,
        "name": "Registry agent",
        "owner_team": "Team R",
        "owner_user": "u@example.invalid",
        "risk_tier": "high",
        "decision33_class": "high_risk",
        "host_type": "databricks_app",
        "plug_point": "gate_hook",
        "model_family": "acme",
        "status": "enforced",
        "gate_state": "RUNNING",
    }
    row.update(over)
    return row


def test_agent_row_without_manifest_is_a_system_node(tmp_path: Path) -> None:
    agents, baseline = _mini(tmp_path)
    rows = {
        "pay": _agent_row("pay"),  # has a manifest: no second node
        "loan-bot-sandbox": _agent_row("loan-bot-sandbox"),
        "old": _agent_row("old", status="retired"),
    }
    g = fill_from_manifests(agents, baseline, rows, tmp_path)
    systems = {n.name: n for n in g.nodes.values() if n.kind == "system"}
    assert set(systems) == {"pay", "loan-bot-sandbox"}
    n = systems["loan-bot-sandbox"]
    assert n.attrs["role"] == "agent" and n.own_risk == "high"
    assert n.decision33_class == "high_risk"  # copied from the human-set row, not inferred
    assert n.evidence == [{"source": "manifest", "ref": "agent_table:loan-bot-sandbox"}]
    assert "u@example.invalid" not in repr(g.nodes)  # owner_user (e-mail) is never copied


def test_registry_agent_makes_its_app_managed(
    svc: InventoryService, adapters, reader: FixtureWorkspaceReader, cases
) -> None:
    row = _agent_row("loan-bot-sandbox")
    row["created_at"] = adapters.clock.now()
    adapters.state.insert("agent", row)
    svc.fill_manifests()
    svc.refresh_workspace(reader, cases)
    names = {r["display_name"] for r in svc.unmanaged()}
    assert "loan-bot-sandbox" not in names and "hr-chat-assistant" in names


def test_removed_manifest_agent_becomes_gone(svc: InventoryService, tmp_path: Path) -> None:
    agents, baseline = _mini(tmp_path)
    svc.fill_manifests(agents, baseline)
    assert svc.agent_view("pay") is not None
    (agents / "pay" / "manifest.yaml").unlink()
    res = svc.fill_manifests(agents, baseline)
    assert res.nodes_gone == 7  # agent, tools, endpoint, model, vendor, owner team
    assert svc.agent_view("pay") is None
    assert {r["status"] for r in svc.state.query("inventory_node")} == {"gone"}
    (agents / "pay" / "manifest.yaml").write_text(MANIFEST, encoding="utf-8")
    svc.fill_manifests(agents, baseline)  # it comes back
    assert svc.agent_view("pay") is not None


def test_allowlist_tolerates_a_scalar_or_a_bad_document(tmp_path: Path) -> None:
    p = tmp_path / "a.yaml"
    p.write_text("apps: bi-portal\nserving_endpoints: {x: 1}\n", encoding="utf-8")
    a = Allowlist.load(p)
    assert a.apps == ["bi-portal"] and a.serving_endpoints == []
    assert a.matches("app", "BI-Portal") and not a.matches("app", "b")
    p.write_text("- just\n- a list\n", encoding="utf-8")
    assert Allowlist.load(p) == Allowlist()


def test_graph_merge_of_equal_sources_is_order_independent() -> None:
    from supervisor.inventory.graph import Graph
    from supervisor.inventory.model import Node

    def build(order: list[str]) -> str | None:
        g = Graph()
        for lv in order:
            g.add_node(Node("tool", "a/t", own_risk=lv, risk_source="manifest"))
        return g.by_name("tool", "a/t").own_risk  # type: ignore[union-attr]

    assert build(["high", "low"]) == build(["low", "high"]) == "high"
