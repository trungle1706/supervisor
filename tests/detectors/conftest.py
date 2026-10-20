"""Detector tests reuse the gateway fixtures (SQLite adapters, fixed clock, memory evidence)."""

from __future__ import annotations

from tests.gateway.conftest import (  # noqa: F401
    MemoryEvidence,
    adapters,
    baseline,
    clock,
    evidence,
    gateway,
)
