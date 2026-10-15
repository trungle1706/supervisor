"""WP14 launch pack: compliance_matrix.* written only when ONBOARD_COMPLIANCE_ENABLED=1."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from supervisor.adapters.llm.mock import MockChat
from supervisor.config import Settings, load_settings
from supervisor.onboard.run import ARTEFACTS, COMPLIANCE_ARTEFACTS, run_onboarding
from tests.conftest import REPO_ROOT

REPO = "fastapi_toolserver_remit"


def _target(tmp_path: Path) -> Path:
    target = tmp_path / REPO
    shutil.copytree(REPO_ROOT / "data" / "corpus" / "repos" / REPO, target)
    return target


def test_off_path_writes_no_compliance_files(
    tmp_path: Path, sqlite_settings: Callable[[], Settings]
) -> None:
    out = tmp_path / "out"
    settings = sqlite_settings()
    assert settings.onboard_compliance_enabled is False
    res = run_onboarding(
        _target(tmp_path), out, settings=settings, chat=MockChat(model_id="mock-onboarding-v1")
    )
    assert set(res.artefacts) == set(ARTEFACTS)
    for name in COMPLIANCE_ARTEFACTS:
        assert not (out / name).exists()
    assert not any("compliance" in line for line in res.lines)


def test_on_path_writes_three_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    settings = load_settings(
        sql_backend="sqlite", data_dir=tmp_path / "data", onboard_compliance_enabled=True
    )
    res = run_onboarding(
        _target(tmp_path), out, settings=settings, chat=MockChat(model_id="mock-onboarding-v1")
    )
    assert set(res.artefacts) == set(ARTEFACTS) | set(COMPLIANCE_ARTEFACTS)
    data = json.loads((out / "compliance_matrix.json").read_text(encoding="utf-8"))
    assert data["rows"] and data["header"]["regkb_version"]
    assert data["header"]["product_id"] == REPO
    assert data["narrative"]["is_mock"] is True
    assert "Not legal advice" in (out / "compliance_matrix.md").read_text(encoding="utf-8")
    assert (out / "compliance_matrix.html").read_text(encoding="utf-8").startswith("<!")
    assert any(line.startswith("[OK] compliance:") for line in res.lines)
