"""Fixtures of the factory tests. The console fixtures come from tests/console (the export route
runs on the real app)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.console.conftest import adapters, console, inbox, seeded, sink, svc, users  # noqa: F401

DATA = Path(__file__).parent / "data"


def load(name: str) -> dict[str, Any]:
    doc = yaml.safe_load((DATA / name).read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


@pytest.fixture
def agent() -> dict[str, Any]:
    return copy.deepcopy(load("agent_single_pass.yaml"))


@pytest.fixture
def loop_agent() -> dict[str, Any]:
    return copy.deepcopy(load("agent_loop_memory.yaml"))


@pytest.fixture
def report() -> dict[str, Any]:
    return copy.deepcopy(load("report_valid.yaml"))
