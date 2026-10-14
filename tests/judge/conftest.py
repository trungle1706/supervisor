"""Judge fixtures: in-memory evidence sink and table store, fixed clock, sample events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.core.canonical import canonical_json, sha256_hex
from supervisor.core.models import AgentEvent

T0 = datetime(2026, 10, 14, 2, 0, 0, tzinfo=UTC)


def assert_no_floats(value: Any, path: str = "$") -> None:
    assert not isinstance(value, float), f"float in chain payload at {path}"
    if isinstance(value, Mapping):
        for k, v in value.items():
            assert_no_floats(v, f"{path}.{k}")
    elif isinstance(value, list | tuple):
        for i, v in enumerate(value):
            assert_no_floats(v, f"{path}[{i}]")


class MemoryEvidence:
    """EvidenceSink for tests. Canonicalises every payload and rejects any float."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        canonical_json(payload)
        assert_no_floats(payload)
        self.entries.append((record_type, record_ref, dict(payload)))
        return sha256_hex({"t": record_type, "r": record_ref, "p": payload})

    def of_type(self, record_type: str) -> list[dict[str, Any]]:
        return [p for t, _, p in self.entries if t == record_type]


class MemoryTables:
    """TableStore for tests (append + query by equality)."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def append(self, table: str, rows: Any) -> int:
        n = 0
        for r in rows:
            row = r.row() if hasattr(r, "row") else dict(r)
            self.tables.setdefault(table, []).append(row)
            n += 1
        return n

    def query(
        self,
        table: str,
        where: Mapping[str, Any] | None = None,
        order_by: Sequence[str] = (),
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = [
            r
            for r in self.tables.get(table, [])
            if all(r.get(k) == v for k, v in (where or {}).items())
        ]
        return rows[:limit] if limit else rows


def make_events(
    texts: Sequence[str],
    *,
    agent_id: str = "payments",
    trace_id: str = "tr-1",
    start: datetime = T0,
    tool: str | None = "transfer",
) -> list[AgentEvent]:
    out = []
    for i, text in enumerate(texts):
        out.append(
            AgentEvent(
                event_id=f"{trace_id}-ev{i}",
                ts=start + timedelta(seconds=i),
                trace_id=trace_id,
                span_id=f"sp{i}",
                agent_id=agent_id,
                agent_version="1.0.0",
                event_type="tool_call" if tool else "message",
                tool_name=tool,
                args_masked=text,
                env="dev",
                source="otel",
            )
        )
    return out


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def evidence() -> MemoryEvidence:
    return MemoryEvidence()


@pytest.fixture
def tables() -> MemoryTables:
    return MemoryTables()
