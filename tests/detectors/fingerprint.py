"""Fingerprint of everything the gate records for a fixed call sequence (WP37).

Used by the "flag off = byte for byte" test: the sequence runs on a gateway built without
detectors and the canonical hash of the answers, the verdict rows, the agent_event rows and the
chain payloads must equal the value recorded on v0.3.0 (before WP37). Volatile fields (random ids
and measured latencies) are dropped; everything else, including every key name, counts.
"""

from __future__ import annotations

import hashlib
from typing import Any

from supervisor.core.canonical import canonical_json
from supervisor.gateway.engine import Gateway

VOLATILE = {
    "decision_id",
    "event_id",
    "verdict_id",
    "span_id",
    "latency_ms",
    "latency_us",
    "total_us",
}

PII_ARGS = {
    "customer_id": "C-1",
    "payee_name": "NGUYEN VAN THU",
    "cccd": "001203004567",
    "note": "Chuyen 1.500.000.000 VND, so dien thoai 0912345678",
}

SEQUENCE: list[tuple[str, str, dict[str, Any]]] = [
    ("customer_service", "read_ticket", {"ticket_id": "T1"}),
    ("customer_service", "ext_transfer_api", {"amount_minor": 1}),
    ("payments", "get_balance", {"account_id": "A-1"}),
    ("payments", "add_payee", PII_ARGS),
    ("payments", "transfer", {"amount_minor": 1_000_000, "customer_id": "C-1", "payee_id": "P-1"}),
    ("payments", "ext_transfer_api", {"amount_minor": 5}),  # PAY-07 pauses the agent
    ("payments", "get_balance", {"account_id": "A-1"}),
    ("nobody", "read_ticket", {}),
]


# Columns WP37 added to agent_event. They exist (as NULL) in every row read back from the store;
# with the flag off nothing writes them, so a NULL here is "not written" and is left out.
WP37_NULL_COLUMNS = {
    "verdict_status",
    "correlation_id",
    "coverage_json",
    "session_id",  # WP27: written only with SESSION_MONITOR_ENABLED
    "session_source",
    "session_json",
    # WP39 additive columns: also NULL unless DETECTORS_ENABLED
    "request_id",
    "consumer_id",
    "latency_rules_us",
    "latency_detectors_us",
    "detector_latency_json",
}


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _clean(v)
            for k, v in value.items()
            if k not in VOLATILE and not (k in WP37_NULL_COLUMNS and v is None)
        }
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def run_sequence(gw: Gateway) -> list[dict[str, Any]]:
    out = []
    for agent, tool, args in SEQUENCE:
        out.append(gw.check(agent, "1.0", tool, dict(args), {"trace_id": "t-fp"}))
    gw.drain()
    return out


def fingerprint(gw: Gateway, answers: list[dict[str, Any]], evidence: Any) -> str:
    rows = {
        "verdict": sorted(
            (_clean(r) for r in gw.tables.query("verdict", {})),
            key=lambda r: canonical_json(r),
        ),
        "agent_event": sorted(
            (_clean(r) for r in gw.tables.query("agent_event", {})),
            key=lambda r: canonical_json(r),
        ),
    }
    chain = [(t, _clean(p)) for t, _, p in evidence.entries]
    doc = {"answers": [_clean(a) for a in answers], "rows": rows, "chain": chain}
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()
