"""Unit tests for the Databricks REST executor, using the recorded fake (no network)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.sql import databricks_rest
from supervisor.adapters.sql.databricks_fake import (
    FakeStatementExecution,
    dml_result,
    failed,
    pending,
    succeeded,
)
from supervisor.adapters.sql.databricks_rest import (
    DatabricksRestExecutor,
    build_databricks_executor,
    make_workspace_client,
)
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.config import load_settings
from supervisor.core.errors import (
    AppendOnlyError,
    ConcurrencyError,
    ConfigError,
    DuplicateKeyError,
    SqlError,
)
from supervisor.core.schema import load_model

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "databricks"
T0 = datetime(2026, 3, 1, 8, 0, 0, tzinfo=UTC)


class FakeTime:
    """Fake monotonic clock plus a recording sleep that can also advance it."""

    def __init__(self, step: float = 0.0) -> None:
        self.now = 0.0
        self.step = step
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += self.step or seconds


def make(
    fake: FakeStatementExecution, ft: FakeTime | None = None, **kw: Any
) -> DatabricksRestExecutor:
    ft = ft or FakeTime()
    return DatabricksRestExecutor(
        fake,
        warehouse_id="wh-test",
        catalog="cat",
        schema="sch",
        sleep=ft.sleep,
        monotonic=ft.monotonic,
        **kw,
    )


def params_of(call_kwargs: dict[str, Any]) -> list[Any]:
    return list(call_kwargs.get("parameters") or [])


def exec_calls(fake: FakeStatementExecution) -> list[dict[str, Any]]:
    return [c.kwargs for c in fake.calls if c.method == "execute_statement"]


def enum_value(x: Any) -> str:
    return str(getattr(x, "value", x))


# ------------------------------------------------------------------ 1. casting


def test_cast_by_model_types() -> None:
    types = load_model().table("agent_event").types
    cols = [
        ("event_id", "STRING"),
        ("ts", "TIMESTAMP"),
        ("amount_minor", "LONG"),
        ("latency_ms", "LONG"),
        ("args_masked", "STRING"),
        ("currency", "STRING"),
    ]
    rows: list[list[str | None]] = [
        ["e1", "2026-03-01T08:15:30.123Z", "1500000", "42", "Nguyễn Thị Hương đã chuyển", None],
    ]
    fake = FakeStatementExecution().add_rows(cols, rows)
    out = make(fake).query("SELECT 1", column_types=types)
    assert out == [
        {
            "event_id": "e1",
            "ts": datetime(2026, 3, 1, 8, 15, 30, 123000, tzinfo=UTC),
            "amount_minor": 1500000,
            "latency_ms": 42,
            "args_masked": "Nguyễn Thị Hương đã chuyển",
            "currency": None,
        }
    ]
    assert isinstance(out[0]["amount_minor"], int)
    assert out[0]["ts"].utcoffset().total_seconds() == 0


def test_cast_bool_and_json_by_model_types() -> None:
    types = {"flag": "bool", "doc": "json", "n": "money"}
    fake = FakeStatementExecution().add_rows(
        [("flag", "BOOLEAN"), ("doc", "STRING"), ("n", "LONG")],
        [["true", '{"k": [1, 2], "v": "Hà Nội"}', None], ["false", None, "7"]],
    )
    out = make(fake).query("SELECT 1", column_types=types)
    assert out[0] == {"flag": True, "doc": {"k": [1, 2], "v": "Hà Nội"}, "n": None}
    assert out[1] == {"flag": False, "doc": None, "n": 7}


def test_cast_by_manifest_type_name() -> None:
    cols = [
        ("a", "LONG"),
        ("b", "DOUBLE"),
        ("c", "BOOLEAN"),
        ("d", "TIMESTAMP"),
        ("e", "DATE"),
        ("f", "STRING"),
    ]
    fake = FakeStatementExecution().add_rows(
        cols, [["9", "2.5", "true", "2026-03-01T00:00:00Z", "2026-03-02", "Đà Nẵng"]]
    )
    row = make(fake).query("SELECT 1")[0]
    assert row["a"] == 9 and isinstance(row["a"], int)
    assert row["b"] == 2.5 and isinstance(row["b"], float)
    assert row["c"] is True
    assert row["d"] == datetime(2026, 3, 1, tzinfo=UTC)
    assert row["e"] == date(2026, 3, 2)
    assert row["f"] == "Đà Nẵng"


# ------------------------------------------------------------------ 2. recording


def test_recorded_two_chunk_select() -> None:
    data = json.loads((FIXTURES / "select_agent_event_2chunks.json").read_text(encoding="utf-8"))
    fake = FakeStatementExecution().add(data["response"], chunks={1: data["chunk_1"]})
    types = load_model().table("agent_event").types
    out = make(fake).query("SELECT * FROM agent_event", column_types=types)
    assert [r["event_id"] for r in out] == [f"ev-00{i}" for i in range(1, 6)]
    assert out[0]["amount_minor"] == 1500000
    assert out[1]["amount_minor"] is None
    assert out[3]["latency_ms"] is None
    assert out[2]["args_masked"] == "Xác minh giấy tờ: Trần Thị Bích"
    assert out[4]["ts"] == datetime(2026, 3, 1, 8, 19, 0, 999000, tzinfo=UTC)
    chunk_calls = [c.kwargs for c in fake.calls if c.method == "get_statement_result_chunk_n"]
    assert len(chunk_calls) == 1
    assert chunk_calls[0]["chunk_index"] == 1


# ------------------------------------------------------------------ 3. polling


def test_polling_until_succeeded_with_capped_backoff() -> None:
    final, chunks = succeeded([("n", "LONG")], [["1"]])
    states = [pending("PENDING"), pending("RUNNING")] + [pending("RUNNING")] * 5 + [final]
    fake = FakeStatementExecution().add(states, chunks=chunks)
    ft = FakeTime()
    out = make(fake, ft).query("SELECT 1")
    assert out == [{"n": 1}]
    assert ft.sleeps == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0, 5.0]
    assert max(ft.sleeps) <= 5.0
    assert sum(1 for c in fake.calls if c.method == "get_statement") == 7


# ------------------------------------------------------------------ 4. deadline


def test_deadline_cancels_and_raises() -> None:
    fake = FakeStatementExecution().add([pending("RUNNING")])
    ft = FakeTime(step=50.0)
    with pytest.raises(SqlError) as ei:
        make(fake, ft).query("SELECT 1")
    msg = str(ei.value)
    assert "timed out" in msg
    assert "wh-test" in msg
    assert len(fake.cancelled) == 1
    assert ft.now > 120


# ------------------------------------------------------------------ 5. failures


def run_failed(message: str, sql_state: str | None = None) -> SqlError:
    fake = FakeStatementExecution().add(failed(message, sql_state))
    with pytest.raises(SqlError) as ei:
        make(fake).execute("SELECT secret FROM x WHERE a = :a", {"a": "TOP-SECRET-VALUE"})
    return ei.value


def test_table_not_found_hints_bootstrap() -> None:
    err = run_failed("[TABLE_OR_VIEW_NOT_FOUND] The table or view `cat`.`sch`.`agent` ...", "42P01")
    assert type(err) is SqlError
    assert "bootstrap_schema" in str(err)
    assert "42P01" in str(err)


def test_append_only_maps_to_append_only_error() -> None:
    err = run_failed(
        "[DELTA_UPDATE_APPEND_ONLY] Cannot UPDATE. This table is configured to only allow appends."
    )
    assert isinstance(err, AppendOnlyError)


def test_concurrent_append_maps_to_concurrency_error() -> None:
    err = run_failed("ConcurrentAppendException: Files were added to the root of the table")
    assert isinstance(err, ConcurrencyError)


def test_error_message_has_target_and_no_param_values() -> None:
    err = run_failed("boom")
    msg = str(err)
    assert "wh-test" in msg
    assert "cat.sch" in msg
    assert "TOP-SECRET-VALUE" not in msg
    assert type(err) is SqlError


def test_transport_exception_wrapped_without_param_values() -> None:
    class Boom(FakeStatementExecution):
        def execute_statement(self, statement: str, warehouse_id: str, **kw: Any) -> Any:
            raise RuntimeError("connection reset")

    with pytest.raises(SqlError) as ei:
        make(Boom()).execute("SELECT :a", {"a": "TOP-SECRET-VALUE"})
    assert "connection reset" in str(ei.value)
    assert "wh-test" in str(ei.value)
    assert "TOP-SECRET-VALUE" not in str(ei.value)


# ------------------------------------------------------------------ 6. parameters


def test_parameters_and_request_options() -> None:
    fake = FakeStatementExecution().add(dml_result(1))
    when = datetime(2026, 3, 1, 8, 15, 30, 123456, tzinfo=UTC)
    make(fake).execute(
        "UPDATE t SET x = :a",
        {"a": 5, "b": True, "c": None, "d": when, "e": {"k": 1}},
        param_types={"c": "timestamp"},
    )
    kw = exec_calls(fake)[0]
    got = {p.name: (p.type, p.value) for p in params_of(kw)}
    assert got == {
        "a": ("BIGINT", "5"),
        "b": ("BOOLEAN", "true"),
        "c": ("TIMESTAMP", None),
        "d": ("TIMESTAMP", "2026-03-01T08:15:30.123456Z"),
        "e": ("STRING", '{"k":1}'),
    }
    assert kw["wait_timeout"] == "30s"
    assert enum_value(kw["format"]) == "JSON_ARRAY"
    assert enum_value(kw["disposition"]) == "INLINE"
    assert enum_value(kw["on_wait_timeout"]) == "CONTINUE"
    assert kw["warehouse_id"] == "wh-test"
    assert kw["catalog"] == "cat"
    assert kw["schema"] == "sch"


def test_no_params_sends_none() -> None:
    fake = FakeStatementExecution().add(dml_result(0))
    make(fake).execute("DELETE FROM t")
    assert exec_calls(fake)[0]["parameters"] is None


# ------------------------------------------------------------------ 7. execute


def test_execute_returns_affected_rows() -> None:
    fake = FakeStatementExecution().add(dml_result(3))
    assert make(fake).execute("UPDATE t SET a = 1") == 3


def test_execute_ddl_returns_minus_one() -> None:
    fake = FakeStatementExecution().add({"status": {"state": "SUCCEEDED"}})
    assert make(fake).execute("CREATE TABLE IF NOT EXISTS x (a INT)") == -1


def test_apply_ddl_runs_each_statement() -> None:
    fake = FakeStatementExecution()
    fake.add({"status": {"state": "SUCCEEDED"}}).add({"status": {"state": "SUCCEEDED"}})
    make(fake).apply_ddl(["CREATE TABLE a (x INT)", "CREATE TABLE b (x INT)"])
    assert fake.statements == ["CREATE TABLE a (x INT)", "CREATE TABLE b (x INT)"]


# ------------------------------------------------------------------ 8. stores


AGENT = {
    "agent_id": "agent-001",
    "name": "Trợ lý tín dụng",
    "owner_team": "Khối Bán lẻ",
    "owner_user": "nguyen.van.a",
    "risk_tier": "high",
    "host_type": "databricks_app",
    "plug_point": "gateway",
    "model_family": "gpt",
    "status": "active",
    "gate_state": "open",
    "created_at": T0,
}

AGENT_COLS = [(n, "STRING") for n in load_model().table("agent").column_names]


def agent_row(version: int) -> list[str | None]:
    out: list[str | None] = []
    for name in load_model().table("agent").column_names:
        if name == "row_version":
            out.append(str(version))
        elif name in ("created_at", "updated_at"):
            out.append("2026-03-01T08:00:00.000000Z")
        else:
            out.append(str(AGENT.get(name)) if AGENT.get(name) is not None else None)
    return out


def test_state_insert_uses_merge_on_databricks() -> None:
    fake = FakeStatementExecution().add(dml_result(1))
    ex = make(fake)
    row = SqlStateStore(ex, FixedClock(T0)).insert("agent", AGENT)
    assert row["row_version"] == 1
    sql = fake.statements[0]
    assert sql.startswith("MERGE INTO `cat`.`sch`.`agent` AS tgt")
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    names = {p.name for p in params_of(exec_calls(fake)[0])}
    assert "v_agent_id" in names and "v_row_version" in names


def test_state_insert_duplicate() -> None:
    fake = FakeStatementExecution().add(dml_result(0))
    with pytest.raises(DuplicateKeyError):
        SqlStateStore(make(fake), FixedClock(T0)).insert("agent", AGENT)


def test_state_update_conflict() -> None:
    fake = FakeStatementExecution()
    fake.add(dml_result(0), match="UPDATE")
    fake.add_rows(
        [(n, "STRING") for n in load_model().table("agent").column_names],
        [agent_row(5)],
        match="SELECT",
    )
    store = SqlStateStore(make(fake), FixedClock(T0))
    with pytest.raises(ConcurrencyError):
        store.update("agent", {"agent_id": "agent-001"}, {"status": "paused"}, expected_version=1)
    assert "`cat`.`sch`.`agent`" in fake.statements[0]


def test_state_update_success() -> None:
    fake = FakeStatementExecution()
    fake.add(dml_result(1), match="UPDATE")
    fake.add_rows(
        [(n, "STRING") for n in load_model().table("agent").column_names],
        [agent_row(2)],
        match="SELECT",
    )
    store = SqlStateStore(make(fake), FixedClock(T0))
    row = store.update("agent", {"agent_id": "agent-001"}, {"status": "paused"}, 1)
    assert row["row_version"] == 2


def test_append_batches_respect_max_params() -> None:
    n_rows = 300
    fake = FakeStatementExecution()
    ex = make(fake)
    rows = [
        {
            "event_id": f"ev-{i:04d}",
            "ts": T0,
            "trace_id": "t",
            "span_id": f"s{i}",
            "agent_id": "agent-001",
            "event_type": "tool_call",
            "env": "prod",
            "source": "gateway",
            "capture_level": "masked",
            "amount_minor": i,
        }
        for i in range(n_rows)
    ]
    per_stmt = ex.max_params // len(load_model().table("agent_event").column_names)
    left = n_rows
    while left > 0:
        fake.add(dml_result(min(per_stmt, left)))
        left -= per_stmt
    total = SqlTableStore(ex).append("agent_event", rows)
    assert total == n_rows
    calls = exec_calls(fake)
    assert len(calls) > 1
    assert all(len(params_of(c)) <= ex.max_params for c in calls)
    assert sum(len(params_of(c)) for c in calls) == n_rows * len(
        load_model().table("agent_event").column_names
    )
    assert all("`cat`.`sch`.`agent_event`" in c["statement"] for c in calls)


def test_qualify_with_prefix() -> None:
    ex = make(FakeStatementExecution(), table_prefix="t1_")
    assert ex.qualify("agent") == "`cat`.`sch`.`t1_agent`"


def test_constructor_rejects_placeholders() -> None:
    with pytest.raises(ConfigError):
        DatabricksRestExecutor(
            FakeStatementExecution(), warehouse_id="FILL-ME-wh", catalog="c", schema="s"
        )
    with pytest.raises(ConfigError):
        DatabricksRestExecutor(
            FakeStatementExecution(), warehouse_id="w", catalog="FILL-ME-c", schema="s"
        )


# ------------------------------------------------------------------ 9. build


def settings(**over: Any) -> Any:
    base: dict[str, Any] = {
        "supervisor_mode": "databricks_app",
        "databricks_catalog": "cat",
        "databricks_schema": "sch",
        "databricks_warehouse_name": "wh-name",
    }
    base.update(over)
    return load_settings(**base)


def stub_client(fake: FakeStatementExecution) -> Any:
    whs = [SimpleNamespace(name="other", id="id-other"), SimpleNamespace(name="wh-name", id="id-7")]
    return SimpleNamespace(
        statement_execution=fake,
        warehouses=SimpleNamespace(list=lambda: iter(whs)),
        config=SimpleNamespace(host="https://adb.example.test"),
    )


def test_build_resolves_warehouse_name() -> None:
    ex = build_databricks_executor(
        settings(table_prefix="p_"), client=stub_client(FakeStatementExecution())
    )
    assert ex.warehouse_id == "id-7"
    assert ex.host == "https://adb.example.test"
    assert ex.identity == "service_principal"
    assert ex.qualify("agent") == "`cat`.`sch`.`p_agent`"
    assert ex.deadline_s == 120.0


def test_build_unknown_warehouse_name() -> None:
    s = settings(databricks_warehouse_name="nope")
    with pytest.raises(ConfigError):
        build_databricks_executor(s, client=stub_client(FakeStatementExecution()))


def test_build_with_placeholders_raises() -> None:
    s = settings(
        databricks_warehouse_name="FILL-ME-warehouse",
        databricks_catalog="FILL-ME-catalog",
        databricks_schema="FILL-ME-schema",
    )
    with pytest.raises(ConfigError):
        build_databricks_executor(s, client=stub_client(FakeStatementExecution()))


def test_build_with_placeholder_warehouse_only() -> None:
    s = settings(databricks_warehouse_name="FILL-ME-warehouse")
    with pytest.raises(ConfigError):
        build_databricks_executor(s, client=stub_client(FakeStatementExecution()))


# ------------------------------------------------------------------ 10. client


def test_retry_cap_goes_into_config_not_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import databricks.sdk
    import databricks.sdk.core

    seen: dict[str, Any] = {}

    class RecConfig:
        token = None
        auth_type = "databricks-cli"

        def __init__(self, **kw: Any) -> None:
            seen["config"] = kw

    class RecClient:
        def __init__(self, **kw: Any) -> None:
            seen["client"] = kw

    monkeypatch.setattr(databricks.sdk.core, "Config", RecConfig)
    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", RecClient)
    s = settings(databricks_retry_timeout_s=75, databricks_host="https://adb.example.test")
    client = make_workspace_client(s)
    assert isinstance(client, RecClient)
    assert seen["config"]["retry_timeout_seconds"] == 75
    assert 60 <= seen["config"]["retry_timeout_seconds"] <= 120
    assert seen["config"]["host"] == "https://adb.example.test"
    assert "retry_timeout_seconds" not in seen["client"]
    assert set(seen["client"]) == {"config"}


def test_pat_auth_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import databricks.sdk
    import databricks.sdk.core

    class PatConfig:
        token = "dapi-not-real"
        auth_type = "pat"

        def __init__(self, **kw: Any) -> None:
            pass

    monkeypatch.setattr(databricks.sdk.core, "Config", PatConfig)
    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", lambda **kw: object())
    with pytest.raises(ConfigError, match="OAuth only"):
        make_workspace_client(settings())


def test_module_exposes_login_hint() -> None:
    assert "databricks auth login" in databricks_rest.LOGIN_HINT
