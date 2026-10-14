"""OpenTelemetry wiring for the demo agents.

Every llm_call, tool_call and message is an OTel span with GenAI semantic-convention
attributes (``gen_ai.*``) plus ``supervisor.*`` attributes. ``AgentEventExporter`` turns
finished spans into ``AgentEvent`` rows and appends them to a ``TableStore``
(``agent_event``). WP4 replaces this exporter with the real normaliser and masker.

PII rule: the exporter writes digests only (``capture_level = "digest"``): tool args are
hashed (``args_hash``), never stored as text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from supervisor.core.canonical import CanonicalError, sha256_hex
from supervisor.core.models import AgentEvent
from supervisor.core.ports import TableStore

# supervisor.* attribute names (the contract with WP3/WP4)
A_AGENT_ID = "supervisor.agent_id"
A_AGENT_VERSION = "supervisor.agent_version"
A_CALLER = "supervisor.caller_agent_id"
A_EVENT_TYPE = "supervisor.event_type"
A_TOOL = "supervisor.tool_name"
A_ARGS_HASH = "supervisor.args_hash"
A_AMOUNT = "supervisor.amount_minor"
A_CURRENCY = "supervisor.currency"
A_STATUS = "supervisor.status"
A_RISK = "supervisor.risk_class"
A_GATE_ALLOW = "supervisor.gate.allow"
A_GATE_ACTION = "supervisor.gate.action"
A_GATE_RULE = "supervisor.gate.rule_id"
A_GATE_REASON = "supervisor.gate.reason"
A_GATE_LATENCY = "supervisor.gate.latency_ms"
A_ENV = "supervisor.env"
A_CLASSIFICATION = "supervisor.classification"


def args_hash(args: Mapping[str, Any]) -> str:
    """SHA-256 of canonical JSON of the args (falls back to sorted JSON if not canonical)."""
    try:
        return sha256_hex(dict(args))
    except CanonicalError:
        text = json.dumps(dict(args), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ts(ns: int | None) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=(ns or 0) // 1000)


def span_to_event(span: ReadableSpan, default_env: str = "dev") -> AgentEvent | None:
    """Convert one finished span to an AgentEvent row (None if not a supervisor span)."""
    attrs = dict(span.attributes or {})
    event_type = attrs.get(A_EVENT_TYPE)
    agent_id = attrs.get(A_AGENT_ID)
    if not event_type or not agent_id:
        return None
    ctx = span.get_span_context()
    trace_id = f"{ctx.trace_id:032x}"
    span_id = f"{ctx.span_id:016x}"
    parent = f"{span.parent.span_id:016x}" if span.parent is not None else None
    latency = None
    if span.start_time is not None and span.end_time is not None:
        latency = int((span.end_time - span.start_time) // 1_000_000)
    amount = attrs.get(A_AMOUNT)
    return AgentEvent(
        event_id=f"{trace_id}-{span_id}",
        ts=_ts(span.start_time),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        agent_id=str(agent_id),
        agent_version=_opt(attrs.get(A_AGENT_VERSION)),
        caller_agent_id=_opt(attrs.get(A_CALLER)),
        event_type=str(event_type),  # type: ignore[arg-type]
        tool_name=_opt(attrs.get(A_TOOL)),
        args_hash=_opt(attrs.get(A_ARGS_HASH)),
        args_masked=None,
        result_masked=None,
        amount_minor=amount if type(amount) is int else None,
        currency=_opt(attrs.get(A_CURRENCY)),
        status=_opt(attrs.get(A_STATUS)),
        latency_ms=latency,
        env=str(attrs.get(A_ENV) or default_env),
        classification=_opt(attrs.get(A_CLASSIFICATION)),
        source="otel",
        capture_level="digest",
    )


def _opt(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


class AgentEventExporter(SpanExporter):
    """In-memory span exporter -> ``agent_event`` rows in a TableStore.

    ``store`` may be None (rows are kept in ``self.events`` only)."""

    def __init__(self, store: TableStore | None = None, env: str = "dev") -> None:
        self.store = store
        self.env = env
        self.events: list[AgentEvent] = []
        self.spans: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        rows = []
        for span in spans:
            self.spans.append(span)
            event = span_to_event(span, self.env)
            if event is not None:
                rows.append(event)
        if rows:
            self.events.extend(rows)
            if self.store is not None:
                self.store.append("agent_event", rows)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def make_tracer_provider(
    exporter: SpanExporter, service_name: str = "supervisor-demo-agents"
) -> TracerProvider:
    """A private TracerProvider (not the global one) with a synchronous processor."""
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider
