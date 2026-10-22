"""Governance (WP-G0) fixtures: a temporary SQLite store with the system service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.governance.systems import SystemService
from supervisor.jobs import bootstrap_schema


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


DRAFT: dict[str, Any] = {
    "name": "Payments - Assistant",
    "owner_user": "owner.lan",
    "owner_team": "payments-team",
    "purpose": "Answers staff questions about domestic transfers.",
    "system_type": "assistant",
    "org_role": "deployer",
    "user_segment": "internal",
    "personal_data": "pseudonymised",
    "human_control": "post_review",
    "autonomy_level": "l1_assistive",  # WP-G2: apply of a classification needs a level
}


def draft(**over: Any) -> dict[str, Any]:
    return {**DRAFT, **over}


def person(user_id: str, *roles: str) -> AuthPrincipal:
    return AuthPrincipal(user_id, "user", "dev_header", frozenset(roles), user_id)


@pytest.fixture
def sink() -> ListSink:
    return ListSink()


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data", llm_base_url="")
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def svc(adapters: Adapters, sink: ListSink) -> SystemService:
    return SystemService.from_adapters(adapters, evidence=sink)


def add_agent(adapters: Adapters, agent_id: str, team: str = "payments-team", **over: Any) -> None:
    row = {
        "agent_id": agent_id,
        "name": agent_id,
        "owner_team": team,
        "owner_user": "owner.lan",
        "business_owner": None,
        "risk_tier": "low",
        "decision33_class": None,
        "host_type": "app",
        "plug_point": "gate",
        "model_family": "qwen",
        "status": "active",
        "gate_state": "ACTIVE",
        "created_at": adapters.clock.now(),
    }
    adapters.state.insert("agent", {**row, **over})


# --------------------------------------------------------------------------- the real app
from tests.console.conftest import Console, console, seeded  # noqa: E402, F401  (fixtures)


@pytest.fixture
def mounted() -> Iterator[None]:
    """Mount the governance routers on the global app (as app.py does with the flags on) and
    take them off again. The app reads the flags once at import, so a test cannot flip them."""
    from supervisor.app import app
    from supervisor.console.systems_routes import router as console_router
    from supervisor.governance.routes import router as api_router
    from supervisor.governance.rules_routes import router as rules_router  # WP-G2

    saved = list(app.router.routes)
    app.include_router(api_router)
    app.include_router(rules_router)
    app.include_router(console_router)
    try:
        yield
    finally:
        app.router.routes[:] = saved
        app.openapi_schema = None


@pytest.fixture
def on(
    console: Console,  # noqa: F811
    mounted: None,
    monkeypatch: pytest.MonkeyPatch,
) -> Console:
    for flag in ("governance_enabled", "console_systems_enabled"):
        monkeypatch.setattr(console.ctx.settings, flag, True)
    return console


# --------------------------------------------------------------------------- WP-G2: flag on
@pytest.fixture
def gadapters(tmp_path: Path) -> Iterator[Adapters]:
    """A temporary SQLite store with GOVERNANCE_ENABLED on (the rules run after each change)."""
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "gdata",
        llm_base_url="",
        governance_enabled=True,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def gsvc(gadapters: Adapters, sink: ListSink) -> SystemService:
    return SystemService.from_adapters(gadapters, evidence=sink)
