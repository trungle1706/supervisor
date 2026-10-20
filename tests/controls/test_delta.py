"""WP30 on the Delta path (databricks_fake): same answers as SQLite, and the right statements."""

from __future__ import annotations

import json
from typing import Any

import pytest

from supervisor.adapters.sql.databricks_fake import (
    FakeStatementExecution,
    dml_result,
)
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.controls.harness_env import CtlEnv
from supervisor.controls.service import ControlService
from supervisor.core.schema import load_model
from supervisor.tasks.service import TaskService
from tests.conftest import REPO_ROOT
from tests.risk.test_databricks_mode import T0, MirrorFake
from tests.tasks.test_tasks import ADMIN


def _plain(x: Any) -> str:
    return json.dumps(x, sort_keys=True, default=str)


@pytest.fixture
def pair(env: CtlEnv) -> tuple[CtlEnv, ControlService, TaskService]:
    env.agent("pay")
    env.classify("pay", "high_risk", "high")
    env.control("CTL-A", evidence=[("rule", "PAY-02"), ("pack", "pack_a")])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.controls.run_status()
    env.tasks.generate("pay", ADMIN)
    fake = MirrorFake(env.adapters.executor)
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    model = load_model()
    state = SqlStateStore(ex, env.adapters.clock, model)
    tables = SqlTableStore(ex, model)
    cs = ControlService(state, tables, env.adapters.clock, env.settings, refs=env.refs)
    ts = TaskService(state, tables, env.adapters.clock, env.settings, controls=cs)
    return env, cs, ts


def test_control_reads_equal_on_both_backends(pair: Any) -> None:
    env, de, _ = pair
    sq = env.controls
    assert _plain(sq.list_controls()) == _plain(de.list_controls())
    assert _plain(sq.get("CTL-A")) == _plain(de.get("CTL-A"))
    assert _plain(sq.agent_compliance("pay")) == _plain(de.agent_compliance("pay"))
    assert _plain(sq.status_summary()) == _plain(de.status_summary())
    assert sq.counts() == de.counts()


def test_string_typed_rows_are_cast(pair: Any) -> None:
    _, de, _ = pair
    c = de.get("CTL-A")
    assert c["agents"] == ["pay"] and isinstance(c["status_by_agent"][0]["working_n"], int)
    assert de.agent_compliance("pay")["controls"][0]["status"] == "working"


def test_task_reads_equal_on_both_backends(pair: Any) -> None:
    env, _, de = pair
    sq = env.tasks
    assert _plain(sq.list_tasks()) == _plain(de.list_tasks())
    assert _plain(sq.agent_summary("pay")) == _plain(de.agent_summary("pay"))
    assert sq.counts() == de.counts()
    tid = sq.rows_of("pay")[0]["task_id"]
    assert _plain(sq.get(tid)) == _plain(de.get(tid))


def test_new_rows_are_insert_only_merges() -> None:
    fake = FakeStatementExecution()
    for t in ("control", "control_map", "task"):
        fake.add(dml_result(1), match=f"MERGE INTO `c`.`s`.`{t}`")
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    model = load_model()
    from supervisor.adapters.clock import FixedClock

    state = SqlStateStore(ex, FixedClock(T0), model)
    state.insert(
        "control",
        {
            "control_id": "C", "title": "t", "objective": "o", "control_type": "preventive",
            "implemented_by": "product", "owner": "o", "status": "draft", "review_date": None,
            "scope_agents": '["*"]', "source": "manual", "created_at": T0, "created_by": "u",
        },
    )  # fmt: skip
    assert fake.statements[0].startswith("MERGE INTO `c`.`s`.`control`")
    assert "WHEN NOT MATCHED THEN INSERT" in fake.statements[0]


def test_append_only_tables_append_with_typed_values() -> None:
    fake = FakeStatementExecution()
    fake.add(dml_result(1), match="MERGE INTO `c`.`s`.`control_status`")
    fake.add(dml_result(1), match="MERGE INTO `c`.`s`.`task_event`")
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    model = load_model()
    tables = SqlTableStore(ex, model)
    for name in ("control_status", "task_event"):
        row = {c: 0 for c in model.table(name).column_names}
        row |= {k: T0 for k in ("ts", "window_start", "window_end") if k in row}
        row |= {k: None for k in ("chain_hash", "from_status", "reason_sha256") if k in row}
        assert tables.append(name, [row]) == 1
    assert all("WHEN NOT MATCHED THEN INSERT" in s for s in fake.statements)


def test_tables_are_in_both_ddls() -> None:
    sq = (REPO_ROOT / "schema" / "ddl" / "sqlite.sql").read_text(encoding="utf-8")
    dl = (REPO_ROOT / "schema" / "ddl" / "databricks.sql").read_text(encoding="utf-8")
    for table in ("control", "control_map", "control_status", "task", "task_event"):
        assert f"CREATE TABLE IF NOT EXISTS {table} " in sq, table
        assert f"`${{catalog}}`.`${{schema}}`.`{table}`" in dl, table
    for table in ("control_status", "task_event"):
        ddl = dl[dl.index(f"`{table}` (") :]
        assert "'delta.appendOnly' = 'true'" in ddl.split("TBLPROPERTIES", 1)[1].split("\n", 1)[0]
