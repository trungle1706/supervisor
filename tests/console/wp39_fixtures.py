"""WP39 fixtures: a console over a gate that writes verdict v2 rows (DETECTORS_ENABLED=1).
The data comes from ``supervisor.demo.activity_seed`` (synthetic only)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.demo import activity_seed
from supervisor.demo.activity_seed import CORR, PLANTED, PLANTED_ARGS

from .conftest import Console


@pytest.fixture
def v2adapters(tmp_path: Path) -> Iterator[Path]:
    """Kept for the fixture name; the store itself is built by ``activity_seed.kit``."""
    yield tmp_path / "data"


@pytest.fixture
def v2console(v2adapters: Path) -> Iterator[Console]:
    with activity_seed.kit(v2adapters, detectors=True, v2=True) as k:
        yield Console(k.client, k.runtime, k.ctx)


def plant(console: Console) -> dict[str, str]:
    return activity_seed.plant_calls(console.runtime, console.ctx)


__all__ = ["CORR", "PLANTED", "PLANTED_ARGS", "Adapters", "plant", "v2adapters", "v2console"]
