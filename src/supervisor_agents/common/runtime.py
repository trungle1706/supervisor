"""Minimal tool-calling loop (no framework).

    runtime = AgentRuntime(manifest, tools, chat, gate=AllowAllHook(), tracer_provider=tp)
    result = runtime.run("customer asks ...")

Each step asks the ChatModel for one JSON action (``ACTION_SCHEMA``): either call a tool
or give the final answer. The tool router calls ``GateHook.check`` before **every** tool
call and records the decision on the tool span. A ``block`` decision skips the tool; a
``pause`` decision stops the run.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode

from supervisor.core.ports import ChatModel, GateHook
from supervisor_agents.common import tracing as T
from supervisor_agents.common.gate import AllowAllHook, safe_check
from supervisor_agents.common.manifest import AgentManifest

ToolFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]

ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "tool", "args", "message"],
    "properties": {
        "action": {"type": "string", "enum": ["tool", "final"]},
        "tool": {"type": "string"},
        "args": {"type": "object"},
        "message": {"type": "string"},
    },
}


class ToolError(Exception):
    """A tool refused the call (bad args, business limit). Shown to the model, not raised."""


@dataclass
class ToolRegistry:
    """Tool name -> python function. Functions take an args dict and return a dict."""

    tools: dict[str, ToolFn] = field(default_factory=dict)

    def register(self, name: str, fn: ToolFn) -> None:
        self.tools[name] = fn

    def get(self, name: str) -> ToolFn | None:
        return self.tools.get(name)

    def names(self) -> list[str]:
        return sorted(self.tools)


@dataclass
class ToolCallRecord:
    tool: str
    args: dict[str, Any]
    decision: dict[str, Any]
    status: str  # ok | error | blocked | paused | unknown_tool
    result: dict[str, Any] | None = None


@dataclass
class RunResult:
    agent_id: str
    trace_id: str
    status: str  # completed | blocked | paused | max_steps | llm_error
    final_message: str
    tool_calls: list[ToolCallRecord]
    steps: int

    @property
    def tool_sequence(self) -> list[str]:
        return [c.tool for c in self.tool_calls]


def _amount(args: Mapping[str, Any]) -> int | None:
    value = args.get("amount_minor")
    return value if type(value) is int else None


class AgentRuntime:
    def __init__(
        self,
        manifest: AgentManifest,
        tools: ToolRegistry,
        chat: ChatModel,
        *,
        gate: GateHook | None = None,
        tracer_provider: TracerProvider | None = None,
        system_prompt: str = "",
        max_steps: int = 8,
        env: str = "dev",
        timeout_s: float | None = None,
        capture_payloads: bool = False,
    ) -> None:
        self.manifest = manifest
        self.tools = tools
        self.chat = chat
        self.gate: GateHook = gate or AllowAllHook()
        self.tracer_provider = tracer_provider or T.make_tracer_provider(T.AgentEventExporter())
        self.tracer = self.tracer_provider.get_tracer("supervisor_agents", manifest.version)
        self.system_prompt = system_prompt or default_system_prompt(manifest)
        self.max_steps = max_steps
        self.env = env
        self.timeout_s = timeout_s
        # WP4: put args/result/message text on spans so the recorder can mask it (masked
        # capture level). Default off: spans then carry hashes only.
        self.capture_payloads = capture_payloads

    def _payload(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    # -- attributes ---------------------------------------------------------------
    def _base(self, event_type: str, caller: str | None) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            T.A_EVENT_TYPE: event_type,
            T.A_AGENT_ID: self.manifest.id,
            T.A_AGENT_VERSION: self.manifest.version,
            T.A_ENV: self.env,
            "gen_ai.agent.id": self.manifest.id,
            "gen_ai.agent.name": self.manifest.name,
        }
        if caller:
            attrs[T.A_CALLER] = caller
        return attrs

    # -- loop -----------------------------------------------------------------------
    def run(
        self,
        task: str,
        *,
        context: Mapping[str, Any] | None = None,
        caller_agent_id: str | None = None,
    ) -> RunResult:
        ctx = dict(context or {})
        with self.tracer.start_as_current_span(
            f"invoke_agent {self.manifest.id}",
            kind=SpanKind.INTERNAL,
            attributes={
                **self._base("message", caller_agent_id),
                "gen_ai.operation.name": "invoke_agent",
                "supervisor.message.role": "user",
                T.A_ARGS_HASH: T.args_hash({"task": task}),
            },
        ) as root:
            if self.capture_payloads:
                root.set_attribute(T.A_ARGS, task)
            trace_id = f"{root.get_span_context().trace_id:032x}"
            result = self._loop(task, ctx, caller_agent_id, trace_id)
            root.set_attribute(T.A_STATUS, result.status)
            return result

    def _loop(self, task: str, ctx: dict[str, Any], caller: str | None, trace_id: str) -> RunResult:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]
        calls: list[ToolCallRecord] = []
        for step in range(1, self.max_steps + 1):
            action = self._llm_call(messages, caller, step)
            if action is None:
                return RunResult(self.manifest.id, trace_id, "llm_error", "", calls, step)
            if action["action"] == "final":
                self._message(action.get("message", ""), caller)
                return RunResult(
                    self.manifest.id, trace_id, "completed", action.get("message", ""), calls, step
                )
            record = self._tool_call(
                action["tool"], dict(action.get("args") or {}), ctx, caller, trace_id
            )
            calls.append(record)
            messages.append(
                {"role": "assistant", "content": json.dumps(action, ensure_ascii=False)}
            )
            if record.status == "paused":
                msg = f"Agent paused by gate ({record.decision.get('rule_id')})."
                self._message(msg, caller, status="paused")
                return RunResult(self.manifest.id, trace_id, "paused", msg, calls, step)
            messages.append(
                {
                    "role": "user",
                    "content": "TOOL_RESULT "
                    + json.dumps(
                        {"tool": record.tool, "status": record.status, "result": record.result},
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            )
        return RunResult(self.manifest.id, trace_id, "max_steps", "", calls, self.max_steps)

    def _llm_call(
        self, messages: list[dict[str, str]], caller: str | None, step: int
    ) -> dict[str, Any] | None:
        attrs = {
            **self._base("llm_call", caller),
            "gen_ai.operation.name": "chat",
            "gen_ai.system": self.chat.family,
            "gen_ai.provider.name": self.chat.family,
            "gen_ai.request.model": self.chat.model_id,
            "gen_ai.output.type": "json",
            "supervisor.llm.is_mock": bool(self.chat.is_mock),
            "supervisor.step": step,
        }
        with self.tracer.start_as_current_span(
            f"chat {self.chat.model_id}", kind=SpanKind.CLIENT, attributes=attrs
        ) as span:
            try:
                out = dict(self.chat.complete_json(messages, ACTION_SCHEMA, self.timeout_s))  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001 - recorded on the span, run ends cleanly
                span.set_attribute(T.A_STATUS, _llm_error_status(exc))
                span.set_attribute("error.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                return None
            span.set_attribute("gen_ai.response.model", self.chat.model_id)
            span.set_attribute(T.A_STATUS, "ok")
            return out

    def _message(self, text: str, caller: str | None, status: str = "ok") -> None:
        with self.tracer.start_as_current_span(
            f"message {self.manifest.id}",
            attributes={
                **self._base("message", caller),
                "gen_ai.operation.name": "chat",
                "supervisor.message.role": "assistant",
                T.A_ARGS_HASH: T.args_hash({"message": text}),
                T.A_STATUS: status,
                **({T.A_ARGS: text} if self.capture_payloads else {}),
            },
        ):
            pass

    def _tool_call(
        self,
        tool: str,
        args: dict[str, Any],
        ctx: dict[str, Any],
        caller: str | None,
        trace_id: str,
    ) -> ToolCallRecord:
        spec = self.manifest.tool(tool)
        risk = spec.risk_class if spec else None
        attrs: dict[str, Any] = {
            **self._base("tool_call", caller),
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool,
            "gen_ai.tool.type": "function",
            T.A_TOOL: tool,
            T.A_ARGS_HASH: T.args_hash(args),
            T.A_RISK: risk or "unregistered",
        }
        amount = _amount(args)
        if amount is not None:
            attrs[T.A_AMOUNT] = amount
            attrs[T.A_CURRENCY] = str(args.get("currency") or "VND")
        with self.tracer.start_as_current_span(
            f"execute_tool {tool}", kind=SpanKind.INTERNAL, attributes=attrs
        ) as span:
            span.set_attribute("gen_ai.tool.call.id", f"{span.get_span_context().span_id:016x}")
            if self.capture_payloads:
                span.set_attribute(T.A_ARGS, self._payload(args))
            gate_ctx = {
                **ctx,
                "trace_id": trace_id,
                "risk_class": risk,
                "caller_agent_id": caller,
                "env": self.env,
            }
            start = time.monotonic()
            decision = safe_check(
                self.gate, self.manifest.id, self.manifest.version, tool, args, gate_ctx, risk
            )
            span.set_attribute(T.A_GATE_ALLOW, bool(decision["allow"]))
            span.set_attribute(T.A_GATE_ACTION, decision["action"])
            span.set_attribute(T.A_GATE_RULE, decision["rule_id"] or "")
            span.set_attribute(T.A_GATE_REASON, decision["reason"][:200])
            span.set_attribute(
                T.A_GATE_LATENCY, decision["latency_ms"] or int((time.monotonic() - start) * 1000)
            )
            if decision.get("correlation_id"):  # WP37: same id as the decision and the chain
                span.set_attribute(T.A_GATE_CORRELATION, str(decision["correlation_id"]))
                span.set_attribute(T.A_GATE_STATUS, str(decision.get("status") or ""))
            if decision.get("session_id"):  # WP27: the conversation this call belongs to
                span.set_attribute(T.A_SESSION_ID, str(decision["session_id"]))
            if not decision["allow"]:
                status = "paused" if decision["action"] == "pause" else "blocked"
                span.set_attribute(T.A_STATUS, status)
                return ToolCallRecord(
                    tool,
                    args,
                    decision,
                    status,
                    {"error": f"{status} by gate", "rule_id": decision["rule_id"]},
                )
            fn = self.tools.get(tool)
            if fn is None:
                span.set_attribute(T.A_STATUS, "unknown_tool")
                return ToolCallRecord(
                    tool, args, decision, "unknown_tool", {"error": "no such tool"}
                )
            try:
                result = dict(fn(args))
                status = "ok"
            except ToolError as exc:
                result, status = {"error": str(exc)}, "error"
            except (KeyError, TypeError, ValueError) as exc:
                result, status = {"error": f"bad arguments: {type(exc).__name__}"}, "error"
                span.set_attribute("error.type", type(exc).__name__)
            except Exception as exc:  # noqa: BLE001 - a broken tool must not crash the run
                result, status = {"error": f"tool failed: {type(exc).__name__}"}, "error"
                span.set_attribute("error.type", type(exc).__name__)
            span.set_attribute(T.A_STATUS, status)
            if self.capture_payloads:
                span.set_attribute(T.A_RESULT, self._payload(result))
            return ToolCallRecord(tool, args, decision, status, result)


def _llm_error_status(exc: Exception) -> str:
    """agent_event.status for a failed LLM call: truncated | timeout | error."""
    names = {c.__name__ for c in type(exc).__mro__}
    if "TruncatedError" in names:
        return "truncated"
    if "LLMTimeoutError" in names or "TimeoutError" in names:
        return "timeout"
    return "error"


def default_system_prompt(manifest: AgentManifest) -> str:
    lines = [
        f"You are the {manifest.name} of a Vietnamese bank. {manifest.description}",
        "Answer with ONE JSON object: "
        '{"action": "tool"|"final", "tool": <tool name or "">, "args": {...}, "message": <text>}.',
        "Money is an integer number of VND in amount_minor. Tools:",
    ]
    for t in manifest.tools:
        lines.append(
            f"- {t.name}({', '.join(f'{k}: {v}' for k, v in t.args.items())}): {t.description}"
        )
    return "\n".join(lines)
