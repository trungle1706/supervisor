"""Delta path with the recorded REST fake: statements, string-typed rows, schema/DDL parity.

The fake (``databricks_fake``) returns only strings, as the Statement Execution API does; the
store must cast by schema and issue insert-only MERGE for new rows and row_version UPDATE for
changes (the same code that runs on SQLite)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.sql.databricks_fake import (
    FakeStatementExecution,
    dml_result,
    succeeded,
)
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlStateStore
from supervisor.adapters.workspace.databricks_sdk import DatabricksWorkspaceReader
from supervisor.config import load_settings
from supervisor.core.schema import load_model
from supervisor.inventory.fill import fill_from_onboarding
from supervisor.inventory.service import InventoryService
from supervisor.inventory.store import InventoryStore
from tests.conftest import REPO_ROOT

T0 = datetime(2026, 10, 20, 5, 0, 0, tzinfo=UTC)
NODE_COLS = load_model().table("inventory_node").column_names
EDGE_COLS = load_model().table("inventory_edge").column_names


def _store(fake: FakeStatementExecution) -> InventoryStore:
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    return InventoryStore(SqlStateStore(ex, FixedClock(T0), load_model()), FixedClock(T0))


def _empty(fake: FakeStatementExecution, cols: list[str], match: str) -> None:
    fake.add(succeeded([(c, "STRING") for c in cols], [])[0], match=match)


def test_new_rows_are_insert_only_merges() -> None:
    fake = FakeStatementExecution()
    _empty(fake, NODE_COLS, "SELECT")  # node read: empty
    for _ in range(3):
        fake.add(dml_result(1), match="MERGE INTO `c`.`s`.`inventory_node`")
    _empty(fake, EDGE_COLS, "FROM `c`.`s`.`inventory_edge`")
    for _ in range(2):
        fake.add(dml_result(1), match="MERGE INTO `c`.`s`.`inventory_edge`")
    store = _store(fake)
    g = fill_from_onboarding(
        {
            "agent_id": "demo",
            "tools": [{"name": "t", "risk_class": "money"}],
            "model_endpoints": [{"name": "ep", "source": "code"}],
        }
    )
    assert len(g.nodes) == 3
    res = store.apply(g, source="onboarding")
    assert res.nodes_new == 3
    merges = [s for s in fake.statements if s.startswith("MERGE INTO `c`.`s`.`inventory_node`")]
    assert len(merges) == 3 and all("WHEN NOT MATCHED THEN INSERT" in m for m in merges)
    assert res.edges_new == 2
    edge_merges = [
        s for s in fake.statements if s.startswith("MERGE INTO `c`.`s`.`inventory_edge`")
    ]
    assert len(edge_merges) == 2 and fake.remaining() == 0


def test_string_rows_are_cast_by_schema() -> None:
    """A Delta read returns strings for json and bool columns; the graph must come back typed."""
    fake = FakeStatementExecution()
    node = {
        "node_id": "inv_aaaaaaaaaaaaaaaa",
        "kind": "tool",
        "name": "pay/send",
        "display_name": "send",
        "status": "active",
        "own_risk": "critical",
        "risk_source": "manifest",
        "decision33_class": None,
        "attrs": json.dumps({"risk_class": "money"}),
        "evidence": json.dumps([{"source": "manifest", "ref": "m.yaml:9"}]),
        "first_seen": "2026-10-20T05:00:00.000000Z",
        "last_seen": "2026-10-20T05:00:00.000000Z",
        "row_version": "3",
        "updated_at": "2026-10-20T05:00:00.000000Z",
    }
    sys_ = {**node, "node_id": "inv_bbbbbbbbbbbbbbbb", "kind": "system", "name": "pay",
            "display_name": "pay", "own_risk": "low", "attrs": json.dumps({"role": "agent"}),
            "evidence": json.dumps([{"source": "manifest", "ref": "m.yaml:1"}])}  # fmt: skip
    cols = [(c, "STRING") for c in NODE_COLS]
    rows = [[r.get(c) for c in NODE_COLS] for r in (sys_, node)]
    fake.add(succeeded(cols, rows)[0], match="inventory_node")
    edge = {
        "edge_id": "ive_cccccccccccccccc",
        "src_id": sys_["node_id"],
        "dst_id": node["node_id"],
        "kind": "uses",
        "source": "manifest",
        "evidence_ref": "m.yaml:9",
        "active": "true",
        "first_seen": node["first_seen"],
        "last_seen": node["last_seen"],
        "row_version": "1",
        "updated_at": node["updated_at"],
    }
    inactive = {**edge, "edge_id": "ive_dddddddddddddddd", "active": "false"}
    fake.add(succeeded([(c, "STRING") for c in EDGE_COLS],
                       [[e.get(c) for c in EDGE_COLS] for e in (edge, inactive)])[0],
             match="inventory_edge")  # fmt: skip
    g = _store(fake).load_graph()
    assert len(g.nodes) == 2 and len(g.edges) == 2
    eff = g.effective_risk()
    assert eff["inv_bbbbbbbbbbbbbbbb"] == "critical"  # inherited through the active edge
    assert [e.active for e in sorted(g.edges.values(), key=lambda e: e.edge_id)] == [True, False]
    assert g.nodes["inv_aaaaaaaaaaaaaaaa"].attrs == {"risk_class": "money"}


def test_ddl_and_model_have_the_tables_in_both_dialects() -> None:
    for name in ("sqlite", "databricks"):
        ddl = (REPO_ROOT / "schema" / "ddl" / f"{name}.sql").read_text(encoding="utf-8")
        assert "inventory_node" in ddl and "inventory_edge" in ddl
    model = load_model()
    assert model.table("inventory_node").primary_key == ("node_id",)
    assert not model.table("inventory_node").append_only  # state table: row_version


def test_sdk_reader_lists_registered_models_from_uc_and_registry() -> None:
    """Review fix: a workspace can hold UC and legacy models at once; both are listed, the
    owner (a user name or e-mail) is not copied, and one refused listing is skipped."""

    def refused() -> Any:
        raise PermissionError("refused")

    uc_model = SimpleNamespace(full_name="main.ml.m1", name="m1", owner="o@example.invalid")
    old_model = SimpleNamespace(name="old", user_id="u@example.invalid")
    both = SimpleNamespace(
        registered_models=SimpleNamespace(list=lambda: [uc_model]),
        model_registry=SimpleNamespace(list_models=lambda: [old_model]),
    )
    assert DatabricksWorkspaceReader(both).list_registered_models() == [
        {"name": "main.ml.m1", "registry": "uc"},
        {"name": "old", "registry": "workspace"},
    ]
    uc_only = SimpleNamespace(
        registered_models=SimpleNamespace(list=lambda: [uc_model]),
        model_registry=SimpleNamespace(list_models=refused),
    )
    assert DatabricksWorkspaceReader(uc_only).list_registered_models() == [
        {"name": "main.ml.m1", "registry": "uc"}
    ]
    legacy = SimpleNamespace(
        registered_models=SimpleNamespace(list=refused),
        model_registry=SimpleNamespace(list_models=lambda: [old_model]),
    )
    assert DatabricksWorkspaceReader(legacy).list_registered_models() == [
        {"name": "old", "registry": "workspace"}
    ]
    none = SimpleNamespace(
        registered_models=SimpleNamespace(list=refused),
        model_registry=SimpleNamespace(list_models=refused),
    )
    with pytest.raises(PermissionError):  # both refused: the section fails, nothing goes gone
        DatabricksWorkspaceReader(none).list_registered_models()


def test_service_builds_in_databricks_app_mode_settings(tmp_path: Any) -> None:
    s = load_settings(
        supervisor_mode="databricks_app",
        sql_backend="sqlite",
        data_dir=tmp_path / "d",
        llm_base_url="",
    )
    svc = InventoryService(SimpleNamespace(), FixedClock(T0), s)
    assert svc.schemas() == [] and s.inventory_enabled is False  # default off
