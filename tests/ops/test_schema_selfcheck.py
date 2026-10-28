"""WP-P3: SCHEMA_SELFCHECK compares schema/model.yaml with information_schema (fake adapter),
builds the SQL plan, never runs DDL, never stops the app; /healthz and the admin page show it."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supervisor.core.errors import SqlError
from supervisor.core.schema import load_model
from supervisor.ops import healthz, schema_selfcheck
from supervisor.ops.schema_selfcheck import SchemaCheck, run_check, run_startup

MODEL = load_model()


class FakeExec:
    """A Databricks-shaped SQL adapter that answers the information_schema query only."""

    dialect = "databricks"
    max_params = 250

    def __init__(
        self,
        live: dict[str, list[str]] | None = None,
        *,
        fail: Exception | None = None,
        prefix: str = "",
    ) -> None:
        self.catalog = "main"
        self.schema = "sup"
        self.table_prefix = prefix
        self.live = live if live is not None else full_live(prefix)
        self.fail = fail
        self.queries: list[tuple[str, dict[str, Any] | None]] = []
        self.executed: list[str] = []

    def query(self, sql: str, params: Any = None, *a: Any, **k: Any) -> list[dict[str, Any]]:
        self.queries.append((sql, params))
        if self.fail is not None:
            raise self.fail
        return [{"table_name": t, "column_name": c} for t, cols in self.live.items() for c in cols]

    def execute(self, sql: str, *a: Any, **k: Any) -> int:  # must never be called
        self.executed.append(sql)
        return -1

    def apply_ddl(self, statements: Any) -> None:  # must never be called
        self.executed.extend(statements)


def full_live(prefix: str = "") -> dict[str, list[str]]:
    return {f"{prefix}{n}": list(t.column_names) for n, t in MODEL.tables.items()}


class Settings:
    evidence_retention_days = 1825
    schema_selfcheck = True
    effective_sql_backend = "databricks_rest"


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    schema_selfcheck.set_state(None)
    healthz.reset_probe_cache()
    yield
    schema_selfcheck.set_state(None)
    healthz.reset_probe_cache()


def test_all_ok_one_query_no_ddl() -> None:
    ex = FakeExec()
    check = run_check(Settings(), ex)
    assert check.status == "ok" and check.schema_ok is True
    assert check.plan == () and check.tables_total == len(MODEL.tables)
    assert len(ex.queries) == 1  # one query for the whole schema
    sql, params = ex.queries[0]
    assert "information_schema.columns" in sql and params == {"schema": "sup"}
    assert ex.executed == []


def test_missing_table_gives_create_statement() -> None:
    live = full_live()
    live.pop("cases")
    check = run_check(Settings(), FakeExec(live))
    assert check.status == "missing" and check.schema_ok is False
    assert check.missing_tables == ("cases",)
    (stmt,) = check.plan
    assert "CREATE TABLE IF NOT EXISTS `main`.`sup`.`cases`" in stmt
    assert "USING DELTA" in stmt


def test_missing_column_gives_alter_add_columns() -> None:
    live = full_live()
    live["agent"] = [c for c in live["agent"] if c not in ("owner_team", "plug_point")]
    check = run_check(Settings(), FakeExec(live))
    assert check.status == "missing"
    assert check.missing_columns == (("agent", ("owner_team", "plug_point")),)
    (stmt,) = check.plan
    assert stmt.startswith("ALTER TABLE `main`.`sup`.`agent` ADD COLUMNS (")
    assert "owner_team STRING" in stmt and "plug_point STRING" in stmt
    assert "NOT NULL" not in stmt  # Delta cannot add a NOT NULL column to a table with rows


def test_comparison_ignores_case_and_honours_table_prefix() -> None:
    live = {k.upper(): [c.upper() for c in v] for k, v in full_live("t_").items()}
    check = run_check(Settings(), FakeExec(live, prefix="t_"))
    assert check.status == "ok"
    check2 = run_check(Settings(), FakeExec(full_live(""), prefix="t_"))
    assert check2.status == "missing" and len(check2.missing_tables) == len(MODEL.tables)
    assert "`t_agent`" in "\n".join(check2.plan)


def test_query_error_is_unknown_and_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    ex = FakeExec(fail=SqlError("PERMISSION_DENIED on information_schema"))
    with caplog.at_level("WARNING", logger="supervisor.ops.schema"):
        check = run_check(Settings(), ex)
    assert check.status == "unknown" and check.schema_ok == "unknown"
    assert "PERMISSION_DENIED" in check.detail
    assert any("self-check failed" in r.message for r in caplog.records)


def test_sqlite_is_a_noop_that_reports_ok() -> None:
    class Lite(FakeExec):
        dialect = "sqlite"  # type: ignore[assignment]

    ex = Lite()
    check = run_check(Settings(), ex)
    assert check.status == "ok" and ex.queries == []


def test_startup_off_stores_nothing() -> None:
    class Off(Settings):
        schema_selfcheck = False

    assert run_startup(Off(), runtime=None) is None
    assert schema_selfcheck.get_state() is None
    assert healthz.schema_ok_value() == "unknown"


def test_startup_stores_state_and_survives_executor_build_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import supervisor.adapters.sql.databricks_rest as rest

    def boom(_settings: Any) -> Any:
        raise RuntimeError("no credentials")

    monkeypatch.setattr(rest, "build_databricks_executor", boom)
    check = run_startup(Settings(), runtime=None)  # runtime failed to build: own executor
    assert check is not None and check.status == "unknown"
    assert schema_selfcheck.get_state() is check
    assert healthz.schema_ok_value() == "unknown"


def test_startup_uses_runtime_executor_and_stores_missing() -> None:
    live = full_live()
    live.pop("rule")

    class Adapters:
        executor = FakeExec(live)

    class Runtime:
        adapters = Adapters()

    check = run_startup(Settings(), Runtime())
    assert check is not None and check.missing_tables == ("rule",)
    assert healthz.schema_ok_value() is False


# ----------------------------------------------------------------------------- /healthz


def test_healthz_fields_default() -> None:
    from supervisor.config import load_settings

    s = load_settings(sql_backend="sqlite")
    body = healthz.body(s, None)
    assert body == {
        "status": "ok",
        "schema_ok": "unknown",
        "judge_sweep": "disabled",
        "gate_timeout_s": s.gate_decision_timeout_s,
        "model_resource": "unknown",
    }


def test_healthz_gate_timeout_follows_setting_and_judge_sweep_follows_job() -> None:
    from supervisor.config import load_settings

    s = load_settings(sql_backend="sqlite", gate_decision_timeout_s=20.0)

    class Job:
        enabled = True

    class Sched:
        jobs = {"judge_sweep": Job()}

    body = healthz.body(s, Sched())
    assert body["gate_timeout_s"] == 20.0 and body["judge_sweep"] == "enabled"
    Job.enabled = False
    assert healthz.body(s, Sched())["judge_sweep"] == "disabled"


def test_model_probe_off_makes_no_call() -> None:
    from supervisor.config import load_settings

    calls: list[int] = []
    s = load_settings(sql_backend="sqlite")
    assert healthz.model_resource(s, lambda _s: calls.append(1) or "ok") == "unknown"
    assert calls == []


def test_model_probe_on_is_cached_for_60_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.config import load_settings

    s = load_settings(sql_backend="sqlite", healthz_model_probe=True)
    calls: list[int] = []

    def probe(_s: Any) -> str:
        calls.append(1)
        return "fail" if len(calls) == 1 else "ok"

    assert healthz.model_resource(s, probe, background=False) == "fail"
    assert healthz.model_resource(s, probe, background=False) == "fail"  # cached
    assert len(calls) == 1
    clock = {"t": healthz.time.monotonic() + 61}
    monkeypatch.setattr(healthz.time, "monotonic", lambda: clock["t"])
    assert healthz.model_resource(s, probe, background=False) == "ok"  # expired: probed again
    assert len(calls) == 2


def test_model_probe_error_never_raises() -> None:
    from supervisor.config import load_settings

    s = load_settings(sql_backend="sqlite", healthz_model_probe=True)

    def probe(_s: Any) -> str:
        raise RuntimeError("gateway down")

    assert healthz.model_resource(s, probe, background=False) == "unknown"


def test_model_probe_background_returns_at_once() -> None:
    from supervisor.config import load_settings

    s = load_settings(sql_backend="sqlite", healthz_model_probe=True)
    import threading

    gate = threading.Event()

    def slow(_s: Any) -> str:
        gate.wait(5)
        return "ok"

    try:
        assert healthz.model_resource(s, slow) == "unknown"  # first call: no answer yet, no wait
    finally:
        gate.set()


def test_mock_llm_probe_is_unknown() -> None:
    from supervisor.config import load_settings

    s = load_settings(sql_backend="sqlite", healthz_model_probe=True, llm_base_url="")
    assert healthz._call_gateway(s) == "unknown"


def test_healthz_endpoint_never_500_when_state_is_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.app import app

    def boom() -> Any:
        raise RuntimeError("x")

    monkeypatch.setattr(schema_selfcheck, "get_state", boom)
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200 and r.json()["schema_ok"] == "unknown"


def test_healthz_endpoint_shows_false_when_schema_differs() -> None:
    from supervisor.app import app

    schema_selfcheck.set_state(SchemaCheck("missing", "t", 1, ("cases",)))
    body = TestClient(app).get("/healthz").json()
    assert body["schema_ok"] is False and body["status"] == "ok"


def test_rest_executor_with_recorded_information_schema_rows() -> None:
    """The real Databricks REST adapter (recorded API) answers the one information_schema query,
    sends the schema as a named parameter, and no DDL is sent."""
    from supervisor.adapters.sql.databricks_fake import FakeStatementExecution, succeeded
    from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor

    live = full_live()
    live.pop("cases")
    rows = [[t, c] for t, cols in live.items() for c in cols]
    final, chunks = succeeded(
        [("table_name", "STRING"), ("column_name", "STRING")], rows, chunk_size=200
    )
    api = FakeStatementExecution().add(final, chunks=chunks)
    ex = DatabricksRestExecutor(api, warehouse_id="wh-1", catalog="main", schema="sup")
    check = run_check(Settings(), ex)
    assert check.status == "missing" and check.missing_tables == ("cases",)
    sent = [c.kwargs for c in api.calls if c.method == "execute_statement"]
    assert len(sent) == 1
    assert "`main`.information_schema.columns" in sent[0]["statement"]
    assert [p.name for p in sent[0]["parameters"]] == ["schema"]
    assert not any(s["statement"].lstrip().upper().startswith(("CREATE", "ALTER")) for s in sent)
