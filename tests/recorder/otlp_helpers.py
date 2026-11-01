"""Test helper: ReadableSpan -> OTLP/HTTP JSON. The product only decodes OTLP (the receiver);
this encoder builds the wire form that the receiver tests send (clean-up audit X4)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.recorder.normalise import _KINDS, _STATUS, span_from_readable


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
