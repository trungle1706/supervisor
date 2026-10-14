"""Preflight Databricks checks (bank guide section 6) with fakes for every branch."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor import preflight
from supervisor.adapters.sql.databricks_fake import FakeStatementExecution, dml_result, failed
from supervisor.config import Settings, load_settings
from supervisor.preflight import Check, databricks_checks, format_check, run_checks, scrub
from supervisor.sandbox import RunResult
from tests.databricks.fakes import FakeFiles

TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyQGJhbmsifQ.c2lnbmF0dXJlLXZhbHVl"


class FakeClient:
    def __init__(
        self,
        *,
        retry: int = 90,
        me_error: Exception | None = None,
        warehouses: list[tuple[str, str]] | None = None,
        endpoint: str | None = "READY",
    ) -> None:
        self.config = SimpleNamespace(
            retry_timeout_seconds=retry, host="https://ws.example.invalid"
        )
        self._me_error = me_error
        self.current_user = SimpleNamespace(me=self._me)
        whs = warehouses if warehouses is not None else [("shared-wh", "abc123")]
        self.warehouses = SimpleNamespace(
            list=lambda: [SimpleNamespace(name=n, id=i) for n, i in whs]
        )
        self.statement_execution = FakeStatementExecution()
        self._endpoint = endpoint
        self.serving_endpoints = SimpleNamespace(get=self._get_endpoint)
        self.files = FakeFiles()

    def _me(self) -> Any:
        if self._me_error:
            raise self._me_error
        return SimpleNamespace(user_name="user01@example.invalid")

    def _get_endpoint(self, name: str) -> Any:
        if self._endpoint is None:
            raise LookupError(f"RESOURCE_DOES_NOT_EXIST: endpoint {name}")
        return SimpleNamespace(
            state=SimpleNamespace(
                ready=SimpleNamespace(value=self._endpoint),
                config_update=SimpleNamespace(value="NOT_UPDATING"),
            )
        )

    def script_sql(self, *, select_ok: bool = True, create_ok: bool = True) -> FakeClient:
        se = self.statement_execution
        if select_ok:
            se.add_rows([("ok", "INT")], [["1"]], match="SELECT 1")
        else:
            se.add(failed("Connection aborted"), match="SELECT 1")
        if create_ok:
            se.add(dml_result(0), match="CREATE TABLE IF NOT EXISTS")
            se.add(dml_result(0), match="DROP TABLE IF EXISTS")
        else:
            se.add(failed("PERMISSION_DENIED: CREATE TABLE on schema"), match="CREATE TABLE")
        return self


def cfg_file(tmp_path: Path, profile: str = "bank") -> Path:
    p = tmp_path / ".databrickscfg"
    p.write_text(f"[{profile}]\nhost = https://ws.example.invalid\nauth_type = databricks-cli\n")
    return p


@pytest.fixture
def laptop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(cfg_file(tmp_path)))
    return load_settings(
        sql_backend="databricks_rest",
        databricks_host="https://ws.example.invalid",
        databricks_config_profile="bank",
        databricks_auth_type="databricks-cli",
        databricks_warehouse_name="shared-wh",
        databricks_catalog="cat",
        databricks_schema="sch",
        llm_endpoint="judge-endpoint",
    )


def cli_ok(argv: list[str]) -> RunResult:
    assert argv[1:5] == ["auth", "token", "--profile", "bank"]
    out = json.dumps({"access_token": TOKEN, "token_type": "Bearer", "expiry": "2026-10-14T06:00Z"})
    return RunResult(tuple(argv), 0, out, "")


def cli_expired(argv: list[str]) -> RunResult:
    return RunResult(tuple(argv), 1, "", "Error: invalid refresh token\nmore")


def names(checks: list[Check]) -> dict[str, str]:
    return {c.name: c.status for c in checks}


def run(s: Settings, client: FakeClient | Exception, cli: Any = cli_ok, **kw: Any) -> list[Check]:
    def factory(_: Settings) -> Any:
        if isinstance(client, Exception):
            raise client
        return client

    return databricks_checks(s, client_factory=factory, cli=cli, **kw)


def test_all_ok_and_token_never_printed(laptop: Settings) -> None:
    checks = run(laptop, FakeClient().script_sql())
    st = names(checks)
    assert all(v == "OK" for v in st.values()), st
    for key in (
        "databricks extra",
        "databricks auth",
        "databricks profile",
        "oauth token (CLI)",
        "databricks sign-in",
        "retry caps",
        "sql warehouse",
        "warehouse reachable",
        "schema writable",
        "serving endpoint",
    ):
        assert key in st, key
    text = "\n".join(format_check(c) for c in checks)
    assert TOKEN not in text and text.isascii()
    assert "shared-wh -> id abc123" in text and "user01@example.invalid" in text
    assert "`cat`.`sch`.`preflight_probe_" in text


def test_not_in_use_is_one_skip() -> None:
    checks = databricks_checks(load_settings())
    assert [(c.status, c.name) for c in checks] == [("SKIP", "databricks")]


def test_extra_missing_fails_with_fix(laptop: Settings) -> None:
    checks = run(laptop, FakeClient(), find_spec=lambda name: None)
    assert [(c.status, c.name) for c in checks] == [("FAIL", "databricks extra")]
    assert "uv sync --python 3.11 --extra databricks" in checks[0].fix


def test_profile_missing_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(cfg_file(tmp_path, "other")))
    s = load_settings(sql_backend="databricks_rest", databricks_config_profile="bank")
    st = names(run(s, FakeClient()))
    assert st["databricks profile"] == "FAIL" and "databricks sign-in" not in st


def test_no_profile_no_sp_fails() -> None:
    s = load_settings(sql_backend="databricks_rest")
    checks = run(s, FakeClient())
    assert names(checks)["databricks auth"] == "FAIL"
    assert "databricks auth login" in checks[-1].fix


def test_expired_refresh_token(laptop: Settings) -> None:
    checks = run(laptop, FakeClient().script_sql(), cli=cli_expired)
    c = next(c for c in checks if c.name == "oauth token (CLI)")
    assert c.status == "FAIL" and "invalid refresh token" in c.detail
    assert c.fix.startswith(
        "databricks auth login --host https://ws.example.invalid --profile bank"
    )


def test_cli_missing_is_skip(laptop: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.sandbox, "which", lambda name: None)
    checks = run(laptop, FakeClient().script_sql(), cli=None)
    assert names(checks)["oauth token (CLI)"] == "SKIP"
    assert names(checks)["databricks sign-in"] == "OK"


def test_sign_in_failure_stops(laptop: Settings) -> None:
    checks = run(laptop, FakeClient(me_error=RuntimeError("cannot configure default credentials")))
    assert checks[-1].name == "databricks sign-in" and checks[-1].status == "FAIL"
    assert "host=https://ws.example.invalid" in checks[-1].detail


def test_client_factory_config_error(laptop: Settings) -> None:
    from supervisor.core.errors import ConfigError

    checks = run(laptop, ConfigError("cannot configure Databricks credentials"))
    assert checks[-1].status == "FAIL" and checks[-1].name == "databricks sign-in"


def test_retry_cap_out_of_range(laptop: Settings) -> None:
    st = names(run(laptop, FakeClient(retry=300).script_sql()))
    assert st["retry caps"] == "FAIL"


def test_warehouse_name_not_found(laptop: Settings) -> None:
    checks = run(laptop, FakeClient(warehouses=[("other", "x")]))
    st = names(checks)
    assert st["sql warehouse"] == "FAIL" and "warehouse reachable" not in st
    assert st["serving endpoint"] == "OK"


def test_warehouse_unreachable(laptop: Settings) -> None:
    st = names(run(laptop, FakeClient().script_sql(select_ok=False)))
    assert st["warehouse reachable"] == "FAIL" and "schema writable" not in st


def test_schema_not_writable(laptop: Settings) -> None:
    checks = run(laptop, FakeClient().script_sql(create_ok=False))
    c = next(c for c in checks if c.name == "schema writable")
    assert c.status == "FAIL" and "CREATE TABLE" in c.fix and "cat.sch" in c.fix


def test_schema_placeholder_skips_reachability(laptop: Settings) -> None:
    s = laptop.model_copy(update={"databricks_catalog": "FILL-ME-catalog"})
    st = names(run(s, FakeClient()))
    assert st["warehouse reachable"] == "SKIP"


@pytest.mark.parametrize("state,expect", [("READY", "OK"), ("NOT_READY", "FAIL"), (None, "FAIL")])
def test_serving_endpoint_states(laptop: Settings, state: str | None, expect: str) -> None:
    st = names(run(laptop, FakeClient(endpoint=state).script_sql()))
    assert st["serving endpoint"] == expect


def test_serving_endpoint_unset_is_skip(laptop: Settings) -> None:
    s = laptop.model_copy(update={"llm_endpoint": None})
    assert names(run(s, FakeClient().script_sql()))["serving endpoint"] == "SKIP"


def test_volume_probe(laptop: Settings) -> None:
    s = laptop.model_copy(update={"recorder_spool_dir": Path("/Volumes/c/s/v/spool")})
    client = FakeClient().script_sql()
    st = names(run(s, client))
    assert st["volume writable"] == "OK" and client.files.store == {}
    client2 = FakeClient().script_sql()
    client2.files.deny.add("/Volumes/c/s/v")
    checks = run(s, client2)
    c = next(c for c in checks if c.name == "volume writable")
    assert c.status == "FAIL" and "WRITE VOLUME" in c.fix


def test_app_mode_uses_service_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in {
        "SUPERVISOR_MODE": "databricks_app",
        "DATABRICKS_HOST": "ws.example.invalid",
        "DATABRICKS_CLIENT_ID": "cid",
        "DATABRICKS_CLIENT_SECRET": "sp-secret-xyz",
        "DATABRICKS_WAREHOUSE_ID": "abc123",
        "DATABRICKS_CATALOG": "cat",
        "DATABRICKS_SCHEMA": "sch",
        "LLM_ENDPOINT": "judge-endpoint",
    }.items():
        monkeypatch.setenv(k, v)
    s = load_settings()

    def no_cli(argv: list[str]) -> RunResult:
        raise AssertionError("no CLI on the App")

    checks = run(s, FakeClient().script_sql(), cli=no_cli)
    st = names(checks)
    assert st["databricks auth"] == "OK" and "oauth token (CLI)" not in st
    assert all(v == "OK" for v in st.values()), st
    assert "sp-secret-xyz" not in "\n".join(format_check(c) for c in checks)


def test_app_mode_without_sp_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_MODE", "databricks_app")
    st = names(run(load_settings(), FakeClient()))
    assert st["databricks auth"] == "FAIL"


def test_truststore_requested_but_not_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSL_OS_TRUSTSTORE", "1")
    monkeypatch.setattr(preflight.bootstrap, "truststore_active", lambda: False)
    c = preflight._check_truststore()
    assert c.status == "FAIL"


def test_run_checks_exit_code(laptop: Settings, capsys: pytest.CaptureFixture) -> None:
    checks = run_checks(lambda: laptop, client_factory=lambda s: FakeClient(), cli=cli_expired)
    assert any(c.status == "FAIL" for c in checks)


def test_scrub_hides_tokens() -> None:
    raw = f'{{"access_token": "{TOKEN}"}} dapi{"0" * 32} client_secret=abc123def'
    out = scrub(raw)
    assert TOKEN not in out and "dapi0000" not in out and "abc123def" not in out
