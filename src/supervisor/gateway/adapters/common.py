"""Shared core of the collector adapters (WP38, ADR D28, docs/collectors.md).

An adapter sits in an agent framework (LangGraph, a FastAPI app, a LiteLLM proxy, a Claude Code
hook). Each one does the same things around the gate call, and they are done once here:

* clean the values the framework gives us before they go on the wire (tool name, consumer id,
  session id, correlation id), so a strange value can never become a header injection, a 400 or
  a way to select another policy;
* cap the size of what is sent;
* call the gate with ``direction`` and the correlation id when the gate supports them;
* apply the fail mode. ``closed`` (default): when the gate cannot answer, the call stops.
  ``open`` is allowed only for tools that are not money, credit or pii_export; those are always
  closed (the same rule as the gate: CLAUDE.md, ADR D03);
* turn a block or a pause into a typed exception (``SupervisorBlocked`` / ``SupervisorPaused``
  from ``supervisor.gateway.sdk``) and give back the masked values when the gate transformed them.

No framework is imported here and no network call is made: the gate is any object with the
``GateHook`` ``check`` method (the SDK's ``HttpGate`` or ``InProcessGate``, or a fake in a test).
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from supervisor.core.ports import GateHook
from supervisor.gateway.sdk import CORRELATION_HEADER, SupervisorBlocked, SupervisorPaused

ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}\Z")
MAX_PAYLOAD_BYTES = 256 * 1024
FAIL_MODES = ("closed", "open")
# Risk classes that are always closed, whatever fail_mode says (same list as the gate).
CLOSED_RISK = frozenset({"money", "credit", "pii_export"})
# Rule ids the SDK gives when the gate could not answer.
UNAVAILABLE_RULES = frozenset({"GATE-UNREACHABLE", "GATE-ERROR", "GATE-MISSING"})
# What an allowed answer may say (WP38 review). Anything else on an ``allow: true`` answer is a
# contradiction or a value this client does not know: it fails closed, like
# ``supervisor_agents.common.gate``.
ALLOWED_ACTIONS = frozenset({"allow", "log", "alert"})
KNOWN_STATUSES = frozenset({"allow", "report", "transform", "skip", "block", "pause"})

__all__ = [
    "CORRELATION_HEADER",
    "UNAVAILABLE_RULES",
    "GateAnswer",
    "GateClient",
    "clean_id",
    "new_correlation_id",
    "safe_tool_name",
    "text_of",
]


def clean_id(value: Any) -> str | None:
    """``value`` when it is a valid id (1..128 of ``A-Za-z0-9_.:@-``), else None. Never raises.
    A newline, a space or any non-ASCII character makes it invalid, so a value that passes is
    safe in a header."""
    return value if isinstance(value, str) and ID_RE.match(value) else None


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def safe_tool_name(name: Any) -> str:
    """A tool name the gate route accepts. A name with other characters (spaces, accents, a
    slash) is mapped to ``A-Za-z0-9_.:@-`` and gets an 8 character hash of the original, so two
    different names do not meet. Register the mapped name in the policy ``tools`` section."""
    raw = name if isinstance(name, str) else str(name)
    if ID_RE.match(raw):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:8]
    base = re.sub(r"[^A-Za-z0-9_.:@-]", "_", raw)[:100].strip("_") or "tool"
    return f"{base}-{digest}"


def text_of(content: Any, limit: int = MAX_PAYLOAD_BYTES) -> str:
    """Plain text of a message content: a string, or a list of blocks with ``text`` entries."""
    if isinstance(content, str):
        return content[:limit]
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)[:limit]
    return ""


@dataclass(frozen=True)
class GateAnswer:
    """The gate's answer plus the ids that were sent. ``raw`` is the answer as received."""

    raw: Mapping[str, Any]
    correlation_id: str
    tool_name: str
    direction: str

    @property
    def allow(self) -> bool:
        return self.raw.get("allow") is True

    @property
    def action(self) -> str:
        return str(self.raw.get("action") or "")

    @property
    def status(self) -> str:
        """The v2 status; for an old gate (no ``status``) it is derived from allow and action."""
        s = self.raw.get("status")
        if isinstance(s, str) and s:
            return s
        if not self.allow:
            return "pause" if self.action == "pause" else "block"
        if self.raw.get("transformed_payload") is not None or self.transformed_args is not None:
            return "transform"  # an older gate (WP24b) masks without a v2 status
        return "report" if self.action in ("log", "alert") else "allow"

    @property
    def rule_id(self) -> str | None:
        r = self.raw.get("rule_id")
        return r if isinstance(r, str) else None

    @property
    def reason(self) -> str:
        return str(self.raw.get("reason") or "")

    @property
    def paused(self) -> bool:
        return not self.allow and (
            self.action == "pause" or self.status == "pause" or "paused" in self.reason.lower()
        )

    @property
    def transformed_args(self) -> dict[str, Any] | None:
        tp = self.raw.get("transformed_payload")
        if isinstance(tp, Mapping) and isinstance(tp.get("args"), Mapping):
            return dict(tp["args"])
        ta = self.raw.get("transformed_args")
        return dict(ta) if isinstance(ta, Mapping) else None

    @property
    def transformed_output(self) -> Any:
        tp = self.raw.get("transformed_payload")
        return tp.get("output") if isinstance(tp, Mapping) else None

    def decision(self) -> dict[str, Any]:
        """The answer for an exception: the gate's fields and the correlation id."""
        out = dict(self.raw)
        out["correlation_id"] = self.correlation_id
        return out


def _size(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):  # not serialisable: treat as too big
        return MAX_PAYLOAD_BYTES + 1


def _local(rule_id: str, reason: str, allow: bool = False, action: str | None = None) -> dict:
    return {
        "allow": allow,
        "action": action or ("allow" if allow else "block"),
        "rule_id": rule_id,
        "reason": reason,
        "latency_ms": 0,
    }


class GateClient:
    """One agent's connection to the gate for an adapter. Thread-safe (no mutable state but a
    cached signature check)."""

    def __init__(
        self,
        gate: GateHook,
        agent_id: str,
        agent_version: str = "1",
        *,
        fail_mode: str = "closed",
        risk_classes: Mapping[str, str] | None = None,
        default_risk_class: str | None = None,
        max_payload_bytes: int = MAX_PAYLOAD_BYTES,
        protocol: str = "llm",
    ) -> None:
        if fail_mode not in FAIL_MODES:
            raise ValueError(f"fail_mode must be one of {FAIL_MODES}")
        if clean_id(agent_id) is None or clean_id(str(agent_version)) is None:
            raise ValueError("agent_id and agent_version must match [A-Za-z0-9_.:@-]{1,128}")
        self.gate = gate
        self.agent_id = agent_id
        self.agent_version = str(agent_version)
        self.fail_mode = fail_mode
        self.risk_classes = dict(risk_classes or {})
        self.default_risk_class = default_risk_class
        self.max_payload_bytes = max_payload_bytes
        self.protocol = protocol if protocol in ("llm", "mcp", "a2a") else "llm"
        self._fn = getattr(gate, "check_v2", None) or gate.check
        try:
            params = inspect.signature(self._fn).parameters
            self._v2 = "direction" in params or any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
        except (TypeError, ValueError):
            self._v2 = False

    # -------------------------------------------------------------------- helpers

    def risk_class_of(self, tool: str) -> str | None:
        return self.risk_classes.get(tool) or self.default_risk_class

    def _closed_for(self, tool: str) -> bool:
        return self.fail_mode == "closed" or self.risk_class_of(tool) in CLOSED_RISK

    # -------------------------------------------------------------------- the call

    def check(
        self,
        tool_name: Any,
        args: Mapping[str, Any] | None = None,
        *,
        direction: str = "input",
        context: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
        consumer_id: Any = None,
        session_id: Any = None,
    ) -> GateAnswer:
        """Ask the gate. Never raises. A strange id is dropped (consumer, session) or replaced
        (correlation id), never forwarded."""
        t0 = time.perf_counter()
        tool = safe_tool_name(tool_name)
        cid = clean_id(correlation_id) or new_correlation_id()
        direction = "output" if direction == "output" else "input"
        ctx: dict[str, Any] = dict(context or {})
        rc = self.risk_class_of(tool)
        if rc and "declared_risk_class" not in ctx:
            ctx["declared_risk_class"] = rc
        if self.protocol != "llm":
            ctx.setdefault("protocol", self.protocol)
        for key, value in (("consumer_id", consumer_id), ("session_id", session_id)):
            ok = clean_id(value)
            if ok:
                ctx[key] = ok
            else:
                ctx.pop(key, None)
        payload_args = dict(args or {})
        too_big = (
            _size(payload_args) + _size(ctx.get("output")) + _size(ctx.get("tool_results"))
            > self.max_payload_bytes
        )
        if too_big:
            raw = (
                _local("SDK-PAYLOAD-TOO-LARGE", "payload is too large to inspect: fail closed")
                if self._closed_for(tool)
                else _local(
                    "SDK-UNINSPECTED", "payload too large to inspect: not sent", True, "alert"
                )
            )
            return GateAnswer(raw, cid, tool, direction)
        if direction == "output" and not self._v2:
            return GateAnswer(
                _local("GATE-DIRECTION", "the gate hook cannot check outputs: fail closed"),
                cid,
                tool,
                direction,
            )
        try:
            if self._v2:
                raw = self._fn(
                    self.agent_id,
                    self.agent_version,
                    tool,
                    payload_args,
                    ctx,
                    direction=direction,
                    correlation_id=cid,
                )  # type: ignore[call-arg]
            else:
                raw = self.gate.check(self.agent_id, self.agent_version, tool, payload_args, ctx)
        except Exception:  # noqa: BLE001 - a hook must not raise; if it does we are closed
            raw = _local("GATE-ERROR", "gate call failed: fail closed")
        if not isinstance(raw, Mapping) or not isinstance(raw.get("allow"), bool):
            raw = _local("GATE-ERROR", "gate answer not understood: fail closed")
        raw = dict(raw)
        if raw.get("rule_id") in UNAVAILABLE_RULES:  # the gate could not answer: the fail mode
            rid = str(raw["rule_id"])
            if self._closed_for(tool):
                raw = _local(rid, "gate unreachable: fail closed")
            else:
                raw = _local(rid, "gate unreachable: fail open", True, "alert")
        raw.setdefault("latency_ms", int((time.perf_counter() - t0) * 1000))
        answer_cid = raw.get("correlation_id")
        return GateAnswer(raw, clean_id(answer_cid) or cid, tool, direction)

    async def acheck(self, tool_name: Any, args: Mapping[str, Any] | None = None, **kw: Any):
        """``check`` in a worker thread (the SDK transport is blocking)."""
        return await asyncio.to_thread(lambda: self.check(tool_name, args, **kw))

    # -------------------------------------------------------------------- the verdict

    @staticmethod
    def contradicts(answer: GateAnswer) -> bool:
        """An ``allow: true`` answer that also says block or pause, or carries an action or a
        status this client does not know (WP38 review). Such an answer fails closed."""
        status = answer.status
        return answer.allow and (
            answer.action not in ALLOWED_ACTIONS
            or status not in KNOWN_STATUSES
            or status in ("block", "pause")
        )

    @staticmethod
    def refusal(answer: GateAnswer) -> GateAnswer | None:
        """None when the call may go on; else the answer that stops it.

        An answer with status ``transform`` that carries no masked values for this direction
        cannot be applied; letting the original through would defeat the transform, so it
        becomes a block (``SDK-TRANSFORM-UNAPPLIED``)."""
        if not answer.allow:
            return answer
        status = answer.status
        if GateClient.contradicts(answer):
            # allow: true next to a block, a pause or a value we do not know: fail closed.
            raw = _local(
                "SDK-ANSWER-CONTRADICTS",
                "the gate answer is not consistent (allow with a stop or an unknown value): "
                "fail closed",
            )
            return GateAnswer(raw, answer.correlation_id, answer.tool_name, answer.direction)
        tp = answer.raw.get("transformed_payload")
        if status == "transform" or tp is not None:
            out = answer.direction == "output"
            have = answer.transformed_output if out else answer.transformed_args
            if out and not isinstance(have, str):
                have = None
            if have is None:
                raw = _local(
                    "SDK-TRANSFORM-UNAPPLIED",
                    "the gate asked for a transform that has no values: fail closed",
                )
                return GateAnswer(raw, answer.correlation_id, answer.tool_name, answer.direction)
        return None

    @classmethod
    def enforce(cls, answer: GateAnswer) -> GateAnswer:
        """Raise ``SupervisorPaused`` or ``SupervisorBlocked`` when the call must not go on."""
        stop = cls.refusal(answer)
        if stop is None:
            return answer
        if stop.paused:
            raise SupervisorPaused(stop.decision())
        raise SupervisorBlocked(stop.decision())
