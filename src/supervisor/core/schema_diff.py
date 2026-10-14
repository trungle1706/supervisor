"""Schema migration: compare live tables with ``schema/model.yaml`` and add what is missing.

Rules (BACKLOG "schema migration step", WP10):

* Additive only. Missing columns are added with ``ALTER TABLE ... ADD COLUMN(S)``.
  Nothing is ever dropped, renamed or retyped; extra live columns and type mismatches
  are reported as warnings for a human.
* Added columns are nullable even when the model says NOT NULL: SQLite and Delta cannot
  add a NOT NULL column to a table that has rows. The app writes the value on new rows.
* Delta only: existing append-only tables get ``delta.appendOnly = true`` and existing
  evidence tables get the retention properties from ``EVIDENCE_RETENTION_DAYS``
  (``ALTER TABLE ... SET TBLPROPERTIES``) when the live value differs.
* Live columns come from the executor: SQLite ``PRAGMA table_info``; Databricks
  ``DESCRIBE TABLE`` (and ``SHOW TBLPROPERTIES``) over the Statement Execution API.

Pure Python over the ``SqlExecutor`` port: no database library is imported here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from supervisor.core.errors import SqlError
from supervisor.core.ports import SqlExecutor
from supervisor.core.schema import (
    DATABRICKS_TYPES,
    DEFAULT_EVIDENCE_RETENTION_DAYS,
    SQLITE_TYPES,
    Column,
    SchemaModel,
    Table,
)

_NOT_FOUND = ("TABLE_OR_VIEW_NOT_FOUND", "NO SUCH TABLE", "DOES NOT EXIST", "NOT FOUND")


@dataclass
class TableDiff:
    table: str
    exists: bool
    missing: list[Column] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    type_mismatch: list[tuple[str, str, str]] = field(default_factory=list)  # col, want, have
    properties: dict[str, str] = field(default_factory=dict)  # to set


@dataclass
class MigrationPlan:
    diffs: list[TableDiff]
    statements: list[str]
    warnings: list[str]

    @property
    def added_columns(self) -> int:
        return sum(len(d.missing) for d in self.diffs if d.exists)

    @property
    def properties_set(self) -> int:
        return sum(1 for d in self.diffs if d.exists and d.properties)


def _sql_str(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def desired_properties(table: Table, retention_days: int) -> dict[str, str]:
    """Delta table properties the model requires (same values as the generated DDL)."""
    props: dict[str, str] = {}
    if table.append_only:
        props["delta.appendOnly"] = "true"
    if table.evidence:
        interval = f"interval {retention_days} days"
        props["delta.logRetentionDuration"] = interval
        props["delta.deletedFileRetentionDuration"] = interval
    return props


def live_columns(executor: SqlExecutor, table: str) -> dict[str, str] | None:
    """{column: declared type (upper case)} of the live table, or None if it does not exist."""
    target = executor.qualify(table)
    if executor.dialect == "sqlite":
        rows = executor.query(f"PRAGMA table_info({target})")  # noqa: S608 - model identifier
        if not rows:
            return None
        return {str(r["name"]): str(r["type"] or "").upper() for r in rows}
    try:
        rows = executor.query(f"DESCRIBE TABLE {target}")  # noqa: S608 - model identifier
    except SqlError as exc:
        if any(k in str(exc).upper() for k in _NOT_FOUND):
            return None
        raise
    out: dict[str, str] = {}
    for r in rows:
        name = str(r.get("col_name") or "").strip()
        if not name or name.startswith("#"):
            break  # partition / metadata sections follow an empty row or a "# ..." row
        out[name] = str(r.get("data_type") or "").upper()
    return out


def live_properties(executor: SqlExecutor, table: str) -> dict[str, str]:
    """Delta table properties (Databricks only; SQLite has none)."""
    if executor.dialect == "sqlite":
        return {}
    rows = executor.query(f"SHOW TBLPROPERTIES {executor.qualify(table)}")  # noqa: S608
    return {str(r.get("key")): str(r.get("value")) for r in rows if r.get("key") is not None}


def _norm(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def diff_table(
    executor: SqlExecutor, table: Table, retention_days: int = DEFAULT_EVIDENCE_RETENTION_DAYS
) -> TableDiff:
    live = live_columns(executor, table.name)
    if live is None:
        return TableDiff(table.name, exists=False)
    types = SQLITE_TYPES if executor.dialect == "sqlite" else DATABRICKS_TYPES
    d = TableDiff(table.name, exists=True)
    names = set(table.column_names)
    for c in table.columns:
        if c.name not in live:
            d.missing.append(c)
        elif live[c.name] and live[c.name] != types[c.type]:
            d.type_mismatch.append((c.name, types[c.type], live[c.name]))
    d.extra = [n for n in live if n not in names]
    if executor.dialect == "databricks":
        want = desired_properties(table, retention_days)
        if want:
            have = live_properties(executor, table.name)
            d.properties = {k: v for k, v in want.items() if _norm(have.get(k, "")) != _norm(v)}
    return d


def statements_for(executor: SqlExecutor, d: TableDiff, table: Table) -> list[str]:
    target = executor.qualify(d.table)
    out: list[str] = []
    if d.missing:
        if executor.dialect == "sqlite":
            out.extend(
                f"ALTER TABLE {target} ADD COLUMN {c.name} {SQLITE_TYPES[c.type]}"
                for c in d.missing
            )
        else:
            cols = ", ".join(f"{c.name} {DATABRICKS_TYPES[c.type]}" for c in d.missing)
            out.append(f"ALTER TABLE {target} ADD COLUMNS ({cols})")
    if d.properties:
        props = ", ".join(f"{_sql_str(k)} = {_sql_str(v)}" for k, v in d.properties.items())
        out.append(f"ALTER TABLE {target} SET TBLPROPERTIES ({props})")
    return out


def plan_migration(
    executor: SqlExecutor,
    model: SchemaModel,
    retention_days: int = DEFAULT_EVIDENCE_RETENTION_DAYS,
) -> MigrationPlan:
    """Read the live schema and return the additive statements. Runs only reads."""
    diffs: list[TableDiff] = []
    statements: list[str] = []
    warnings: list[str] = []
    for table in model.tables.values():
        d = diff_table(executor, table, retention_days)
        diffs.append(d)
        if not d.exists:
            warnings.append(f"{d.table}: table missing (run the CREATE step first)")
            continue
        statements.extend(statements_for(executor, d, table))
        for c in d.missing:
            if not c.nullable:
                warnings.append(
                    f"{d.table}.{c.name}: added as NULLABLE (model says NOT NULL); "
                    "existing rows hold NULL"
                )
        for name, want, have in d.type_mismatch:
            warnings.append(f"{d.table}.{name}: live type {have}, model wants {want} (not changed)")
        for name in d.extra:
            warnings.append(f"{d.table}.{name}: column not in schema/model.yaml (kept)")
    return MigrationPlan(diffs, statements, warnings)


def migrate(
    executor: SqlExecutor,
    model: SchemaModel,
    retention_days: int = DEFAULT_EVIDENCE_RETENTION_DAYS,
    *,
    dry_run: bool = False,
) -> MigrationPlan:
    """Plan, then apply the additive statements (unless ``dry_run``)."""
    plan = plan_migration(executor, model, retention_days)
    if plan.statements and not dry_run:
        executor.apply_ddl(plan.statements)
    return plan
