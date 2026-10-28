"""Schema self-check (WP-P3): compare ``schema/model.yaml`` with the warehouse, read only.

Why: on the first live run the console failed with TABLE_OR_VIEW_NOT_FOUND because the
warehouse tables came from an older bootstrap. With ``SCHEMA_SELFCHECK=1`` the app reads
``information_schema.columns`` once at start (one query for the whole schema), lists the missing
tables and columns, and builds the exact SQL plan for a person to run. The app NEVER runs DDL
itself. The plan is shown at ``/console/admin/schema`` and summarised in ``/healthz``.

Rules:

* Off by default. On SQLite the check is a no-op that reports ok.
* A failing check never stops the app: the state becomes ``unknown`` and a WARNING is logged.
* Unity Catalog ``information_schema`` lists only objects the caller may see. A table that exists
  but is invisible to the app identity shows as missing; the plan uses ``CREATE TABLE IF NOT
  EXISTS``, which is harmless in that case, and the page says so.
* Added columns are nullable (Delta cannot add a NOT NULL column to a table that has rows).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from supervisor.core.schema import (
    DATABRICKS_TYPES,
    SchemaModel,
    Table,
    databricks_statements,
    load_model,
)

log = logging.getLogger("supervisor.ops.schema")

Status = Literal["ok", "missing", "unknown", "off"]
MAX_DETAIL = 300


@dataclass(frozen=True)
class SchemaCheck:
    status: Status
    checked_at: str | None = None
    tables_total: int = 0
    missing_tables: tuple[str, ...] = ()
    missing_columns: tuple[tuple[str, tuple[str, ...]], ...] = ()
    plan: tuple[str, ...] = ()
    detail: str = ""
    backend: str = ""

    @property
    def schema_ok(self) -> bool | str:
        """``True``, ``False`` or ``"unknown"`` for /healthz."""
        if self.status == "ok":
            return True
        if self.status == "missing":
            return False
        return "unknown"

    @property
    def problem(self) -> bool:
        return self.status == "missing"

    @property
    def missing_column_count(self) -> int:
        return sum(len(cols) for _, cols in self.missing_columns)


_lock = threading.Lock()
_state: SchemaCheck | None = None


def get_state() -> SchemaCheck | None:
    with _lock:
        return _state


def set_state(check: SchemaCheck | None) -> None:
    global _state
    with _lock:
        _state = check


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def plan_for(
    model: SchemaModel,
    missing_tables: list[str],
    missing_columns: dict[str, list[str]],
    *,
    catalog: str,
    schema: str,
    prefix: str,
    retention_days: int,
) -> list[str]:
    """SQL a person runs in the SQL editor: CREATE for missing tables, ALTER ... ADD COLUMNS
    for missing columns. Same text as ``schema/ddl/databricks.sql`` for the CREATE part."""
    out: list[str] = []
    for name in missing_tables:
        one = SchemaModel(model.version, {name: model.tables[name]}, model.source_hash)
        out.extend(
            databricks_statements(
                one, catalog=catalog, schema=schema, prefix=prefix, retention_days=retention_days
            )
        )
    for name, cols in missing_columns.items():
        table: Table = model.tables[name]
        wanted = [table.column(c) for c in cols]
        fq = f"{_ident(catalog)}.{_ident(schema)}.{_ident(prefix + name)}"
        listing = ", ".join(f"{c.name} {DATABRICKS_TYPES[c.type]}" for c in wanted)
        out.append(f"ALTER TABLE {fq} ADD COLUMNS ({listing})")
    return out


def compare(
    model: SchemaModel,
    live: dict[str, set[str]],
    *,
    prefix: str,
) -> tuple[list[str], dict[str, list[str]]]:
    """(missing tables, {table: missing columns}) from {live table: {live columns}}."""
    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}
    for name, table in model.tables.items():
        cols = live.get(f"{prefix}{name}".lower())
        if cols is None:
            missing_tables.append(name)
            continue
        gone = [c for c in table.column_names if c.lower() not in cols]
        if gone:
            missing_columns[name] = gone
    return missing_tables, missing_columns


def run_check(
    settings: Any,
    executor: Any,
    model: SchemaModel | None = None,
) -> SchemaCheck:
    """Compare the model with the warehouse behind ``executor``. Never raises."""
    try:
        model = model or load_model()
        if getattr(executor, "dialect", "") != "databricks":
            return SchemaCheck(
                "ok",
                _now(),
                len(model.tables),
                detail="SQLite: tables are created by the app itself; nothing to compare",
                backend="sqlite",
            )
        catalog = str(executor.catalog)
        schema = str(executor.schema)
        prefix = str(getattr(executor, "table_prefix", "") or "")
        rows = executor.query(
            f"SELECT table_name, column_name FROM {_ident(catalog)}.information_schema.columns "  # noqa: S608
            "WHERE lower(table_schema) = lower(:schema)",
            {"schema": schema},
        )
        live: dict[str, set[str]] = {}
        for r in rows:
            tname = str(r.get("table_name") or "").lower()
            cname = str(r.get("column_name") or "").lower()
            if tname and cname:
                live.setdefault(tname, set()).add(cname)
        missing_tables, missing_columns = compare(model, live, prefix=prefix)
        plan = plan_for(
            model,
            missing_tables,
            missing_columns,
            catalog=catalog,
            schema=schema,
            prefix=prefix,
            retention_days=int(getattr(settings, "evidence_retention_days", 1825)),
        )
        status: Status = "missing" if (missing_tables or missing_columns) else "ok"
        return SchemaCheck(
            status,
            _now(),
            len(model.tables),
            tuple(missing_tables),
            tuple((t, tuple(c)) for t, c in missing_columns.items()),
            tuple(plan),
            backend="databricks",
        )
    except Exception as exc:  # noqa: BLE001 - the check must never stop the app
        from supervisor.preflight import scrub

        log.warning("schema self-check failed (%s); schema state is unknown", type(exc).__name__)
        text = scrub(f"{type(exc).__name__}: {exc}")[:MAX_DETAIL]
        return SchemaCheck("unknown", _now(), detail=text, backend="databricks")


def run_startup(settings: Any, runtime: Any | None = None) -> SchemaCheck | None:
    """Called once from the app lifespan (in a worker thread). Stores and returns the result.
    Returns None and stores nothing when SCHEMA_SELFCHECK is off (the off path is unchanged)."""
    if not getattr(settings, "schema_selfcheck", False):
        return None
    try:
        executor: Any
        if runtime is not None:
            executor = runtime.adapters.executor
            sp = getattr(executor, "sp_only", None)
            executor = sp() if callable(sp) else executor
        elif settings.effective_sql_backend == "databricks_rest":
            # The runtime did not build (often because a table is missing): read with our own
            # executor so the page can still say what is missing.
            from supervisor.adapters.sql.databricks_rest import build_databricks_executor

            executor = build_databricks_executor(settings)
        else:
            executor = None
        if executor is None:
            check = SchemaCheck("ok", _now(), detail="SQLite: no comparison", backend="sqlite")
        else:
            check = run_check(settings, executor)
    except Exception as exc:  # noqa: BLE001 - startup must not crash
        from supervisor.preflight import scrub

        log.warning("schema self-check could not start (%s)", type(exc).__name__)
        check = SchemaCheck(
            "unknown", _now(), detail=scrub(f"{type(exc).__name__}: {exc}")[:MAX_DETAIL]
        )
    set_state(check)
    if check.status == "missing":
        log.warning(
            "[WARN] schema self-check: %d table(s) and %d column(s) missing in the warehouse; "
            "run the SQL plan at /console/admin/schema or "
            "python -m supervisor.jobs.bootstrap_schema",
            len(check.missing_tables),
            check.missing_column_count,
        )
    return check
