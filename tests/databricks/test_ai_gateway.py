"""WP-P3: responses-shape LLM client and the AI Gateway URL in databricks_app mode."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from supervisor.adapters.llm.errors import LLMError, TruncatedError
from supervisor.adapters.llm.openai_compatible import OpenAICompatibleChat
from supervisor.config import load_settings
from supervisor.core.errors import ConfigError

GW = "https://ws.example.invalid/ai-gateway/mlflow/v1"
MODEL = "FILL-ME-cat.FILL-ME-schema.FILL-ME-model"
SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
MSGS = [
    {"role": "system", "content": "SYS"},
    {"role": "user", "content": "Q1"},
    {"role": "assistant", "content": "A1"},
    {"role": "user", "content": "Q2"},
]


def _chat(handler: Any, **kw: Any) -> OpenAICompatibleChat:
    return OpenAICompatibleChat(
        GW,
        MODEL,
        api_key="sekret-key",
        api_shape="responses",
        transport=httpx.MockTransport(handler),
        **kw,
    )


def test_request_body_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"output_text": '{"a": 1}', "status": "completed"})

    assert _chat(handler, max_tokens=99).complete_json(MSGS, SCHEMA) == {"a": 1}
    b = seen["body"]
    assert seen["url"] == f"{GW}/responses" and seen["auth"] == "Bearer sekret-key"
    assert b["model"] == MODEL and b["max_output_tokens"] == 99 and b["temperature"] == 0
    assert b["instructions"] == "SYS" and "messages" not in b and "max_tokens" not in b
    assert b["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "Q1"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "A1"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "Q2"}]},
    ]
    fmt = b["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["name"] == "reply" and fmt["strict"] is False
    assert fmt["schema"] == SCHEMA


def test_temperature_off() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"output_text": '{"a": 1}'})

    _chat(handler, send_temperature=False).complete_json(MSGS, SCHEMA)
    assert "temperature" not in seen


def test_parse_output_array() -> None:
    out = [
        {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "think"}]},
        {
            "type": "message",
            "content": [
                {"type": "output_text", "text": '{"a":'},
                {"type": "output_text", "text": " 2}"},
            ],
        },
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": out})

    assert _chat(handler).complete_json(MSGS, SCHEMA) == {"a": 2}


def test_truncation() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output_text": '{"a',
            },
        )

    with pytest.raises(TruncatedError):
        _chat(handler).complete_json(MSGS, SCHEMA)


def test_http_error_masks_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad token sekret-key")

    with pytest.raises(LLMError) as ei:
        _chat(handler).complete_json(MSGS, SCHEMA)
    assert "sekret-key" not in str(ei.value) and "401" in str(ei.value)


def test_malformed_response() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": 1})

    with pytest.raises(LLMError, match="malformed"):
        _chat(handler).complete_json(MSGS, SCHEMA)


def test_default_shape_is_chat() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"a": 1}'}}]}
        )

    chat = OpenAICompatibleChat(GW, MODEL, transport=httpx.MockTransport(handler))
    assert chat.api_shape == "chat"
    chat.complete_json(MSGS, SCHEMA)
    assert seen["url"].endswith("/chat/completions")
    with pytest.raises(LLMError):
        OpenAICompatibleChat(GW, MODEL, api_shape="soap")


APP = {
    "SUPERVISOR_MODE": "databricks_app",
    "DATABRICKS_HOST": "ws.example.invalid",
    "DATABRICKS_CLIENT_ID": "c",
    "DATABRICKS_CLIENT_SECRET": "s",
}


def test_gateway_url_accepted_in_app_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in APP.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LLM_BASE_URL", GW + "/")
    monkeypatch.setenv("LLM_MODEL", MODEL)
    monkeypatch.setenv("LLM_API_SHAPE", "responses")
    s = load_settings()  # no LLM_ENDPOINT binding needed
    assert s.llm_uses_workspace_auth and s.llm_api_shape == "responses" and s.llm_model == MODEL
    assert not s.is_workspace_serving_url(GW + "/other")


def test_gateway_url_rejected_in_laptop_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_HOST", "ws.example.invalid")
    monkeypatch.setenv("LLM_BASE_URL", GW)
    with pytest.raises(ConfigError, match="loopback"):
        load_settings()


def test_default_api_shape() -> None:
    assert load_settings().llm_api_shape == "chat"


def test_judge_factory_uses_workspace_auth_on_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.adapters import factory

    for k, v in APP.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LLM_BASE_URL", GW)
    monkeypatch.setenv("LLM_MODEL", MODEL)
    monkeypatch.setenv("LLM_API_SHAPE", "responses")
    monkeypatch.setenv("JUDGE_T1_MODEL", "glm-5-judge")
    monkeypatch.setenv("JUDGE_T1_FAMILY", "")
    s = load_settings()
    fake = SimpleNamespace(
        config=SimpleNamespace(authenticate=lambda: {"Authorization": "Bearer t"})
    )
    monkeypatch.setattr(
        "supervisor.adapters.sql.databricks_rest.make_workspace_client", lambda _s: fake
    )
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url) + "|" + req.headers["authorization"])
        return httpx.Response(200, json={"output_text": '{"a": 1}'})

    chat = factory.make_judge_chat_model(s, "t1")
    chat._transport = httpx.MockTransport(handler)  # type: ignore[attr-defined]
    assert chat.complete_json(MSGS, SCHEMA) == {"a": 1}
    assert seen == [f"{GW}/responses|Bearer t"]
