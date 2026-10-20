"""D14 contract: the adapter against recorded Anthropic OpenAI-compatible responses.

The fixture ``tests/fixtures/llm/anthropic_compat.json`` holds the real 400 answers (strict
required, schema keywords refused, temperature refused) and a real 200 success. The fake
server below applies the same three rules, so the test fails if the request stops
satisfying them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from supervisor.adapters.factory import make_judge_chat_model
from supervisor.adapters.llm import jsonschema_lite
from supervisor.adapters.llm.errors import LLMError, LLMOutputError
from supervisor.adapters.llm.openai_compatible import OpenAICompatibleChat
from supervisor.config import load_settings
from supervisor.judge.prompts.schema import OUTPUT_SCHEMA, STRICT_OUTPUT_SCHEMA, validate_output

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "llm" / "anthropic_compat.json").read_text("utf-8")
)
MSGS = [{"role": "user", "content": "judge this"}]


def _walk_keys(node: Any) -> set[str]:
    """Schema keywords only (names under ``properties`` are data, not keywords)."""
    found: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            found.add(k)
            if k == "properties" and isinstance(v, dict):
                for sub in v.values():
                    found |= _walk_keys(sub)
            else:
                found |= _walk_keys(v)
    elif isinstance(node, list):
        for x in node:
            found |= _walk_keys(x)
    return found


class FakeAnthropic:
    """Applies the three recorded rules; answers with the recorded bodies."""

    def __init__(self, success_content: str | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.success_content = success_content

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        js = body["response_format"]["json_schema"]
        if not js.get("strict"):
            rec = FIXTURE["400_not_strict"]
        elif _walk_keys(js["schema"]) & jsonschema_lite.STRICT_UNSUPPORTED:
            rec = FIXTURE["400_schema_keywords"]
        elif "temperature" in body:
            rec = FIXTURE["400_temperature"]
        else:
            rec = FIXTURE["200_success"]
            if self.success_content is not None:
                rec = json.loads(json.dumps(rec))
                rec["body"]["choices"][0]["message"]["content"] = self.success_content
        return httpx.Response(rec["status"], json=rec["body"])


def _chat(server: FakeAnthropic, **kw: Any) -> OpenAICompatibleChat:
    return OpenAICompatibleChat(
        "https://api.anthropic.com/v1",
        "claude-haiku-5-5",
        api_key="test-key-not-real",
        transport=httpx.MockTransport(server),
        **kw,
    )


def test_recorded_fixture_is_what_we_think() -> None:
    assert FIXTURE["400_not_strict"]["status"] == 400
    assert "strict" in FIXTURE["400_not_strict"]["body"]["error"]["message"]
    assert "maximum" in FIXTURE["400_schema_keywords"]["body"]["error"]["message"]
    assert "temperature" in FIXTURE["400_temperature"]["body"]["error"]["message"]
    assert FIXTURE["200_success"]["status"] == 200


def test_shipped_defaults_hit_the_recorded_400() -> None:
    """The old behaviour (D14 defect), unchanged when the flags stay off."""
    server = FakeAnthropic()
    with pytest.raises(LLMError, match="HTTP 400.*strict"):
        _chat(server).complete_json(MSGS, OUTPUT_SCHEMA, timeout_s=5)
    assert server.requests[0]["temperature"] == 0
    assert server.requests[0]["response_format"]["json_schema"]["schema"] == OUTPUT_SCHEMA


def test_strict_without_dropping_temperature_hits_the_recorded_400() -> None:
    server = FakeAnthropic()
    with pytest.raises(LLMError, match="temperature"):
        _chat(server, strict_schema=True).complete_json(MSGS, OUTPUT_SCHEMA, timeout_s=5)


def test_strict_and_no_temperature_gets_the_recorded_success() -> None:
    server = FakeAnthropic()
    out = _chat(server, strict_schema=True, send_temperature=False).complete_json(
        MSGS, OUTPUT_SCHEMA, timeout_s=5
    )
    sent = server.requests[0]
    assert "temperature" not in sent
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["response_format"]["json_schema"]["schema"] == STRICT_OUTPUT_SCHEMA
    assert validate_output(out)["label"] == "benign"


def test_reply_is_still_validated_against_the_full_schema() -> None:
    """The endpoint cannot enforce maximum/pattern, so the adapter must."""
    bad = json.dumps(
        {
            "suspicion_bp": 20000,  # above the maximum that was stripped from the request
            "label": "benign",
            "evidence_spans": [],
            "rationale": "x",
            "policy_refs": ["not-a-ref"],  # violates the pattern that was stripped
        }
    )
    server = FakeAnthropic(success_content=bad)
    with pytest.raises(LLMOutputError, match="maximum|pattern"):
        _chat(server, strict_schema=True, send_temperature=False).complete_json(
            MSGS, OUTPUT_SCHEMA, timeout_s=5
        )
    assert len(server.requests) == 2  # one anti-repetition retry, as before


def test_strict_copy_drops_keywords_but_keeps_property_names() -> None:
    assert not (_walk_keys(STRICT_OUTPUT_SCHEMA) & jsonschema_lite.STRICT_UNSUPPORTED)
    assert _walk_keys(OUTPUT_SCHEMA) & {"minimum", "maximum", "pattern", "maxItems"}
    # the full schema is untouched (copy, not in-place)
    assert OUTPUT_SCHEMA["properties"]["suspicion_bp"]["maximum"] == 10000
    schema = {"type": "object", "properties": {"pattern": {"type": "string", "minLength": 1}}}
    assert jsonschema_lite.strict_compatible(schema) == {
        "type": "object",
        "properties": {"pattern": {"type": "string"}},
    }


def test_settings_flags_reach_the_judge_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_ALLOW_REMOTE", "1")
    monkeypatch.setenv("JUDGE_T1_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("JUDGE_T1_BASE_URL", "https://api.anthropic.com/v1")
    default = make_judge_chat_model(load_settings(_env_file=None), "t1")
    assert (default.strict_schema, default.send_temperature) == (False, True)  # type: ignore[attr-defined]
    monkeypatch.setenv("LLM_STRICT_SCHEMA", "1")
    monkeypatch.setenv("LLM_SEND_TEMPERATURE", "0")
    chat = make_judge_chat_model(load_settings(_env_file=None), "t1")
    assert (chat.strict_schema, chat.send_temperature) == (True, False)  # type: ignore[attr-defined]
    server = FakeAnthropic()
    chat._client = httpx.Client(transport=httpx.MockTransport(server))  # type: ignore[attr-defined]
    assert (
        validate_output(chat.complete_json(MSGS, OUTPUT_SCHEMA, timeout_s=5))["suspicion_bp"] == 0
    )


def test_defaults_request_is_unchanged_for_other_servers() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
        )

    chat = OpenAICompatibleChat(
        "http://127.0.0.1:8001/v1", "qwen3.8-27b-int4", transport=httpx.MockTransport(handler)
    )
    chat.complete_json(
        MSGS, {"type": "object", "properties": {"n": {"type": "integer", "minimum": 0}}}
    )
    body = captured[0]
    assert body["temperature"] == 0
    assert body["response_format"]["json_schema"]["strict"] is False
    assert body["response_format"]["json_schema"]["schema"]["properties"]["n"]["minimum"] == 0
