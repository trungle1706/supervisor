from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate tests from the developer's shell and .env."""
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("RUN_DATABRICKS_UNUSED", raising=False)
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data" / "local"))
    for var in ("SUPERVISOR_HOST", "SUPERVISOR_PORT", "SQL_BACKEND", "TABLE_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """WP-D1: any real DNS lookup or outbound connection fails the test. Opt in with
    ``pytestmark = pytest.mark.usefixtures("no_network")``. It is not autouse: a few suites open
    loopback sockets on purpose (HTTP servers, MCP, benchmarks)."""

    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("a real network call was attempted")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)


# --- tests that need a git checkout skip inside an unpacked release zip (no .git) -------
_NEEDS_GIT = (
    "tests/e2e/test_release.py",
    "tests/onboard/test_run_e2e.py",
    "tests/onboard/test_adapters.py::test_revision_in_git_tree",
    "tests/test_no_secrets.py::test_no_env_file_tracked",
    "tests/test_no_secrets.py::test_no_secret_patterns",
)


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    if (REPO_ROOT / ".git").exists():
        return
    skip = pytest.mark.skip(reason="needs a git checkout (not an unpacked release zip)")
    for item in items:
        rel = item.nodeid
        if any(rel == k or rel.startswith(k + "::") or rel.startswith(k) for k in _NEEDS_GIT):
            item.add_marker(skip)
