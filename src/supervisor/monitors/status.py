"""Monitor status per agent and day: a monitor that cannot run says so (WP1b-B, D06).

Before WP1b-B the quality, fairness, drift and multi-agent monitors wrote nothing for an
agent they could not read, and "on but silent" looked like "all clear". Now each monitor
writes one entry per agent into ``oversight_metric.monitor_status`` (a JSON column):

``ok``              the monitor produced values for the agent (``n`` = items it read);
``not_applicable``  the agent has no binding and none can be derived (``code`` and a
                    ``reason`` that names the missing tool or setting);
``no_data``         the binding exists but the window holds nothing to compute yet
                    (for example drift still collecting its baseline).

Entries are merged into the existing row of (day, agent). A status that did not change is
not written again, so a monitor that runs every minute does not churn the table. Statuses
are derived data: they are not put on the evidence chain.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from supervisor.monitors.common import MonitorContext, upsert_metric

OK = "ok"
NOT_APPLICABLE = "not_applicable"
NO_DATA = "no_data"
STATUSES = (OK, NOT_APPLICABLE, NO_DATA)
MONITORS = ("quality", "fairness", "drift", "multiagent")


def _load(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def read_status(ctx: MonitorContext, day: date, agent_id: str) -> dict[str, Any]:
    row = ctx.state.get("oversight_metric", {"metric_date": day, "agent_id": agent_id})
    return _load(row.get("monitor_status")) if row else {}


def set_status(
    ctx: MonitorContext,
    day: date,
    agent_id: str,
    monitor: str,
    status: str,
    *,
    code: str = "",
    reason: str = "",
    n: int | None = None,
) -> bool:
    """Record the status of ``monitor`` for the agent and day. True when the row changed."""
    if monitor not in MONITORS or status not in STATUSES:
        raise ValueError(f"unknown monitor or status: {monitor!r} / {status!r}")
    entry: dict[str, Any] = {"status": status}
    if code:
        entry["code"] = code
    if reason:
        entry["reason"] = reason[:300]
    if n is not None:
        entry["n"] = int(n)
    current = read_status(ctx, day, agent_id)
    if current.get(monitor) == entry:
        return False
    current[monitor] = entry
    upsert_metric(ctx, day, agent_id, {"monitor_status": current})
    return True


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tzinfo=UTC)
    return start, start + timedelta(days=1)


def count_events(
    ctx: MonitorContext,
    agent_id: str,
    start: datetime,
    end: datetime,
    *,
    event_types: Sequence[str] = (),
    tools: Sequence[str] = (),
) -> int:
    """Number of ``agent_event`` rows of the agent in [start, end), by type and tool name."""
    params: dict[str, Any] = {"a": agent_id, "f": start, "t": end}
    types = {"a": "string", "f": "timestamp", "t": "timestamp"}
    parts = ["agent_id = :a", "ts >= :f", "ts < :t"]
    for col, values in (("event_type", event_types), ("tool_name", tools)):
        if values:
            names = []
            for i, v in enumerate(values):
                key = f"{col[:2]}{i}"
                params[key], types[key] = v, "string"
                names.append(f":{key}")
            parts.append(f"{col} IN ({', '.join(names)})")
    sql = (
        f"SELECT COUNT(*) AS n FROM {ctx.executor.qualify('agent_event')} "  # noqa: S608 - names from model.yaml
        f"WHERE {' AND '.join(parts)}"
    )
    rows = ctx.executor.query(sql, params, column_types={"n": "int"}, param_types=types)
    return int(rows[0]["n"]) if rows else 0


def count_verdicts(
    ctx: MonitorContext, agent_id: str, checker_id: str, start: datetime, end: datetime
) -> int:
    sql = (
        f"SELECT COUNT(*) AS n FROM {ctx.executor.qualify('verdict')} "  # noqa: S608 - names from model.yaml
        "WHERE agent_id = :a AND checker_id = :c AND ts >= :f AND ts < :t"
    )
    rows = ctx.executor.query(
        sql,
        {"a": agent_id, "c": checker_id, "f": start, "t": end},
        column_types={"n": "int"},
        param_types={"a": "string", "c": "string", "f": "timestamp", "t": "timestamp"},
    )
    return int(rows[0]["n"]) if rows else 0


def observed_tools(ctx: MonitorContext, since: datetime) -> dict[str, set[str]]:
    """Tool names each agent was seen calling since ``since`` (feeds the derived bindings)."""
    sql = (
        f"SELECT DISTINCT agent_id, tool_name FROM {ctx.executor.qualify('agent_event')} "  # noqa: S608 - names from model.yaml
        "WHERE tool_name IS NOT NULL AND ts >= :f"
    )
    rows = ctx.executor.query(
        sql,
        {"f": since},
        column_types={"agent_id": "string", "tool_name": "string"},
        param_types={"f": "timestamp"},
    )
    out: dict[str, set[str]] = {}
    for r in rows:
        out.setdefault(str(r["agent_id"]), set()).add(str(r["tool_name"]))
    return out


def known_agents(
    ctx: MonitorContext, resolver: Any | None, observed: Mapping[str, set[str]]
) -> list[str]:
    """Every agent a monitor should report on: registry rows, bound agents, agents seen."""
    ids = {str(r["agent_id"]) for r in ctx.state.query("agent")} | set(observed)
    if resolver is not None:
        ids |= set(resolver.agent_ids())
    return sorted(ids)


__all__ = [
    "known_agents",
    "count_events",
    "count_verdicts",
    "day_bounds",
    "observed_tools",
    "MONITORS",
    "NOT_APPLICABLE",
    "NO_DATA",
    "OK",
    "STATUSES",
    "read_status",
    "set_status",
]
