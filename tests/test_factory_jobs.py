from __future__ import annotations

from pathlib import Path

import pytest

from supervisor import sandbox
from supervisor.adapters.factory import build_adapters, build_sql_executor
from supervisor.adapters.sql.sqlite import SqliteExecutor
from supervisor.config import load_settings
from supervisor.core.errors import ConfigError
from supervisor.core.ports import Clock, SqlExecutor, StateStore, TableStore


def test_factory_laptop_uses_sqlite(tmp_path: Path) -> None:
    a = build_adapters(load_settings(data_dir=tmp_path))
    try:
        assert isinstance(a.executor, SqliteExecutor)
        assert isinstance(a.executor, SqlExecutor)
        assert isinstance(a.tables, TableStore) and isinstance(a.state, StateStore)
        assert isinstance(a.clock, Clock)
        assert a.executor.describe().endswith("supervisor.db")
    finally:
        a.close()


def test_factory_databricks_without_config_fails_clearly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(tmp_path / "none.cfg"))
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("DATABRICKS_HOST", "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    s = load_settings(
        supervisor_mode="databricks_app",
        databricks_warehouse_id="FILL-ME-warehouse-id",
        databricks_catalog="FILL-ME-catalog",
        databricks_schema="FILL-ME-schema",
    )
    with pytest.raises(ConfigError) as e:
        build_sql_executor(s)
    assert (
        "databricks auth login" in str(e.value)
        or "FILL-ME" in str(e.value)
        or "WAREHOUSE" in str(e.value)
    )


def test_bootstrap_schema_job_runs_twice(tmp_path: Path) -> None:
    argv = [sandbox.python_executable(), "-m", "supervisor.jobs.bootstrap_schema"]
    for _ in range(2):
        res = sandbox.run(argv, cwd=tmp_path, timeout_s=120)
        assert res.returncode == 0, res.stdout + res.stderr
        assert res.stdout.startswith("[OK] schema applied") and res.stdout.isascii()
    assert (tmp_path / "data" / "local" / "supervisor.db").exists()


def test_bootstrap_schema_reports_failure_ascii(tmp_path: Path) -> None:
    res = sandbox.run(
        [sandbox.python_executable(), "-m", "supervisor.jobs.bootstrap_schema"],
        cwd=tmp_path,
        env={"DATABRICKS_TOKEN": "x" * 12},
        timeout_s=120,
    )
    assert res.returncode == 1 and res.stdout.startswith("[FAIL]")
    assert "x" * 12 not in res.stdout + res.stderr
