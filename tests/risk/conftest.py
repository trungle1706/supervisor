"""Risk register test fixtures: SQLite store with the inventory filled, a service, seed helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.config import load_settings
from supervisor.inventory.service import InventoryService
from supervisor.jobs import bootstrap_schema
from supervisor.risk.harness import _Env
from supervisor.risk.service import RiskService
from tests.conftest import REPO_ROOT

FIX = REPO_ROOT / "tests" / "fixtures" / "risk"
STARTERS = REPO_ROOT / "config" / "risks"
WORKSPACE_7 = REPO_ROOT / "tests" / "fixtures" / "inventory" / "workspace_7.json"


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
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        inventory_enabled=True,
        risk_register_enabled=True,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def inventory(adapters: Adapters) -> InventoryService:
    svc = InventoryService.from_adapters(adapters)
    svc.fill_manifests()
    return svc


@pytest.fixture
def svc(adapters: Adapters, inventory: InventoryService, sink: ListSink) -> RiskService:
    return RiskService.from_adapters(adapters, evidence=sink)


@pytest.fixture
def with_workspace(
    adapters: Adapters, inventory: InventoryService, tmp_path: Path
) -> InventoryService:
    allow = tmp_path / "allow.yaml"
    allow.write_text("apps:\n  - bi-portal\n", encoding="utf-8")
    adapters.settings.inventory_allowlist_file = allow
    inventory.refresh_workspace(FixtureWorkspaceReader.from_file(WORKSPACE_7))
    return inventory


@pytest.fixture
def env() -> Iterator[_Env]:
    e = _Env()
    try:
        yield e
    finally:
        e.close()


def risk_data(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Test risk",
        "category": "money_movement",
        "agent_id": "payments",
        "inherent_likelihood": 4,
        "inherent_impact": 5,
        "residual_likelihood": 2,
        "residual_impact": 5,
        "treatment": "mitigate",
        "owner": "Payments Ops",
        "review_date": "2027-04-20",
        "status": "active",
    }
    return base | kw


def hours_ago(adapters: Adapters, hours: int) -> dt.datetime:
    return adapters.clock.now() - dt.timedelta(hours=hours)
