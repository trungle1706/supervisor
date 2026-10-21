"""Detector tests reuse the gateway fixtures (SQLite adapters, fixed clock, memory evidence)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.core.detectors import DetectorRegistry
from supervisor.detectors import build_registry
from supervisor.detectors.config import ResolvedDetectors, load_config, parse_config
from supervisor.gateway.detector_gate import DetectorGate
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import (
    Policy,
    StorePolicyProvider,
    deploy_policy,
)
from tests.conftest import REPO_ROOT
from tests.gateway import conftest as _gw

# The gateway fixtures, shared as they are (SQLite adapters, fixed clock, memory evidence).
MemoryEvidence = _gw.MemoryEvidence
adapters = _gw.adapters
baseline = _gw.baseline
clock = _gw.clock
evidence = _gw.evidence
gateway = _gw.gateway

CONFIG = REPO_ROOT / "config" / "detectors.yaml"


@pytest.fixture
def masker() -> VnRegexMasker:
    return VnRegexMasker(b"test-key", "t")


def make_gate(
    masker: VnRegexMasker,
    *,
    extra: list[Any] | None = None,
    config_text: str | None = None,
    registry: DetectorRegistry | None = None,
) -> DetectorGate:
    """Detector gate on the committed config (or ``config_text``), plus extra detectors."""
    reg = registry or build_registry(masker)
    for det in extra or []:
        reg.register(det)
    cfg = parse_config(config_text, "test") if config_text else load_config(CONFIG)
    return DetectorGate(reg, ResolvedDetectors(cfg, reg))


GatewayFactory = Callable[..., Gateway]


@pytest.fixture
def make_gateway(
    adapters: Any,
    evidence: MemoryEvidence,
    baseline: Policy,
    masker: VnRegexMasker,
) -> Iterator[GatewayFactory]:
    """Factory: a gateway with detectors on. ``policy`` replaces the baseline; ``gate`` the
    detector gate; other keywords go to ``Gateway``."""
    made: list[Gateway] = []

    def factory(
        *, policy: Policy | None = None, gate: DetectorGate | None = None, **kw: Any
    ) -> Gateway:
        deploy_policy(policy or baseline, adapters.state, adapters.clock)
        gw = Gateway(
            StorePolicyProvider(adapters.state, refresh_s=0),
            adapters.tables,
            adapters.state,
            evidence,
            adapters.clock,
            state_cache_ttl_s=0,
            detector_gate=gate or make_gate(masker),
            **kw,
        )
        made.append(gw)
        return gw

    yield factory
    for gw in made:
        gw.close()


@pytest.fixture
def gw_on(make_gateway: GatewayFactory) -> Gateway:
    return make_gateway()
