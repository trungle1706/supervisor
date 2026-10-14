"""Onboard fixtures: discoveries of the three demo agents, a mock chat, a settings factory."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from supervisor.adapters.llm.mock import MockChat
from supervisor.adapters.repo import LocalGitRepoReader
from supervisor.config import Settings, load_settings
from supervisor.onboard.discover import Discovery, discover
from supervisor.onboard.models import AgentProfile
from supervisor.onboard.understand import understand
from tests.conftest import REPO_ROOT

AGENTS_DIR = REPO_ROOT / "src" / "supervisor_agents"
AGENT_IDS = ("payments", "credit_prequal", "customer_service")


@pytest.fixture(scope="session")
def discoveries() -> dict[str, Discovery]:
    return {a: discover(LocalGitRepoReader(AGENTS_DIR / a)) for a in AGENT_IDS}


@pytest.fixture(scope="session")
def profiles(discoveries: dict[str, Discovery]) -> dict[str, AgentProfile]:
    chat = MockChat(model_id="mock-onboarding-v1")
    return {a: understand(d, chat) for a, d in discoveries.items()}


@pytest.fixture
def sqlite_settings(tmp_path: Path) -> Callable[[], Settings]:
    def make() -> Settings:
        return load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")

    return make
