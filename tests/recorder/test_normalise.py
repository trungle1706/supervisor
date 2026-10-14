"""Normaliser: the same span gives the same agent_event row via in-process and OTLP JSON."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime

import pytest

from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.recorder.capture import AgentCapture, CapturePolicy
from supervisor.recorder.normalise import (
    Normaliser,
    OtlpFormatError,
    SpanData,
    amount_band,
    infer_event_type,
    ns_to_datetime,
    span_from_readable,
    spans_from_otlp_json,
    spans_to_otlp_json,
)
from tests.recorder.conftest import PII_ACCOUNT, PII_NAME, payments_spans

MASKED = CapturePolicy({"payments": AgentCapture("masked")})


def _rows(items, drop=("source",)):
    return [{k: v for k, v in i.event.row().items() if k not in drop} for i in items]


@pytest.mark.parametrize("masked", [False, True])
def test_inprocess_and_otlp_json_give_identical_rows(masked: bool, masker: VnRegexMasker) -> None:
    spans = payments_spans()
    norm = Normaliser(masker if masked else None, MASKED, "dev")
    inproc = norm.normalise_many([span_from_readable(s) for s in spans], "otel")
    wire = json.loads(json.dumps(spans_to_otlp_json(spans)))  # through real JSON text
    otlp = norm.normalise_many(spans_from_otlp_json(wire), "otlp")
    assert len(inproc) == len(spans) == 7  # root + final message, 3 llm, 2 tools
    assert len(inproc) == len(otlp)
    assert _rows(inproc) == _rows(otlp)
    assert {i.event.source for i in inproc} == {"otel"}
    assert {i.event.source for i in otlp} == {"otlp"}
    types = sorted(i.event.event_type for i in inproc)
    assert types == ["llm_call"] * 3 + ["message"] * 2 + ["tool_call"] * 2
    for item in inproc:
        ev = item.event
        assert ev.event_id == f"{ev.trace_id}-{ev.span_id}"
        assert ev.agent_id == "payments" and ev.agent_version == "1.0.0" and ev.env == "test"
        assert ev.capture_level == ("masked" if masked else "digest")
        text = json.dumps(item.event.row(), default=str, ensure_ascii=False)
        assert PII_NAME not in text and PII_ACCOUNT not in text  # never raw in agent_event
    payee = next(i.event for i in inproc if i.event.tool_name == "add_payee")
    assert len(payee.args_hash or "") == 64 and payee.parent_span_id
    if masked:
        assert payee.args_masked and "<PERSON:" in payee.args_masked
        assert payee.classification == "pii" and payee.mask_version == "vn_regex-1:t1"
    else:
        assert payee.args_masked is None and payee.mask_version is None


def test_handwritten_otlp_json_spec_shapes() -> None:
    """A payload as another OTLP SDK writes it: int64 as strings, enum names, base64 ids."""
    trace = bytes(range(16))
    span = bytes(range(8))
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "supervisor.agent_id", "value": {"stringValue": "ext_bot"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "x"},
                        "spans": [
                            {
                                "traceId": base64.b64encode(trace).decode(),
                                "spanId": base64.b64encode(span).decode(),
                                "parentSpanId": "",
                                "name": "execute_tool transfer",
                                "kind": "SPAN_KIND_INTERNAL",
                                "startTimeUnixNano": "1760418000123456789",
                                "endTimeUnixNano": "1760418000223456789",
                                "attributes": [
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "execute_tool"},
                                    },
                                    {
                                        "key": "gen_ai.tool.name",
                                        "value": {"stringValue": "transfer"},
                                    },
                                    {
                                        "key": "supervisor.amount_minor",
                                        "value": {"intValue": "9007199254740993"},
                                    },
                                    {"key": "supervisor.currency", "value": {"stringValue": "VND"}},
                                    {"key": "x.ratio", "value": {"doubleValue": 0.5}},
                                ],
                                "status": {"code": "STATUS_CODE_ERROR"},
                            }
                        ],
                    }
                ],
            }
        ]
    }
    [sd] = spans_from_otlp_json(payload)
    assert sd.trace_id == trace.hex() and sd.span_id == span.hex() and sd.parent_span_id is None
    item = Normaliser(None, CapturePolicy(), "dev").normalise(sd, "otlp")
    assert item is not None
    ev = item.event
    assert ev.agent_id == "ext_bot" and ev.event_type == "tool_call" and ev.tool_name == "transfer"
    assert ev.amount_minor == 9007199254740993  # > 2**53: no float on the way
    assert ev.ts == datetime(2025, 10, 14, 5, 0, 0, 123456, tzinfo=UTC)
    assert ev.latency_ms == 100 and ev.status == "error" and ev.capture_level == "digest"


def test_double_amount_is_not_accepted_as_money() -> None:
    sd = SpanData("a" * 32, "b" * 16, None, "t", "INTERNAL", 1, 2,
                  {"supervisor.agent_id": "a", "supervisor.event_type": "tool_call",
                   "supervisor.amount_minor": 100.0})  # fmt: skip
    item = Normaliser().normalise(sd, "otlp")
    assert item is not None and item.event.amount_minor is None


def test_non_agent_spans_are_skipped() -> None:
    sd = SpanData("a" * 32, "b" * 16, None, "GET /", "SERVER", 1, 2, {"http.method": "GET"})
    assert Normaliser().normalise(sd, "otlp") is None


@pytest.mark.parametrize(
    ("attrs", "kind", "expected"),
    [
        ({"supervisor.event_type": "handoff"}, "INTERNAL", "handoff"),
        ({"supervisor.event_type": "bogus"}, "INTERNAL", None),
        ({"gen_ai.operation.name": "chat"}, "CLIENT", "llm_call"),
        ({"gen_ai.request.model": "m"}, "CLIENT", "llm_call"),
        ({"gen_ai.tool.name": "t"}, "INTERNAL", "tool_call"),
        (
            {"gen_ai.operation.name": "invoke_agent", "supervisor.caller_agent_id": "a"},
            "INTERNAL",
            "handoff",
        ),  # fmt: skip
        ({"gen_ai.operation.name": "invoke_agent"}, "INTERNAL", "message"),
        ({}, "INTERNAL", None),
    ],
)
def test_event_type_inference(attrs: dict, kind: str, expected: str | None) -> None:
    assert infer_event_type(attrs, kind) == expected


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"resourceSpans": "x"},
        {"resourceSpans": [{"scopeSpans": [{"spans": [{"traceId": "zz", "spanId": "1" * 16}]}]}]},
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "a" * 32,
                                    "spanId": "b" * 16,
                                    "startTimeUnixNano": "1.5",
                                }
                            ]
                        }
                    ]
                }
            ]
        },  # fmt: skip
        {
            "resourceSpans": [
                {"scopeSpans": [{"spans": [{"traceId": "a" * 32, "spanId": "b" * 16, "kind": 99}]}]}
            ]
        },  # fmt: skip
    ],
)
def test_malformed_otlp_raises_format_error(bad: object) -> None:
    with pytest.raises(OtlpFormatError):
        spans_from_otlp_json(bad)


def test_ts_and_amount_band_are_integer_safe() -> None:
    assert ns_to_datetime(1_760_418_000_999_999_999).microsecond == 999_999
    assert amount_band(95_000_000) == "1e7-1e8" and amount_band(0) == "le0"
    assert amount_band(None) is None


def _otlp(span_extra: dict, attrs: list | None = None, resource: object = None) -> dict:
    span = {"traceId": "a" * 32, "spanId": "b" * 16, "startTimeUnixNano": "1", **span_extra}
    span["attributes"] = attrs or [
        {"key": "supervisor.agent_id", "value": {"stringValue": "a1"}},
        {"key": "supervisor.event_type", "value": {"stringValue": "tool_call"}},
    ]
    rs: dict = {"scopeSpans": [{"spans": [span]}]}
    if resource is not None:
        rs["resource"] = resource
    return {"resourceSpans": [rs]}


HUGE = [{"key": "supervisor.amount_minor", "value": {"intValue": "99999999999999999999999"}}]


@pytest.mark.parametrize(
    "payload",
    [
        _otlp({}, resource="x"),
        _otlp({}, attrs=[{"key": "k", "value": {"kvlistValue": {"values": [1]}}}]),
        _otlp({}, attrs=[{"key": "k", "value": {"arrayValue": {"values": "x"}}}]),
        _otlp({"startTimeUnixNano": "9" * 30}),
        _otlp({"startTimeUnixNano": "²"}),
        _otlp({"startTimeUnixNano": "-5"}),
        _otlp({}, attrs=HUGE),
    ],
)
def test_hostile_otlp_shapes_are_format_errors(payload: dict) -> None:
    with pytest.raises(OtlpFormatError):
        spans_from_otlp_json(payload)


def test_identifier_fields_never_carry_pii_or_long_text(masker: VnRegexMasker) -> None:
    attrs = {
        "supervisor.agent_id": "a1",
        "supervisor.event_type": "tool_call",
        "supervisor.env": "0912345678",
        "supervisor.tool_name": "CCCD 079203001234",
        "supervisor.status": "x" * 100_000,
        "supervisor.agent_version": "1.0.0",
        "supervisor.amount_minor": 2**63,
        "supervisor.args_hash": "not-a-hash",
    }
    sd = SpanData("a" * 32, "b" * 16, None, "t", "INTERNAL", 1, 2, attrs)
    item = Normaliser(masker, MASKED, "dev").normalise(sd, "otel")
    assert item is not None
    ev = item.event
    assert "0912345678" not in ev.env
    assert ev.tool_name is None and ev.status is None and ev.agent_version == "1.0.0"
    assert ev.amount_minor is None and ev.args_hash is None


def test_digest_text_hash_is_keyed_not_plain_sha256(masker: VnRegexMasker) -> None:
    attrs = {
        "supervisor.agent_id": "a1",
        "supervisor.event_type": "message",
        "supervisor.args": "0912345678",
    }
    sd = SpanData("a" * 32, "b" * 16, None, "t", "INTERNAL", 1, 2, attrs)
    item = Normaliser(masker, CapturePolicy.digest_only()).normalise(sd, "otel")
    assert item is not None and item.event.args_hash
    assert item.event.args_hash != hashlib.sha256(b"0912345678").hexdigest()
    plain = Normaliser(None).normalise(sd, "otel")
    assert plain is not None and plain.event.args_hash is None
