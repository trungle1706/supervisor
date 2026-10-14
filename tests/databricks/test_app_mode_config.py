"""Databricks App mode settings: injected service principal, bound serving endpoint."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from supervisor.adapters.factory import make_chat_model
from supervisor.config import load_settings
from supervisor.core.errors import ConfigError
from supervisor.databricks.serving import DatabricksServingChat

APP_ENV = {
    "SUPERVISOR_MODE": "databricks_app",
    "DATABRICKS_HOST": "ws.example.invalid",
    "DATABRICKS_CLIENT_ID": "client-1",
    "DATABRICKS_CLIENT_SECRET": "very-secret",
    "LLM_ENDPOINT": "databricks-meta-llama-3-3-70b-instruct",
}


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in APP_ENV.items():
        monkeypatch.setenv(k, v)


def test_sp_without_profile(app_env: None) -> None:
    s = load_settings()
    assert s.databricks_auth_kind == "service_principal"
    assert s.databricks_config_profile is None
    assert s.databricks_host == "https://ws.example.invalid"


def test_profile_wins_on_laptop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "p1")
    assert load_settings().databricks_auth_kind == "cli_profile"
    monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE")
    assert load_settings().databricks_auth_kind == "sdk_default"


def test_host_scheme_kept_and_trailing_slash_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_HOST", "https://ws.example.invalid/")
    assert load_settings().databricks_host == "https://ws.example.invalid"
    monkeypatch.setenv("DATABRICKS_HOST", "https://FILL-ME-workspace-host")
    assert load_settings().databricks_host == "https://FILL-ME-workspace-host"


def test_serving_endpoint_becomes_llm_settings(app_env: None) -> None:
    s = load_settings()
    assert s.llm_base_url == "https://ws.example.invalid/serving-endpoints"
    assert s.llm_model == APP_ENV["LLM_ENDPOINT"]
    assert s.llm_uses_workspace_auth and not s.llm_allow_remote


def test_remote_implied_only_for_workspace_endpoint(
    app_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.invalid/v1")
    with pytest.raises(ConfigError, match="LLM_BASE_URL must be a loopback"):
        load_settings()
    monkeypatch.setenv("LLM_BASE_URL", "https://ws.example.invalid/serving-endpoints")
    assert load_settings().llm_uses_workspace_auth


def test_workspace_url_not_implied_in_laptop_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_HOST", "ws.example.invalid")
    monkeypatch.setenv("LLM_ENDPOINT", "ep")
    monkeypatch.setenv("LLM_BASE_URL", "https://ws.example.invalid/serving-endpoints")
    with pytest.raises(ConfigError, match="loopback"):
        load_settings()


def test_explicit_empty_base_url_keeps_mock(app_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "")
    s = load_settings()
    assert s.llm_base_url == "" and not s.llm_uses_workspace_auth
    assert make_chat_model(s).is_mock


def test_endpoint_without_host_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_MODE", "databricks_app")
    monkeypatch.setenv("LLM_ENDPOINT", "ep")
    with pytest.raises(ConfigError, match="DATABRICKS_HOST"):
        load_settings()


def test_placeholder_endpoint_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_MODE", "databricks_app")
    monkeypatch.setenv("LLM_ENDPOINT", "FILL-ME-serving-endpoint-name")
    s = load_settings()
    assert s.llm_base_url == "http://127.0.0.1:11434/v1" and not s.llm_uses_workspace_auth


def test_spool_dir_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOOL_DIR", "/Volumes/c/s/v/spool")
    assert str(load_settings().recorder_spool_dir) == "/Volumes/c/s/v/spool"
    assert str(load_settings(recorder_spool_dir="/x/y").recorder_spool_dir) == "/x/y"


def test_workspace_client_gets_sp_explicitly(app_env: None) -> None:
    from supervisor.adapters.sql.databricks_rest import config_kwargs

    kw = config_kwargs(load_settings())
    assert kw == {
        "host": "https://ws.example.invalid",
        "client_id": "client-1",
        "client_secret": "very-secret",
        "auth_type": "oauth-m2m",
    }
    assert "profile" not in kw


class _Cfg:
    def __init__(self) -> None:
        self.n = 0

    def authenticate(self) -> dict[str, str]:
        self.n += 1
        return {"Authorization": f"Bearer tok{1 if self.n < 3 else 2}"}


class _Client:
    def __init__(self) -> None:
        self.config = _Cfg()


def test_serving_chat_uses_fresh_token(app_env: None) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers["Authorization"])
        assert str(req.url) == "https://ws.example.invalid/serving-endpoints/chat/completions"
        assert req.read() and b'"model":"databricks-meta-llama' in req.read().replace(b" ", b"")
        body: dict[str, Any] = {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}]
        }
        return httpx.Response(200, json=body)

    s = load_settings()
    client = _Client()
    chat = DatabricksServingChat.from_settings(
        s, client=client, transport=httpx.MockTransport(handler)
    )
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    for _ in range(3):
        assert chat.complete_json([{"role": "user", "content": "x"}], schema) == {"ok": True}
    assert seen == ["Bearer tok1", "Bearer tok1", "Bearer tok2"]
    assert "tok" not in repr(chat)
    assert chat.family == "meta"
    chat.close()


def test_serving_chat_error_hides_credentials(app_env: None) -> None:
    class Bad:
        class config:  # noqa: N801
            @staticmethod
            def authenticate() -> dict[str, str]:
                raise RuntimeError("secret-material-here")

    chat = DatabricksServingChat.from_settings(load_settings(), client=Bad())
    with pytest.raises(Exception) as e:
        chat.complete_json([{"role": "user", "content": "x"}], {"type": "object"})
    assert "secret-material-here" not in str(e.value)
