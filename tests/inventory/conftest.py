"""Inventory test fixtures: SQLite store, case service, the 7-item workspace fixture."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters, make_masker
from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.cases.service import CaseService
from supervisor.config import load_settings
from supervisor.inventory.service import InventoryService
from supervisor.jobs import bootstrap_schema
from tests.conftest import REPO_ROOT

FIX = REPO_ROOT / "tests" / "fixtures" / "inventory"
WORKSPACE_7 = FIX / "workspace_7.json"


class ListSink:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        self.records.append((record_type, record_ref, dict(payload)))
        return hashlib.sha256(json.dumps([record_type, record_ref]).encode()).hexdigest()


@pytest.fixture
def allowlist_file(tmp_path: Path) -> Path:
    p = tmp_path / "allow.yaml"
    p.write_text("apps:\n  - bi-portal\nserving_endpoints:\n  - never-*\n", encoding="utf-8")
    return p


@pytest.fixture
def adapters(tmp_path: Path, allowlist_file: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        inventory_enabled=True,
        inventory_allowlist_file=allowlist_file,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def svc(adapters: Adapters) -> InventoryService:
    return InventoryService.from_adapters(adapters)


@pytest.fixture
def sink() -> ListSink:
    return ListSink()


@pytest.fixture
def cases(adapters: Adapters, sink: ListSink) -> CaseService:
    return CaseService(
        adapters.state,
        adapters.tables,
        sink,
        adapters.clock,
        masker=make_masker(adapters.settings),
    )


@pytest.fixture
def reader() -> FixtureWorkspaceReader:
    return FixtureWorkspaceReader.from_file(WORKSPACE_7)
