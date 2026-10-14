"""Gateway fixtures: SQLite adapters, fixed clock, in-memory evidence sink."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.core.canonical import canonical_json, sha256_hex
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import Policy, StorePolicyProvider, deploy_policy, load_policy_dir
from supervisor.jobs import bootstrap_schema
from tests.conftest import REPO_ROOT

T0 = datetime(2026, 10, 14, 2, 0, 0, tzinfo=UTC)
POLICY_DIR = REPO_ROOT / "policies"


class MemoryEvidence:
    """EvidenceSink for tests. Canonicalises every payload and rejects any float."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        canonical_json(payload)
        assert_no_floats(payload)
        self.entries.append((record_type, record_ref, dict(payload)))
        return sha256_hex({"t": record_type, "r": record_ref, "p": payload})

    def of_type(self, record_type: str) -> list[dict[str, Any]]:
        return [p for t, _, p in self.entries if t == record_type]


def assert_no_floats(value: Any, path: str = "$") -> None:
    assert not isinstance(value, float), f"float in chain payload at {path}"
    if isinstance(value, Mapping):
        for k, v in value.items():
            assert_no_floats(v, f"{path}.{k}")
    elif isinstance(value, list | tuple):
        for i, v in enumerate(value):
            assert_no_floats(v, f"{path}[{i}]")


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def adapters(tmp_path: Path, clock: FixedClock) -> Iterator[Adapters]:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    a = build_adapters(settings, clock=clock)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def evidence() -> MemoryEvidence:
    return MemoryEvidence()


@pytest.fixture(scope="session")
def baseline() -> Policy:
    return load_policy_dir(POLICY_DIR)


@pytest.fixture
def gateway(adapters: Adapters, evidence: MemoryEvidence, baseline: Policy) -> Iterator[Gateway]:
    """Gateway on the baseline policy, deployed to the rule table and read back from it."""
    deploy_policy(baseline, adapters.state, adapters.clock)
    gw = Gateway(
        StorePolicyProvider(adapters.state, refresh_s=0),
        adapters.tables,
        adapters.state,
        evidence,
        adapters.clock,
        state_cache_ttl_s=0,
    )
    try:
        yield gw
    finally:
        gw.close()
