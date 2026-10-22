"""WP-S1 fixtures: a store with GOVERNANCE_ENABLED and GUARDIAN_BINDINGS_ENABLED on."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.governance.guardians import GuardianNarrower, GuardianService
from supervisor.governance.systems import SystemService
from supervisor.jobs import bootstrap_schema

from .conftest import ListSink, add_agent, draft

OWNER = "owner.lan"
PLAIN: dict[str, Any] = {"personal_data": "none"}  # no guardian floor
CUSTOMER: dict[str, Any] = {"user_segment": "customer", "personal_data": "identifiable"}  # dlp_vn
MONEY: dict[str, Any] = {**CUSTOMER, "money_movement": True}  # dlp_vn + injection_regex


@pytest.fixture
def sadapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "sdata",
        llm_base_url="",
        governance_enabled=True,
        guardian_bindings_enabled=True,
        detectors_enabled=True,
        session_monitor_enabled=True,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def ssvc(sadapters: Adapters, sink: ListSink) -> SystemService:
    return SystemService.from_adapters(sadapters, evidence=sink)


@pytest.fixture
def guard(sadapters: Adapters, sink: ListSink) -> GuardianService:
    return GuardianService.from_adapters(sadapters, evidence=sink)


@pytest.fixture
def narrow(sadapters: Adapters) -> GuardianNarrower:
    return GuardianNarrower(sadapters.state, sadapters.settings, ttl_s=0)


def make_system(ssvc: SystemService, agents: tuple[str, ...] = (), **over: Any) -> str:
    sid = str(ssvc.register(draft(**{**PLAIN, **over}), OWNER)["system_id"])
    for agent in agents:
        if not any(str(a["agent_id"]) == agent for a in ssvc.state.query("agent")):
            add_agent(SimpleNamespace(state=ssvc.state, clock=ssvc.clock), agent)  # type: ignore[arg-type]
        ssvc.link(sid, "agent", agent, OWNER)
    return sid
