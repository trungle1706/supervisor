from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from supervisor.config import get_settings, is_loopback_url, load_settings
from supervisor.core.errors import ConfigError, SupervisorError


@pytest.fixture
def client() -> TestClient:
    get_settings.cache_clear()
    from supervisor.app import app

    return TestClient(app, raise_server_exceptions=False)


def test_healthz_and_version(client: TestClient) -> None:
    assert client.get("/healthz").json()["status"] == "ok"
    v = client.get("/version").json()
    assert v["mode"] == "laptop" and v["sql_backend"] == "sqlite"


def test_errors_are_400_not_500(client: TestClient) -> None:
    from supervisor.app import app

    @app.get("/_boom_known")
    def boom_known() -> None:
        raise SupervisorError("table X missing; run bootstrap_schema")

    @app.get("/_boom_unknown")
    def boom_unknown() -> None:
        raise RuntimeError("x")

    r = client.get("/_boom_known")
    assert r.status_code == 400 and "bootstrap_schema" in r.json()["error"]
    assert client.get("/_boom_unknown").status_code == 400


def test_paths_resolve_absolute(tmp_path: Path) -> None:
    from supervisor.config import REPO_ROOT

    s = load_settings(data_dir=Path("rel/dir"))
    assert s.data_dir.is_absolute() and s.data_dir == REPO_ROOT / "rel" / "dir"
    assert s.sqlite_path == s.data_dir / "supervisor.db"


def test_token_hard_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_TOKEN", "secretvalue")
    with pytest.raises(ConfigError) as e:
        load_settings()
    assert "secretvalue" not in str(e.value)


def test_host_port_use_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST", "my-shell-hostname")
    monkeypatch.setenv("SUPERVISOR_PORT", "8123")
    s = load_settings()
    assert s.host == "127.0.0.1" and s.port == 8123


def test_env_file_from_repo_root_not_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / "elsewhere" / "custom.env"
    env.parent.mkdir()
    env.write_text("SUPERVISOR_MODE=dev\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SUPERVISOR_MODE=databricks_app\n", encoding="utf-8")
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", str(env))
    assert load_settings().supervisor_mode == "dev"


def test_token_in_env_file_fails(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DATABRICKS_TOKEN=abc\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings()


@pytest.mark.parametrize(
    "url,ok",
    [
        ("http://127.0.0.1:11434/v1", True),
        ("http://localhost:8080", True),
        ("http://[::1]:1/v1", True),
        ("https://api.example.com/v1", False),
        ("http://10.0.0.5/v1", False),
    ],
)
def test_loopback(url: str, ok: bool) -> None:
    assert is_loopback_url(url) is ok


def test_remote_llm_needs_opt_in() -> None:
    with pytest.raises(ConfigError):
        load_settings(llm_base_url="https://api.example.com/v1")
    s = load_settings(llm_base_url="https://api.example.com/v1", llm_allow_remote=True)
    assert s.llm_base_url.startswith("https://")


def test_mode_selects_backend() -> None:
    assert load_settings().effective_sql_backend == "sqlite"
    assert load_settings(supervisor_mode="databricks_app").effective_sql_backend == (
        "databricks_rest"
    )


def test_placeholders_mean_not_configured() -> None:
    s = load_settings(
        databricks_warehouse_id="FILL-ME-warehouse-id",
        databricks_catalog="FILL-ME-catalog",
        databricks_schema="FILL-ME-schema",
    )
    assert s.databricks_configured is False


def test_truststore_off_by_default() -> None:
    from supervisor import bootstrap

    assert bootstrap.truststore_requested() is False
