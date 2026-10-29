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


@pytest.fixture(scope="session", autouse=True)
def _regkb_cache() -> None:
    """WP-T1: one RegKB load per process for the same file content (tests/_cache.py)."""
    from tests._cache import install_regkb_cache

    install_regkb_cache()


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


# --- WP-T1: the `slow` marker --------------------------------------------------------------
# Marked here (not in each file) so that tests added by other work packages in these places are
# covered without edits. A test file is slow when its path starts with one of these prefixes or
# its file name has one of these parts. `pytest -m "not slow"` is the daily run; the full run
# (no -m) includes them. Measured numbers: docs/testing.md.
SLOW_PATH_PREFIXES = (
    "tests/e2e/",  # end to end: release bundles, runbook, ingress
    "tests/perf/",  # latency budgets
    "tests/pii_eval/",  # PII evaluation regression
)
SLOW_FILE_PARTS = ("harness", "_perf", "_e2e", "_bench")
SLOW_NODEIDS = (
    # single tests found slow by --durations (>8 s on a loaded host), see docs/testing.md
    "tests/regkb/test_w2_change.py::",
    "tests/console/test_w2_change.py::",
    "tests/regkb/test_lawagent.py::test_cli_refuses_a_mock_model_and_runs_with_allow_mock",
    "tests/console/test_c4_portfolio.py::test_grid_is_capped_at_50_rows",
    "tests/console/test_wp39_review.py::test_export_of_50000_rows_is_capped",
    "tests/console/test_wp39_followups.py::test_detectors_tab_reads_the_recorded_report",
    "tests/console/test_wp39_analytics.py::test_detectors_tab_latency_and_the_indicative_marker",
)


def _is_slow(rel: str) -> bool:
    path = rel.split("::", 1)[0]
    name = path.rsplit("/", 1)[-1]
    return (
        rel.startswith(SLOW_PATH_PREFIXES)
        or any(part in name for part in SLOW_FILE_PARTS)
        or any(rel.startswith(n) for n in SLOW_NODEIDS)
    )


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    slow = pytest.mark.slow
    for item in items:
        if _is_slow(item.nodeid):
            item.add_marker(slow)
    if (REPO_ROOT / ".git").exists():
        return
    skip = pytest.mark.skip(reason="needs a git checkout (not an unpacked release zip)")
    for item in items:
        rel = item.nodeid
        if any(rel == k or rel.startswith(k + "::") or rel.startswith(k) for k in _NEEDS_GIT):
            item.add_marker(skip)
