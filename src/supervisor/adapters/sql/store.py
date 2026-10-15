"""TableStore (append-only) and StateStore (row_version optimistic concurrency).

Both work on any SqlExecutor. Table and column names come only from
schema/model.yaml; values always go through named parameters.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from supervisor.core.errors import (
    AppendOnlyError,
    ConcurrencyError,
    DuplicateKeyError,
    NotFoundError,
    SqlError,
)
from supervisor.core.ports import Clock, SqlExecutor
from supervisor.core.schema import SchemaModel, Table, load_model


def _as_dict(row: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(row, BaseModel):
        return row.model_dump(mode="python")
    return dict(row)


class _Base:
    def __init__(self, executor: SqlExecutor, model: SchemaModel | None = None) -> None:
        self.x = executor
        self.model = model or load_model()

    def _table(self, name: str) -> Table:
        return self.model.table(name)

    def _check_columns(self, t: Table, names: Iterable[str]) -> None:
        unknown = sorted(set(names) - set(t.column_names))
        if unknown:
            raise SqlError(f"{t.name}: unknown columns {unknown}")

    def _complete(self, t: Table, row: dict[str, Any]) -> dict[str, Any]:
        self._check_columns(t, row)
        out = {}
        for c in t.columns:
            value = row.get(c.name)
            if value is None and not c.nullable:
                raise SqlError(f"{t.name}.{c.name} is required (NOT NULL)")
            out[c.name] = value
        return out

    def _where(
        self, t: Table, where: Mapping[str, Any] | None, prefix: str = "w_"
    ) -> tuple[str, dict[str, Any], dict[str, str]]:
        if not where:
            return "", {}, {}
        self._check_columns(t, where)
        parts, params, types = [], {}, {}
        for name, value in where.items():
            if value is None:
                parts.append(f"{name} IS NULL")
            else:
                parts.append(f"{name} = :{prefix}{name}")
                params[f"{prefix}{name}"] = value
                types[f"{prefix}{name}"] = t.column(name).type
        return " WHERE " + " AND ".join(parts), params, types

    def query(
        self,
        table: str,
        where: Mapping[str, Any] | None = None,
        order_by: Sequence[str] = (),
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Equality filter; ``order_by`` names columns, ``-col`` for descending."""
        t = self._table(table)
        clause, params, types = self._where(t, where)
        order = []
        for item in order_by:
            col = item.lstrip("-")
            self._check_columns(t, [col])
            order.append(f"{col} {'DESC' if item.startswith('-') else 'ASC'}")
        sql = f"SELECT {', '.join(t.column_names)} FROM {self.x.qualify(t.name)}{clause}"
        if order:
            sql += " ORDER BY " + ", ".join(order)
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return self.x.query(sql, params, column_types=t.types, param_types=types)


class SqlTableStore(_Base):
    """Append-only tables. There is no update or delete method on purpose.

    The one exception is retention (ADR D13): ``redact_columns`` nulls the personal-data
    columns the model lists under ``retention`` and nothing else.
    """

    def _retention_check(self, table: str, columns: Sequence[str], time_column: str) -> Table:
        t = self._table(table)
        allowed = set(t.retention_columns)
        if not columns or any(c not in allowed for c in columns):
            raise SqlError(f"{table}: {list(columns)} are not retention columns in the model")
        self._check_columns(t, [time_column])
        return t

    def _due_clause(self, t: Table, columns: Sequence[str], time_column: str) -> str:
        parts = [f"{c} <> ''" if not t.column(c).nullable else f"{c} IS NOT NULL" for c in columns]
        return f"{time_column} < :before AND (" + " OR ".join(parts) + ")"

    def count_due(
        self, table: str, columns: Sequence[str], time_column: str, before_ts: datetime
    ) -> int:
        t = self._retention_check(table, columns, time_column)
        sql = (
            f"SELECT COUNT(*) AS n FROM {self.x.qualify(t.name)} "
            f"WHERE {self._due_clause(t, columns, time_column)}"
        )
        rows = self.x.query(sql, {"before": before_ts}, param_types={"before": "timestamp"})
        return int(rows[0]["n"]) if rows else 0

    def redact_columns(
        self,
        table: str,
        columns: Sequence[str],
        time_column: str,
        before_ts: datetime,
        now: datetime | None = None,
    ) -> int:
        t = self._retention_check(table, columns, time_column)
        params: dict[str, Any] = {"before": before_ts}
        types = {"before": "timestamp"}
        sets = [f"{c} = NULL" if t.column(c).nullable else f"{c} = ''" for c in columns]
        if t.append_only:
            if self.x.dialect == "databricks":
                raise AppendOnlyError(
                    f"{table}: Delta appendOnly refuses UPDATE; retention is report-only here "
                    "(ADR D13)"
                )
        else:
            if now is None:
                raise SqlError(f"{table}: redact_columns needs now for a state table")
            sets += ["row_version = row_version + 1", "updated_at = :now"]
            params["now"] = now
            types["now"] = "timestamp"
        sql = (
            f"UPDATE {self.x.qualify(t.name)} SET {', '.join(sets)} "
            f"WHERE {self._due_clause(t, columns, time_column)}"
        )
        return max(0, self.x.execute(sql, params, param_types=types))

    def append(
        self,
        table: str,
        rows: Iterable[Mapping[str, Any] | BaseModel],
        *,
        dedupe: bool = True,
    ) -> int:
        """Append rows. A row whose primary key exists raises DuplicateKeyError.

        SQLite enforces the primary key. Delta does not, so on Databricks the
        insert is an insert-only MERGE (allowed on delta.appendOnly tables) and a
        short count means a duplicate (the other rows of that batch are kept).
        On SQLite a duplicate rejects the whole statement. ``dedupe=False`` uses a plain INSERT on
        Databricks (faster, at-least-once; duplicates are not detected).
        """
        t = self._table(table)
        if not t.append_only:
            raise AppendOnlyError(f"{table} is a state table; use StateStore")
        data = [self._complete(t, _as_dict(r)) for r in rows]
        if not data:
            return 0
        cols = t.column_names
        target = self.x.qualify(t.name)
        per_stmt = max(1, self.x.max_params // len(cols))
        total = 0
        for start in range(0, len(data), per_stmt):
            batch = data[start : start + per_stmt]
            params: dict[str, Any] = {}
            types: dict[str, str] = {}
            for i, row in enumerate(batch):
                for c in t.columns:
                    params[f"{c.name}_{i}"] = row[c.name]
                    types[f"{c.name}_{i}"] = c.type
            if self.x.dialect == "databricks" and dedupe:
                selects = [
                    "SELECT " + ", ".join(f":{c}_{i} AS {c}" for c in cols)
                    for i in range(len(batch))
                ]
                on = " AND ".join(f"tgt.{k} = src.{k}" for k in t.primary_key)
                sql = (
                    f"MERGE INTO {target} AS tgt USING ("
                    + " UNION ALL ".join(selects)
                    + f") AS src ON {on} WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}) "
                    + f"VALUES ({', '.join('src.' + c for c in cols)})"
                )
            else:
                values = [
                    "(" + ", ".join(f":{c}_{i}" for c in cols) + ")" for i in range(len(batch))
                ]
                sql = f"INSERT INTO {target} ({', '.join(cols)}) VALUES " + ", ".join(values)
            n = self.x.execute(sql, params, param_types=types)
            if dedupe and 0 <= n < len(batch):
                raise DuplicateKeyError(
                    f"{table}: {len(batch) - n} of {len(batch)} rows already exist "
                    f"(primary key {list(t.primary_key)}); the others were appended"
                )
            total += n if n >= 0 else len(batch)
        return total


class SqlStateStore(_Base):
    """Mutable rows. Every write bumps ``row_version``; updates check it."""

    def __init__(
        self, executor: SqlExecutor, clock: Clock, model: SchemaModel | None = None
    ) -> None:
        super().__init__(executor, model)
        self.clock = clock

    def _state_table(self, name: str) -> Table:
        t = self._table(name)
        if t.append_only:
            raise AppendOnlyError(f"{name} is append-only; use TableStore.append")
        return t

    def _key(self, t: Table, key: Mapping[str, Any]) -> dict[str, Any]:
        if set(key) != set(t.primary_key):
            raise SqlError(f"{t.name}: key must be exactly {list(t.primary_key)}")
        if any(v is None for v in key.values()):
            raise SqlError(f"{t.name}: key values cannot be null")
        return dict(key)

    def get(self, table: str, key: Mapping[str, Any]) -> dict[str, Any] | None:
        t = self._state_table(table)
        rows = self.query(table, self._key(t, key), limit=2)
        return rows[0] if rows else None

    def insert(self, table: str, row: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
        t = self._state_table(table)
        data = _as_dict(row)
        data["row_version"] = 1
        data["updated_at"] = self.clock.now()
        data = self._complete(t, data)
        key = {k: data[k] for k in t.primary_key}
        params = {f"v_{k}": v for k, v in data.items()}
        types = {f"v_{c.name}": c.type for c in t.columns}
        cols = t.column_names
        target = self.x.qualify(t.name)
        if self.x.dialect == "sqlite":
            sql = (
                f"INSERT INTO {target} ({', '.join(cols)}) "
                f"VALUES ({', '.join(':v_' + c for c in cols)})"
            )
            try:
                self.x.execute(sql, params, param_types=types)
            except DuplicateKeyError as exc:
                raise DuplicateKeyError(f"{table} {key} already exists") from exc
        else:
            # Delta has no enforced primary key: MERGE inserts only when absent.
            on = " AND ".join(f"tgt.{k} = src.{k}" for k in t.primary_key)
            sql = (
                f"MERGE INTO {target} AS tgt USING (SELECT "
                + ", ".join(f":v_{c} AS {c}" for c in cols)
                + f") AS src ON {on} WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}) "
                f"VALUES ({', '.join('src.' + c for c in cols)})"
            )
            n = self.x.execute(sql, params, param_types=types)
            if n == 0:
                raise DuplicateKeyError(f"{table} {key} already exists")
        return data

    def update(
        self,
        table: str,
        key: Mapping[str, Any],
        changes: Mapping[str, Any],
        expected_version: int,
    ) -> dict[str, Any]:
        t = self._state_table(table)
        key = self._key(t, key)
        changes = dict(changes)
        for reserved in (*t.primary_key, "row_version", "updated_at"):
            if reserved in changes:
                raise SqlError(f"{table}: cannot change {reserved} with update()")
        self._check_columns(t, changes)
        for name, value in changes.items():
            if value is None and not t.column(name).nullable:
                raise SqlError(f"{table}.{name} is required (NOT NULL)")
        now = self.clock.now()
        sets = [f"{c} = :s_{c}" for c in changes]
        sets += ["row_version = :s_row_version", "updated_at = :s_updated_at"]
        params: dict[str, Any] = {f"s_{c}": v for c, v in changes.items()}
        params.update(s_row_version=expected_version + 1, s_updated_at=now)
        types = {f"s_{c}": t.column(c).type for c in changes}
        types.update(s_row_version="int", s_updated_at="timestamp")
        where = " AND ".join(f"{k} = :k_{k}" for k in key) + " AND row_version = :k_expected"
        params.update({f"k_{k}": v for k, v in key.items()}, k_expected=expected_version)
        types.update({f"k_{k}": t.column(k).type for k in key}, k_expected="int")
        sql = f"UPDATE {self.x.qualify(t.name)} SET {', '.join(sets)} WHERE {where}"
        n = self.x.execute(sql, params, param_types=types)
        if n < 0:
            raise SqlError(
                f"{table} {key}: the backend did not report affected rows, so the "
                f"optimistic concurrency check cannot be proven ({self.x.describe()})"
            )
        if n == 0:
            current = self.get(table, key)
            if current is None:
                raise NotFoundError(f"{table} {key} does not exist")
            raise ConcurrencyError(
                f"{table} {key}: expected row_version {expected_version}, "
                f"found {current['row_version']}; re-read and retry"
            )
        row = self.get(table, key)
        assert row is not None
        return row

    def upsert(
        self, table: str, row: Mapping[str, Any] | BaseModel, expected_version: int | None
    ) -> dict[str, Any]:
        """Insert when ``expected_version`` is None, else update with the version check."""
        t = self._state_table(table)
        data = _as_dict(row)
        data.pop("row_version", None)
        data.pop("updated_at", None)
        if expected_version is None:
            return self.insert(table, data)
        key = {k: data.pop(k) for k in t.primary_key}
        return self.update(table, key, data, expected_version)
