"""Transparency report fixtures: a store with the three demo agents, their inventory, the starter
risks and a real chain writer (the harness environment), one per test module scope."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from supervisor.transparency.harness import Env


@pytest.fixture
def env() -> Iterator[Env]:
    e = Env()
    try:
        yield e
    finally:
        e.close()
