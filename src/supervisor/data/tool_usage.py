"""Synthetic gate decisions for tool analytics tests and demos (WP22).

Deterministic: the same ``seed`` gives the same rows, byte for byte. Three agents with fixed
usage stories so the least-privilege suggestion has a known answer:

* ``payments``: ``add_payee`` stops 40 days before the end (unused in a 30 day window);
  ``ext_transfer_api`` is called now and then and paused by PAY-07 (used, not declared).
* ``customer_service``: ``open_dispute`` stops 45 days before the end; ``waive_fee`` is busy.
* ``credit_prequal``: all four tools used; ``request_documents`` is rare (one call on a few days).

Rows have the ``agent_event`` shape (event_type ``gate_decision``). Users are random hashes,
never real ids. No customer data.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

SEED = 20261020
AGENTS = ("payments", "customer_service", "credit_prequal")


@dataclass(frozen=True)
class ToolPlan:
    tool: str
    weight: int  # relative calls per day
    first_day: int = 0  # first day offset from the start
    last_day: int | None = None  # last day offset (inclusive); None = until the end
    every: int = 1  # active every Nth day only


# (agent -> tool plans). Offsets are counted from the start of the range (day 0).
def plans(days: int) -> dict[str, list[ToolPlan]]:
    return {
        "payments": [
            ToolPlan("get_balance", 8),
            ToolPlan("list_payees", 4),
            ToolPlan("add_payee", 2, last_day=days - 41),
            ToolPlan("transfer", 6),
            ToolPlan("ext_transfer_api", 1, first_day=days // 2, every=9),
        ],
        "customer_service": [
            ToolPlan("lookup_customer", 9),
            ToolPlan("read_ticket", 7),
            ToolPlan("reply", 7),
            ToolPlan("waive_fee", 3),
            ToolPlan("open_dispute", 2, last_day=days - 46),
        ],
        "credit_prequal": [
            ToolPlan("fetch_application", 5),
            ToolPlan("credit_score_lookup", 5),
            ToolPlan("decide_prequal", 3),
            ToolPlan("request_documents", 1, every=20),
        ],
    }


def _json_keys(user: str | None) -> str:
    return json.dumps({"keys": {"customer_id": user}} if user else {"keys": {}}, sort_keys=True)


def generate(
    seed: int = SEED,
    *,
    days: int = 90,
    end_day: date = date(2026, 10, 20),
    scale: int = 1,
) -> Iterator[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Yield ``(agent_event_row, verdict_row_or_None)`` for ``days`` UTC days ending ``end_day``.

    ``scale`` multiplies the calls per day (the performance test uses a large scale). Rows are
    produced day by day, lazily, so a million rows never sit in memory.
    """
    rng = random.Random(seed)  # noqa: S311 - synthetic data, not security
    start = end_day - timedelta(days=days - 1)
    users = [f"{rng.getrandbits(64):016x}" for _ in range(40)]
    callers = (None, None, "orchestrator", "ui_gateway")
    plan = plans(days)
    n = 0
    for offset in range(days):
        day = start + timedelta(days=offset)
        base = datetime(day.year, day.month, day.day, tzinfo=UTC)
        for agent in AGENTS:
            for p in plan[agent]:
                if offset < p.first_day or (p.last_day is not None and offset > p.last_day):
                    continue
                if (offset - p.first_day) % p.every:
                    continue
                for _ in range(p.weight * scale):
                    n += 1
                    us = rng.randrange(86_400_000_000)
                    ts = base + timedelta(microseconds=us)
                    roll = rng.randrange(1000)
                    declared = p.tool != "ext_transfer_api"
                    if not declared:
                        status, action = "denied", "pause"
                    elif roll < 30:
                        status, action = "denied", "block"
                    elif roll < 40:
                        status, action = "denied", "pause"
                    elif roll < 70:
                        status, action = "allowed", "alert"
                    else:
                        status, action = "allowed", "allow"
                    lat = 150 + int(rng.expovariate(1 / 900)) + (rng.randrange(40) * 25)
                    legacy = rng.randrange(20) == 0  # old row: millisecond latency only
                    event_id = f"ev{seed % 100000:05d}-{n:08d}"
                    row = {
                        "event_id": event_id,
                        "ts": ts,
                        "trace_id": event_id,
                        "span_id": event_id[-16:],
                        "agent_id": agent,
                        "event_type": "gate_decision",
                        "tool_name": p.tool,
                        "caller_agent_id": rng.choice(callers),
                        "args_masked": _json_keys(rng.choice(users) if rng.randrange(10) else None),
                        "status": status,
                        "classification": action,
                        "latency_ms": lat // 1000,
                        "latency_us": None if legacy else lat,
                        "env": "test",
                        "source": "proxy",
                        "capture_level": "digest",
                    }
                    verdict = None
                    if rng.randrange(200) == 0:
                        verdict = {
                            "verdict_id": f"vd-{event_id}",
                            "ts": ts,
                            "event_id": event_id,
                            "agent_id": agent,
                            "tier": 0,
                            "checker_id": "gate.tier0a",
                            "is_mock": False,
                            "advisory": False,
                            "label": "rule_error",
                            "action": action,
                        }
                    yield row, verdict
