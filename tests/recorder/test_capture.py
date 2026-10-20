"""Capture levels: digest / masked / raw, applied from the agent manifest."""

from __future__ import annotations

import json

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.recorder.capture import (
    AgentCapture,
    CapturePolicy,
    capture_from_manifest,
    load_manifest_policy,
)
from supervisor.recorder.normalise import Normaliser, SpanData
from supervisor_agents.common.tracing import AgentEventExporter
from tests.recorder.conftest import PII_ACCOUNT, PII_NAME, payments_spans

ARGS = json.dumps({"payee_name": PII_NAME, "account_number": PII_ACCOUNT}, ensure_ascii=False)


def _span(extra: dict | None = None) -> SpanData:
    attrs = {
        "supervisor.agent_id": "a1",
        "supervisor.event_type": "tool_call",
        "supervisor.tool_name": "add_payee",
        "supervisor.args": ARGS,
        "supervisor.result": json.dumps({"ok": True, "payee": PII_NAME}, ensure_ascii=False),
        "supervisor.amount_minor": 95_000_000,
        **(extra or {}),
    }
    return SpanData("a" * 32, "b" * 16, None, "t", "INTERNAL", 10**18, 10**18 + 5 * 10**6, attrs)


def _norm(level: str, raw_allowed: bool = False, masker: VnRegexMasker | None = None):
    m = masker or VnRegexMasker(b"k", "k1")
    return Normaliser(m, CapturePolicy({"a1": AgentCapture(level, raw_allowed)}))  # type: ignore[arg-type]


def test_digest_has_no_text_but_hash_and_amount() -> None:
    item = _norm("digest").normalise(_span(), "otel")
    assert item is not None and item.raw is None
    ev = item.event
    assert ev.capture_level == "digest" and ev.args_masked is None and ev.result_masked is None
    assert len(ev.args_hash or "") == 64 and ev.amount_minor == 95_000_000
    assert ev.classification == "pii" and ev.mask_version is None  # scanned, not stored


def test_masked_has_masked_text_only() -> None:
    item = _norm("masked").normalise(_span(), "otel")
    assert item is not None and item.raw is None
    ev = item.event
    assert ev.capture_level == "masked" and ev.mask_version == "vn_regex-3:k1"
    assert ev.args_masked and "<PERSON:" in ev.args_masked and PII_NAME not in ev.args_masked
    assert PII_ACCOUNT not in ev.args_masked
    assert ev.result_masked and PII_NAME not in ev.result_masked


def test_raw_needs_manifest_permission_and_goes_to_restricted_table() -> None:
    not_allowed = _norm("raw", raw_allowed=False).normalise(_span(), "otel")
    assert not_allowed is not None and not_allowed.event.capture_level == "masked"
    assert not_allowed.raw is None
    item = _norm("raw", raw_allowed=True).normalise(_span(), "otel")
    assert item is not None and item.event.capture_level == "raw"
    assert PII_NAME not in (item.event.args_masked or "")  # agent_event stays masked
    assert item.raw is not None and item.raw["access_class"] == "restricted"
    assert item.raw["args_raw"] == ARGS and item.raw["event_id"] == item.event.event_id


def test_span_can_lower_but_not_raise_level() -> None:
    lowered = _norm("raw", True).normalise(_span({"supervisor.capture_level": "digest"}), "otel")
    assert lowered is not None and lowered.event.capture_level == "digest" and lowered.raw is None
    raised = _norm("digest").normalise(_span({"supervisor.capture_level": "raw"}), "otel")
    assert raised is not None and raised.event.capture_level == "digest"


def test_no_masker_means_digest_even_for_raw_agents() -> None:
    norm = Normaliser(None, CapturePolicy({"a1": AgentCapture("raw", True)}))
    item = norm.normalise(_span(), "otel")
    assert item is not None and item.event.capture_level == "digest" and item.raw is None
    assert item.event.args_masked is None


def test_unknown_agents_never_get_raw() -> None:
    pol = CapturePolicy({}, "raw")  # type: ignore[arg-type]
    assert pol.effective("x", None, True) == "masked"
    assert CapturePolicy({}, "digest").effective("x", None, True) == "digest"


def test_manifest_capture_block() -> None:
    assert capture_from_manifest({}) == AgentCapture("masked", False)
    assert capture_from_manifest({"capture": {"level": "raw", "raw_allowed": True}}).level == "raw"
    for bad in ({"level": "raw"}, {"level": "all"}, {"raw_allowed": "yes"}, ["x"]):
        with pytest.raises(ValueError):
            capture_from_manifest({"capture": bad})
    pol = load_manifest_policy()
    assert set(pol.agents) == {"payments", "customer_service", "credit_prequal"}
    assert all(a.level == "masked" and not a.raw_allowed for a in pol.agents.values())


def test_agent_exporter_applies_manifest_level_and_writes_raw(adapters: Adapters) -> None:
    pol = CapturePolicy({"payments": AgentCapture("raw", True)})
    exporter = AgentEventExporter(
        adapters.tables, env="test", masker=VnRegexMasker(b"k", "k1"), policy=pol
    )
    exporter.export(payments_spans())
    events = adapters.tables.query("agent_event", {"agent_id": "payments"})
    assert len(events) == 7 and {e["capture_level"] for e in events} == {"raw"}
    assert PII_NAME not in json.dumps(events, default=str, ensure_ascii=False)
    raw = adapters.tables.query("agent_event_raw")
    assert raw and all(r["access_class"] == "restricted" for r in raw)
    assert any(PII_NAME in (r["args_raw"] or "") for r in raw)


def test_runtime_payload_capture_is_off_by_default() -> None:
    spans = payments_spans(capture_payloads=False)
    assert not any("supervisor.args" in (s.attributes or {}) for s in spans)
    item = _norm("masked").normalise(
        SpanData("a" * 32, "b" * 16, None, "t", "INTERNAL", 1, 2,
                 {"supervisor.agent_id": "a1", "supervisor.event_type": "message"}),
        "otel",
    )  # fmt: skip
    assert item is not None and item.event.args_masked is None
