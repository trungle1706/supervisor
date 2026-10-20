"""Synthetic verdict v2 rows for the WP39 console tests (no gate involved)."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

from supervisor.core.canonical import canonical_json

SHADOW_CODES = ("injection.ignore_previous", "pii.phone", "pii.person")


def add_decision(
    c: Any,
    *,
    agent: str = "payments",
    status: str = "allow",
    action: str = "allow",
    corr: str | None = None,
    request_id: str | None = None,
    direction: str = "input",
    consumer: str | None = None,
    gaps: tuple[str, ...] = (),
    codes: tuple[str, ...] = (),
    not_executed: tuple[str, ...] = (),
    age_s: int = 60,
    tool: str = "get_balance",
    trace: str | None = None,
    span: str | None = None,
    lat: tuple[int, int, int] | None = (1500, 300, 400),
    fragments: list[dict[str, Any]] | None = None,
    entities: list[dict[str, Any]] | None = None,
    hint: str = "report",
    rule: str | None = None,
) -> str:
    """One gate decision (agent_event) plus its finding rows. ``lat`` is (total, rules,
    detectors) in microseconds. Returns the decision id."""
    tables = c.ctx.tables
    now = c.ctx.clock.now() - timedelta(seconds=age_s)
    eid = uuid.uuid4().hex
    trace = trace or f"t-{eid[:10]}"
    span = span or f"s-{eid[:10]}"
    cov: dict[str, Any] = {
        "direction": direction,
        "inspected": ["args"] if direction == "input" else ["output"],
        "not_inspected": [{"part": "tool_results", "reason": g} for g in gaps],
        "chars": 10,
    }
    tables.append(
        "agent_event",
        [
            {
                "event_id": eid,
                "ts": now,
                "trace_id": trace,
                "span_id": span,
                "agent_id": agent,
                "event_type": "gate_decision",
                "tool_name": tool,
                "args_hash": "h" * 64,
                "args_masked": canonical_json({"keys": {}}),
                "status": "denied" if status in ("block", "pause") else "allowed",
                "latency_ms": (lat[0] // 1000) if lat else 0,
                "latency_us": lat[0] if lat else None,
                "env": "test",
                "classification": "pause"
                if status == "pause"
                else ("block" if status == "block" else action),
                "source": "proxy",
                "capture_level": "digest",
                "verdict_status": status,
                "correlation_id": corr,
                "request_id": request_id,
                "coverage_json": canonical_json(cov),
                "consumer_id": consumer,
                "latency_rules_us": lat[1] if lat else None,
                "latency_detectors_us": lat[2] if lat else None,
                "detector_latency_json": canonical_json({"dlp_vn": (lat[2] // 2) if lat else 0})
                if lat
                else None,
            }
        ],
    )
    rows = []
    for code in codes:
        rows.append(
            _finding(
                eid,
                now,
                agent,
                tool,
                trace,
                corr,
                request_id,
                direction,
                code,
                None,
                status,
                hint,
                fragments,
                entities,
            )
        )
    for reason in not_executed:
        rows.append(
            _finding(
                eid,
                now,
                agent,
                tool,
                trace,
                corr,
                request_id,
                direction,
                f"not_executed.{reason}",
                reason,
                status,
                "report",
                None,
                None,
            )
        )
    if rows:
        tables.append("finding", rows)
    return eid


def _finding(
    eid,
    now,
    agent,
    tool,
    trace,
    corr,
    request_id,
    direction,
    code,
    reason,
    status,
    hint,
    fragments,
    entities,
) -> dict[str, Any]:  # noqa: ANN001
    return {
        "finding_id": uuid.uuid4().hex,
        "ts": now,
        "event_id": eid,
        "request_id": request_id or "req-" + eid[:8],
        "correlation_id": corr or "corr-" + eid[:8],
        "trace_id": trace,
        "agent_id": agent,
        "tool_name": tool,
        "direction": direction,
        "detector_slug": "dlp_vn" if code.startswith("pii") or reason else "injection_regex",
        "detector_id": ("dlp_vn" if code.startswith("pii") or reason else "injection_regex")
        + "@1.0.0",
        "code": code,
        "score_bp": 0 if reason else 9500,
        "threshold_bp": 8000,
        "masked_count": 0 if reason else 1,
        "action_hint": hint,
        "not_executed_reason": reason,
        "preset": "balanced",
        "is_mock": False,
        "verdict_status": status,
        "entities_masked": json.dumps(entities) if entities else None,
        "fragments_masked": json.dumps(fragments) if fragments else None,
    }
