"""Brute-force reference for the rollup: plain Python over the raw rows (no SQL)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from typing import Any

from supervisor.monitors.common import percentile


def brute_force(
    events: list[dict], verdicts: list[dict]
) -> dict[tuple[date, str, str], dict[str, Any]]:
    err_ids = {v["event_id"] for v in verdicts if v["label"] == "rule_error"}
    groups: dict[tuple[date, str, str], list[dict]] = defaultdict(list)
    for e in events:
        if e["event_type"] != "gate_decision" or not e.get("tool_name"):
            continue
        groups[(e["ts"].date(), e["agent_id"], e["tool_name"])].append(e)
    out = {}
    for key, rows in groups.items():
        lat = sorted(
            r["latency_us"] if r.get("latency_us") is not None else r["latency_ms"] * 1000
            for r in rows
        )
        allows = sum(r["status"] == "allowed" for r in rows)
        pauses = sum(r["status"] == "denied" and r["classification"] == "pause" for r in rows)
        users = {json.loads(r["args_masked"])["keys"].get("customer_id") for r in rows} - {None}
        out[key] = {
            "calls": len(rows),
            "allows": allows,
            "pauses": pauses,
            "blocks": len(rows) - allows - pauses,
            "errors": sum(r["event_id"] in err_ids for r in rows),
            "p50_us": percentile(lat, 50),
            "p95_us": percentile(lat, 95),
            "distinct_callers": len({r["caller_agent_id"] for r in rows} - {None}),
            "distinct_users": len(users),
            "first_seen": min(r["ts"] for r in rows),
            "last_seen": max(r["ts"] for r in rows),
        }
    return out
