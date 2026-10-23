"""ChatModel over any OpenAI-compatible ``/v1/chat/completions`` endpoint (httpx only).

Guards for small CPU models (docs/BANK_DEPLOY_GUIDE.md section 2.4):

* ``response_format: {"type": "json_schema", ...}`` so the server enforces the grammar;
* ``max_tokens`` cap (settings ``LLM_MAX_TOKENS``, default 8192);
* ``finish_reason == "length"`` -> :class:`TruncatedError` (no blind retry);
* invalid JSON / schema mismatch / visible repetition -> exactly one retry with an
  anti-repetition instruction, then :class:`LLMOutputError`;
* strict endpoints (``LLM_STRICT_SCHEMA=1``, D14): ``strict: true`` and a copy of the schema
  without the keywords such endpoints refuse (minimum, maximum, pattern, maxItems, ...); the
  reply is still checked against the FULL schema here;
* ``LLM_SEND_TEMPERATURE=0`` leaves ``temperature`` out of the request (Anthropic's
  OpenAI-compatible endpoint refuses it);
* per-call timeout (settings ``LLM_TIMEOUT_S``) -> :class:`LLMTimeoutError`.

The API key is sent only in the ``Authorization`` header. It never appears in logs,
``repr`` or error messages.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

import httpx

from supervisor.adapters.llm import jsonschema_lite
from supervisor.adapters.llm.errors import (
    LLMError,
    LLMOutputError,
    LLMTimeoutError,
    TruncatedError,
)

log = logging.getLogger(__name__)


def _is_loopback(url: str) -> bool:
    host = (urlparse(url).hostname or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# Model-name prefix -> model family. First match wins; checked after vendor prefixes are cut.
FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("gpt", "openai"),
    ("qwen", "qwen"),
    ("llama", "meta"),
    ("gemma", "google"),
    ("gemini", "google"),
    ("deepseek", "deepseek"),
    # D05: with the derived family an unknown id cannot be judged, so name the Mistral models.
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("ministral", "mistral"),
    ("codestral", "mistral"),
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


def looks_repetitive(text: str, window: int = 32, times: int = 6, tail: int = 4000) -> bool:
    """True if some ``window``-char text (with >= 4 distinct chars, so runs of spaces,
    dashes or zeros do not count) occurs ``times`` or more in the last ``tail`` chars.
    Linear in ``tail``; used only to label a reply that already failed to parse."""
    text = text[-tail:]
    if len(text) < window * times:
        return False
    counts: Counter[str] = Counter()
    for i in range(len(text) - window + 1):
        chunk = text[i : i + window]
        if len(set(chunk)) < 4:
            continue
        counts[chunk] += 1
        if counts[chunk] >= times:
            return True
    return False


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class OpenAICompatibleChat:
    """``ChatModel`` adapter. One instance per configured endpoint."""

    is_mock = False
    supports_deadline = True  # WP-D3: complete_json(..., deadline=) bounds all attempts together

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout_s: float = 600.0,
        max_tokens: int = 8192,
        family: str | None = None,
        family_source: str | None = None,
        transport: httpx.BaseTransport | None = None,
        strict_schema: bool = False,
        send_temperature: bool = True,
        api_shape: str = "chat",
    ) -> None:
        if api_shape not in ("chat", "responses"):
            raise LLMError(f"unknown LLM_API_SHAPE {api_shape!r} (use chat or responses)")
        self.api_shape = api_shape
        if not base_url:
            raise LLMError("LLM_BASE_URL is empty; use MockChat")
        self.base_url = base_url.rstrip("/")
        self.model_id = model
        self.family = family or model_family(model)
        # D05: where the family came from (derived | declared-test-only); set by the factory.
        self.family_source = family_source or "derived"
        self.default_timeout_s = float(timeout_s)
        self.max_tokens = int(max_tokens)
        # OpenAI strict mode rejects open objects (tool args); Ollama enforces the grammar anyway.
        self.strict_schema = strict_schema
        self.send_temperature = send_temperature
        self.__api_key = api_key or None
        # Loopback endpoints must not go through a corporate HTTP(S)_PROXY.
        self._client = httpx.Client(transport=transport, trust_env=not _is_loopback(base_url))

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
            strict_schema=settings.llm_strict_schema,
            send_temperature=settings.llm_send_temperature,
            api_shape=getattr(settings, "llm_api_shape", "chat"),
        )

    def close(self) -> None:
        self._client.close()

    def endpoint_family(self, timeout_s: float = 5.0) -> str | None:
        """Family named by the endpoint's own ``GET /models`` metadata (D05), else None.

        Looks at ``root``, ``id`` and ``display_name`` of the entry for this model (vLLM puts
        the weights name in ``root``). Any failure gives None: the probe only adds evidence,
        it never blocks a working endpoint."""
        headers = {"Authorization": f"Bearer {self.__api_key}"} if self.__api_key else {}
        try:
            resp = self._client.get(f"{self.base_url}/models", headers=headers, timeout=timeout_s)
            entries = resp.json()["data"] if resp.status_code == 200 else []
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, Mapping) or entry.get("id") != self.model_id:
                continue
            for field in ("root", "id", "display_name"):
                fam = model_family(str(entry.get(field) or ""))
                if fam != "unknown":
                    return fam
        return None

    # -- ChatModel ---------------------------------------------------------------
    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float | None = None,
        deadline: float | None = None,
    ) -> Mapping[str, Any]:
        """``deadline`` (``time.monotonic()`` value, WP-D3) bounds all attempts together: an
        attempt gets at most the time left, and the anti-repetition retry is skipped when the time
        left is under the timeout of one attempt."""
        timeout = float(timeout_s) if timeout_s and timeout_s > 0 else self.default_timeout_s
        msgs = [dict(m) for m in messages]
        problem = ""
        for attempt in (1, 2):
            attempt_timeout = timeout
            if deadline is not None:
                left = deadline - time.monotonic()
                if left <= 0 or (attempt == 2 and left < timeout):
                    raise LLMTimeoutError(
                        f"model {self.model_id}: no time left for attempt {attempt}"
                    )
                attempt_timeout = min(timeout, left)
            try:
                content = self._post(msgs, json_schema, attempt_timeout)
            except TruncatedError as exc:
                if attempt == 1:
                    raise
                raise TruncatedError(f"{exc} (on the anti-repetition retry)") from exc
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
        # Strict endpoints refuse some keywords: send a stripped copy, validate with the full one.
        sent = jsonschema_lite.strict_compatible(schema) if self.strict_schema else dict(schema)
        if self.api_shape == "responses":
            body = self._responses_body(msgs, sent)
            path = "responses"
        else:
            body = self._chat_body(msgs, sent)
            path = "chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.__api_key:
            headers["Authorization"] = f"Bearer {self.__api_key}"
        url = f"{self.base_url}/{path}"
        return self._send(url, body, headers, timeout)

    def _chat_body(self, msgs: list[dict[str, str]], sent: Mapping[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model_id,
            "messages": msgs,
            "max_tokens": self.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "reply",
                    "schema": sent,
                    "strict": self.strict_schema,
                },
            },
        }
        if self.send_temperature:
            body["temperature"] = 0
        return body

    def _responses_body(
        self, msgs: list[dict[str, str]], sent: Mapping[str, Any]
    ) -> dict[str, Any]:
        """OpenAI responses API: system text -> ``instructions``; others -> typed input items."""
        system = "\n\n".join(m["content"] for m in msgs if m.get("role") == "system")
        items: list[dict[str, Any]] = []
        for m in msgs:
            role = m.get("role")
            if role == "system":
                continue
            kind = "output_text" if role == "assistant" else "input_text"
            items.append(
                {
                    "role": "assistant" if role == "assistant" else "user",
                    "content": [{"type": kind, "text": m.get("content", "")}],
                }
            )
        body: dict[str, Any] = {
            "model": self.model_id,
            "max_output_tokens": self.max_tokens,
            "input": items,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "reply",
                    "schema": dict(sent),
                    "strict": self.strict_schema,
                }
            },
        }
        if system:
            body["instructions"] = system
        if self.send_temperature:
            body["temperature"] = 0
        return body

    def _send(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> str:
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
        if self.api_shape == "responses":
            return self._read_responses(resp)
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

    def _read_responses(self, resp: httpx.Response) -> str:
        try:
            data = resp.json()
            if not isinstance(data, dict):
                raise TypeError("not an object")
            if data.get("status") == "incomplete":
                details = data.get("incomplete_details") or {}
                if details.get("reason") == "max_output_tokens":
                    raise TruncatedError(
                        f"reply from {self.model_id} was cut off at "
                        f"max_output_tokens={self.max_tokens} (raise LLM_MAX_TOKENS)"
                    )
            text = data.get("output_text")
            if not isinstance(text, str) or not text:
                parts: list[str] = []
                for item in data["output"]:
                    for part in item.get("content") or []:
                        if part.get("type") == "output_text":
                            parts.append(str(part.get("text") or ""))
                text = "".join(parts)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError(f"model endpoint {self.base_url} sent a malformed response") from exc
        return text

    @staticmethod
    def _parse(content: str, schema: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
        text = content.strip()
        fenced = _FENCE.match(text)
        if fenced:
            text = fenced.group(1)
        try:
            value = json.loads(text)
        except ValueError:
            return None, "repetition detected" if looks_repetitive(content) else "not valid JSON"
        if not isinstance(value, dict):
            return None, "JSON is not an object"
        errs = jsonschema_lite.errors(value, schema)
        if errs:
            return None, "; ".join(errs[:3])
        return value, ""
