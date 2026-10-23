"""WP-P5: SQL on behalf of the signed-in user (sandbox-only switch)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from supervisor.adapters.auth.base import UserToken
from supervisor.adapters.auth.user_token import UserTokenMiddleware, forwarded_token
from supervisor.adapters.sql.databricks_fake import (
    FakeStatementExecution,
    dml_result,
    failed,
)
from supervisor.adapters.sql.databricks_rest import (
    DatabricksRestExecutor,
    _make_user_api_factory,
)
from supervisor.config import load_settings
from supervisor.core.errors import ConfigError, SqlError

USER = "user-tok-123"  # noqa: S105
APP = {
    "SUPERVISOR_MODE": "databricks_app",
    "DATABRICKS_HOST": "ws.example.invalid",
    "DATABRICKS_CLIENT_ID": "c",
    "DATABRICKS_CLIENT_SECRET": "s",
}


def _executor() -> tuple[DatabricksRestExecutor, FakeStatementExecution, FakeStatementExecution]:
    sp, user = FakeStatementExecution(), FakeStatementExecution()
    seen: list[str] = []

    def factory(token: str) -> Any:
        seen.append(token)
        return user

    ex = DatabricksRestExecutor(
        sp, warehouse_id="wh", catalog="c", schema="s", identity="service_principal",
        user_api_factory=factory,
    )  # fmt: skip
    ex.seen = seen  # type: ignore[attr-defined]
    return ex, sp, user


def test_config_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_settings().sql_user_token_forward is False
    monkeypatch.setenv("SQL_USER_TOKEN_FORWARD", "1")
    monkeypatch.setenv("DATABRICKS_HOST", "ws.example.invalid")
    with pytest.raises(ConfigError, match="SQL_USER_TOKEN_FORWARD"):
        load_settings()  # laptop mode
    for k, v in APP.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    with pytest.raises(ConfigError, match="SQL_USER_TOKEN_FORWARD"):
        load_settings()
    monkeypatch.setenv("SQL_BACKEND", "databricks_rest")
    assert load_settings().sql_user_token_forward is True
    monkeypatch.delenv("SQL_BACKEND")
    assert load_settings().sql_user_token_forward is True  # auto resolves to rest in app mode


@pytest.mark.parametrize(("llm", "sql", "expect"), [(0, 0, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1)])
def test_middleware_for_either_flag(llm: int, sql: int, expect: int) -> None:
    from supervisor.ops import middleware

    app = FastAPI()
    s = SimpleNamespace(
        rate_limit_enabled=False, max_request_bytes=0, security_headers_enabled=False,
        hsts_enabled=False, request_id_header="X-Request-ID",
        llm_user_token_forward=bool(llm), sql_user_token_forward=bool(sql),
    )  # fmt: skip
    middleware.install(app, s)
    assert sum(m.cls is UserTokenMiddleware for m in app.user_middleware) == expect


def test_console_request_uses_user_api_and_background_uses_sp() -> None:
    ex, sp, user = _executor()
    sp.add(dml_result(1))
    user.add(dml_result(1))
    app = FastAPI()
    app.add_middleware(UserTokenMiddleware)

    @app.get("/q")
    def q() -> dict[str, int]:  # sync: runs in a worker thread with a copied context
        return {"n": ex.execute("UPDATE t SET a = 1")}

    c = TestClient(app)
    assert c.get("/q", headers={"X-Forwarded-Access-Token": USER}).json() == {"n": 1}
    assert ex.seen == [USER] and len(user.calls) == 1 and not sp.calls  # type: ignore[attr-defined]
    assert c.get("/q").json() == {"n": 1}  # no header: SP
    assert ex.seen == [USER] and len(sp.calls) == 1  # type: ignore[attr-defined]
    sp.add(dml_result(1))
    ex.execute("UPDATE t SET a = 2")  # background call, no context
    assert len(sp.calls) == 2 and ex.seen == [USER]  # type: ignore[attr-defined]


def test_flag_off_ignores_token() -> None:
    sp = FakeStatementExecution().add(dml_result(1))
    ex = DatabricksRestExecutor(sp, warehouse_id="wh", catalog="c", schema="s")
    with forwarded_token(UserToken(USER)):
        ex.execute("UPDATE t SET a = 1")
    assert len(sp.calls) == 1


def test_error_names_identity_and_hides_token(caplog: pytest.LogCaptureFixture) -> None:
    ex, sp, user = _executor()
    user.add(failed(f"PERMISSION_DENIED for {USER}"))
    with caplog.at_level(logging.DEBUG), forwarded_token(UserToken(USER)):
        with pytest.raises(SqlError) as ei:
            ex.execute(f"SELECT '{USER}'")
    assert "identity=user_forwarded" in str(ei.value)
    assert USER not in str(ei.value) and USER not in caplog.text
    sp.add(failed("PERMISSION_DENIED"))
    with pytest.raises(SqlError, match="identity=service_principal"):
        ex.execute("SELECT 1")


def test_factory_failure_hides_token() -> None:
    def boom(token: str) -> Any:
        raise RuntimeError(f"bad {token}")

    ex = DatabricksRestExecutor(
        FakeStatementExecution(), warehouse_id="wh", catalog="c", schema="s",
        identity="service_principal", user_api_factory=boom,
    )  # fmt: skip
    with forwarded_token(UserToken(USER)), pytest.raises(SqlError) as ei:
        ex.execute("SELECT 1")
    assert "identity=user_forwarded" in str(ei.value) and USER not in str(ei.value)


def test_real_factory_sends_bearer() -> None:
    api = _make_user_api_factory(load_settings(), "https://ws.example.invalid")(USER)
    headers = api._api._cfg.authenticate()  # noqa: SLF001
    assert headers["Authorization"] == f"Bearer {USER}"


def test_runtime_build_runs_as_sp_inside_a_token_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.adapters.auth.user_token import current_forwarded_token
    from supervisor.gateway import wiring as gw

    seen: list[object] = []

    def fake_build(settings: Any = None, policy_dir: Any = None) -> Any:
        seen.append(current_forwarded_token())
        return SimpleNamespace(gateway=object())

    monkeypatch.setattr("supervisor.wiring._build_runtime", fake_build)
    monkeypatch.setattr(gw, "_runtime", None)
    monkeypatch.setattr(gw, "_gateway", None)
    ex, _sp, user = _executor()
    user.add(dml_result(1))
    app = FastAPI()
    app.add_middleware(UserTokenMiddleware)

    @app.get("/q")
    def q() -> dict[str, int]:
        gw.install_runtime(None)  # lazy build inside the request
        return {"n": ex.execute("UPDATE t SET a = 1")}

    assert TestClient(app).get("/q", headers={"X-Forwarded-Access-Token": USER}).json() == {"n": 1}
    assert seen == [None]  # the build saw no token
    assert ex.seen == [USER]  # type: ignore[attr-defined]  # the request's own SQL still did


def test_real_factory_close_hook_closes_session() -> None:
    api = _make_user_api_factory(load_settings(), "https://ws.example.invalid")(USER)
    api._supervisor_close()  # noqa: SLF001 - must not raise
