"""Load ``schema/model.yaml``; render DDL; convert values to and from the database.

Pure Python: no database library is imported here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from supervisor.core.canonical import canonical_json, format_ts, parse_ts, sha256_bytes_hex

# The app runs from source (laptop: repo checkout; App: source_code_path ./ with
# PYTHONPATH=src). A built wheel would NOT contain schema/model.yaml.
MODEL_PATH = Path(__file__).resolve().parents[3] / "schema" / "model.yaml"
DDL_DIR = MODEL_PATH.parent / "ddl"

TYPES = ("string", "text", "int", "money", "float", "bool", "timestamp", "date", "json")
SQLITE_TYPES = {
    "string": "TEXT",
    "text": "TEXT",
    "int": "INTEGER",
    "money": "INTEGER",
    "float": "REAL",
    "bool": "INTEGER",
    "timestamp": "TEXT",
    "date": "TEXT",
    "json": "TEXT",
}
DATABRICKS_TYPES = {
    "string": "STRING",
    "text": "STRING",
    "int": "BIGINT",
    "money": "BIGINT",
    "float": "DOUBLE",
    "bool": "BOOLEAN",
    "timestamp": "TIMESTAMP",
    "date": "DATE",
    "json": "STRING",
}
# Databricks result manifest type_name -> portable type (used when no model types are given)
DATABRICKS_TYPE_NAMES = {
    "STRING": "string",
    "CHAR": "string",
    "LONG": "int",
    "INT": "int",
    "SHORT": "int",
    "BYTE": "int",
    "DOUBLE": "float",
    "FLOAT": "float",
    "DECIMAL": "string",  # never float: could be money; caller casts explicitly
    "BOOLEAN": "bool",
    "TIMESTAMP": "timestamp",
    "TIMESTAMP_NTZ": "timestamp",
    "DATE": "date",
}
STATE_COLUMNS = (("row_version", "int"), ("updated_at", "timestamp"))
IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
Dialect = Literal["sqlite", "databricks"]
CATALOG_PH = "${catalog}"
SCHEMA_PH = "${schema}"
DEFAULT_EVIDENCE_RETENTION_DAYS = 1825
RETENTION_CLASSES = ("raw", "masked", "notice")  # ADR D13; days come from RETENTION_*_DAYS
RETENTION_TYPES = ("string", "text", "json")


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool


@dataclass(frozen=True)
class Table:
    name: str
    kind: Literal["append_only", "state"]
    description: str
    primary_key: tuple[str, ...]
    columns: tuple[Column, ...]
    indexes: tuple[tuple[str, ...], ...] = ()
    evidence: bool = False  # WP6: Delta retention properties (EVIDENCE_RETENTION_DAYS)
    # WP18 (ADR D13): personal-data retention classes, ((class, (column, ...)), ...).
    retention: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def retention_columns(self) -> tuple[str, ...]:
        return tuple(c for _, cols in self.retention for c in cols)

    @property
    def append_only(self) -> bool:
        return self.kind == "append_only"

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    @property
    def types(self) -> dict[str, str]:
        return {c.name: c.type for c in self.columns}

    def column(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(f"table {self.name} has no column {name}")


@dataclass(frozen=True)
class SchemaModel:
    version: int
    tables: dict[str, Table] = field(default_factory=dict)
    source_hash: str = ""

    def table(self, name: str) -> Table:
        try:
            return self.tables[name]
        except KeyError:
            raise KeyError(f"unknown table {name!r} (not in schema/model.yaml)") from None


def _parse_type(spec: str, where: str) -> tuple[str, bool]:
    spec = str(spec).strip()
    nullable = spec.endswith("?")
    base = spec.rstrip("?")
    if base not in TYPES:
        raise ValueError(f"{where}: unknown type {spec!r}; allowed: {', '.join(TYPES)}")
    return base, nullable


def _parse_retention(
    tname: str, spec: Any, cols: list[Column], pk: tuple[str, ...]
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(spec, dict):
        raise ValueError(f"{tname}: retention must be a mapping class -> [columns]")
    by_name = {c.name: c for c in cols}
    if spec and "ts" not in by_name:
        raise ValueError(f"{tname}: retention needs a ts column")
    out: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for klass, names in spec.items():
        if klass not in RETENTION_CLASSES:
            raise ValueError(f"{tname}: unknown retention class {klass!r}; {RETENTION_CLASSES}")
        if not isinstance(names, list) or not names:
            raise ValueError(f"{tname}: retention.{klass} must be a non-empty list of columns")
        for n in names:
            if n not in by_name:
                raise ValueError(f"{tname}: retention column {n!r} is not defined")
            if n in pk or n == "ts":
                raise ValueError(f"{tname}.{n}: key or time column cannot be a retention column")
            if by_name[n].type not in RETENTION_TYPES:
                raise ValueError(f"{tname}.{n}: retention columns must be text-like")
            if n in seen:
                raise ValueError(f"{tname}.{n}: listed in more than one retention class")
            seen.add(n)
        out.append((klass, tuple(names)))
    return tuple(out)


def parse_model(text: str) -> SchemaModel:
    raw = yaml.safe_load(text)
    tables: dict[str, Table] = {}
    for tname, spec in raw["tables"].items():
        if not IDENT.match(tname):
            raise ValueError(f"bad table name {tname!r}")
        kind = spec["kind"]
        if kind not in ("append_only", "state"):
            raise ValueError(f"{tname}: kind must be append_only or state")
        pk = tuple(spec["primary_key"])
        cols = []
        for cname, ctype in spec["columns"].items():
            if not IDENT.match(cname):
                raise ValueError(f"{tname}: bad column name {cname!r}")
            base, nullable = _parse_type(ctype, f"{tname}.{cname}")
            if cname.endswith("_minor") and base != "money":
                raise ValueError(f"{tname}.{cname}: *_minor columns must be type money")
            if base == "money" and not cname.endswith("_minor"):
                raise ValueError(f"{tname}.{cname}: money columns must end in _minor")
            if cname in pk and nullable:
                raise ValueError(f"{tname}.{cname}: primary key columns cannot be nullable")
            cols.append(Column(cname, base, nullable))
        if kind == "state":
            for cname, ctype in STATE_COLUMNS:
                if any(c.name == cname for c in cols):
                    raise ValueError(f"{tname}: {cname} is added by the generator; remove it")
                cols.append(Column(cname, ctype, False))
        names = {c.name for c in cols}
        missing = [k for k in pk if k not in names]
        if missing:
            raise ValueError(f"{tname}: primary key columns not defined: {missing}")
        indexes = tuple(tuple(ix) for ix in spec.get("indexes", []))
        for ix in indexes:
            if any(c not in names for c in ix):
                raise ValueError(f"{tname}: index {ix} names an unknown column")
        evidence = spec.get("evidence", False)
        if not isinstance(evidence, bool):
            raise ValueError(f"{tname}: evidence must be true or false")
        retention = _parse_retention(tname, spec.get("retention") or {}, cols, pk)
        tables[tname] = Table(
            tname,
            kind,
            spec.get("description", "").strip(),
            pk,
            tuple(cols),
            indexes,
            evidence,
            retention,
        )
    return SchemaModel(int(raw["version"]), tables, sha256_bytes_hex(text.encode("utf-8")))


@lru_cache(maxsize=4)
def load_model(path: Path = MODEL_PATH) -> SchemaModel:
    return parse_model(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- DDL rendering


def _sql_str(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def sqlite_statements(model: SchemaModel, prefix: str = "") -> list[str]:
    out: list[str] = []
    for t in model.tables.values():
        name = f"{prefix}{t.name}"
        lines = []
        for c in t.columns:
            null = "" if c.nullable else " NOT NULL"
            lines.append(f"  {c.name} {SQLITE_TYPES[c.type]}{null}")
        lines.append(f"  PRIMARY KEY ({', '.join(t.primary_key)})")
        out.append(
            f"-- {t.name} ({t.kind}): {t.description}\n"
            f"CREATE TABLE IF NOT EXISTS {name} (\n" + ",\n".join(lines) + "\n)"
        )
        for ix in t.indexes:
            ix_name = f"ix_{name}_{'_'.join(ix)}"
            out.append(f"CREATE INDEX IF NOT EXISTS {ix_name} ON {name} ({', '.join(ix)})")
        if t.append_only and t.retention:
            # ADR D13: the only allowed UPDATE sets retention columns to NULL. DROP first so an
            # existing database loses the old blanket trigger (bootstrap_schema refreshes it).
            keep = [c for c in t.column_names if c not in t.retention_columns]
            msg = _sql_str(f"{t.name} is append-only")
            out.append(f"DROP TRIGGER IF EXISTS trg_{name}_no_update")
            out.append(
                f"CREATE TRIGGER trg_{name}_no_update\n"
                f"BEFORE UPDATE OF {', '.join(keep)} ON {name}\n"
                f"BEGIN\n  SELECT RAISE(ABORT, {msg});\nEND"
            )
            ro_msg = _sql_str(f"{t.name} is append-only: retention may only set NULL")
            when = " OR ".join(f"NEW.{c} IS NOT NULL" for c in t.retention_columns)
            out.append(
                f"CREATE TRIGGER IF NOT EXISTS trg_{name}_retention_null_only\n"
                f"BEFORE UPDATE OF {', '.join(t.retention_columns)} ON {name}\n"
                f"WHEN {when}\n"
                f"BEGIN\n  SELECT RAISE(ABORT, {ro_msg});\nEND"  # noqa: S608
            )
            out.append(
                f"CREATE TRIGGER IF NOT EXISTS trg_{name}_no_delete\n"
                f"BEFORE DELETE ON {name}\n"
                f"BEGIN\n  SELECT RAISE(ABORT, {msg});\nEND"
            )
        elif t.append_only:
            for op in ("UPDATE", "DELETE"):
                msg = _sql_str(f"{t.name} is append-only")
                out.append(
                    f"CREATE TRIGGER IF NOT EXISTS trg_{name}_no_{op.lower()}\n"
                    f"BEFORE {op} ON {name}\n"
                    f"BEGIN\n  SELECT RAISE(ABORT, {msg});\nEND"
                )
    return out


def databricks_statements(
    model: SchemaModel,
    catalog: str = CATALOG_PH,
    schema: str = SCHEMA_PH,
    prefix: str = "",
    retention_days: int = DEFAULT_EVIDENCE_RETENTION_DAYS,
) -> list[str]:
    if (
        isinstance(retention_days, bool)
        or not isinstance(retention_days, int)
        or retention_days < 1
    ):
        raise ValueError("retention_days must be a positive int")
    out: list[str] = []
    for t in model.tables.values():
        fq = f"`{catalog}`.`{schema}`.`{prefix}{t.name}`"
        lines = []
        for c in t.columns:
            null = "" if c.nullable else " NOT NULL"
            lines.append(f"  {c.name} {DATABRICKS_TYPES[c.type]}{null}")
        props = ["'supervisor.kind' = " + _sql_str(t.kind)]
        if t.append_only:
            props.insert(0, "'delta.appendOnly' = 'true'")
        if t.evidence:
            interval = f"'interval {retention_days} days'"
            props.insert(-1, f"'delta.logRetentionDuration' = {interval}")
            props.insert(-1, f"'delta.deletedFileRetentionDuration' = {interval}")
        header = [f"-- {t.name} ({t.kind}): {t.description}"]
        header.append(
            f"-- primary key (enforced by the app, not by Delta): {', '.join(t.primary_key)}"
        )
        if t.append_only:
            header.append(
                "-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history "
                "retention (logRetentionDuration) to the legal period; never VACUUM below it."
            )
        out.append(
            "\n".join(header)
            + f"\nCREATE TABLE IF NOT EXISTS {fq} (\n"
            + ",\n".join(lines)
            + "\n)\nUSING DELTA\n"
            + f"COMMENT {_sql_str(t.description)}\n"
            + "TBLPROPERTIES ("
            + ", ".join(props)
            + ")"
        )
    return out


def render_file(statements: list[str], dialect: Dialect, model: SchemaModel) -> str:
    head = (
        f"-- GENERATED from schema/model.yaml (version {model.version}). Do not edit.\n"
        f"-- Regenerate: uv run python -m schema.generate\n"
        f"-- Dialect: {dialect}\n"
    )
    return head + "\n" + "".join(s + ";\n\n" for s in statements).rstrip("\n") + "\n"


def render_sqlite(model: SchemaModel) -> str:
    return render_file(sqlite_statements(model), "sqlite", model)


def render_databricks(model: SchemaModel) -> str:
    return render_file(databricks_statements(model), "databricks", model)


# ---------------------------------------------------------------- value conversion


def to_sqlite(value: Any) -> Any:
    """Python value -> sqlite parameter."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, datetime):
        return format_ts(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict | list):
        return canonical_json(value)
    if hasattr(value, "value") and not isinstance(value, int | float | str):
        return value.value  # Enum
    return value


def to_param(value: Any, type_: str | None) -> tuple[str | None, str]:
    """Python value -> (string value or None, Databricks parameter type)."""
    if type_ is None:
        type_ = infer_type(value)
    db_type = DATABRICKS_TYPES[type_]
    if value is None:
        return None, db_type
    if hasattr(value, "value") and not isinstance(value, int | float | str | bool):
        value = value.value  # Enum
    if type_ == "bool":
        return ("true" if value else "false"), db_type
    if type_ in ("int", "money"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"expected int for {type_}, got {type(value).__name__}")
        return str(value), db_type
    if type_ == "float":
        return repr(float(value)), db_type
    if type_ == "timestamp":
        return (format_ts(value) if isinstance(value, datetime) else str(value)), db_type
    if type_ == "date":
        return (value.isoformat() if isinstance(value, date) else str(value)), db_type
    if type_ == "json":
        return (value if isinstance(value, str) else canonical_json(value)), db_type
    return str(value), db_type


def infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, datetime):
        return "timestamp"
    if isinstance(value, date):
        return "date"
    if isinstance(value, dict | list):
        return "json"
    return "string"


def from_db(raw: Any, type_: str | None) -> Any:
    """Database value (native sqlite value or Databricks string) -> Python value."""
    if raw is None or type_ is None:
        return raw
    if type_ in ("string", "text"):
        return raw if isinstance(raw, str) else str(raw)
    if type_ in ("int", "money"):
        return raw if isinstance(raw, int) and not isinstance(raw, bool) else int(raw)
    if type_ == "float":
        return float(raw)
    if type_ == "bool":
        if isinstance(raw, str):
            return raw.strip().lower() in ("true", "1")
        return bool(raw)
    if type_ == "timestamp":
        return raw if isinstance(raw, datetime) else parse_ts(str(raw))
    if type_ == "date":
        return raw if isinstance(raw, date) else date.fromisoformat(str(raw)[:10])
    if type_ == "json":
        return json.loads(raw) if isinstance(raw, str) else raw
    raise ValueError(f"unknown type {type_}")


def cast_row(row: Mapping[str, Any], types: Mapping[str, str]) -> dict[str, Any]:
    return {k: from_db(v, types.get(k)) for k, v in row.items()}
