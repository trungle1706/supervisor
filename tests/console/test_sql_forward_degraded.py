"""WP-P5: SQL_USER_TOKEN_FORWARD with a service principal that has no grant yet."""

from __future__ import annotations

import copy
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supervisor.adapters.auth.base import UserToken
from supervisor.adapters.auth.user_token import forwarded_token
from supervisor.adapters.factory import build_adapters
from supervisor.adapters.sql.databricks_fake import FakeStatementExecution, dml_result
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.sqlite import SqliteExecutor
from supervisor.adapters.sql.store import SqlTableStore
from supervisor.config import load_settings
from supervisor.core.errors import SqlError
from supervisor.core.schema import load_model
from supervisor.jobs import bootstrap_schema

TOKEN = "eyFAKE-user-token-never-logged-0123456789"  # noqa: S105
HDR = {"X-Forwarded-Email": "rev@bank.example", "X-Forwarded-Access-Token": TOKEN}


def test_chain_tables_use_sp_only_executor() -> None:
    from supervisor.wiring import _chain_tables

    sp, user = FakeStatementExecution(), FakeStatementExecution()
    ex = DatabricksRestExecutor(
        sp, warehouse_id="wh", catalog="c", schema="s", identity="service_principal",
        user_api_factory=lambda _t: user,
    )  # fmt: skip
    model = load_model()
    adapters = SimpleNamespace(executor=ex, model=model, tables=SqlTableStore(ex, model))
    chain_tables = _chain_tables(adapters)
    sp.add(dml_result(1), match="chain_entry")
    user.add(dml_result(1), match="incident")
    with forwarded_token(UserToken(TOKEN)):
        chain_tables.x.execute(
            "INSERT INTO chain_entry VALUES (1)"
        )  # chain: SP, even inside a token request
        ex.execute("UPDATE incident SET a = 1")  # everything else: the user
    assert any("chain_entry" in s for s in sp.statements) and not sp.remaining()
    assert [("incident" in s) for s in user.statements] == [True]


def test_build_runtime_gives_chain_the_sp_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import supervisor.wiring as w

    class Marked(SqliteExecutor):
        def sp_only(self) -> Any:
            twin = copy.copy(self)
            twin.marker = True  # type: ignore[attr-defined]
            return twin

    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d", llm_base_url="")
    assert settings.sqlite_path is not None
    adapters = build_adapters(settings, executor=Marked(settings.sqlite_path, table_prefix=""))
    bootstrap_schema.run(settings, adapters)
    seen: list[Any] = []
    real = w.build_chain_writer

    def spy(settings: Any, tables: Any, clock: Any, *a: Any) -> Any:
        seen.append(tables)
        return real(settings, tables, clock, *a)

    monkeypatch.setattr(w, "build_chain_writer", spy)
    rt = w.build_runtime(settings, adapters=adapters)
    try:
        assert getattr(seen[0].x, "marker", False) is True
        assert getattr(adapters.executor, "marker", False) is False
    finally:
        rt.close()


def test_user_api_cause_is_dropped_and_session_closed(caplog: pytest.LogCaptureFixture) -> None:
    def boom(token: str) -> Any:
        raise RuntimeError(f"bad {token}")

    ex = DatabricksRestExecutor(
        FakeStatementExecution(), warehouse_id="wh", catalog="c", schema="s",
        identity="service_principal", user_api_factory=boom,
    )  # fmt: skip
    with forwarded_token(UserToken(TOKEN)), pytest.raises(SqlError) as ei:
        ex.execute("SELECT 1")
    text = "".join(traceback.format_exception(ei.value))
    assert TOKEN not in text and TOKEN not in caplog.text
    closed: list[bool] = []
    user = FakeStatementExecution()

    def execute_statement(*a: Any, **k: Any) -> Any:
        raise RuntimeError(f"denied {TOKEN}")

    user.execute_statement = execute_statement  # type: ignore[method-assign]
    user._supervisor_close = lambda: closed.append(True)  # type: ignore[attr-defined]
    ex2 = DatabricksRestExecutor(
        FakeStatementExecution(), warehouse_id="wh", catalog="c", schema="s",
        user_api_factory=lambda _t: user,
    )  # fmt: skip
    with forwarded_token(UserToken(TOKEN)), pytest.raises(SqlError) as ei2:
        ex2.execute("SELECT 1")
    assert TOKEN not in "".join(traceback.format_exception(ei2.value))
    assert closed == [True]


@pytest.fixture
def degraded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from supervisor.adapters.auth import set_provider
    from supervisor.app import app
    from supervisor.console import context as cc
    from supervisor.gateway import wiring as gate_wiring

    auth = tmp_path / "auth.yaml"
    auth.write_text(
        "service_principal_id: app-sp-test\nroles:\n  reviewer: {users: [rev@bank.example]}\n",
        encoding="utf-8",
    )
    settings = load_settings(
        supervisor_mode="databricks_app", sql_backend="databricks_rest",
        databricks_host="https://ws.example.invalid", data_dir=tmp_path / "data",
        llm_base_url="", auth_config_file=auth, sql_user_token_forward=True,
        governance_enabled=True,
        console_systems_enabled=True, console_nav_v3=True,
        databricks_client_id="c", databricks_client_secret="s",
        databricks_warehouse_id="wh", databricks_catalog="cat", databricks_schema="sch",
    )  # fmt: skip
    ex = SqliteExecutor(tmp_path / "x.db", table_prefix="")
    monkeypatch.setattr("supervisor.adapters.factory.build_sql_executor", lambda _s: ex)
    a = build_adapters(settings)
    bootstrap_schema.run(settings, a)
    monkeypatch.setattr("supervisor.config.get_settings", lambda: settings)

    def boom(*_a: Any, **_k: Any) -> Any:
        raise SqlError("PERMISSION_DENIED identity=service_principal")

    monkeypatch.setattr(gate_wiring, "install_runtime", boom)
    cc.set_context(None)
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        cc.set_context(None)
        set_provider(None)
        a.close()


def test_degraded_console_renders_reads_and_400s_gate_paths(degraded: TestClient) -> None:
    for url in ("/console/", "/console/governance", "/console/supervisor"):
        r = degraded.get(url, headers=HDR)
        assert r.status_code == 200, (url, r.status_code, r.text[:300])
        assert TOKEN not in r.text
    r = degraded.post(
        "/console/agents/credit_prequal/pause",
        data={"reason": "x"},
        headers={**HDR, "HX-Request": "true"},
    )
    assert r.status_code == 400, r.text
    assert "gateway unavailable" in r.text
