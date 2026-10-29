"""Governance (WP-G0) fixtures: a temporary SQLite store with the system service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.adapters.factory import Adapters
from supervisor.governance.systems import SystemService
from tests._seed import adapters_from_template


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
def adapters(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Adapters]:
    # WP-T1: a file copy of a store built once per process (tests/_seed.py); ``seeded`` and
    # ``console`` get the copy with the demo replay already run.
    kind = "replayed" if "seeded" in request.fixturenames else "bare"
    a = adapters_from_template(kind, tmp_path / "data")
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
from supervisor.app import app as _app  # noqa: E402
from tests.console.conftest import Console, console, seeded  # noqa: E402, F401  (fixtures)

APP_LIFESPAN = _app.router.lifespan_context  # before any test mounts a router


def restore_app(app: Any, routes: list[Any], lifespan: Any) -> None:
    """Take the mounted routers off the global app again. ``include_router`` also wraps
    ``app.router.lifespan_context`` (one nesting per call), so restoring only the routes leaves a
    deeper chain after every test; after a few hundred tests the app start-up recurses."""
    app.router.routes[:] = routes
    app.router.lifespan_context = lifespan
    app.openapi_schema = None


@pytest.fixture
def mounted() -> Iterator[None]:
    """Mount the governance routers on the global app (as app.py does with the flags on) and
    take them off again. The app reads the flags once at import, so a test cannot flip them."""
    from supervisor.app import app
    from supervisor.console.classify_routes import api_router as classify_api  # WP-C1
    from supervisor.console.classify_routes import router as classify_console  # WP-C1
    from supervisor.console.smart_guardian_routes import console_router as sg_console  # WP-G4
    from supervisor.console.systems_routes import router as console_router
    from supervisor.governance.guardian_routes import console_router as guardians_console  # WP-S1
    from supervisor.governance.guardian_routes import router as guardians_router  # WP-S1
    from supervisor.governance.orchestrator_routes import router as orchestrator_router  # WP-F4
    from supervisor.governance.risk_dimension_routes import router as risk_dim_router  # WP-C2
    from supervisor.governance.routes import router as api_router
    from supervisor.governance.rules_routes import router as rules_router  # WP-G2
    from supervisor.governance.smart_guardian_routes import router as sg_router  # WP-G4

    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(api_router)
    app.include_router(rules_router)
    app.include_router(guardians_router)  # WP-S1 (the handlers answer 400 while the flag is off)
    app.include_router(guardians_console)
    app.include_router(console_router)
    app.include_router(risk_dim_router)  # WP-C2 (400 while RISK_DIMENSIONS is off)
    app.include_router(classify_console)  # WP-C1 (400 while CLASSIFICATION_V2 is off)
    app.include_router(classify_api)
    app.include_router(orchestrator_router)  # WP-F4 (400 while ONBOARD_ORCHESTRATOR is off)
    app.include_router(sg_router)  # WP-G4 (400 while SMART_GUARDIAN is off)
    app.include_router(sg_console)
    try:
        yield
    finally:
        restore_app(app, saved, lifespan)


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
    a = adapters_from_template("bare", tmp_path / "gdata", governance_enabled=True)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def gsvc(gadapters: Adapters, sink: ListSink) -> SystemService:
    return SystemService.from_adapters(gadapters, evidence=sink)


# WP-G5 fixtures (a store on a fixed clock, a rig of services): tests/governance/g5_support.py
from .g5_support import clock, rig, store  # noqa: E402, F401
