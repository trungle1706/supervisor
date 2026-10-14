"""ChatModel over any OpenAI-compatible ``/v1/chat/completions`` endpoint (httpx only).

Guards for small CPU models (docs/BANK_DEPLOY_GUIDE.md section 2.4):

* ``response_format: {"type": "json_schema", ...}`` so the server enforces the grammar;
* ``max_tokens`` cap (settings ``LLM_MAX_TOKENS``, default 8192);
* ``finish_reason == "length"`` -> :class:`TruncatedError` (no blind retry);
* invalid JSON / schema mismatch / visible repetition -> exactly one retry with an
  anti-repetition instruction, then :class:`LLMOutputError`;
* per-call timeout (settings ``LLM_TIMEOUT_S``) -> :class:`LLMTimeoutError`.

The API key is sent only in the ``Authorization`` header. It never appears in logs,
``repr`` or error messages.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from supervisor.adapters.llm import jsonschema_lite
from supervisor.adapters.llm.errors import (
    LLMError,
    LLMOutputError,
    LLMTimeoutError,
    TruncatedError,
)

log = logging.getLogger(__name__)

# Model-name prefix -> model family. First match wins; checked after vendor prefixes are cut.
FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("gpt", "openai"),
    ("qwen", "qwen"),
    ("llama", "meta"),
    ("gemma", "google"),
    ("deepseek", "deepseek"),
)
_VENDOR_PREFIXES = ("databricks-", "meta-", "anthropic.", "openai/", "us.")

ANTI_REPETITION = (
    "Your previous reply was not valid JSON for the schema or it repeated itself. "
    "Answer again with ONE short JSON object that matches the schema. Do not repeat text."
)


def model_family(model: str) -> str:
    """Family from the model name: claude->anthropic, gpt->openai, ... else ``unknown``."""
    name = model.strip().lower().rsplit("/", 1)[-1]
    changed = True
    while changed:
        changed = False
        for p in _VENDOR_PREFIXES:
            if name.startswith(p):
                name, changed = name[len(p) :], True
    for prefix, family in FAMILY_PREFIXES:
        if name.startswith(prefix):
            return family
    return "unknown"


def looks_repetitive(text: str, chunk: int = 16, times: int = 6) -> bool:
    """True if some ``chunk``-char window repeats ``times`` or more times back to back."""
    if len(text) < chunk * times:
        return False
    pattern = re.compile(r"(.{" + str(chunk) + r",}?)\1{" + str(times - 1) + ",}", re.DOTALL)
    return pattern.search(text) is not None


class OpenAICompatibleChat:
    """``ChatModel`` adapter. One instance per configured endpoint."""

    is_mock = False

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout_s: float = 600.0,
        max_tokens: int = 8192,
        family: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise LLMError("LLM_BASE_URL is empty; use MockChat")
        self.base_url = base_url.rstrip("/")
        self.model_id = model
        self.family = family or model_family(model)
        self.default_timeout_s = float(timeout_s)
        self.max_tokens = int(max_tokens)
        self.__api_key = api_key or None
        self._client = httpx.Client(transport=transport)

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleChat(base_url={self.base_url!r}, model={self.model_id!r}, "
            f"family={self.family!r}, key={'set' if self.__api_key else 'none'})"
        )

    @classmethod
    def from_settings(
        cls, settings: Any, transport: httpx.BaseTransport | None = None
    ) -> OpenAICompatibleChat:
        key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
        return cls(
            settings.llm_base_url,
            settings.llm_model,
            api_key=key,
            timeout_s=settings.llm_timeout_s,
            max_tokens=settings.llm_max_tokens,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    # -- ChatModel ---------------------------------------------------------------
    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]:
        timeout = float(timeout_s) if timeout_s and timeout_s > 0 else self.default_timeout_s
        msgs = [dict(m) for m in messages]
        problem = ""
        for attempt in (1, 2):
            content = self._post(msgs, json_schema, timeout)
            parsed, problem = self._parse(content, json_schema)
            if parsed is not None:
                return parsed
            log.warning(
                "llm reply rejected (attempt %d, model=%s): %s", attempt, self.model_id, problem
            )
            msgs = [*msgs, {"role": "user", "content": ANTI_REPETITION}]
        raise LLMOutputError(f"model {self.model_id} gave no valid JSON after one retry: {problem}")

    # -- internals ---------------------------------------------------------------
    def _post(self, msgs: list[dict[str, str]], schema: Mapping[str, Any], timeout: float) -> str:
        body = {
            "model": self.model_id,
            "messages": msgs,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "reply", "schema": dict(schema), "strict": True},
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.__api_key:
            headers["Authorization"] = f"Bearer {self.__api_key}"
        url = f"{self.base_url}/chat/completions"
        start = time.monotonic()
        try:
            resp = self._client.post(url, json=body, headers=headers, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"model {self.model_id} at {self.base_url} did not answer within {timeout:.0f} s "
                "(raise LLM_TIMEOUT_S for slow CPU models)"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"cannot reach model endpoint {self.base_url}: {type(exc).__name__}"
            ) from exc
        log.debug(
            "llm call model=%s status=%s ms=%d",
            self.model_id,
            resp.status_code,
            int((time.monotonic() - start) * 1000),
        )
        if resp.status_code >= 400:
            text = resp.text[:300]
            if self.__api_key:
                text = text.replace(self.__api_key, "***")
            raise LLMError(
                f"model endpoint {self.base_url} returned HTTP {resp.status_code}: {text}"
            )
        try:
            data = resp.json()
            choice = data["choices"][0]
            finish = choice.get("finish_reason")
            content = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError(f"model endpoint {self.base_url} sent a malformed response") from exc
        if finish == "length":
            raise TruncatedError(
                f"reply from {self.model_id} was cut off at max_tokens={self.max_tokens} "
                "(raise num_ctx in the Modelfile or LLM_MAX_TOKENS)"
            )
        return content

    @staticmethod
    def _parse(content: str, schema: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if looks_repetitive(content):
            return None, "repetition detected"
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[4:] if text.startswith("json") else text
        try:
            value = json.loads(text)
        except ValueError:
            return None, "not valid JSON"
        if not isinstance(value, dict):
            return None, "JSON is not an object"
        errs = jsonschema_lite.errors(value, schema)
        if errs:
            return None, "; ".join(errs[:3])
        return value, ""
