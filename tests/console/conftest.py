from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.adapters.auth.dev_header import DevHeaderPrincipal
from supervisor.adapters.factory import Adapters, make_masker
from supervisor.adapters.notify import InboxNotifier
from supervisor.cases.service import CaseService
from supervisor.config import REPO_ROOT
from tests._seed import adapters_from_template


class ListSink:
    """In-memory EvidenceSink (tests)."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        self.records.append((record_type, record_ref, dict(payload)))
        return hashlib.sha256(json.dumps([record_type, record_ref]).encode()).hexdigest()

    def of(self, record_type: str) -> list[dict[str, Any]]:
        return [p for t, _, p in self.records if t == record_type]


@pytest.fixture
def adapters(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Adapters]:
    # WP-T1: a file copy of a store built once per process. A test that asks for ``seeded`` (or
    # ``console``) gets the copy of the store with the demo replay already run.
    kind = "replayed" if "seeded" in request.fixturenames else "bare"
    a = adapters_from_template(kind, tmp_path / "data")
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def users() -> dict[str, AuthPrincipal]:
    return DevHeaderPrincipal.from_file(REPO_ROOT / "config" / "users.yaml").users


@pytest.fixture
def sink() -> ListSink:
    return ListSink()


@pytest.fixture
def inbox(adapters: Adapters) -> InboxNotifier:
    return InboxNotifier(adapters.state, adapters.clock)


@pytest.fixture
def svc(adapters: Adapters, sink: ListSink, inbox: InboxNotifier) -> CaseService:
    return CaseService(
        adapters.state,
        adapters.tables,
        sink,
        adapters.clock,
        masker=make_masker(adapters.settings),
        notifier=inbox,
    )


# --------------------------------------------------------------------------- seeded console


class Console:
    """TestClient on the real app with the console context on a seeded runtime."""

    def __init__(self, client: Any, runtime: Any, ctx: Any) -> None:
        self.client = client
        self.runtime = runtime
        self.ctx = ctx

    def get(self, url: str, user: str | None = "reviewer.an", **kw: Any) -> Any:
        headers = dict(kw.pop("headers", {}) or {})
        if user:
            headers["X-Dev-User"] = user
        return self.client.get(url, headers=headers, **kw)

    def post(
        self,
        url: str,
        data: Mapping[str, Any] | None = None,
        user: str = "reviewer.an",
        htmx: bool = True,
        **kw: Any,
    ) -> Any:
        headers = dict(kw.pop("headers", {}) or {})
        headers["X-Dev-User"] = user
        if htmx:
            headers["HX-Request"] = "true"
        return self.client.post(url, data=dict(data or {}), headers=headers, **kw)


@pytest.fixture
def seeded(adapters: Adapters) -> Iterator[Any]:
    """Demo replay behind the real gateway (four incidents), then a fresh runtime on the
    same store for the console (as after an app restart)."""
    # the replay already ran in the template that ``adapters`` copied (tests/_seed.py)
    from supervisor.wiring import build_runtime

    runtime = build_runtime(adapters.settings, adapters=adapters, policy_refresh_s=0.0)
    try:
        yield runtime
    finally:
        runtime.close()


@pytest.fixture
def console(seeded: Any) -> Iterator[Console]:
    from fastapi.testclient import TestClient

    from supervisor.adapters.auth import set_provider
    from supervisor.app import app
    from supervisor.console.context import build_context, set_context
    from supervisor.gateway import wiring as gate_wiring

    ctx = build_context(seeded)
    set_context(ctx)
    gate_wiring.set_gateway(seeded.gateway)
    try:
        yield Console(TestClient(app, raise_server_exceptions=False), seeded, ctx)
    finally:
        set_context(None)
        gate_wiring.set_gateway(None)
        set_provider(None)


def add_gate_block(adapters: Any, agent: str = "payments", rule: str = "PAY-99") -> str:
    """A tier-0 block verdict that no case covers yet (what the next intake picks up)."""
    import uuid

    event_id = uuid.uuid4().hex
    adapters.tables.append(
        "verdict",
        [
            {
                "verdict_id": uuid.uuid4().hex,
                "ts": adapters.clock.now(),
                "trace_id": "t-" + event_id[:8],
                "event_id": event_id,
                "agent_id": agent,
                "tier": 0,
                "checker_id": "gate.tier0a",
                "is_mock": False,
                "advisory": False,
                "label": "matched",
                "action": "block",
                "rule_id": rule,
                "rationale_masked": f"rule {rule} matched",
            }
        ],
    )
    return event_id


from .wp39_fixtures import v2adapters, v2console  # noqa: E402, F401  (WP39 fixtures)
