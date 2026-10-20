"""Control catalogue and task list test fixtures: a temporary SQLite store with the services."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from supervisor.controls.harness_env import CtlEnv


class ListSink:
    """In-memory EvidenceSink."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        self.records.append((record_type, record_ref, dict(payload)))
        return hashlib.sha256(
            json.dumps([record_type, record_ref, len(self.records)]).encode()
        ).hexdigest()

    def of(self, record_type: str) -> list[dict[str, Any]]:
        return [p for t, _, p in self.records if t == record_type]


@pytest.fixture
def sink() -> ListSink:
    return ListSink()


@pytest.fixture
def env(sink: ListSink) -> Iterator[CtlEnv]:
    e = CtlEnv(sink=sink)
    try:
        yield e
    finally:
        e.close()
