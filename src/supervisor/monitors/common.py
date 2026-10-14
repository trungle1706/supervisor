"""Shared helpers for the monitors: integer statistics, time-range reads, cases, state.

All statistics are integers. Percentiles use the nearest-rank method (no interpolation,
so the result is always one of the observed values).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError
from supervisor.core.models import Case, CaseEvent
from supervisor.core.ports import Clock, EvidenceSink, SqlExecutor, StateStore, TableStore
from supervisor.core.schema import SchemaModel

OPEN_STATUSES = ("open", "triage", "escalated")
SEVERITY_ORDER = ("low", "medium", "high", "critical")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------------- context


@dataclass
class MonitorContext:
    """What a monitor needs. Built by the jobs (CLI) or by the scheduler (app)."""

    tables: TableStore
    state: StateStore
    executor: SqlExecutor
    model: SchemaModel
    clock: Clock
    evidence: EvidenceSink

    @classmethod
    def from_adapters(cls, adapters: Any, evidence: EvidenceSink) -> MonitorContext:
        return cls(
            tables=adapters.tables,
            state=adapters.state,
            executor=adapters.executor,
            model=adapters.model,
            clock=adapters.clock,
            evidence=evidence,
        )


# --------------------------------------------------------------------------- integer stats


def percentile(values: Sequence[int], p: int) -> int:
    """Nearest-rank percentile (0 < p <= 100) of a non-empty list of ints."""
    if not values:
        raise ValueError("percentile of an empty list")
    if not 0 < p <= 100:
        raise ValueError("p must be in 1..100")
    ordered = sorted(int(v) for v in values)
    rank = (p * len(ordered) + 99) // 100  # ceil(p/100 * n)
    return ordered[max(0, rank - 1)]


def median(values: Sequence[int]) -> int:
    return percentile(values, 50)


def scaled_mad(values: Sequence[int], center: int) -> int:
    """Median absolute deviation, scaled by 1.4826 (so it estimates sigma), integer."""
    mad = median([abs(int(v) - center) for v in values])
    return mad * 14826 // 10000


def rate_bp(part: int, whole: int) -> int | None:
    """part / whole in integer basis points (floor), None when whole is 0."""
    if whole <= 0:
        return None
    return part * 10000 // whole


# --------------------------------------------------------------------------- time


def epoch_s(ts: datetime) -> int:
    return int((ts - EPOCH).total_seconds())


def floor_window(ts: datetime, window_s: int) -> datetime:
    """Start of the epoch-aligned window that holds ``ts``."""
    return EPOCH + timedelta(seconds=(epoch_s(ts) // window_s) * window_s)


def as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def read_range(
    ctx: MonitorContext,
    table: str,
    ts_from: datetime,
    ts_to: datetime,
    where: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rows of ``table`` with ``ts_from <= ts < ts_to`` (and equality filters), by ts."""
    t = ctx.model.table(table)
    params: dict[str, Any] = {"r_from": ts_from, "r_to": ts_to}
    types: dict[str, str] = {"r_from": "timestamp", "r_to": "timestamp"}
    parts = ["ts >= :r_from", "ts < :r_to"]
    for i, (name, value) in enumerate(sorted((where or {}).items())):
        col = t.column(name)  # raises for an unknown column
        if value is None:
            parts.append(f"{col.name} IS NULL")
        else:
            parts.append(f"{col.name} = :w{i}")
            params[f"w{i}"] = value
            types[f"w{i}"] = col.type
    sql = (
        f"SELECT {', '.join(t.column_names)} FROM {ctx.executor.qualify(t.name)} "  # noqa: S608 - names from model.yaml
        f"WHERE {' AND '.join(parts)} ORDER BY ts"
    )
    return ctx.executor.query(sql, params, column_types=t.types, param_types=types)


# --------------------------------------------------------------------------- state rows


def get_state(ctx: MonitorContext, monitor: str, key: str) -> dict[str, Any] | None:
    row = ctx.state.get("monitor_state", {"monitor": monitor, "state_key": key})
    if row is None:
        return None
    value = row["value"]
    if isinstance(value, str):
        import json

        value = json.loads(value)
    return dict(value) if isinstance(value, Mapping) else {"value": value}


def put_state(ctx: MonitorContext, monitor: str, key: str, value: Mapping[str, Any]) -> None:
    row = ctx.state.get("monitor_state", {"monitor": monitor, "state_key": key})
    data = {"monitor": monitor, "state_key": key, "value": dict(value)}
    if row is None:
        try:
            ctx.state.insert("monitor_state", data)
            return
        except DuplicateKeyError:
            row = ctx.state.get("monitor_state", {"monitor": monitor, "state_key": key})
            assert row is not None
    ctx.state.update(
        "monitor_state",
        {"monitor": monitor, "state_key": key},
        {"value": dict(value)},
        expected_version=row["row_version"],
    )


def threshold(ctx: MonitorContext, agent_id: str, metric: str, default: int) -> int:
    """``policy_threshold`` value for (agent, metric), else (``*``, metric), else default."""
    for scope in (agent_id, "*"):
        row = ctx.state.get("policy_threshold", {"agent_id": scope, "metric": metric})
        if row is not None and isinstance(row.get("threshold"), int):
            return int(row["threshold"])
    return default


def upsert_metric(
    ctx: MonitorContext, metric_date: date, agent_id: str, changes: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge ``changes`` into the ``oversight_metric`` row of (date, agent). Retries once."""
    key = {"metric_date": metric_date, "agent_id": agent_id}
    for attempt in range(3):
        row = ctx.state.get("oversight_metric", key)
        data = {**dict(changes), "computed_at": ctx.clock.now()}
        try:
            if row is None:
                return ctx.state.insert("oversight_metric", {**key, **data})
            return ctx.state.update("oversight_metric", key, data, row["row_version"])
        except (ConcurrencyError, DuplicateKeyError):
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------- cases


def find_open_case(
    ctx: MonitorContext, agent_id: str, case_type: str, case_id: str | None = None
) -> dict[str, Any] | None:
    """The open case of this type for the agent (or the given case if still open)."""
    if case_id:
        row = ctx.state.get("cases", {"case_id": case_id})
        return row if row is not None and row["status"] in OPEN_STATUSES else None
    rows = ctx.state.query("cases", {"agent_id": agent_id, "case_type": case_type})
    open_rows = [r for r in rows if r["status"] in OPEN_STATUSES]
    return max(open_rows, key=lambda r: r["opened_at"]) if open_rows else None


def open_case(
    ctx: MonitorContext,
    *,
    agent_id: str,
    severity: str,
    case_type: str,
    summary: str,
    actor: str,
    evidence_payload: Mapping[str, Any],
    regulation_refs: Iterable[str] = (),
) -> str:
    """Insert a ``cases`` row and its first ``case_event``; record both on the chain.

    ``evidence_payload`` must hold integers and strings only (no floats, no raw PII)."""
    now = ctx.clock.now()
    case_id = f"CASE-{case_type}-{uuid.uuid4().hex[:16]}"
    case = Case(
        case_id=case_id,
        agent_id=agent_id,
        severity=severity,  # type: ignore[arg-type]
        status="open",
        opened_at=now,
        regulation_refs=list(regulation_refs),
        summary=summary[:2000],
        case_type=case_type,
    )
    row = case.row()
    row.pop("row_version", None)
    row.pop("updated_at", None)
    ctx.state.insert("cases", row)
    event = CaseEvent(
        case_id=case_id,
        seq=0,
        ts=now,
        actor=actor,
        actor_kind="system",
        action="opened",
        comment_masked=summary[:2000],
    )
    ctx.tables.append("case_event", [event])
    ctx.evidence.record(
        "case_opened",
        f"case:{case_id}",
        {
            **dict(evidence_payload),
            "case_id": case_id,
            "agent_id": agent_id,
            "severity": severity,
            "case_type": case_type,
            "opened_by": actor,
            "ts": format_ts(now),
        },
    )
    ctx.evidence.record(
        "case_event",
        f"case_event:{case_id}:0",
        {
            "case_id": case_id,
            "agent_id": agent_id,
            "seq": 0,
            "action": "opened",
            "actor": actor,
            "actor_kind": "system",
            "ts": format_ts(now),
        },
    )
    return case_id


def raise_severity(
    ctx: MonitorContext, case_id: str, severity: str, *, actor: str, reason: str
) -> bool:
    """Raise an open case to ``severity`` (never lowers). True when the case changed."""
    row = ctx.state.get("cases", {"case_id": case_id})
    if row is None or row["status"] not in OPEN_STATUSES:
        return False
    if SEVERITY_ORDER.index(severity) <= SEVERITY_ORDER.index(row["severity"]):
        return False
    now = ctx.clock.now()
    ctx.state.update("cases", {"case_id": case_id}, {"severity": severity}, row["row_version"])
    events = ctx.tables.query("case_event", {"case_id": case_id}, order_by=["-seq"], limit=1)
    seq = events[0]["seq"] + 1 if events else 0
    ctx.tables.append(
        "case_event",
        [
            CaseEvent(
                case_id=case_id,
                seq=seq,
                ts=now,
                actor=actor,
                actor_kind="system",
                action=f"raise_severity:{severity}",
                comment_masked=reason[:2000],
            )
        ],
    )
    ctx.evidence.record(
        "case_event",
        f"case_event:{case_id}:{seq}",
        {
            "case_id": case_id,
            "agent_id": row["agent_id"],
            "seq": seq,
            "action": f"raise_severity:{severity}",
            "from_severity": row["severity"],
            "actor": actor,
            "actor_kind": "system",
            "ts": format_ts(now),
        },
    )
    return True


__all__ = [
    "MonitorContext",
    "as_dt",
    "find_open_case",
    "floor_window",
    "get_state",
    "median",
    "open_case",
    "percentile",
    "put_state",
    "raise_severity",
    "rate_bp",
    "read_range",
    "scaled_mad",
    "threshold",
    "upsert_metric",
]
