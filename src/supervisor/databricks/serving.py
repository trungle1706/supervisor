"""ChatModel for the workspace's own model-serving endpoint (Databricks App mode).

The endpoint is OpenAI-compatible at ``https://<host>/serving-endpoints`` with the
endpoint name as the model. Authentication is the App's own identity (service principal,
OAuth M2M). The SDK refreshes the OAuth token; this wrapper asks it for fresh headers
before each call and rebuilds the HTTP client only when the token changes. The token is
never logged, never shown in ``repr`` and never put in an error message.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from supervisor.adapters.llm.errors import LLMError
from supervisor.adapters.llm.openai_compatible import OpenAICompatibleChat, model_family

HeaderFactory = Callable[[], Mapping[str, str]]


def _bearer(headers: Mapping[str, str]) -> str:
    value = headers.get("Authorization") or headers.get("authorization") or ""
    if not value.startswith("Bearer "):
        raise LLMError(
            "the workspace identity gave no OAuth bearer token for the serving endpoint "
            "(check that the App has CAN_QUERY on the bound serving_endpoint resource)"
        )
    return value[len("Bearer ") :]


class DatabricksServingChat:
    """``ChatModel`` over the bound serving endpoint, with per-call fresh OAuth headers."""

    is_mock = False
    supports_deadline = True

    def __init__(
        self,
        base_url: str,
        endpoint: str,
        headers: HeaderFactory,
        *,
        timeout_s: float = 600.0,
        max_tokens: int = 8192,
        family: str | None = None,
        transport: Any = None,
        api_shape: str = "chat",
        strict_schema: bool = False,
        send_temperature: bool = True,
    ) -> None:
        self.api_shape = api_shape
        self.strict_schema = strict_schema
        self.send_temperature = send_temperature
        self.family_source = "derived"
        self.base_url = base_url.rstrip("/")
        self.model_id = endpoint
        self.family = family or model_family(endpoint)
        self._headers = headers
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._transport = transport
        self._token_fp: str | None = None
        self._chat: OpenAICompatibleChat | None = None

    def __repr__(self) -> str:
        return f"DatabricksServingChat(base_url={self.base_url!r}, endpoint={self.model_id!r})"

    def _current(self) -> OpenAICompatibleChat:
        try:
            headers = self._headers()
        except Exception as exc:  # noqa: BLE001 - SDK auth errors; never echo credentials
            raise LLMError(
                f"cannot get an OAuth token for serving endpoint {self.model_id} at "
                f"{self.base_url}: {type(exc).__name__}"
            ) from exc
        token = _bearer(headers)
        fp = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if self._chat is None or fp != self._token_fp:
            if self._chat is not None:
                self._chat.close()
            self._chat = OpenAICompatibleChat(
                self.base_url,
                self.model_id,
                api_key=token,
                timeout_s=self._timeout_s,
                max_tokens=self._max_tokens,
                family=self.family,
                family_source=self.family_source,
                transport=self._transport,
                api_shape=self.api_shape,
                strict_schema=self.strict_schema,
                send_temperature=self.send_temperature,
            )
            self._token_fp = fp
        return self._chat

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float | None = None,
        deadline: float | None = None,
    ) -> Mapping[str, Any]:
        return self._current().complete_json(messages, json_schema, timeout_s, deadline)

    def endpoint_family(self, timeout_s: float = 5.0) -> str | None:
        """No metadata probe over the workspace identity: the family comes from the model id."""
        return None

    def close(self) -> None:
        if self._chat is not None:
            self._chat.close()
            self._chat = None

    @classmethod
    def from_settings(
        cls, settings: Any, client: Any = None, transport: Any = None
    ) -> DatabricksServingChat:
        """Build from Settings. ``client`` is a WorkspaceClient (built when None)."""
        if client is None:
            from supervisor.adapters.sql.databricks_rest import make_workspace_client

            client = make_workspace_client(settings)
        return cls(
            settings.llm_base_url,
            settings.llm_model,
            client.config.authenticate,
            timeout_s=settings.llm_timeout_s,
            max_tokens=settings.llm_max_tokens,
            transport=transport,
            api_shape=getattr(settings, "llm_api_shape", "chat"),
            strict_schema=settings.llm_strict_schema,
            send_temperature=settings.llm_send_temperature,
        )
