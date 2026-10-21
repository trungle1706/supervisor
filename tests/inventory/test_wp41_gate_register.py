"""WP41 (D19): a gate-only agent is registered in the inventory on its first decision.

INVENTORY_ENABLED off: nothing changes. On: one `system` node with `attrs.role = agent` and the
evidence source `gate`, for an agent the policy lists; never for an id the policy does not know.
Both stores: SQLite through the runtime, and the Delta path with the recorded REST fake.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.sql.databricks_fake import (
    FakeStatementExecution,
    dml_result,
    succeeded,
)
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlStateStore
from supervisor.config import load_settings
from supervisor.core.schema import load_model
from supervisor.inventory.gate_register import GateRegistrar
from supervisor.inventory.model import SOURCES
from supervisor.wiring import build_runtime

T0 = datetime(2026, 10, 21, 5, 0, 0, tzinfo=UTC)


def _nodes(rt: object) -> list[dict]:
    return rt.adapters.state.query("inventory_node", {"kind": "system"})  # type: ignore[attr-defined]


def test_gate_is_an_inventory_source() -> None:
    assert "gate" in SOURCES


def test_flag_off_registers_nothing(tmp_path: Path) -> None:
    rt = build_runtime(load_settings(sql_backend="sqlite", data_dir=tmp_path / "d"))
    try:
        rt.gateway.check("payments", "1", "get_balance", {"account_id": "A-1"}, {})
        rt.gateway.drain()
        assert _nodes(rt) == []
    finally:
        rt.close()


def test_first_decision_registers_the_agent_once(tmp_path: Path) -> None:
    s = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d", inventory_enabled=True)
    rt = build_runtime(s)
    try:
        for _ in range(3):
            rt.gateway.check("payments", "1", "get_balance", {"account_id": "A-1"}, {})
        rt.gateway.drain()
        rows = _nodes(rt)
        assert [r["name"] for r in rows] == ["payments"]
        node = rows[0]
        assert node["status"] == "active"
        assert node["attrs"]["role"] == "agent" and node["attrs"]["registered_by"] == "gate"
        assert [e["source"] for e in node["evidence"]] == ["gate"]
        # an id the policy does not list is not registered (anonymous input fills nothing)
        rt.gateway.check("ghost-agent", "1", "get_balance", {"account_id": "A-1"}, {})
        rt.gateway.drain()
        assert [r["name"] for r in _nodes(rt)] == ["payments"]
    finally:
        rt.close()


def test_a_later_manifest_fill_keeps_the_node_and_adds_its_evidence(tmp_path: Path) -> None:
    from supervisor.inventory.service import InventoryService

    s = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d", inventory_enabled=True)
    rt = build_runtime(s)
    try:
        rt.gateway.check("payments", "1", "get_balance", {"account_id": "A-1"}, {})
        rt.gateway.drain()
        InventoryService.from_adapters(rt.adapters).fill_manifests()
        node = [r for r in _nodes(rt) if r["name"] == "payments"]
        assert len(node) == 1
        assert {e["source"] for e in node[0]["evidence"]} == {"gate", "manifest"}
    finally:
        rt.close()


def test_a_failing_store_does_not_stop_the_gate_and_is_retried() -> None:
    class Boom:
        def query(self, *a: object, **k: object) -> list:
            raise RuntimeError("store down")

    reg = GateRegistrar(Boom(), FixedClock(T0))
    assert reg.register("payments") is False and not reg.seen("payments")


def test_delta_path_inserts_one_node_with_a_merge() -> None:
    model = load_model()
    node_cols = model.table("inventory_node").column_names
    edge_cols = model.table("inventory_edge").column_names
    fake = FakeStatementExecution()
    fake.add(succeeded([(c, "STRING") for c in node_cols], [])[0], match="SELECT")
    fake.add(
        succeeded([(c, "STRING") for c in edge_cols], [])[0], match="FROM `c`.`s`.`inventory_edge`"
    )
    fake.add(dml_result(1), match="MERGE INTO `c`.`s`.`inventory_node`")
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    reg = GateRegistrar(SqlStateStore(ex, FixedClock(T0), model), FixedClock(T0))
    assert reg.register("payments") is True
    merges = [s for s in fake.statements if s.startswith("MERGE INTO `c`.`s`.`inventory_node`")]
    assert len(merges) == 1 and "WHEN NOT MATCHED THEN INSERT" in merges[0]
    assert reg.register("payments") is False  # once per process
