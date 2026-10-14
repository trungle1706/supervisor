"""requirements.txt must equal `uv export` of uv.lock (App BUILD installs from it)."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor import sandbox
from supervisor.cli import EXPORT_REQS_ARGV
from tests.conftest import REPO_ROOT


def test_requirements_match_lock(tmp_path: Path) -> None:
    if sandbox.which("uv") is None:
        pytest.skip("uv not on PATH")
    out = tmp_path / "requirements.txt"
    res = sandbox.run([*EXPORT_REQS_ARGV, "-o", str(out)], cwd=REPO_ROOT, timeout_s=300)
    assert res.ok, res.stderr
    committed = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert out.read_text(encoding="utf-8") == committed, (
        "requirements.txt is stale: run uv run python -m supervisor.cli export-reqs"
    )


def test_requirements_have_runtime_deps() -> None:
    text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("fastapi==", "uvicorn==", "databricks-sdk==", "truststore==", "pydantic=="):
        assert pkg in text, pkg
    assert "pytest" not in text and "ruff" not in text
