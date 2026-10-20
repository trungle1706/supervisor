"""Tool-call middleware for LangGraph and deepagents agents (WP38, docs/collectors.md).

``SupervisorToolMiddleware`` wraps the execution of every tool call:

1. before the tool runs it asks the gate (``direction=input``: tool name, arguments, session id,
   consumer id, a correlation id);
2. a block or a pause raises ``SupervisorBlocked`` / ``SupervisorPaused`` (typed, so the agent
   code can show the reason and the correlation id). With ``on_block="message"`` a block (not a
   pause) becomes an error tool message instead, so the model can read the reason;
3. the gate may answer with masked arguments (``transformed_payload``); the tool then runs with
   them;
4. after the tool ran, the output is checked (``direction=output``, ``context.output``) and may
   be replaced by its masked form or refused.

LangGraph and LangChain are NOT dependencies of Supervisor. This module imports neither: the
object it wraps only needs the attributes used below (``request.tool_call`` with ``name``,
``args`` and ``id``; ``request.override(tool_call=...)`` or a dataclass copy; a result with a
``content``). That is the public shape of a tool-call request in the agent middleware of LangChain
1.x, which deepagents uses too. ``as_agent_middleware()`` builds a real ``AgentMiddleware`` and
imports LangChain only when called. Tests use fakes.

    mw = SupervisorToolMiddleware(HttpGate(url, credential=cred), "my-agent", "1")
    agent = create_agent(model, tools, middleware=[mw.as_agent_middleware()])
    # a plain LangGraph ToolNode: ToolNode(tools, wrap_tool_call=mw.wrap_tool_call)
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from supervisor.core.ports import GateHook
from supervisor.gateway.adapters.common import (
    GateAnswer,
    GateClient,
    clean_id,
    new_correlation_id,
    text_of,
)
from supervisor.gateway.sdk import SupervisorBlocked, SupervisorPaused

Getter = str | Callable[[Any], str | None] | None


def _resolve(spec: Getter, request: Any) -> str | None:
    if spec is None:
        return None
    if callable(spec):
        try:
            return spec(request)
        except Exception:  # noqa: BLE001 - a getter that fails gives no id
            return None
    return spec


def _thread_id(request: Any) -> str | None:
    """Default session id: ``thread_id`` of the LangGraph run config, when the request has it."""
    cur: Any = getattr(request, "runtime", None)
    for name in ("config", "configurable"):
        cur = cur.get(name) if isinstance(cur, Mapping) else getattr(cur, name, None)
    if isinstance(cur, Mapping):
        return clean_id(cur.get("thread_id"))
    return None


def _with_args(request: Any, new_args: dict[str, Any]) -> Any:
    """A copy of the request whose tool call has ``new_args``."""
    tc = dict(request.tool_call)
    tc["args"] = new_args
    override = getattr(request, "override", None)
    if callable(override):
        return override(tool_call=tc)
    if dataclasses.is_dataclass(request) and not isinstance(request, type):
        return dataclasses.replace(request, tool_call=tc)
    clone = copy.copy(request)
    clone.tool_call = tc
    return clone


def _with_content(result: Any, content: str) -> Any:
    """A copy of a tool result (a message with ``content``) holding ``content``."""
    update = getattr(result, "model_copy", None)
    if callable(update):
        return update(update={"content": content})
    if isinstance(result, Mapping):
        return {**result, "content": content}
    clone = copy.copy(result)
    clone.content = content
    return clone


class SupervisorToolMiddleware:
    """See the module text. ``gate`` is any GateHook (``HttpGate`` in production)."""

    name = "SupervisorToolMiddleware"

    def __init__(
        self,
        gate: GateHook,
        agent_id: str,
        agent_version: str = "1",
        *,
        fail_mode: str = "closed",
        consumer_id: Getter = None,
        session_id: Getter = _thread_id,
        risk_classes: Mapping[str, str] | None = None,
        default_risk_class: str | None = None,
        check_output: bool = True,
        apply_transform: bool = True,
        on_block: str = "raise",
        max_payload_bytes: int = 256 * 1024,
    ) -> None:
        if on_block not in ("raise", "message"):
            raise ValueError("on_block must be 'raise' or 'message'")
        self.client = GateClient(
            gate,
            agent_id,
            agent_version,
            fail_mode=fail_mode,
            risk_classes=risk_classes,
            default_risk_class=default_risk_class,
            max_payload_bytes=max_payload_bytes,
        )
        self.consumer_id = consumer_id
        self.session_id = session_id
        self.check_output = check_output
        self.apply_transform = apply_transform
        self.on_block = on_block

    # ------------------------------------------------------------------ pieces

    def _input_check(self, request: Any, cid: str) -> tuple[Any, GateAnswer | None]:
        tc = request.tool_call
        args = tc.get("args")
        args = dict(args) if isinstance(args, Mapping) else {"value": args}
        ctx: dict[str, Any] = {}
        call_id = clean_id(tc.get("id"))
        if call_id:
            ctx["tool_call_id"] = call_id
        return args, self._ask(request, tc.get("name"), args, "input", ctx, cid)

    def _ask(
        self, request: Any, name: Any, args: dict[str, Any], direction: str, ctx: dict, cid: str
    ) -> GateAnswer:
        return self.client.check(
            name,
            args,
            direction=direction,
            context=ctx,
            correlation_id=cid,
            consumer_id=_resolve(self.consumer_id, request),
            session_id=_resolve(self.session_id, request),
        )

    def _after_input(self, request: Any, args: dict[str, Any], ans: GateAnswer) -> Any:
        if ans.allow and not self.apply_transform:
            return request  # the owner chose not to apply masked values
        self.client.enforce(ans)
        new_args = ans.transformed_args
        if self.apply_transform and ans.status == "transform" and new_args is not None:
            return _with_args(request, new_args)
        return request

    def _output_ctx(self, result: Any) -> str:
        content = (
            result.get("content")
            if isinstance(result, Mapping)
            else getattr(result, "content", None)
        )
        return text_of(content)

    def _after_output(self, result: Any, ans: GateAnswer) -> Any:
        if ans.allow and not self.apply_transform:
            return result
        self.client.enforce(ans)
        new = ans.transformed_output
        if self.apply_transform and ans.status == "transform" and isinstance(new, str):
            return _with_content(result, new)
        return result

    def _blocked_message(self, request: Any, exc: SupervisorBlocked) -> Any:
        """An error ToolMessage for a block (never for a pause). Imports LangChain lazily; if it
        is not installed the exception is raised as with ``on_block="raise"``."""
        if isinstance(exc, SupervisorPaused):
            raise exc
        try:
            from langchain_core.messages import ToolMessage  # type: ignore[import-not-found]
        except ImportError:
            raise exc from None
        tc = request.tool_call
        rule = exc.decision.get("rule_id")
        cid = exc.decision.get("correlation_id")
        return ToolMessage(
            content=f"Blocked by supervisor ({rule}), reference {cid}.",
            tool_call_id=tc.get("id"),
            name=tc.get("name"),
            status="error",
        )

    # ------------------------------------------------------------------ public API

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        cid = new_correlation_id()
        try:
            args, ans = self._input_check(request, cid)
            assert ans is not None
            request = self._after_input(request, args, ans)
        except SupervisorBlocked as exc:
            if self.on_block == "message":
                return self._blocked_message(request, exc)
            raise
        result = handler(request)
        if not self.check_output:
            return result
        text = self._output_ctx(result)
        if not text:
            return result
        out = self._ask(request, request.tool_call.get("name"), {}, "output", {"output": text}, cid)
        try:
            return self._after_output(result, out)
        except SupervisorBlocked as exc:
            if self.on_block == "message":
                return self._blocked_message(request, exc)
            raise

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        import asyncio

        cid = new_correlation_id()
        try:
            tc = request.tool_call
            args = tc.get("args")
            args = dict(args) if isinstance(args, Mapping) else {"value": args}
            ctx = {"tool_call_id": c} if (c := clean_id(tc.get("id"))) else {}
            ans = await asyncio.to_thread(
                self._ask, request, tc.get("name"), args, "input", ctx, cid
            )
            request = self._after_input(request, args, ans)
        except SupervisorBlocked as exc:
            if self.on_block == "message":
                return self._blocked_message(request, exc)
            raise
        result = await handler(request)
        if not self.check_output:
            return result
        text = self._output_ctx(result)
        if not text:
            return result
        name = request.tool_call.get("name")
        out = await asyncio.to_thread(self._ask, request, name, {}, "output", {"output": text}, cid)
        try:
            return self._after_output(result, out)
        except SupervisorBlocked as exc:
            if self.on_block == "message":
                return self._blocked_message(request, exc)
            raise

    def as_agent_middleware(self) -> Any:
        """A real LangChain ``AgentMiddleware`` that delegates to this object. Imports LangChain
        when called (it is not a dependency of Supervisor)."""
        from langchain.agents.middleware import AgentMiddleware  # type: ignore[import-not-found]

        outer = self

        class SupervisorMiddleware(AgentMiddleware):  # type: ignore[misc]
            def wrap_tool_call(self, request: Any, handler: Any) -> Any:
                return outer.wrap_tool_call(request, handler)

            async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
                return await outer.awrap_tool_call(request, handler)

        return SupervisorMiddleware()
