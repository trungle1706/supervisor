"""Proxy log reader: reduced field set, masking, coverage row, bad lines."""

from __future__ import annotations

import json
from pathlib import Path

from supervisor.adapters.factory import Adapters
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.recorder.capture import AgentCapture, CapturePolicy
from supervisor.recorder.normalise import Normaliser
from supervisor.recorder.proxy_log import PROXY_MISSING, ProxyLogSource, read_proxy_log
from supervisor.recorder.sink import EventWriter

LINES = [
    {
        "ts": "2026-10-14T05:00:00.120Z",
        "agent_id": "vendor_bot",
        "agent_version": "2.1",
        "request_id": "r-0001",
        "session_id": "s-77",
        "kind": "tool_call",
        "tool": "transfer",
        "args": {
            "to_account": "602554736615",
            "amount_minor": 5000000,
            "memo": "cho Nguyễn Gia Tuấn",
        },
        "result": {"ok": True},
        "status": "ok",
        "latency_ms": 85,
        "amount_minor": 5000000,
        "currency": "VND",
        "env": "uat",
    },
    {
        "ts": "2026-10-14T05:00:01Z",
        "agent_id": "vendor_bot",
        "request_id": "r-0002",
        "session_id": "s-77",
        "kind": "llm_call",
    },
]
BAD = [
    "not json",
    json.dumps({"ts": "2026-10-14T05:00:02Z", "agent_id": "vendor_bot", "kind": "tool_call"}),
    json.dumps({"ts": "x", "agent_id": "a", "request_id": "r", "kind": "tool_call"}),
    json.dumps(
        {
            "ts": "2026-10-14T05:00:02Z",
            "agent_id": "a",
            "request_id": "r",
            "kind": "tool_call",
            "amount_minor": 10.5,
        }
    ),
    json.dumps({"ts": "2026-10-14T05:00:02Z", "agent_id": "a", "request_id": "r", "kind": "x"}),
]


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "proxy.jsonl"
    text = "\n".join([json.dumps(x, ensure_ascii=False) for x in LINES] + BAD + [""])
    path.write_text(text, encoding="utf-8")
    return path


def test_proxy_log_rows_coverage_and_errors(
    tmp_path: Path, masker: VnRegexMasker, adapters: Adapters
) -> None:
    norm = Normaliser(masker, CapturePolicy({"vendor_bot": AgentCapture("masked")}))
    res = read_proxy_log(_write(tmp_path), norm)
    assert [n for n, _ in res.errors] == [3, 4, 5, 6, 7]
    assert "amount_minor must be an integer" in res.errors[3][1]
    assert len(res.items) == 2
    tool_ev, llm_ev = (i.event for i in res.items)
    assert tool_ev.source == "proxy" and tool_ev.event_type == "tool_call"
    assert tool_ev.tool_name == "transfer" and tool_ev.amount_minor == 5_000_000
    assert tool_ev.parent_span_id is None and tool_ev.caller_agent_id is None  # reduced
    assert tool_ev.trace_id == llm_ev.trace_id  # same session -> same trace
    assert tool_ev.latency_ms == 85 and tool_ev.env == "uat" and len(tool_ev.args_hash or "") == 64
    assert tool_ev.args_masked and "602554736615" not in tool_ev.args_masked
    assert "Nguyễn Gia Tuấn" not in tool_ev.args_masked
    [cov] = res.coverage
    assert cov["agent_id"] == "vendor_bot" and cov["capability"] == "reduced"
    assert cov["source"] == "proxy" and cov["missing"] == list(PROXY_MISSING)

    writer = EventWriter(adapters.tables)
    assert writer.write(res.items).written == 2
    assert writer.write_coverage(res.coverage) == 1
    assert writer.write_coverage(res.coverage) == 0  # idempotent
    stored = adapters.tables.query("trace_coverage")
    assert stored[0]["missing"] == list(PROXY_MISSING)


def test_proxy_source_is_a_trace_source(tmp_path: Path) -> None:
    src = ProxyLogSource(_write(tmp_path), Normaliser())
    rows = list(src.read())
    assert len(rows) == 2 and all(r["capture_level"] == "digest" for r in rows)
    assert all(r["args_masked"] is None for r in rows)
