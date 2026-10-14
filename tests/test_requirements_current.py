"""requirements.txt must equal `uv export` of uv.lock (App BUILD installs from it)."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor import sandbox
from supervisor.cli import EXPORT_REQS_ARGV, render_requirements
from supervisor.core.errors import SupervisorError
from tests.conftest import REPO_ROOT


def test_requirements_match_lock() -> None:
    if sandbox.which("uv") is None:
        pytest.skip("uv not on PATH")
    res = sandbox.run(EXPORT_REQS_ARGV, cwd=REPO_ROOT, timeout_s=300)
    assert res.ok, res.stderr
    committed = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert render_requirements(res.stdout) == committed, (
        "requirements.txt is stale: run uv run python -m supervisor.cli export-reqs"
    )


def test_requirements_have_runtime_deps() -> None:
    text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("fastapi==", "uvicorn==", "databricks-sdk==", "truststore==", "pydantic=="):
        assert pkg in text, pkg
    assert "pytest" not in text and "ruff" not in text


def test_nexus_lines_committed_but_commented() -> None:
    text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "# --index-url https://FILL-ME-nexus-host/repository/pypi-common-group/simple/" in text
    assert "# --trusted-host FILL-ME-nexus-host" in text
    assert [ln for ln in text.splitlines() if ln.startswith("--")] == []


def test_nexus_switch_turns_lines_on() -> None:
    out = render_requirements("fastapi==1\n", "nexus.example.invalid")
    lines = out.splitlines()
    assert "--index-url https://nexus.example.invalid/repository/pypi-common-group/simple/" in lines
    assert "--trusted-host nexus.example.invalid" in lines
    assert lines[-1] == "fastapi==1"
    for bad in ("FILL-ME-nexus-host", "http://x", "a b"):
        with pytest.raises(SupervisorError):
            render_requirements("", bad)


def test_export_reqs_cli_writes_local_copy(tmp_path: Path) -> None:
    if sandbox.which("uv") is None:
        pytest.skip("uv not on PATH")
    from supervisor.cli import main

    out = tmp_path / "req.txt"
    assert main(["export-reqs", "-o", str(out), "--nexus", "nexus.example.invalid"]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Exported from uv.lock")
    assert "--trusted-host nexus.example.invalid" in text.splitlines()
    assert "fastapi==" in text
