"""Live Databricks checks (RUN_DATABRICKS=1). Each test prints what it saw; the conftest
writes all results to data\\local\\live-results\\live-<time>.txt for the owner to paste back.

Order matters only for reading the results file; every test is independent.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Any

import pytest

from supervisor.core.errors import AppendOnlyError, SqlError
from supervisor.core.schema import parse_model, to_param
from supervisor.core.schema_diff import live_columns, migrate
from tests.live.conftest import ascii_print, unique, volume_dir

pytestmark = pytest.mark.databricks

T_MICRO = datetime(2026, 10, 14, 5, 0, 0, 123456, tzinfo=UTC)


def _track(x: Any, name: str) -> str:
    x.created.append(name)
    return x.qualify(name)


# 1 ------------------------------------------------------------------ transport + timestamps
def test_01_statement_execution_round_trip_timestamp(live_executor: Any) -> None:
    text, db_type = to_param(T_MICRO, "timestamp")
    ascii_print(f"param sent: {text} as {db_type}")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", text or "")
    rows = live_executor.query(
        "SELECT :ts AS ts, CAST(:ts AS STRING) AS raw, current_user() AS who, "
        "current_timezone() AS tz",
        {"ts": T_MICRO},
        column_types={"ts": "timestamp", "raw": "string", "who": "string", "tz": "string"},
        param_types={"ts": "timestamp"},
    )
    ascii_print(f"returned: {rows[0]}")
    assert rows[0]["ts"] == T_MICRO, "microseconds or the UTC offset were lost"


# 2 ------------------------------------------------------------------ insert-only MERGE
def test_02_insert_only_merge_on_append_only_table(live_executor: Any) -> None:
    x = live_executor
    t = _track(x, unique("ao_merge"))
    x.execute(
        f"CREATE TABLE {t} (id BIGINT NOT NULL, v STRING) USING DELTA "
        "TBLPROPERTIES ('delta.appendOnly' = 'true')"
    )
    merge = (
        f"MERGE INTO {t} AS tgt USING (SELECT :id AS id, :v AS v) AS src ON tgt.id = src.id "
        "WHEN NOT MATCHED THEN INSERT (id, v) VALUES (src.id, src.v)"
    )
    first = x.execute(merge, {"id": 1, "v": "a"}, param_types={"id": "int", "v": "string"})
    second = x.execute(merge, {"id": 1, "v": "b"}, param_types={"id": "int", "v": "string"})
    rows = x.query(f"SELECT id, v FROM {t}", column_types={"id": "int", "v": "string"})
    ascii_print(f"first MERGE affected={first}, second MERGE affected={second}, rows={rows}")
    assert first == 1 and second == 0 and rows == [{"id": 1, "v": "a"}]


# 3 ------------------------------------------------------------------ UPDATE / DELETE refused
@pytest.mark.parametrize("op", ["UPDATE", "DELETE"])
def test_03_update_delete_rejected_on_append_only(live_executor: Any, op: str) -> None:
    x = live_executor
    t = _track(x, unique(f"ao_{op.lower()}"))
    x.execute(
        f"CREATE TABLE {t} (id BIGINT NOT NULL) USING DELTA "
        "TBLPROPERTIES ('delta.appendOnly' = 'true')"
    )
    x.execute(f"INSERT INTO {t} VALUES (1)")
    sql = f"UPDATE {t} SET id = 2" if op == "UPDATE" else f"DELETE FROM {t} WHERE id = 1"
    with pytest.raises(SqlError) as exc:
        x.execute(sql)
    ascii_print(f"{op} error: {type(exc.value).__name__}: {str(exc.value)[:300]}")
    assert isinstance(exc.value, AppendOnlyError), "error not mapped to AppendOnlyError"


# 4 ------------------------------------------------------------------ migration
OLD = """
version: 1
tables:
  {name}:
    kind: append_only
    evidence: true
    description: live migration probe
    primary_key: [id]
    columns:
      id: string
      ts: timestamp
"""
NEW_EXTRA = "      note: string?\n      amount_minor: money?\n"


def test_04_migration_add_columns(live_executor: Any, live_settings: Any) -> None:
    from supervisor.core.schema import databricks_statements

    x = live_executor
    name = unique("migr")
    _track(x, name)
    old = parse_model(OLD.format(name=name))
    new = parse_model(OLD.format(name=name) + NEW_EXTRA)
    stmts = databricks_statements(
        old,
        catalog=x.catalog,
        schema=x.schema,
        prefix=x.table_prefix,
        retention_days=30,  # differs from settings: migration must reset it
    )
    x.apply_ddl(stmts)
    x.execute(
        f"INSERT INTO {x.qualify(name)} (id, ts) VALUES ('a', :ts)",
        {"ts": T_MICRO},
        param_types={"ts": "timestamp"},
    )
    plan = migrate(x, new, retention_days=live_settings.evidence_retention_days)
    for s in plan.statements:
        ascii_print(f"applied: {s}")
    cols = live_columns(x, name) or {}
    ascii_print(f"columns now: {cols}")
    assert {"note", "amount_minor"} <= set(cols)
    again = migrate(x, new, retention_days=live_settings.evidence_retention_days)
    assert again.statements == [], again.statements


# 5 ------------------------------------------------------------------ Volume anchor
def test_05_uc_volume_anchor_put_and_refuse_overwrite(live_settings: Any, live_client: Any) -> None:
    from supervisor.databricks.files import VolumeFiles
    from supervisor.evidence.anchor import AnchorError, UcVolumeAnchor

    base = volume_dir(live_settings)
    if not base:
        pytest.skip("set LIVE_VOLUME_PATH=/Volumes/<catalog>/<schema>/<volume>/supervisor-live")
    vf = VolumeFiles(live_client.files)
    anchor = UcVolumeAnchor(vf, base)
    name = f"live-{unique('anchor')}.json"
    receipt = anchor.put(name, b'{"live": true}')
    ascii_print(f"receipt: {receipt}")
    with pytest.raises(AnchorError) as exc:
        anchor.put(name, b'{"live": false}')
    ascii_print(f"second put refused: {str(exc.value)[:200]}")
    assert vf.read(f"{base}/{name}") == b'{"live": true}'
    vf.delete(f"{base}/{name}")  # the test file only; real anchors are never deleted


# 6 ------------------------------------------------------------------ Volume spool
def test_06_volume_spool_put_pull_ack(live_settings: Any, live_client: Any, tmp_path: Any) -> None:
    from supervisor.databricks.files import VolumeFiles, VolumeSpool

    base = volume_dir(live_settings)
    if not base:
        pytest.skip("set LIVE_VOLUME_PATH=/Volumes/<catalog>/<schema>/<volume>/supervisor-live")
    spool = VolumeSpool(VolumeFiles(live_client.files), f"{base}/{unique('spool')}")
    spool.put({"kind": "otlp", "payload": {"resourceSpans": []}})
    pulled = spool.pull(tmp_path)
    for p in tmp_path.glob("*.jsonl"):
        p.replace(p.with_name(p.stem + ".done"))
    removed = spool.ack(tmp_path)
    ascii_print(f"pulled={pulled} removed={removed}")
    assert len(pulled) == 1 and removed == pulled


# 7 ------------------------------------------------------------------ preflight end to end
def test_07_preflight_end_to_end(live_settings: Any) -> None:
    from supervisor.config import REPO_ROOT, load_settings
    from supervisor.preflight import format_check, run_checks

    checks = run_checks(lambda: load_settings(_env_file=str(REPO_ROOT / ".env")))
    for c in checks:
        ascii_print(format_check(c))
    names = {c.name for c in checks}
    assert "databricks sign-in" in names, "Databricks checks did not run: is .env complete?"
    assert not [c.name for c in checks if c.status == "FAIL"]


# 8 ------------------------------------------------------------------ serving endpoint (optional)
def test_08_serving_endpoint_json(live_settings: Any, live_client: Any) -> None:
    from supervisor.config import is_placeholder
    from supervisor.databricks.serving import DatabricksServingChat

    if is_placeholder(live_settings.llm_endpoint):
        pytest.skip("set LLM_ENDPOINT=<serving endpoint name> in .env to test it")
    chat = DatabricksServingChat(
        f"{live_settings.databricks_host}/serving-endpoints",
        str(live_settings.llm_endpoint),
        live_client.config.authenticate,
        timeout_s=120,
        max_tokens=64,
    )
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    reply = chat.complete_json(
        [{"role": "user", "content": 'Reply with JSON {"answer": "ok"} only.'}], schema
    )
    chat.close()
    ascii_print(f"reply: {reply}")
    assert "answer" in reply


# 9 ------------------------------------------------------------------ cluster runner (optional)
def test_09_command_execution_runner(live_settings: Any, live_client: Any) -> None:
    from supervisor.config import is_placeholder
    from supervisor.databricks.command_exec import CommandRunner, params_cell, sentinel_code

    if is_placeholder(live_settings.databricks_cluster_name) and is_placeholder(
        live_settings.databricks_cluster_id
    ):
        pytest.skip("set DATABRICKS_CLUSTER_NAME=<shared cluster name> in .env to test it")
    runner = CommandRunner.from_settings(
        live_settings.model_copy(update={"databricks_command_deadline_s": 600}), live_client
    )
    res = runner.run(
        [
            params_cell({"N": 41}),
            "result = {'n': N + 1, 'spark': spark.version}\n",
            sentinel_code("result"),
        ]
    )
    ascii_print(
        f"ok={res.ok} exit={res.exit} destroyed={res.context_destroyed} error={res.error[:300]}"
    )
    assert res.ok and res.exit and res.exit["n"] == 42 and res.context_destroyed


def test_10_environment_summary() -> None:
    """Prints what the owner should check by eye (no secrets)."""
    keys = ("SSL_OS_TRUSTSTORE", "DATABRICKS_CONFIG_PROFILE", "DATABRICKS_AUTH_TYPE")
    for k in keys:
        ascii_print(f"{k}={os.environ.get(k, '(from .env or unset)')}")
    assert "DATABRICKS_TOKEN" not in os.environ


# 12 ----------------------------------------------------------------- inventory scan v2 (WP-G3)
def test_12_inventory_scan_v2_read_calls(live_settings: Any, live_client: Any) -> None:
    """Calls each read-only call of the scan sources v2 once and prints [OK] with the number of
    items, or [FAIL] with the exception class. A permission error is reported, not a failure of
    the kit: the owner reads the lines and tells us which calls their role may use. A missing SDK
    attribute (AttributeError, TypeError) fails the test: the call shape is wrong."""
    from supervisor.adapters.workspace.databricks_sdk import DatabricksWorkspaceReader

    reader = DatabricksWorkspaceReader(live_client, max_items=50)
    schemas = [s.strip() for s in live_settings.inventory_scan_schemas.split(",") if s.strip()]
    calls: list[tuple[str, Any]] = [
        ("serving endpoints (entities, agent flag)", reader.list_serving_endpoints),
        ("registered models", reader.list_registered_models),
        ("model versions", reader.list_model_versions),
        ("genie spaces", reader.list_genie_spaces),
        ("jobs (task parameters)", reader.list_jobs),
        ("vector search indexes", reader.list_vector_indexes),
        ("uc connections (mcp flag)", reader.list_connections),
    ]
    if schemas:
        cat, _, sch = schemas[0].partition(".")
        calls.append((f"uc functions of {schemas[0]}", lambda: reader.list_functions(cat, sch)))
    else:
        ascii_print("[SKIP] uc functions: set INVENTORY_SCAN_SCHEMAS=catalog.schema in .env")
    shape_errors: list[str] = []
    for label, fn in calls:
        try:
            n = len(fn())
            ascii_print(f"[OK] {label}: {n} item(s)")
        except (AttributeError, TypeError) as exc:
            shape_errors.append(label)
            ascii_print(f"[FAIL] {label}: {type(exc).__name__}: {str(exc)[:200]}")
        except Exception as exc:  # noqa: BLE001 - e.g. permission denied: report, do not fail
            ascii_print(f"[FAIL] {label}: {type(exc).__name__} (see docs/inventory.md, scan v2)")
    assert not shape_errors, f"SDK call shape is wrong for: {shape_errors}"
