"""WP-P2 review (M4): read-only helpers read every POLICY_DIR folder, not only the first."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from supervisor.analytics.tools import risk_classes
from supervisor.config import REPO_ROOT, load_settings
from supervisor.monitors.bindings import BindingResolver

FRAGMENT = """\
policy_version: 1
tools:
  search_policies: read_only
agents:
  kb_chatbot:
    name: KB
    owner_user: u@example.invalid
    owner_team: T
    risk_tier: low
"""


@pytest.fixture
def two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "base"
    shutil.copytree(REPO_ROOT / "policies", base)
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "f.yaml").write_text(FRAGMENT, encoding="utf-8")
    monkeypatch.setenv("POLICY_DIR", f"{base}{os.pathsep}{extra}")
    return extra


def test_analytics_risk_classes_see_the_second_folder(two: Path, tmp_path: Path) -> None:
    s = load_settings(data_dir=tmp_path / "d")
    assert len(s.policy_dirs) == 2
    assert risk_classes(list(s.policy_dirs))["search_policies"] == "read_only"
    assert "search_policies" not in risk_classes(s.policy_dirs[0])


def test_monitor_bindings_see_agents_of_the_second_folder(two: Path, tmp_path: Path) -> None:
    s = load_settings(data_dir=tmp_path / "d")
    resolver = BindingResolver.from_settings(s)
    assert "kb_chatbot" in resolver._agents
    assert "payments" in resolver._agents
