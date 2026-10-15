"""Fixtures of the compliance advisor tests."""

from __future__ import annotations

import pytest

from supervisor.regkb import KnowledgeBase, load_kb


@pytest.fixture(scope="session")
def kb() -> KnowledgeBase:
    return load_kb()
