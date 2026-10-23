"""WP-P4: judges call the AI Gateway with the signed-in user's forwarded token (sandbox-only)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from supervisor.adapters.auth.base import UserToken
from supervisor.adapters.auth.user_token import (
    UserTokenMiddleware,
    current_forwarded_token,
    forwarded_token,
)
from supervisor.adapters.llm.errors import LLMError
from supervisor.config import load_settings
from supervisor.core.errors import ConfigError

GW = "https://ws.example.invalid/ai-gateway/mlflow/v1"
MODEL = "FILL-ME-cat.FILL-ME-schema.FILL-ME-model"
SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
MSGS = [{"role": "user", "content": "Q"}]
APP = {
    "SUPERVISOR_MODE": "databricks_app",
    "DATABRICKS_HOST": "ws.example.invalid",
    "DATABRICKS_CLIENT_ID": "c",
    "DATABRICKS_CLIENT_SECRET": "s",
}
USER_TOKEN = "user-tok-123"  # noqa: S105
SP_TOKEN = "sp-tok-456"  # noqa: S105


def _env(monkeypatch: pytest.MonkeyPatch, *, app: bool = True, url: str = GW) -> None:
    if app:
        for k, v in APP.items():
            monkeypatch.setenv(k, v)
    else:
        monkeypatch.setenv("DATABRICKS_HOST", "ws.example.invalid")
    monkeypatch.setenv("LLM_BASE_URL", url)
    monkeypatch.setenv("LLM_MODEL", MODEL)
    monkeypatch.setenv("LLM_API_SHAPE", "responses")
    monkeypatch.setenv("LLM_USER_TOKEN_FORWARD", "1")


def test_default_off() -> None:
    assert load_settings().llm_user_token_forward is False


def test_config_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, app=False)
    with pytest.raises(ConfigError):
        load_settings()  # laptop mode
    _env(monkeypatch, url="http://127.0.0.1:11434/v1")
    with pytest.raises(ConfigError, match="LLM_USER_TOKEN_FORWARD"):
        load_settings()  # app mode, loopback URL
    _env(monkeypatch)
    assert load_settings().llm_user_token_forward is True  # app mode, gateway URL
    _env(monkeypatch, url="https://ws.example.invalid/serving-endpoints")
    assert load_settings().llm_user_token_forward is True


def _judge_chat(monkeypatch: pytest.MonkeyPatch, handler: Any, forward: bool = True) -> Any:
    from supervisor.adapters import factory

    _env(monkeypatch)
    monkeypatch.setenv("LLM_USER_TOKEN_FORWARD", "1" if forward else "0")
    monkeypatch.setenv("JUDGE_T1_MODEL", "glm-5-judge")
    monkeypatch.setenv("JUDGE_T1_FAMILY", "")
    s = load_settings()
    fake = SimpleNamespace(
        config=SimpleNamespace(authenticate=lambda: {"Authorization": f"Bearer {SP_TOKEN}"})
    )
    monkeypatch.setattr(
        "supervisor.adapters.sql.databricks_rest.make_workspace_client", lambda _s: fake
    )
    chat = factory.make_judge_chat_model(s, "t1")
    chat._transport = httpx.MockTransport(handler)
    return chat


def _ok(seen: list[str]) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers["authorization"])
        return httpx.Response(200, json={"output_text": '{"a": 1}'})

    return handler


def test_judge_uses_forwarded_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    chat = _judge_chat(monkeypatch, _ok(seen))
    assert chat.auth_label() is None
    with forwarded_token(UserToken(USER_TOKEN)):
        assert chat.auth_label() == "user_forwarded"
        assert chat.complete_json(MSGS, SCHEMA) == {"a": 1}
    assert seen == [f"Bearer {USER_TOKEN}"]


def test_fallback_to_sp_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    chat = _judge_chat(monkeypatch, _ok(seen))
    assert chat.complete_json(MSGS, SCHEMA) == {"a": 1}
    assert seen == [f"Bearer {SP_TOKEN}"]


def test_flag_off_ignores_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    chat = _judge_chat(monkeypatch, _ok(seen), forward=False)
    with forwarded_token(UserToken(USER_TOKEN)):
        assert chat.auth_label() is None
        chat.complete_json(MSGS, SCHEMA)
    assert seen == [f"Bearer {SP_TOKEN}"]


def test_403_raises_llm_error_without_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=f"denied for {USER_TOKEN}")

    chat = _judge_chat(monkeypatch, handler)
    with caplog.at_level(logging.DEBUG), forwarded_token(UserToken(USER_TOKEN)):
        with pytest.raises(LLMError) as ei:
            chat.complete_json(MSGS, SCHEMA)
    assert USER_TOKEN not in str(ei.value) and "403" in str(ei.value)
    assert USER_TOKEN not in caplog.text
    assert USER_TOKEN not in repr(UserToken(USER_TOKEN))


def test_contextvar_set_per_request_and_cleared() -> None:
    app = FastAPI()
    app.add_middleware(UserTokenMiddleware)
    seen: list[str | None] = []

    @app.get("/x")
    def x() -> dict[str, bool]:  # sync endpoint: runs in a worker thread
        t = current_forwarded_token()
        seen.append(t.reveal() if t else None)
        return {"ok": True}

    c = TestClient(app)
    c.get("/x", headers={"X-Forwarded-Access-Token": "tok-a"})
    c.get("/x")
    c.get("/x", headers={"X-Forwarded-Access-Token": "tok-b"})
    assert seen == ["tok-a", None, "tok-b"]
    assert current_forwarded_token() is None


def test_middleware_installed_only_when_flag_on() -> None:
    from supervisor.ops import middleware

    for flag, expect in ((False, 0), (True, 1)):
        app = FastAPI()
        s = SimpleNamespace(
            rate_limit_enabled=False,
            max_request_bytes=0,
            security_headers_enabled=False,
            hsts_enabled=False,
            request_id_header="X-Request-ID",
            llm_user_token_forward=flag,
        )
        middleware.install(app, s)
        assert sum(m.cls is UserTokenMiddleware for m in app.user_middleware) == expect
