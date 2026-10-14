"""Schema migration (additive): SQLite with an older schema, Databricks with recorded output."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import build_adapters
from supervisor.adapters.sql.databricks_fake import (
    FakeStatementExecution,
    dml_result,
    failed,
    succeeded,
)
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.sqlite import SqliteExecutor
from supervisor.config import load_settings
from supervisor.core.schema import (
    DATABRICKS_TYPES,
    SchemaModel,
    load_model,
    parse_model,
    sqlite_statements,
)
from supervisor.core.schema_diff import desired_properties, live_columns, migrate, plan_migration
from supervisor.jobs import bootstrap_schema

T0 = datetime(2026, 10, 14, 5, 0, 0, tzinfo=UTC)
DESCRIBE_COLS = [("col_name", "STRING"), ("data_type", "STRING"), ("comment", "STRING")]
PROPS_COLS = [("key", "STRING"), ("value", "STRING")]

SMALL = """
version: 1
tables:
  agent:
    kind: state
    description: agents
    primary_key: [agent_id]
    columns:
      agent_id: string
      name: string
      risk_tier: string?
  chain_entry:
    kind: append_only
    evidence: true
    description: evidence
    primary_key: [seq]
    columns:
      seq: int
      entry_hash: string
      payload: json
"""


def _older(model: SchemaModel, drop: dict[str, set[str]]) -> SchemaModel:
    """The same model with some columns removed (an older deployed schema)."""
    from dataclasses import replace

    tables = {}
    for name, t in model.tables.items():
        cols = tuple(c for c in t.columns if c.name not in drop.get(name, set()))
        tables[name] = replace(t, columns=cols)
    return SchemaModel(model.version, tables, "older")


# ------------------------------------------------------------------ SQLite


def test_sqlite_older_schema_gets_missing_columns(tmp_path: Path) -> None:
    model = load_model()
    drop = {"agent": {"decision33_class", "business_owner"}, "agent_event": {"latency_ms"}}
    db = tmp_path / "old.db"
    x = SqliteExecutor(db)
    x.apply_ddl(sqlite_statements(_older(model, drop)))
    assert "latency_ms" not in (live_columns(x, "agent_event") or {})

    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d", sqlite_path=db)
    adapters = build_adapters(settings, executor=x, clock=FixedClock(T0))
    plans: list = []
    result = bootstrap_schema.run(settings, adapters, plan_out=plans)
    assert result["added_columns"] == 3
    cols = live_columns(x, "agent") or {}
    assert {"decision33_class", "business_owner"} <= set(cols)
    assert "latency_ms" in (live_columns(x, "agent_event") or {})
    assert any("ADD COLUMN latency_ms INTEGER" in s for s in plans[0].statements)
    # append-only triggers still hold after ALTER
    trg = x.query(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'agent_event'"
    )
    assert len(trg) == 2
    # idempotent
    again = bootstrap_schema.run(settings, adapters)
    assert again["added_columns"] == 0
    assert migrate(x, model).statements == []
    x.close()


def test_sqlite_extra_column_kept_and_reported(tmp_path: Path) -> None:
    model = parse_model(SMALL)
    x = SqliteExecutor(tmp_path / "x.db")
    x.apply_ddl(sqlite_statements(model))
    x.execute("ALTER TABLE agent ADD COLUMN legacy TEXT")
    plan = migrate(x, model)
    assert plan.statements == []
    assert any("agent.legacy" in w and "kept" in w for w in plan.warnings)
    assert "legacy" in (live_columns(x, "agent") or {})


def test_not_null_column_added_nullable_with_warning(tmp_path: Path) -> None:
    model = parse_model(SMALL)
    x = SqliteExecutor(tmp_path / "x.db")
    x.apply_ddl(sqlite_statements(_older(model, {"agent": {"name"}})))
    x.execute("INSERT INTO agent (agent_id, row_version, updated_at) VALUES ('a', 1, 'x')")
    plan = migrate(x, model)
    assert plan.statements == ['ALTER TABLE "agent" ADD COLUMN name TEXT']
    assert any("agent.name" in w and "NULLABLE" in w for w in plan.warnings)
    assert x.query("SELECT name FROM agent") == [{"name": None}]


def test_missing_table_is_reported_not_created(tmp_path: Path) -> None:
    model = parse_model(SMALL)
    x = SqliteExecutor(tmp_path / "x.db")
    plan = plan_migration(x, model)
    assert plan.statements == [] and len(plan.warnings) == 2


# ------------------------------------------------------------------ Databricks (recorded)


def _exec(fake: FakeStatementExecution) -> DatabricksRestExecutor:
    return DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")


def _describe(columns: list[tuple[str, str]]) -> dict:
    rows: list[list[str | None]] = [[n, t.lower(), None] for n, t in columns]
    rows += [["", "", ""], ["# Partition Information", "", ""], ["# col_name", "data_type", ""]]
    return succeeded(DESCRIBE_COLS, rows)[0]


def _props(props: dict[str, str]) -> dict:
    return succeeded(PROPS_COLS, [[k, v] for k, v in props.items()])[0]


def test_databricks_plan_from_recorded_describe() -> None:
    model = parse_model(SMALL)
    fake = FakeStatementExecution()
    fake.add(_describe([("agent_id", "STRING"), ("row_version", "BIGINT")]), match="DESCRIBE")
    fake.add(
        _describe(
            [("seq", "BIGINT"), ("entry_hash", "STRING"), ("payload", "STRING"), ("old", "INT")]
        ),
        match="DESCRIBE TABLE `c`.`s`.`chain_entry`",
    )
    fake.add(
        _props(
            {
                "delta.appendOnly": "true",
                "delta.logRetentionDuration": "interval 30 days",
                "delta.deletedFileRetentionDuration": "interval 1825 days",
                "delta.minReaderVersion": "1",
            }
        ),
        match="SHOW TBLPROPERTIES `c`.`s`.`chain_entry`",
    )
    fake.add(dml_result(0), match="ALTER TABLE `c`.`s`.`agent` ADD COLUMNS")
    fake.add(dml_result(0), match="ALTER TABLE `c`.`s`.`chain_entry` SET TBLPROPERTIES")
    plan = migrate(_exec(fake), model, retention_days=1825)
    assert plan.statements == [
        "ALTER TABLE `c`.`s`.`agent` ADD COLUMNS "
        "(name STRING, risk_tier STRING, updated_at TIMESTAMP)",
        "ALTER TABLE `c`.`s`.`chain_entry` SET TBLPROPERTIES "
        "('delta.logRetentionDuration' = 'interval 1825 days')",
    ]
    assert any("chain_entry.old" in w for w in plan.warnings)
    assert any("agent.updated_at" in w and "NULLABLE" in w for w in plan.warnings)
    assert fake.remaining() == 0
    # state table has no desired properties: SHOW TBLPROPERTIES was not sent for it
    assert not any("SHOW TBLPROPERTIES `c`.`s`.`agent`" in s for s in fake.statements)


def test_databricks_type_mismatch_is_warning_only() -> None:
    model = parse_model(SMALL)
    fake = FakeStatementExecution()
    fake.add(
        _describe(
            [
                ("agent_id", "STRING"),
                ("name", "STRING"),
                ("risk_tier", "INT"),
                ("row_version", "BIGINT"),
                ("updated_at", "TIMESTAMP"),
            ]
        ),
        match="`agent`",
    )
    fake.add(failed("[TABLE_OR_VIEW_NOT_FOUND] chain_entry"), match="`chain_entry`")
    plan = migrate(_exec(fake), model)
    assert plan.statements == []
    assert any("agent.risk_tier: live type INT" in w for w in plan.warnings)
    assert any("chain_entry: table missing" in w for w in plan.warnings)


def test_databricks_full_bootstrap_matching_schema_is_noop(tmp_path: Path) -> None:
    """Create step + DESCRIBE/SHOW for every model table; live matches -> no ALTER."""
    model = load_model()
    fake = FakeStatementExecution()
    for t in model.tables.values():
        fake.add(dml_result(0), match=f"CREATE TABLE IF NOT EXISTS `c`.`s`.`{t.name}`")
    for t in model.tables.values():
        cols = [(c.name, DATABRICKS_TYPES[c.type]) for c in t.columns]
        fake.add(_describe(cols), match=f"DESCRIBE TABLE `c`.`s`.`{t.name}`")
        want = desired_properties(t, 1825)
        if want:
            fake.add(_props(want), match=f"SHOW TBLPROPERTIES `c`.`s`.`{t.name}`")
    sv = model.table("schema_version")
    fake.add_rows([(c.name, DATABRICKS_TYPES[c.type]) for c in sv.columns], [])
    fake.add(dml_result(1), match="MERGE INTO `c`.`s`.`schema_version`")
    settings = load_settings(
        sql_backend="databricks_rest",
        databricks_catalog="c",
        databricks_schema="s",
        databricks_warehouse_id="wh",
        data_dir=tmp_path,
    )
    adapters = build_adapters(settings, executor=_exec(fake), clock=FixedClock(T0))
    result = bootstrap_schema.run(settings, adapters)
    assert result["added_columns"] == 0 and result["properties_set"] == 0
    assert not any(s.startswith("ALTER") for s in fake.statements)
    assert fake.remaining() == 0


def test_plan_cli_prints_without_applying(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "p.db"
    model = load_model()
    x = SqliteExecutor(db)
    x.apply_ddl(sqlite_statements(_older(model, {"agent": {"business_owner"}})))
    x.close()
    monkeypatch.setenv("SQLITE_PATH", str(db))
    assert bootstrap_schema.main(["--plan"]) == 0
    out = capsys.readouterr().out
    assert 'ALTER TABLE "agent" ADD COLUMN business_owner TEXT;' in out
    assert "nothing applied" in out
    x = SqliteExecutor(db)
    assert "business_owner" not in (live_columns(x, "agent") or {})
    x.close()


def test_grant_statements_for_app_principal(tmp_path: Path) -> None:
    from supervisor.core.errors import ConfigError

    settings = load_settings(
        sql_backend="databricks_rest",
        databricks_catalog="c",
        databricks_schema="s",
        databricks_warehouse_id="wh",
        data_dir=tmp_path,
    )
    adapters = build_adapters(settings, executor=_exec(FakeStatementExecution()))
    stmts = bootstrap_schema.grant_statements(adapters, "1234-abcd-app-sp")
    assert len(stmts) == len(adapters.model.tables)
    assert stmts[0].startswith("GRANT SELECT, MODIFY ON TABLE `c`.`s`.`")
    assert stmts[0].endswith("TO `1234-abcd-app-sp`")
    for bad in ("FILL-ME-sp", "x`; DROP", ""):
        with pytest.raises(ConfigError):
            bootstrap_schema.grant_statements(adapters, bad)
    sqlite = build_adapters(load_settings(data_dir=tmp_path / "q"))
    with pytest.raises(ConfigError, match="Databricks"):
        bootstrap_schema.grant_statements(sqlite, "sp")
