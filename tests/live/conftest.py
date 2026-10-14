"""Live test kit (WP10): runs only with RUN_DATABRICKS=1 on the bank laptop.

Reads the repo ``.env`` (your CLI OAuth profile, warehouse, catalog.schema). Every table
gets a unique prefix ``lv_<8 hex>_`` and is dropped at the end. A results file with one
line per test (no secrets) is written to ``data\\local\\live-results\\`` for you to paste
back. See docs/live-test-kit.md.
"""

from __future__ import annotations

import importlib.metadata
import os
import platform
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_ROOT

LIVE = os.environ.get("RUN_DATABRICKS") == "1"
RESULTS_DIR = REPO_ROOT / "data" / "local" / "live-results"
_RESULTS: list[dict[str, Any]] = []
_ENV: dict[str, str] = {}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if LIVE:
        return
    skip = pytest.mark.skip(reason="live Databricks test: set RUN_DATABRICKS=1")
    for item in items:
        if "tests/live/" in item.nodeid.replace("\\", "/"):
            item.add_marker(skip)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not LIVE or "tests/live/" not in report.nodeid.replace("\\", "/"):
        return
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        from supervisor.preflight import scrub

        detail = ""
        if report.outcome == "skipped" and isinstance(report.longrepr, tuple):
            detail = str(report.longrepr[2])
        elif report.outcome == "failed":
            lines = str(report.longrepr).strip().splitlines()
            errs: list[str] = []
            for ln in [x for x in lines if x.startswith("E ")] or lines[-3:]:
                ln = ln[1:].strip()[:240]
                if ln and ln not in errs:
                    errs.append(ln)
            detail = " | ".join(errs[:3])
        out = "".join(s for name, s in report.sections if "stdout" in name).strip()
        _RESULTS.append(
            {
                "test": report.nodeid.split("::")[-1],
                "outcome": report.outcome.upper(),
                "seconds": round(report.duration, 1),
                "detail": scrub(detail)[:600],
                "stdout": scrub(out)[-800:],
            }
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not LIVE or not _RESULTS:
        return
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"live-{stamp}.txt"
    lines = [f"supervisor live test kit {stamp}"]
    lines += [f"{k}: {v}" for k, v in sorted(_ENV.items())]
    lines.append("-" * 72)
    for r in _RESULTS:
        lines.append(f"[{r['outcome']}] {r['test']} ({r['seconds']} s)")
        if r["detail"]:
            lines.append(f"    {r['detail']}")
        for out_line in r["stdout"].splitlines()[-8:]:
            lines.append(f"    | {out_line}")
    failed = sum(1 for r in _RESULTS if r["outcome"] == "FAILED")
    lines.append("-" * 72)
    lines.append(f"{len(_RESULTS)} tests, {failed} failed")
    text = "\n".join(lines) + "\n"
    path.write_text(text.encode("ascii", "backslashreplace").decode("ascii"), encoding="utf-8")
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if tr is not None:
        tr.write_line(f"[OK] live results written to {path} (paste this file back)")


@pytest.fixture(scope="session")
def live_settings() -> Any:
    from supervisor.bootstrap import bootstrap

    bootstrap()  # truststore when SSL_OS_TRUSTSTORE=1
    from supervisor.config import load_settings

    s = load_settings(
        _env_file=str(REPO_ROOT / ".env"),
        sql_backend="databricks_rest",
        table_prefix=f"lv_{uuid.uuid4().hex[:8]}_",
    )
    if not s.databricks_configured:
        pytest.fail(
            "live kit needs .env with DATABRICKS_CONFIG_PROFILE, DATABRICKS_WAREHOUSE_NAME "
            "(or _ID), "
            "DATABRICKS_CATALOG and DATABRICKS_SCHEMA (see docs/live-test-kit.md)"
        )
    try:
        sdk_v = importlib.metadata.version("databricks-sdk")
    except importlib.metadata.PackageNotFoundError:
        sdk_v = "not installed"
    _ENV.update(
        {
            "python": platform.python_version(),
            "os": platform.platform(),
            "databricks-sdk": str(sdk_v),
            "host": str(s.databricks_host),
            "profile": str(s.databricks_config_profile),
            "auth": s.databricks_auth_kind,
            "warehouse": str(s.databricks_warehouse_name or s.databricks_warehouse_id),
            "schema": f"{s.databricks_catalog}.{s.databricks_schema}",
            "table prefix": s.table_prefix,
            "truststore": os.environ.get("SSL_OS_TRUSTSTORE", "0"),
        }
    )
    return s


@pytest.fixture(scope="session")
def live_client(live_settings: Any) -> Any:
    from supervisor.adapters.sql.databricks_rest import make_workspace_client

    return make_workspace_client(live_settings)


@pytest.fixture(scope="session")
def live_executor(live_settings: Any, live_client: Any) -> Iterator[Any]:
    from supervisor.adapters.sql.databricks_rest import build_databricks_executor

    x = build_databricks_executor(live_settings, live_client)
    created: list[str] = []
    x.created = created  # type: ignore[attr-defined]
    yield x
    for name in created:
        try:
            x.execute(f"DROP TABLE IF EXISTS {x.qualify(name)}")
        except Exception as exc:  # noqa: BLE001 - report, keep dropping
            print(f"[WARN] could not drop {x.qualify(name)}: {exc}")


def volume_dir(settings: Any) -> str | None:
    """A Volume folder for the file tests: LIVE_VOLUME_PATH, else a /Volumes ANCHOR_PATH."""
    path = os.environ.get("LIVE_VOLUME_PATH")
    if path:
        return path.rstrip("/")
    if settings.anchor_kind == "uc_volume" and settings.anchor_path:
        return str(settings.anchor_path).rstrip("/")
    return None


def unique(name: str) -> str:
    return f"{name}_{uuid.uuid4().hex[:6]}"


def ascii_print(text: str) -> None:
    print(text.encode("ascii", "backslashreplace").decode("ascii"))


def results_path() -> Path:
    return RESULTS_DIR
