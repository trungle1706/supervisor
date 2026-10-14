from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.adapters.auth.dev_header import DevHeaderPrincipal
from supervisor.adapters.factory import Adapters, build_adapters, make_masker
from supervisor.adapters.notify import InboxNotifier
from supervisor.cases.service import CaseService
from supervisor.config import REPO_ROOT, load_settings
from supervisor.jobs import bootstrap_schema


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
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data", llm_base_url="")
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
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
