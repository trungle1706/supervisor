"""D13: POLICY_DIR and FACT_SOURCE settings reach the served app's wiring.

Laptop mode runs the real runtime on SQLite; databricks_app mode checks the same settings
and the same wiring functions (the Delta store itself is covered by the databricks fakes)."""

from __future__ import annotations

import shutil
import sqlite3
import textwrap
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.facts import (
    SqliteFactSource,
    load_query_map,
    make_fact_source,
    split_fact_source,
)
from supervisor.config import load_settings
from supervisor.core.errors import ConfigError
from supervisor.gateway.facts import MappingFactSource
from supervisor.wiring import POLICY_DIR, build_runtime, resolve_policy_dir
from tests.conftest import REPO_ROOT

QUERY_MAP = """\
sources:
  application:
    query: >-
      SELECT documents_complete, status, amount_minor
      FROM applications WHERE application_id = ?
    bool_fields: [documents_complete]
"""


@pytest.fixture
def warehouse(tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / "fake_warehouse.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE applications (application_id TEXT PRIMARY KEY, documents_complete INTEGER,"
        " status TEXT, amount_minor INTEGER)"
    )
    con.executemany(
        "INSERT INTO applications VALUES (?,?,?,?)",
        [("APP-1", 1, "open", 5000000), ("APP-2", 0, "open", 7000000)],
    )
    con.commit()
    con.close()
    qm = tmp_path / "fact_queries.yaml"
    qm.write_text(QUERY_MAP, encoding="utf-8")
    return db, qm


@pytest.fixture
def custom_policy(tmp_path: Path) -> Path:
    d = tmp_path / "policy"
    d.mkdir()
    shutil.copy(REPO_ROOT / "policies" / "schema.json", d / "schema.json")
    text = (REPO_ROOT / "policies" / "baseline.yaml").read_text(encoding="utf-8")
    block = textwrap.indent(
        textwrap.dedent(
            """\
          bench_agent:
            name: Bench agent
            owner_user: bench-lead@example.invalid
            owner_team: Bench
            risk_tier: high
            model_family: qwen
            host_type: python_inprocess
            plug_point: gate_hook
            initial_state: RUNNING
        """
        ),
        "  ",
    )
    text = text.replace("agents:\n", "agents:\n" + block, 1)
    (d / "baseline.yaml").write_text(text, encoding="utf-8")
    return d


# -- defaults -----------------------------------------------------------------------------
def test_defaults_keep_the_old_behaviour(tmp_path: Path) -> None:
    s = load_settings(_env_file=None, data_dir=tmp_path / "d", sql_backend="sqlite")
    assert s.policy_dir is None and s.fact_source == "" and s.fact_query_map is None
    assert resolve_policy_dir(s) == POLICY_DIR
    assert make_fact_source(s) is None
    rt = build_runtime(s)
    try:
        assert rt.gateway.facts is None and "bench_agent" not in rt.policy.doc.agents
    finally:
        rt.close()


# -- settings validation ------------------------------------------------------------------
def test_policy_dir_is_absolute_and_must_exist(tmp_path: Path, custom_policy: Path) -> None:
    s = load_settings(_env_file=None, policy_dir=custom_policy)
    assert s.policy_dir == custom_policy and s.policy_dir.is_absolute()
    with pytest.raises(ConfigError, match="POLICY_DIR is not a folder"):
        load_settings(_env_file=None, policy_dir=tmp_path / "nope")


def test_policy_dir_relative_resolves_against_repo_root() -> None:
    s = load_settings(_env_file=None, policy_dir=Path("policies"))
    assert s.policy_dir == REPO_ROOT / "policies"


@pytest.mark.parametrize("bad", ["mysql:host", "sqlite:", "nonsense", "callable:"])
def test_bad_fact_source_is_a_config_error(bad: str) -> None:
    with pytest.raises(ConfigError, match="FACT_SOURCE"):
        load_settings(_env_file=None, fact_source=bad)


def test_sqlite_fact_source_needs_a_query_map(warehouse: tuple[Path, Path]) -> None:
    db, qm = warehouse
    with pytest.raises(ConfigError, match="FACT_QUERY_MAP"):
        load_settings(_env_file=None, fact_source=f"sqlite:{db}")
    s = load_settings(_env_file=None, fact_source=f"sqlite:{db}", fact_query_map=qm)
    assert split_fact_source(s.fact_source) == ("sqlite", str(db))


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM applications WHERE application_id = ?",
        "SELECT 1; DROP TABLE applications",
        "SELECT * FROM applications",
        "SELECT * FROM applications WHERE a = ? AND b = ?",
    ],
)
def test_query_map_rejects_unsafe_queries(tmp_path: Path, query: str) -> None:
    f = tmp_path / "q.yaml"
    f.write_text(f'sources:\n  application:\n    query: "{query}"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="one SELECT|query"):
        load_query_map(f)


# -- the sqlite fact source -----------------------------------------------------------------
def test_sqlite_source_reads_and_is_read_only(warehouse: tuple[Path, Path]) -> None:
    db, qm = warehouse
    src = SqliteFactSource(db, load_query_map(qm))
    try:
        rec = src.get("application", "APP-1")
        assert rec == {"documents_complete": True, "status": "open", "amount_minor": 5000000}
        assert src.get("application", "APP-404") is None
        assert src.get("unknown_source", "APP-1") is None
        # the key is bound, never pasted into the SQL
        assert src.get("application", "x' OR '1'='1") is None
        with pytest.raises(sqlite3.OperationalError):
            src._conn.execute("DELETE FROM applications")  # noqa: SLF001
        with pytest.raises(sqlite3.OperationalError):
            src._conn.execute("INSERT INTO applications VALUES ('X',1,'x',1)")  # noqa: SLF001
    finally:
        src.close()
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM applications").fetchone() == (2,)


def test_sqlite_source_database_error_fails_closed(
    tmp_path: Path, warehouse: tuple[Path, Path]
) -> None:
    db, _ = warehouse
    q = tmp_path / "bad.yaml"
    q.write_text('sources:\n  application:\n    query: "SELECT nope FROM nowhere WHERE k = ?"\n')
    src = SqliteFactSource(db, load_query_map(q))
    assert src.get("application", "APP-1") is None  # None -> gateway rule error -> fail mode
    src.close()
    with pytest.raises(ConfigError, match="not found"):
        SqliteFactSource(tmp_path / "missing.db", {})


def test_callable_kind_builds_the_mapping_source() -> None:
    s = load_settings(
        _env_file=None, fact_source="callable:tests.gateway.test_policy_dir_fact_source:factory"
    )
    assert make_fact_source(s).get("application", "A") == {"documents_complete": True}  # type: ignore[union-attr]
    bad = load_settings(_env_file=None, fact_source="callable:no.such.module:f")
    with pytest.raises(ConfigError, match="FACT_SOURCE callable"):
        make_fact_source(bad)


def factory(settings: Any) -> MappingFactSource:
    return MappingFactSource({"application": lambda key: {"documents_complete": True}})


# -- wiring in both modes ------------------------------------------------------------------
def _decide(rt: Any, app_id: str) -> dict[str, Any]:
    return dict(
        rt.gateway.check(
            "credit_prequal",
            "1.0.0",
            "decide_prequal",
            {"application_id": app_id, "decision": "approve", "amount_minor": 100, "reason": "x"},
            {},
        )
    )


def test_laptop_runtime_uses_policy_dir_and_sqlite_facts(
    tmp_path: Path, warehouse: tuple[Path, Path], custom_policy: Path
) -> None:
    db, qm = warehouse
    s = load_settings(
        _env_file=None,
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        policy_dir=custom_policy,
        fact_source=f"sqlite:{db}",
        fact_query_map=qm,
    )
    rt = build_runtime(s)
    try:
        assert "bench_agent" in rt.policy.doc.agents  # the served app loaded the other folder
        assert isinstance(rt.gateway.facts, SqliteFactSource)
        bad = _decide(rt, "APP-2")  # documents not complete -> CRD-01
        assert bad["allow"] is False and bad["rule_id"] == "CRD-01"
        unknown = _decide(rt, "APP-404")  # no record -> rule error -> fails closed
        assert unknown["allow"] is False
        ok = _decide(rt, "APP-1")
        assert ok.get("rule_id") != "CRD-01"
    finally:
        rt.close()


def test_databricks_app_mode_settings_and_wiring(
    tmp_path: Path, warehouse: tuple[Path, Path], custom_policy: Path
) -> None:
    """databricks_app mode: the settings validate and the same resolvers pick the values.
    The Delta store and policy deploy are exercised by the Databricks fakes elsewhere; here
    the runtime is built on a SQLite store with the databricks_app settings object."""
    from supervisor.adapters.factory import build_adapters

    db, qm = warehouse
    s = load_settings(
        _env_file=None,
        supervisor_mode="databricks_app",
        databricks_host="https://adb-1.example.invalid",
        policy_dir=custom_policy,
        fact_source=f"sqlite:{db}",
        fact_query_map=qm,
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
    )
    assert s.supervisor_mode == "databricks_app"
    assert resolve_policy_dir(s) == custom_policy
    src = make_fact_source(s)
    assert isinstance(src, SqliteFactSource)
    assert src.get("application", "APP-1") == {
        "documents_complete": True,
        "status": "open",
        "amount_minor": 5000000,
    }
    src.close()
    adapters = build_adapters(s)
    try:
        rt = build_runtime(s, adapters=adapters)
        try:
            assert "bench_agent" in rt.policy.doc.agents
            assert isinstance(rt.gateway.facts, SqliteFactSource)
            assert _decide(rt, "APP-2")["rule_id"] == "CRD-01"
        finally:
            rt.close()
    finally:
        adapters.close()


def test_gateway_wiring_build_gateway_uses_both(
    tmp_path: Path, warehouse: tuple[Path, Path], custom_policy: Path
) -> None:
    from supervisor.gateway.wiring import build_gateway

    db, qm = warehouse
    s = load_settings(
        _env_file=None,
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        policy_dir=custom_policy,
        fact_source=f"sqlite:{db}",
        fact_query_map=qm,
    )
    events: list[Any] = []

    class Sink:
        def record(self, t: str, r: str, p: Any) -> str:
            events.append((t, r))
            return "h"

    gw = build_gateway(s, evidence=Sink())
    assert isinstance(gw.facts, SqliteFactSource)
