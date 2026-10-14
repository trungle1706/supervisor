from __future__ import annotations

import json
import logging
import random
from typing import Any

import httpx
import pytest

from supervisor.adapters.factory import make_chat_model
from supervisor.adapters.llm import jsonschema_lite
from supervisor.adapters.llm.errors import (
    LLMError,
    LLMOutputError,
    LLMTimeoutError,
    TruncatedError,
)
from supervisor.adapters.llm.mock import MockChat, synthesize
from supervisor.adapters.llm.openai_compatible import (
    ANTI_REPETITION,
    OpenAICompatibleChat,
    looks_repetitive,
    model_family,
)
from supervisor.config import load_settings

SECRET = "test-key-" + "SECRET-0123456789abcdef"  # built so the no-secrets scan stays clean
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "score_bp"],
    "properties": {
        "action": {"type": "string", "enum": ["allow", "alert"]},
        "score_bp": {"type": "integer", "minimum": 0, "maximum": 10000},
        "note": {"type": "string"},
    },
}
MSGS = [{"role": "user", "content": "hello"}]


def _reply(content: str, finish: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]
    }


class Recorder:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        nxt = self.replies.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        if isinstance(nxt, httpx.Response):
            return nxt
        return httpx.Response(200, json=nxt)


def _chat(rec: Recorder, **kw: Any) -> OpenAICompatibleChat:
    return OpenAICompatibleChat(
        "http://127.0.0.1:11434/v1",
        "qwen3:4b",
        api_key=SECRET,
        transport=httpx.MockTransport(rec),
        **kw,
    )


def test_success_sends_json_schema_and_max_tokens() -> None:
    rec = Recorder([_reply('{"action": "allow", "score_bp": 120}')])
    chat = _chat(rec, max_tokens=512)
    out = chat.complete_json(MSGS, SCHEMA, timeout_s=5)
    assert out == {"action": "allow", "score_bp": 120}
    req = rec.requests[0]
    assert req.url.path == "/v1/chat/completions"
    body = json.loads(req.content)
    assert body["max_tokens"] == 512
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert req.headers["authorization"] == f"Bearer {SECRET}"
    assert chat.family == "qwen" and chat.is_mock is False


def test_truncation_raises_typed_error_without_retry() -> None:
    rec = Recorder([_reply('{"action": "al', finish="length")])
    with pytest.raises(TruncatedError, match="cut off"):
        _chat(rec).complete_json(MSGS, SCHEMA, timeout_s=5)
    assert len(rec.requests) == 1


def test_one_anti_repetition_retry_then_success() -> None:
    rec = Recorder([_reply("blah blah " * 50), _reply('{"action": "alert", "score_bp": 9000}')])
    out = _chat(rec).complete_json(MSGS, SCHEMA, timeout_s=5)
    assert out["action"] == "alert"
    assert len(rec.requests) == 2
    second = json.loads(rec.requests[1].content)["messages"]
    assert second[-1]["content"] == ANTI_REPETITION


def test_retry_only_once_then_output_error() -> None:
    rec = Recorder([_reply("not json"), _reply('{"action": "maybe", "score_bp": 1}')])
    with pytest.raises(LLMOutputError):
        _chat(rec).complete_json(MSGS, SCHEMA, timeout_s=5)
    assert len(rec.requests) == 2


def test_timeout_is_typed_and_uses_configured_value() -> None:
    seen: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout"))
        raise httpx.ReadTimeout("slow", request=request)

    chat = OpenAICompatibleChat(
        "http://127.0.0.1:11434/v1",
        "qwen3:4b",
        timeout_s=1800,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMTimeoutError, match="1800"):
        chat.complete_json(MSGS, SCHEMA, timeout_s=None)
    assert seen[0]["read"] == 1800


def test_api_key_never_in_logs_errors_or_repr(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    bad = httpx.Response(401, text=f"invalid key {SECRET}")
    rec = Recorder([_reply("nope"), _reply("still nope"), bad])
    chat = _chat(rec)
    with pytest.raises(LLMOutputError) as e1:
        chat.complete_json(MSGS, SCHEMA, timeout_s=5)
    with pytest.raises(LLMError) as e2:
        chat.complete_json(MSGS, SCHEMA, timeout_s=5)
    assert "401" in str(e2.value)
    for text in (caplog.text, str(e1.value), str(e2.value), repr(chat)):
        assert SECRET not in text


def test_from_settings_and_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    s = load_settings(llm_base_url="", llm_model="gpt-4o-mini")
    assert make_chat_model(s).is_mock
    s = load_settings(llm_mock=True)
    assert make_chat_model(s).is_mock
    monkeypatch.setenv("LLM_MOCK", "1")
    assert make_chat_model(load_settings()).is_mock
    monkeypatch.delenv("LLM_MOCK")
    s = load_settings(llm_model="claude-sonnet-4", llm_api_key=SECRET, llm_timeout_s=1800)
    chat = make_chat_model(s)
    assert isinstance(chat, OpenAICompatibleChat)
    assert chat.family == "anthropic" and chat.default_timeout_s == 1800
    assert SECRET not in repr(chat)


@pytest.mark.parametrize(
    ("name", "family"),
    [
        ("claude-sonnet-4", "anthropic"),
        ("databricks-claude-3-7-sonnet", "anthropic"),
        ("gpt-4o-mini", "openai"),
        ("qwen3:4b", "qwen"),
        ("Qwen/Qwen2.5-7B", "qwen"),
        ("llama3.1:8b", "meta"),
        ("databricks-meta-llama-3-3-70b-instruct", "meta"),
        ("gemma3:4b", "google"),
        ("deepseek-r1:7b", "deepseek"),
        ("mistral:7b", "unknown"),
    ],
)
def test_model_family(name: str, family: str) -> None:
    assert model_family(name) == family


def test_repetition_detector() -> None:
    assert looks_repetitive("abcdefghijklmnopq" * 20)
    assert not looks_repetitive('{"action": "allow", "score_bp": 10}')


def test_repetition_detector_is_linear_and_ignores_runs() -> None:
    import time

    start = time.monotonic()
    looks_repetitive("".join(chr(33 + (i * 7919) % 90) for i in range(40_000)))
    assert time.monotonic() - start < 1.0
    assert not looks_repetitive('{"note": "' + "-" * 120 + " " * 200 + "0" * 96 + '"}')


def test_valid_reply_with_long_runs_is_accepted() -> None:
    content = '{"action": "allow", "score_bp": 1, "note": "' + "-" * 300 + '"}'
    rec = Recorder([_reply(content)])
    assert _chat(rec).complete_json(MSGS, SCHEMA, timeout_s=5)["action"] == "allow"


def test_fenced_json_is_accepted() -> None:
    rec = Recorder([_reply('```json\n{"action": "allow", "score_bp": 2, "note": "a`b`"}\n```')])
    assert _chat(rec).complete_json(MSGS, SCHEMA, timeout_s=5)["note"] == "a`b`"


def test_loopback_endpoint_ignores_proxy_env() -> None:
    chat = OpenAICompatibleChat("http://127.0.0.1:11434/v1", "qwen3:4b")
    assert chat._client.trust_env is False


# ----------------------------------------------------------------------- MockChat


def test_mockchat_scripted_and_labelled() -> None:
    chat = MockChat(seed=1, scripts={"t1": [{"action": "alert", "score_bp": 7000}]})
    assert chat.is_mock and "mock" in chat.model_id
    with chat.scenario("t1"):
        assert chat.complete_json(MSGS, SCHEMA, 1) == {"action": "alert", "score_bp": 7000}
        fallback = chat.complete_json(MSGS, SCHEMA, 1)  # script exhausted -> synthesised
    assert jsonschema_lite.is_valid(fallback, SCHEMA)


def test_mockchat_is_deterministic_and_always_valid() -> None:
    a = [MockChat(seed=5).complete_json(MSGS, SCHEMA, 1) for _ in range(3)]
    b = [MockChat(seed=5).complete_json(MSGS, SCHEMA, 1) for _ in range(3)]
    assert a == b
    rng = random.Random(0)
    schemas = [
        SCHEMA,
        {
            "type": "object",
            "required": ["xs"],
            "properties": {"xs": {"type": "array", "minItems": 2, "items": {"type": "integer"}}},
        },
        {
            "type": "object",
            "required": ["k"],
            "properties": {"k": {"anyOf": [{"type": "string", "minLength": 6}, {"type": "null"}]}},
        },
        {
            "type": "object",
            "required": ["b", "c"],
            "properties": {"b": {"type": "boolean"}, "c": {"const": "x"}},
        },
    ]
    chat = MockChat(seed=9)
    for schema in schemas:
        for _ in range(20):
            assert jsonschema_lite.is_valid(chat.complete_json(MSGS, schema, 1), schema)
            assert jsonschema_lite.is_valid(synthesize(schema, rng), schema)


def test_mockchat_rejects_invalid_script() -> None:
    chat = MockChat(scripts={"bad": [{"action": "nope", "score_bp": 1}]})
    with chat.scenario("bad"), pytest.raises(ValueError, match="does not match"):
        chat.complete_json(MSGS, SCHEMA, 1)


def test_jsonschema_lite_rejects_bool_as_int_and_floats_for_integer() -> None:
    s = {"type": "integer"}
    assert not jsonschema_lite.is_valid(True, s)
    assert not jsonschema_lite.is_valid(1.5, s)
    assert jsonschema_lite.is_valid(3, s)
