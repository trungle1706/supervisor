"""Behaviour every SqlExecutor + store must share (sqlite always, Databricks opt-in)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.core.errors import (
    AppendOnlyError,
    ConcurrencyError,
    DuplicateKeyError,
    NotFoundError,
    SqlError,
)
from supervisor.core.models import Agent, AgentEvent, Case, OversightMetric
from supervisor.jobs import bootstrap_schema

from .conftest import T0


def _event(i: int, **kw: object) -> AgentEvent:
    base: dict[str, object] = dict(
        event_id=f"e{i:04d}",
        ts=T0 + timedelta(seconds=i),
        trace_id="t1",
        span_id=f"s{i}",
        agent_id="payments",
        event_type="tool_call",
        tool_name="transfer",
        args_masked="Chuyển tiền cho Nguyễn Văn *** (CCCD ***)",
        amount_minor=9_000_000_000_000 + i,
        currency="VND",
        latency_ms=12,
        env="test",
        source="otel",
    )
    base.update(kw)
    return AgentEvent(**base)  # type: ignore[arg-type]


def _agent(agent_id: str = "payments") -> Agent:
    return Agent(
        agent_id=agent_id,
        name="Payments agent",
        owner_team="retail",
        owner_user="owner@example.invalid",
        risk_tier="high",
        host_type="databricks_app",
        plug_point="supervised_tool",
        model_family="qwen",
        created_at=T0,
    )


def test_bootstrap_is_idempotent(adapters: Adapters) -> None:
    bootstrap_schema.run(adapters.settings, adapters)
    rows = adapters.state.query("schema_version")
    assert [r["version"] for r in rows] == [adapters.model.version]
    assert rows[0]["model_hash"] == adapters.model.source_hash


def test_append_and_query_round_trip_types(adapters: Adapters) -> None:
    events = [_event(i) for i in range(3)] + [_event(3, amount_minor=None, currency=None)]
    assert adapters.tables.append("agent_event", events) == 4
    rows = adapters.tables.query("agent_event", {"agent_id": "payments"}, order_by=["ts"])
    assert [r["event_id"] for r in rows] == ["e0000", "e0001", "e0002", "e0003"]
    first = rows[0]
    assert first["ts"] == T0 and first["ts"].tzinfo is not None
    assert first["amount_minor"] == 9_000_000_000_000 and isinstance(first["amount_minor"], int)
    assert first["args_masked"].startswith("Chuyển tiền")
    assert first["latency_ms"] == 12
    assert rows[3]["amount_minor"] is None
    assert AgentEvent.model_validate(first) == events[0]


def test_query_filters_order_limit(adapters: Adapters) -> None:
    adapters.tables.append("agent_event", [_event(i) for i in range(5)])
    rows = adapters.tables.query("agent_event", order_by=["-ts"], limit=2)
    assert [r["event_id"] for r in rows] == ["e0004", "e0003"]
    assert adapters.tables.query("agent_event", {"event_id": "e0002"})[0]["span_id"] == "s2"
    assert adapters.tables.query("agent_event", {"parent_span_id": None}, limit=1)
    assert (
        adapters.tables.query("agent_event", {"ts": T0 + timedelta(seconds=1)})[0]["event_id"]
        == "e0001"
    )


def test_append_batches_many_rows(adapters: Adapters) -> None:
    n = 120
    assert adapters.tables.append("agent_event", [_event(i) for i in range(n)]) == n
    got = adapters.executor.query(
        f"SELECT COUNT(*) AS n FROM {adapters.executor.qualify('agent_event')}",
        column_types={"n": "int"},
    )
    assert got == [{"n": n}]


def test_append_only_tables_reject_update_and_delete(adapters: Adapters) -> None:
    adapters.tables.append("agent_event", [_event(1)])
    t = adapters.executor.qualify("agent_event")
    with pytest.raises(AppendOnlyError):
        adapters.executor.execute(f"UPDATE {t} SET env = 'x' WHERE event_id = 'e0001'")
    with pytest.raises(AppendOnlyError):
        adapters.executor.execute(f"DELETE FROM {t} WHERE event_id = 'e0001'")
    assert adapters.tables.query("agent_event")[0]["env"] == "test"


def test_stores_refuse_wrong_table_kind(adapters: Adapters) -> None:
    with pytest.raises(AppendOnlyError):
        adapters.tables.append("agent", [_agent()])
    with pytest.raises(AppendOnlyError):
        adapters.state.insert("agent_event", _event(1))


def test_unknown_column_and_missing_required(adapters: Adapters) -> None:
    with pytest.raises(SqlError):
        adapters.tables.append("agent_event", [{**_event(1).row(), "bogus": 1}])
    with pytest.raises(SqlError):
        adapters.tables.append("agent_event", [{**_event(1).row(), "trace_id": None}])
    with pytest.raises(SqlError):
        adapters.tables.query("agent_event", {"bogus; DROP TABLE agent": 1})


def test_state_insert_get_update(adapters: Adapters) -> None:
    row = adapters.state.insert("agent", _agent())
    assert row["row_version"] == 1
    got = adapters.state.get("agent", {"agent_id": "payments"})
    assert got is not None and got["row_version"] == 1 and got["updated_at"] == T0
    assert Agent.model_validate(got).gate_state == "SHADOW"
    upd = adapters.state.update("agent", {"agent_id": "payments"}, {"gate_state": "PAUSED"}, 1)
    assert upd["gate_state"] == "PAUSED" and upd["row_version"] == 2


def test_state_duplicate_insert(adapters: Adapters) -> None:
    adapters.state.insert("agent", _agent())
    with pytest.raises(DuplicateKeyError):
        adapters.state.insert("agent", _agent())


def test_state_optimistic_concurrency(adapters: Adapters) -> None:
    adapters.state.insert("agent", _agent())
    key = {"agent_id": "payments"}
    adapters.state.update("agent", key, {"gate_state": "PAUSED"}, expected_version=1)
    with pytest.raises(ConcurrencyError):
        adapters.state.update("agent", key, {"gate_state": "RUNNING"}, expected_version=1)
    current = adapters.state.get("agent", key)
    assert current is not None and current["gate_state"] == "PAUSED"
    with pytest.raises(NotFoundError):
        adapters.state.update("agent", {"agent_id": "nope"}, {"gate_state": "PAUSED"}, 1)


def test_state_upsert_json_date_bool(adapters: Adapters) -> None:
    case = Case(
        case_id="c1",
        agent_id="payments",
        severity="high",
        opened_at=T0,
        regulation_refs=["SBV-09/2020", "QD-33"],
        summary="Chuyển khoản vượt hạn mức",
        report_due_at=T0 + timedelta(hours=24),
    )
    first = adapters.state.upsert("cases", case, expected_version=None)
    second = adapters.state.upsert(
        "cases", {**first, "status": "triage"}, expected_version=first["row_version"]
    )
    assert second["status"] == "triage" and second["regulation_refs"] == ["SBV-09/2020", "QD-33"]
    m = OversightMetric(
        metric_date=date(2026, 10, 14),
        agent_id="payments",
        coverage=0.97,
        chain_ok=True,
        computed_at=datetime(2026, 10, 15, tzinfo=UTC),
    )
    saved = adapters.state.insert("oversight_metric", m)
    got = adapters.state.get(
        "oversight_metric", {"metric_date": date(2026, 10, 14), "agent_id": "payments"}
    )
    assert got is not None and got["metric_date"] == date(2026, 10, 14)
    assert got["chain_ok"] is True and got["coverage"] == pytest.approx(0.97)
    assert saved["row_version"] == 1


def test_state_update_cannot_touch_key_or_version(adapters: Adapters) -> None:
    adapters.state.insert("agent", _agent())
    for bad in ({"agent_id": "x"}, {"row_version": 9}, {"updated_at": T0}):
        with pytest.raises(SqlError):
            adapters.state.update("agent", {"agent_id": "payments"}, bad, 1)
