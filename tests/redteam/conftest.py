"""Fixtures of the multi-turn red team tests: three sandbox demo agents shared by the module."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from supervisor.assurance.targets import DemoAgentTarget
from supervisor.redteam.multiturn.catalogue import load_objectives
from supervisor.redteam.multiturn.model import AGENTS, Objective
from tests.gateway.conftest import adapters, baseline, clock, evidence, gateway  # noqa: F401


@pytest.fixture(scope="session")
def sandbox(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    base: Path = tmp_path_factory.mktemp("mt_redteam")
    targets = {a: DemoAgentTarget(a, base) for a in AGENTS}
    try:
        yield targets
    finally:
        for t in targets.values():
            t.close()


@pytest.fixture(scope="session")
def objectives() -> list[Objective]:
    return load_objectives()


def pick(objs: list[Objective], family: str, kind: str, lang: str = "vi") -> Objective:
    return next(o for o in objs if o.family == family and o.kind == kind and o.lang == lang)
