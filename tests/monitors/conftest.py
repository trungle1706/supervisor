"""Monitor fixtures: SQLite store on a temp path, fixed clock, in-memory evidence sink."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from tests.judge.conftest import MemoryEvidence

# Monday 00:00 UTC: windows are whole days from here.
T0 = datetime(2026, 9, 7, 0, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def adapters(clock: FixedClock) -> Iterator[Adapters]:
    settings = load_settings()
    a = build_adapters(settings, clock=clock)
    bootstrap_schema.run(settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def evidence() -> MemoryEvidence:
    return MemoryEvidence()
