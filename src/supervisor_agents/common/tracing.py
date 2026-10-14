"""OpenTelemetry wiring for the demo agents.

Every llm_call, tool_call and message is an OTel span with GenAI semantic-convention
attributes (``gen_ai.*``) plus ``supervisor.*`` attributes. ``AgentEventExporter`` turns
finished spans into ``AgentEvent`` rows and appends them to a ``TableStore``
(``agent_event``) through the WP4 normaliser (``supervisor.recorder.normalise``).

PII rule: without a Masker the exporter writes digests only (``capture_level = "digest"``):
tool args are hashed (``args_hash``), never stored as text. Payload text attributes
(``supervisor.args`` / ``supervisor.result``) are set only when ``capture_payloads`` is on
in the runtime (default off).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from supervisor.core.canonical import CanonicalError, sha256_hex
from supervisor.core.models import AgentEvent
from supervisor.core.ports import Masker, TableStore
from supervisor.recorder.capture import CapturePolicy
from supervisor.recorder.normalise import Normaliser, span_from_readable

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
A_ARGS = "supervisor.args"
A_RESULT = "supervisor.result"


def args_hash(args: Mapping[str, Any]) -> str:
    """SHA-256 of canonical JSON of the args (falls back to sorted JSON if not canonical)."""
    try:
        return sha256_hex(dict(args))
    except CanonicalError:
        text = json.dumps(dict(args), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def span_to_event(span: ReadableSpan, default_env: str = "dev") -> AgentEvent | None:
    """Convert one finished span to an AgentEvent row (None if not a supervisor span).

    Digest level (no Masker): goes through the WP4 normaliser like every other path."""
    item = Normaliser(None, CapturePolicy.digest_only(), default_env).normalise(
        span_from_readable(span), "otel"
    )
    return item.event if item is not None else None


class AgentEventExporter(SpanExporter):
    """In-process span exporter -> ``agent_event`` rows in a TableStore (source ``otel``).

    Rows come from ``supervisor.recorder.normalise`` (the same code as the OTLP receiver).
    ``store`` may be None (rows are kept in ``self.events`` only). Without a ``masker`` every
    row is ``digest`` (no text). With a masker, the capture ``policy`` (from the agent
    manifests) decides digest / masked / raw; raw rows go to ``agent_event_raw``."""

    def __init__(
        self,
        store: TableStore | None = None,
        env: str = "dev",
        *,
        masker: Masker | None = None,
        policy: CapturePolicy | None = None,
    ) -> None:
        self.store = store
        self.env = env
        self.normaliser = Normaliser(
            masker, policy or (CapturePolicy() if masker else CapturePolicy.digest_only()), env
        )
        self.events: list[AgentEvent] = []
        self.spans: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.spans.extend(spans)
        items = self.normaliser.normalise_many((span_from_readable(s) for s in spans), "otel")
        rows = [i.event for i in items]
        raw = [i.raw for i in items if i.raw is not None]
        if rows:
            self.events.extend(rows)
            if self.store is not None:
                self.store.append("agent_event", rows)
                if raw:
                    self.store.append("agent_event_raw", raw)
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
