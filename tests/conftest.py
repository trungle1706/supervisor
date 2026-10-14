from __future__ import annotations

from pathlib import Path

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
