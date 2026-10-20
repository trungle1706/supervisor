"""Guardrail for a LiteLLM proxy that asks the Supervisor gate (WP38, docs/collectors.md).

Written from the public hook interface of LiteLLM custom guardrails (``CustomGuardrail`` with
``async_pre_call_hook`` and ``async_post_call_success_hook``). LiteLLM is NOT a dependency of
Supervisor: nothing here imports it. ``SupervisorGuardrail`` has the two hook methods and can be
called by any host; ``build_litellm_guardrail()`` makes a real subclass of LiteLLM's
``CustomGuardrail`` and imports LiteLLM only when it is called.

* pre-call: the messages of the request go to the gate as ``args["messages"]`` of the tool
  ``llm_request`` (register it in the policy ``tools`` section). A block raises
  ``SupervisorBlocked`` (``SupervisorPaused`` for a pause); masked messages from the gate replace
  the request messages.
* post-call: the text of the model answer goes to the gate with ``direction=output``; a block
  raises, a masked answer replaces the text.

The consumer id is the LiteLLM user id of the key (or its team id, or the end user); the session
id is ``litellm_call_id`` of the request. Streaming answers are not checked (the hook sees them
chunk by chunk); keep ``fail_mode="closed"`` and use a non-streaming route for money flows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.core.ports import GateHook
from supervisor.gateway.adapters.common import (
    GateAnswer,
    GateClient,
    clean_id,
    new_correlation_id,
    text_of,
)
from supervisor.gateway.sdk import SupervisorBlocked

_CONSUMER_ATTRS = ("user_id", "end_user_id", "team_id")


def _unapplied(ans: GateAnswer) -> dict[str, Any]:
    out = ans.decision()
    out.update(
        allow=False,
        action="block",
        rule_id="SDK-TRANSFORM-UNAPPLIED",
        reason="masked values without messages: fail closed",
    )
    return out


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)


class SupervisorGuardrail:
    """Duck-typed LiteLLM custom guardrail. See the module text."""

    def __init__(
        self,
        gate: GateHook,
        agent_id: str,
        agent_version: str = "1",
        *,
        tool_name: str = "llm_request",
        fail_mode: str = "closed",
        check_output: bool = True,
        consumer_from: tuple[str, ...] = _CONSUMER_ATTRS,
        risk_class: str | None = "read_only",
        max_payload_bytes: int = 256 * 1024,
    ) -> None:
        self.client = GateClient(
            gate,
            agent_id,
            agent_version,
            fail_mode=fail_mode,
            default_risk_class=risk_class,
            max_payload_bytes=max_payload_bytes,
        )
        self.tool_name = tool_name
        self.check_output = check_output
        self.consumer_from = consumer_from

    # ------------------------------------------------------------------ helpers

    def _consumer(self, key: Any) -> str | None:
        for attr in self.consumer_from:
            value = clean_id(_get(key, attr))
            if value:
                return value
        return None

    @staticmethod
    def _session(data: Mapping[str, Any]) -> str | None:
        return clean_id(data.get("litellm_call_id"))

    # ------------------------------------------------------------------ hooks

    async def async_pre_call_hook(
        self, user_api_key_dict: Any, cache: Any, data: dict[str, Any], call_type: str
    ) -> dict[str, Any]:
        messages = data.get("messages")
        if not isinstance(messages, list):
            return data  # an embedding or an image call: no text to check
        cid = new_correlation_id()
        data.setdefault("metadata", {})
        ans = await self.client.acheck(
            self.tool_name,
            {"messages": messages},
            context={"call_type": str(call_type)[:64]},
            correlation_id=cid,
            consumer_id=self._consumer(user_api_key_dict),
            session_id=self._session(data),
        )
        self.client.enforce(ans)
        new = ans.transformed_args
        if new is not None:
            if not isinstance(new.get("messages"), list):  # cannot apply it: fail closed
                raise SupervisorBlocked(_unapplied(ans))
            data["messages"] = new["messages"]
        if isinstance(data.get("metadata"), dict):
            data["metadata"]["supervisor_correlation_id"] = ans.correlation_id
        return data

    async def async_post_call_success_hook(
        self, data: dict[str, Any], user_api_key_dict: Any, response: Any
    ) -> Any:
        if not self.check_output:
            return response
        choices = _get(response, "choices")
        if not isinstance(choices, list) or not choices:
            return response
        msg = _get(choices[0], "message")
        content = _get(msg, "content")
        text = text_of(content)
        if not text:
            return response
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        ans = await self.client.acheck(
            self.tool_name,
            {},
            direction="output",
            context={"output": text},
            correlation_id=clean_id(meta.get("supervisor_correlation_id")),
            consumer_id=self._consumer(user_api_key_dict),
            session_id=self._session(data),
        )
        self.client.enforce(ans)
        new = ans.transformed_output
        if isinstance(new, str):
            if isinstance(msg, dict):
                msg["content"] = new
            else:
                msg.content = new
        return response


def build_litellm_guardrail(*args: Any, **kwargs: Any) -> Any:
    """A real LiteLLM ``CustomGuardrail`` that delegates to ``SupervisorGuardrail``. Imports
    LiteLLM when called. ``guardrail_name`` and ``event_hook`` go to LiteLLM, the rest to ours."""
    from litellm.integrations.custom_guardrail import CustomGuardrail  # type: ignore[import-not-found]

    name = kwargs.pop("guardrail_name", "supervisor")
    inner = SupervisorGuardrail(*args, **kwargs)

    class _Guardrail(CustomGuardrail):  # type: ignore[misc]
        async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):  # type: ignore[no-untyped-def]
            return await inner.async_pre_call_hook(user_api_key_dict, cache, data, call_type)

        async def async_post_call_success_hook(self, data, user_api_key_dict, response):  # type: ignore[no-untyped-def]
            return await inner.async_post_call_success_hook(data, user_api_key_dict, response)

    return _Guardrail(guardrail_name=name, event_hook=["pre_call", "post_call"])
