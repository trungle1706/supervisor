"""Tool analytics fixtures: SQLite store, fixed clock, the 90 day synthetic decision set."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from itertools import islice
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import Settings, load_settings
from supervisor.data import tool_usage
from supervisor.jobs import bootstrap_schema
from supervisor.monitors.common import MonitorContext
from tests.judge.conftest import MemoryEvidence

END = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
BATCH = 800


def batches(it: Iterator[Any], n: int = BATCH) -> Iterator[list[Any]]:
    while chunk := list(islice(it, n)):
        yield chunk


def load_events(adapters: Adapters, **gen_kw: Any) -> tuple[list[dict], list[dict]]:
    """Generate and store the synthetic set. Returns (events, verdicts) for brute force."""
    events: list[dict] = []
    verdicts: list[dict] = []
    for chunk in batches(tool_usage.generate(end_day=END, **gen_kw)):
        ev = [e for e, _ in chunk]
        vd = [v for _, v in chunk if v is not None]
        adapters.tables.append("agent_event", ev)
        if vd:
            adapters.tables.append("verdict", vd)
        events += ev
        verdicts += vd
    return events, verdicts


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "perf: performance test (WP22 rollup of 1M decisions)")


@pytest.fixture
def settings() -> Settings:
    return load_settings(tool_analytics_enabled=True, console_tools_enabled=True)


@pytest.fixture
def adapters(settings: Settings) -> Iterator[Adapters]:
    a = build_adapters(settings, clock=FixedClock(NOW))
    bootstrap_schema.run(settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def ctx(adapters: Adapters) -> MonitorContext:
    return MonitorContext.from_adapters(adapters, MemoryEvidence())


@pytest.fixture
def loaded(adapters: Adapters) -> tuple[list[dict], list[dict]]:
    return load_events(adapters)
