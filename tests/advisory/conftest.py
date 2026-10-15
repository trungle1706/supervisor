"""Advisory fixtures: one advice per corpus repo and per demo agent (computed once)."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor.adapters.llm.mock import MockChat
from supervisor.advisory.integration.advise import Advice, advise
from tests.conftest import REPO_ROOT

CORPUS = REPO_ROOT / "data" / "corpus"
REPOS = sorted(p.name for p in (CORPUS / "repos").iterdir() if p.is_dir())
DEMO = ("payments", "customer_service", "credit_prequal")


def target_of(name: str) -> Path:
    if name in DEMO:
        return REPO_ROOT / "src" / "supervisor_agents" / name
    return CORPUS / "repos" / name


@pytest.fixture(scope="session")
def advices() -> dict[str, Advice]:
    chat = MockChat(model_id="mock-advisory-v1")
    return {n: advise(target_of(n), chat=chat) for n in (*REPOS, *DEMO)}
