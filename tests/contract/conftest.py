"""Contract fixtures: the same tests run on every SqlExecutor.

* sqlite: always (temp file).
* databricks_rest: only with RUN_DATABRICKS=1. Uses the real settings from the
  repo .env / environment, a unique table prefix, and drops its tables afterwards.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from tests.conftest import REPO_ROOT

T0 = datetime(2026, 10, 14, 5, 0, 0, 123456, tzinfo=UTC)


def _sqlite(tmp_path: Path) -> Adapters:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    return build_adapters(settings, clock=FixedClock(T0))


def _databricks() -> Adapters:
    from supervisor.bootstrap import bootstrap

    bootstrap()
    prefix = f"ct_{uuid.uuid4().hex[:8]}_"
    settings = load_settings(
        _env_file=str(REPO_ROOT / ".env"), sql_backend="databricks_rest", table_prefix=prefix
    )
    return build_adapters(settings, clock=FixedClock(T0))


@pytest.fixture(params=["sqlite", "databricks_rest"])
def adapters(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Adapters]:
    if request.param == "databricks_rest":
        if os.environ.get("RUN_DATABRICKS") != "1":
            pytest.skip("live Databricks test: set RUN_DATABRICKS=1")
        a = _databricks()
    else:
        a = _sqlite(tmp_path)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        if a.executor.dialect == "databricks":
            for t in a.model.tables:
                a.executor.execute(f"DROP TABLE IF EXISTS {a.executor.qualify(t)}")
        a.close()
