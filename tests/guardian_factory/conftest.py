# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""Guardian factory (WP-G1) fixtures: a temporary SQLite store with the flag on, a list sink for
the chain, a fake ChatModel, and the real app console."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.guardian_factory.store import GuardianDefStore
from supervisor.jobs import bootstrap_schema
from tests.console.conftest import Console, adapters, console, seeded  # noqa: F401  (fixtures)


class ListSink:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        self.records.append((record_type, record_ref, dict(payload)))
        return hashlib.sha256(json.dumps([record_type, record_ref]).encode()).hexdigest()

    def of(self, record_type: str) -> list[dict[str, Any]]:
        return [p for t, _, p in self.records if t == record_type]


class FakeChat:
    """A fake ChatModel for tests only: answers what it was given."""

    family = "fake"
    model_id = "fake-model"
    is_mock = False

    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[list[Mapping[str, str]]] = []

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float,
    ) -> Mapping[str, Any]:
        self.calls.append(list(messages))
        if self.error:
            raise self.error
        return self.answer


def person(user_id: str, *roles: str) -> AuthPrincipal:
    return AuthPrincipal(user_id, "user", "dev_header", frozenset(roles), user_id)


def regex_def(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "account-numbers",
        "name": "Account numbers",
        "description": "Masks bank account numbers.",
        "owner_group": "data",
        "type": "regex",
        "stage": "input",
        "scope": {"agents": "*", "tools": "*", "data_classes": []},
        "action_on_fail": "redact",
        "sensitivity": 2,
        "config": {"pattern": r"(?<!\d)\d{9,14}(?!\d)", "mask_token": "<ACCOUNT>"},
    }
    return {**base, **over}


@pytest.fixture
def sink() -> ListSink:
    return ListSink()


@pytest.fixture
def gadapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        guardian_factory=True,
        detectors_enabled=True,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def store(gadapters: Adapters, sink: ListSink) -> GuardianDefStore:
    return GuardianDefStore(
        gadapters.state, gadapters.tables, gadapters.clock, gadapters.settings, evidence=sink
    )


@pytest.fixture
def gf(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:  # noqa: F811
    """The real app console with the flag and DETECTORS_ENABLED on."""
    monkeypatch.setattr(console.ctx.settings, "guardian_factory", True)
    monkeypatch.setattr(console.ctx.settings, "detectors_enabled", True)
    return console
