from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.evidence.chain import ChainWriter
from supervisor.evidence.signer import _Ed25519Signer
from supervisor.jobs.bootstrap_schema import run as bootstrap_run

T0 = datetime(2026, 10, 14, 2, 0, 0, tzinfo=UTC)
SEED = bytes(range(32))  # fixed test key: deterministic signatures (Ed25519 is deterministic)


def fixed_signer(seed: bytes = SEED) -> _Ed25519Signer:
    return _Ed25519Signer(Ed25519PrivateKey.from_private_bytes(seed), "dev")


@dataclass
class Env:
    adapters: Adapters
    clock: FixedClock
    tmp: Path


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    settings = load_settings(data_dir=tmp_path / "data")
    clock = FixedClock(T0)
    adapters = build_adapters(settings, clock=clock)
    bootstrap_run(settings, adapters)
    yield Env(adapters, clock, tmp_path)
    adapters.close()


def make_writer(env: Env, **kw: object) -> ChainWriter:
    kw.setdefault("writer_id", "test-writer")
    kw.setdefault("root_every_n", 1000)
    kw.setdefault("root_every_s", 10_000)
    return ChainWriter(env.adapters.tables, env.clock, fixed_signer(), **kw)  # type: ignore[arg-type]


def populate(env: Env, n: int = 6, root_every_n: int = 3) -> None:
    """Two agent lanes, a few root commits, closed (sealed)."""
    w = make_writer(env, root_every_n=root_every_n)
    for i in range(n):
        env.clock.advance(1)
        w.record(
            "verdict",
            f"verdict:v{i}",
            {"agent_id": "a1" if i % 2 else "a2", "score_bp": 1000 * i, "label": "nghi_ngo"},
        )
    w.close()
