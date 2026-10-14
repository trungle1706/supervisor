"""OpenTelemetry span -> ``agent_event`` row. Pure functions, no I/O.

Two span inputs, one shape (``SpanData``):

* ``span_from_readable``: an SDK ``ReadableSpan`` (in-process exporter, source ``otel``).
* ``spans_from_otlp_json``: an OTLP/HTTP JSON ``ExportTraceServiceRequest`` (source ``otlp``).

``Normaliser.normalise`` turns one ``SpanData`` into an ``AgentEvent`` (plus a restricted
raw row when the capture level is ``raw``). The same span gives the same row on both paths
(except ``source``, which names the path). Integers stay integers: OTLP JSON carries
64-bit values as strings and they are parsed with ``int()``; nothing goes through a float.

Attribute contract (``supervisor.*``, written by the agent SDK or by an onboarded agent):

=============================  ===============================================
``supervisor.agent_id``        agent id (fallback ``gen_ai.agent.id``)
``supervisor.agent_version``   agent version
``supervisor.event_type``      llm_call | tool_call | message | handoff
``supervisor.tool_name``       tool name (fallback ``gen_ai.tool.name``)
``supervisor.args_hash``       SHA-256 of canonical args, computed by the agent
``supervisor.args``            args / message text (masked or dropped here)
``supervisor.result``          tool result text (masked or dropped here)
``supervisor.amount_minor``    integer minor units (int attribute only)
``supervisor.capture_level``   optional: ask for a LOWER capture level
=============================  ===============================================
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from supervisor.core.models import AgentEvent
from supervisor.core.ports import Masker
from supervisor.recorder.capture import CaptureLevel, CapturePolicy

Source = Literal["otel", "otlp", "proxy"]

A_AGENT_ID = "supervisor.agent_id"
A_AGENT_VERSION = "supervisor.agent_version"
A_CALLER = "supervisor.caller_agent_id"
A_EVENT_TYPE = "supervisor.event_type"
A_TOOL = "supervisor.tool_name"
A_ARGS_HASH = "supervisor.args_hash"
A_ARGS = "supervisor.args"
A_RESULT = "supervisor.result"
A_AMOUNT = "supervisor.amount_minor"
A_CURRENCY = "supervisor.currency"
A_STATUS = "supervisor.status"
A_ENV = "supervisor.env"
A_CLASSIFICATION = "supervisor.classification"
A_CAPTURE = "supervisor.capture_level"

ARGS_KEYS = (
    A_ARGS,
    "gen_ai.tool.call.arguments",
    "supervisor.message.text",
    "gen_ai.input.messages",
)
RESULT_KEYS = (A_RESULT, "gen_ai.tool.call.result", "gen_ai.output.messages")
EVENT_TYPES = ("llm_call", "tool_call", "message", "handoff", "gate_decision")
LLM_OPERATIONS = {"chat", "text_completion", "generate_content", "completion"}
MAX_TEXT_CHARS = 8000
TRUNCATED = "...[truncated]"
RESTRICTED = "restricted"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_KINDS = ("UNSPECIFIED", "INTERNAL", "SERVER", "CLIENT", "PRODUCER", "CONSUMER")
_STATUS = ("UNSET", "OK", "ERROR")


class OtlpFormatError(ValueError):
    """The OTLP JSON payload is malformed (a user error: HTTP 400)."""


@dataclass(frozen=True)
class SpanData:
    """Transport-neutral span. Ids are lowercase hex; times are integer nanoseconds."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str  # INTERNAL | SERVER | CLIENT | PRODUCER | CONSUMER | UNSPECIFIED
    start_ns: int
    end_ns: int | None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    status_code: str = "UNSET"  # UNSET | OK | ERROR
    resource: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Normalised:
    event: AgentEvent
    raw: dict[str, Any] | None = None  # agent_event_raw row (capture level raw only)


# ------------------------------------------------------------------ helpers


def ns_to_datetime(ns: int) -> datetime:
    """Integer nanoseconds since epoch -> aware UTC datetime (microsecond precision)."""
    return _EPOCH + timedelta(microseconds=int(ns) // 1000)


def datetime_to_ns(value: datetime) -> int:
    delta = value.astimezone(UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def amount_band(amount_minor: int | None) -> str | None:
    """Order-of-magnitude band of an amount, for digests shown to judges: ``1e6-1e7``."""
    if amount_minor is None:
        return None
    if amount_minor <= 0:
        return "le0"
    digits = len(str(amount_minor))
    return f"1e{digits - 1}-1e{digits}"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _opt(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _as_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, tuple | list):
        value = list(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _first(attrs: Mapping[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        text = _as_text(attrs.get(key))
        if text is not None:
            return text
    return None


def _cap(text: str) -> str:
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[: MAX_TEXT_CHARS - len(TRUNCATED)] + TRUNCATED


def infer_event_type(attrs: Mapping[str, Any], kind: str) -> str | None:
    """Event type from ``supervisor.event_type``, else from GenAI attributes and span kind."""
    explicit = attrs.get(A_EVENT_TYPE)
    if explicit in EVENT_TYPES:
        return str(explicit)
    if explicit:
        return None
    op = str(attrs.get("gen_ai.operation.name") or "")
    if op == "execute_tool" or attrs.get("gen_ai.tool.name") or attrs.get(A_TOOL):
        return "tool_call"
    if op in LLM_OPERATIONS or (kind == "CLIENT" and attrs.get("gen_ai.request.model")):
        return "llm_call"
    if op in ("handoff", "invoke_agent") and attrs.get(A_CALLER):
        return "handoff"
    if op in ("invoke_agent", "create_agent") or attrs.get("supervisor.message.role"):
        return "message"
    return None


# ------------------------------------------------------------------ in-process spans


def span_from_readable(span: Any) -> SpanData:
    """``opentelemetry.sdk.trace.ReadableSpan`` -> SpanData."""
    ctx = span.get_span_context()
    parent = span.parent
    kind_name = getattr(span.kind, "name", "INTERNAL")
    status = getattr(getattr(span, "status", None), "status_code", None)
    resource = getattr(getattr(span, "resource", None), "attributes", None) or {}
    return SpanData(
        trace_id=f"{ctx.trace_id:032x}",
        span_id=f"{ctx.span_id:016x}",
        parent_span_id=f"{parent.span_id:016x}" if parent is not None else None,
        name=str(span.name),
        kind=kind_name,
        start_ns=int(span.start_time or 0),
        end_ns=int(span.end_time) if span.end_time is not None else None,
        attributes=dict(span.attributes or {}),
        status_code=getattr(status, "name", "UNSET"),
        resource=dict(resource),
    )


# ------------------------------------------------------------------ OTLP JSON


def _encode_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}  # int64 as string (OTLP JSON / proto3 JSON mapping)
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, tuple | list):
        return {"arrayValue": {"values": [_encode_value(v) for v in value]}}
    return {"stringValue": str(value)}


def _encode_attrs(attrs: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"key": k, "value": _encode_value(v)} for k, v in attrs.items()]


def spans_to_otlp_json(spans: Sequence[Any]) -> dict[str, Any]:
    """ReadableSpans -> OTLP/HTTP JSON ``ExportTraceServiceRequest`` (hex ids, string int64)."""
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    out: dict[str, Any] = {"resourceSpans": []}
    resources: dict[str, dict[str, Any]] = {}
    for span in spans:
        data = span_from_readable(span)
        rkey = json.dumps(data.resource, sort_keys=True, default=str)
        if rkey not in resources:
            resources[rkey] = {
                "resource": {"attributes": _encode_attrs(data.resource)},
                "scopeSpans": [],
            }
            out["resourceSpans"].append(resources[rkey])
        scope = getattr(span, "instrumentation_scope", None)
        sname = getattr(scope, "name", "") or ""
        sver = getattr(scope, "version", "") or ""
        gkey = (rkey, sname, sver)
        if gkey not in groups:
            groups[gkey] = {"scope": {"name": sname, "version": sver}, "spans": []}
            resources[rkey]["scopeSpans"].append(groups[gkey])
        item: dict[str, Any] = {
            "traceId": data.trace_id,
            "spanId": data.span_id,
            "parentSpanId": data.parent_span_id or "",
            "name": data.name,
            "kind": _KINDS.index(data.kind) if data.kind in _KINDS else 0,
            "startTimeUnixNano": str(data.start_ns),
            "attributes": _encode_attrs(data.attributes),
            "status": {"code": _STATUS.index(data.status_code)}
            if data.status_code in _STATUS
            else {},
        }
        if data.end_ns is not None:
            item["endTimeUnixNano"] = str(data.end_ns)
        groups[gkey]["spans"].append(item)
    return out


def _decode_id(value: Any, nbytes: int, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise OtlpFormatError(f"{what} must be a non-empty string")
    text = value.strip()
    if len(text) == nbytes * 2:
        try:
            int(text, 16)
            return text.lower()
        except ValueError:
            pass
    try:
        raw = base64.b64decode(text, validate=True)  # proto3 JSON mapping of bytes
    except (binascii.Error, ValueError):
        raw = b""
    if len(raw) == nbytes:
        return raw.hex()
    raise OtlpFormatError(f"{what} must be {nbytes * 2} hex characters")


def _decode_int(value: Any, what: str) -> int:
    if isinstance(value, bool):
        raise OtlpFormatError(f"{what} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise OtlpFormatError(f"{what} must be an integer (string or number)")


def _decode_value(value: Any, depth: int = 0) -> Any:
    if not isinstance(value, Mapping) or depth > 8:
        raise OtlpFormatError("attribute value must be an AnyValue object")
    if "stringValue" in value:
        return str(value["stringValue"])
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "intValue" in value:
        return _decode_int(value["intValue"], "intValue")
    if "doubleValue" in value:
        raw = value["doubleValue"]
        if isinstance(raw, bool) or not isinstance(raw, int | float | str):
            raise OtlpFormatError("doubleValue must be a number")
        try:
            return float(raw)  # non-money attributes only; money attributes must be intValue
        except ValueError as exc:
            raise OtlpFormatError("doubleValue must be a number") from exc
    if "arrayValue" in value:
        items = (value["arrayValue"] or {}).get("values") or []
        return tuple(_decode_value(v, depth + 1) for v in items)
    if "kvlistValue" in value:
        items = (value["kvlistValue"] or {}).get("values") or []
        return json.dumps(
            {str(kv.get("key")): _decode_value(kv.get("value"), depth + 1) for kv in items},
            ensure_ascii=False,
            sort_keys=True,
        )
    if "bytesValue" in value:
        return str(value["bytesValue"])
    return None  # empty AnyValue


def _decode_attrs(items: Any, what: str) -> dict[str, Any]:
    if items is None:
        return {}
    if not isinstance(items, list):
        raise OtlpFormatError(f"{what} must be a list")
    out: dict[str, Any] = {}
    for kv in items:
        if not isinstance(kv, Mapping) or not isinstance(kv.get("key"), str):
            raise OtlpFormatError(f"{what}: each item needs a string key")
        out[kv["key"]] = _decode_value(kv.get("value") or {})
    return out


def _decode_kind(value: Any) -> str:
    if value is None:
        return "UNSPECIFIED"
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(_KINDS):
        return _KINDS[value]
    if isinstance(value, str):
        name = value.upper().removeprefix("SPAN_KIND_")
        if name in _KINDS:
            return name
    raise OtlpFormatError(f"unknown span kind {value!r}")


def _decode_status(value: Any) -> str:
    code = (value or {}).get("code", 0) if isinstance(value, Mapping) else 0
    if isinstance(code, int) and not isinstance(code, bool) and 0 <= code < len(_STATUS):
        return _STATUS[code]
    if isinstance(code, str):
        name = code.upper().removeprefix("STATUS_CODE_")
        if name in _STATUS:
            return name
    raise OtlpFormatError(f"unknown status code {code!r}")


def spans_from_otlp_json(payload: Any) -> list[SpanData]:
    """OTLP/HTTP JSON ``ExportTraceServiceRequest`` -> SpanData list. Raises OtlpFormatError."""
    if not isinstance(payload, Mapping):
        raise OtlpFormatError("body must be a JSON object with resourceSpans")
    rs_list = payload.get("resourceSpans")
    if not isinstance(rs_list, list):
        raise OtlpFormatError("resourceSpans must be a list")
    out: list[SpanData] = []
    for rs in rs_list:
        if not isinstance(rs, Mapping):
            raise OtlpFormatError("resourceSpans items must be objects")
        resource = _decode_attrs((rs.get("resource") or {}).get("attributes"), "resource")
        scope_spans = rs.get("scopeSpans", rs.get("instrumentationLibrarySpans")) or []
        if not isinstance(scope_spans, list):
            raise OtlpFormatError("scopeSpans must be a list")
        for ss in scope_spans:
            spans = (ss or {}).get("spans") or [] if isinstance(ss, Mapping) else None
            if not isinstance(spans, list):
                raise OtlpFormatError("scopeSpans items must hold a spans list")
            for sp in spans:
                if not isinstance(sp, Mapping):
                    raise OtlpFormatError("spans items must be objects")
                parent = sp.get("parentSpanId") or None
                end = sp.get("endTimeUnixNano")
                out.append(
                    SpanData(
                        trace_id=_decode_id(sp.get("traceId"), 16, "traceId"),
                        span_id=_decode_id(sp.get("spanId"), 8, "spanId"),
                        parent_span_id=_decode_id(parent, 8, "parentSpanId") if parent else None,
                        name=str(sp.get("name") or ""),
                        kind=_decode_kind(sp.get("kind")),
                        start_ns=_decode_int(sp.get("startTimeUnixNano", 0), "startTimeUnixNano"),
                        end_ns=_decode_int(end, "endTimeUnixNano")
                        if end not in (None, "")
                        else None,
                        attributes=_decode_attrs(sp.get("attributes"), "span attributes"),
                        status_code=_decode_status(sp.get("status")),
                        resource=resource,
                    )
                )
    return out


# ------------------------------------------------------------------ normaliser


@dataclass
class Normaliser:
    """SpanData -> AgentEvent under a capture policy and an optional Masker.

    With ``masker=None`` every event is captured at ``digest`` (no text)."""

    masker: Masker | None = None
    policy: CapturePolicy = field(default_factory=CapturePolicy)
    default_env: str = "dev"

    @property
    def mask_version(self) -> str | None:
        if self.masker is None:
            return None
        return str(getattr(self.masker, "mask_version", type(self.masker).__name__))

    def agent_id_of(self, span: SpanData) -> str | None:
        a = span.attributes
        return (
            _opt(a.get(A_AGENT_ID))
            or _opt(a.get("gen_ai.agent.id"))
            or _opt(span.resource.get(A_AGENT_ID))
        )

    def level_for(self, span: SpanData, agent_id: str) -> CaptureLevel:
        requested = _opt(span.attributes.get(A_CAPTURE))
        return self.policy.effective(agent_id, requested, self.masker is not None)

    def normalise(self, span: SpanData, source: Source) -> Normalised | None:
        """One span -> one row, or None when the span is not an agent event."""
        attrs = span.attributes
        agent_id = self.agent_id_of(span)
        event_type = infer_event_type(attrs, span.kind)
        if not agent_id or not event_type:
            return None
        level = self.level_for(span, agent_id)
        args_text = _first(attrs, ARGS_KEYS)
        result_text = _first(attrs, RESULT_KEYS)
        args_hash = _opt(attrs.get(A_ARGS_HASH)) or (text_hash(args_text) if args_text else None)

        args_masked = result_masked = None
        found_pii = False
        if self.masker is not None:
            masked = [
                self.masker.mask(t) if t is not None else None for t in (args_text, result_text)
            ]
            found_pii = any(
                m is not None and m != t
                for m, t in zip(masked, (args_text, result_text), strict=True)
            )
            if level in ("masked", "raw"):
                args_masked = _cap(masked[0]) if masked[0] is not None else None
                result_masked = _cap(masked[1]) if masked[1] is not None else None

        latency = None
        if span.end_ns is not None and span.start_ns:
            latency = max(0, (span.end_ns - span.start_ns) // 1_000_000)
        amount = attrs.get(A_AMOUNT)
        currency = _opt(attrs.get(A_CURRENCY))
        status = _opt(attrs.get(A_STATUS)) or ("error" if span.status_code == "ERROR" else None)
        classification = _opt(attrs.get(A_CLASSIFICATION))
        if classification is None and self.masker is not None and (args_text or result_text):
            classification = "pii" if found_pii else "internal"
        event_id = f"{span.trace_id}-{span.span_id}"
        ts = ns_to_datetime(span.start_ns)
        event = AgentEvent(
            event_id=event_id,
            ts=ts,
            trace_id=span.trace_id,
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            agent_id=agent_id,
            agent_version=_opt(attrs.get(A_AGENT_VERSION)),
            caller_agent_id=_opt(attrs.get(A_CALLER)),
            event_type=event_type,  # type: ignore[arg-type]
            tool_name=_opt(attrs.get(A_TOOL)) or _opt(attrs.get("gen_ai.tool.name")),
            args_hash=args_hash,
            args_masked=args_masked,
            result_masked=result_masked,
            amount_minor=amount if type(amount) is int else None,
            currency=currency if currency and len(currency) == 3 and currency.isupper() else None,
            status=status,
            latency_ms=latency,
            env=str(attrs.get(A_ENV) or span.resource.get(A_ENV) or self.default_env),
            classification=classification,
            source=source,
            capture_level=level,
            mask_version=self.mask_version if level != "digest" else None,
        )
        raw = None
        if level == "raw" and (args_text is not None or result_text is not None):
            raw = {
                "event_id": event_id,
                "ts": ts,
                "trace_id": span.trace_id,
                "agent_id": agent_id,
                "args_raw": args_text,
                "result_raw": result_text,
                "access_class": RESTRICTED,
            }
        return Normalised(event, raw)

    def normalise_many(self, spans: Iterable[SpanData], source: Source) -> list[Normalised]:
        out = []
        for span in spans:
            item = self.normalise(span, source)
            if item is not None:
                out.append(item)
        return out
