"""TableStore (append-only) and StateStore (row_version optimistic concurrency).

Both work on any SqlExecutor. Table and column names come only from
schema/model.yaml; values always go through named parameters.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence
from copy import deepcopy
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
from supervisor.core.schema import SchemaModel, Table, load_model, to_param

DEFAULT_SCOPE_MAX_ROWS = 5000
_MEMO_MAX_ROWS = 50_000  # result rows an append-only memo may hold per scope
_MAX_DROPS = 3  # a table written this often inside one scope is read straight from SQL again


def _as_dict(row: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(row, BaseModel):
        return row.model_dump(mode="python")
    return dict(row)


class _Snapshot:
    """All rows of one state table, read once, with a lazy index per column."""

    def __init__(self, table: Table, rows: list[dict[str, Any]]) -> None:
        self.table = table
        self.rows = rows
        self.json_cols = [c.name for c in table.columns if c.type == "json"]
        self._index: dict[str, dict[str | None, list[dict[str, Any]]]] = {}

    @staticmethod
    def key(value: Any, type_: str) -> str | None:
        return None if value is None else to_param(value, type_)[0]

    def index(self, col: str) -> dict[str | None, list[dict[str, Any]]]:
        idx = self._index.get(col)
        if idx is None:
            type_ = self.table.column(col).type
            idx = {}
            for r in self.rows:
                idx.setdefault(self.key(r[col], type_), []).append(r)
            self._index[col] = idx
        return idx

    def fetch(
        self, where: Mapping[str, Any] | None, order_by: Sequence[str], limit: int | None
    ) -> list[dict[str, Any]]:
        t = self.table
        rows = self.rows
        if where:
            keyed = [(c, self.key(v, t.column(c).type)) for c, v in where.items()]
            first_col, first_key = keyed[0]
            rows = self.index(first_col).get(first_key, [])
            for c, k in keyed[1:]:
                type_ = t.column(c).type
                rows = [r for r in rows if self.key(r[c], type_) == k]
        if order_by:
            rows = list(rows)
            for item in reversed(order_by):  # stable sorts, last key first
                col = item.lstrip("-")
                # NULLs first when ascending, last when descending (SQLite and Delta agree)
                rows.sort(
                    key=lambda r, c=col: (0,) if r[c] is None else (1, r[c]),
                    reverse=item.startswith("-"),
                )
        if limit is not None:
            rows = rows[: max(0, int(limit))]
        out = []
        for r in rows:
            c = dict(r)
            for name in self.json_cols:
                c[name] = deepcopy(c[name])
            out.append(c)
        return out


class _Scope:
    def __init__(self, max_rows: int) -> None:
        self.max_rows = max_rows
        self.lock = threading.RLock()
        self.tables: dict[tuple[int, str], _Snapshot | None] = {}  # None: read it from SQL
        self.drops: dict[tuple[int, str], int] = {}
        # append-only tables are too big to load whole: the same query is answered once
        self.memo: dict[tuple[int, str], dict[str, list[dict[str, Any]]]] = {}
        self.memo_rows = 0


_SCOPE: contextvars.ContextVar[_Scope | None] = contextvars.ContextVar(
    "supervisor_store_read_scope", default=None
)


@contextlib.contextmanager
def read_scope(max_rows: int = DEFAULT_SCOPE_MAX_ROWS) -> Iterator[None]:
    """STORE_READ_CACHE: inside this block the first ``query`` on a state table reads the whole
    table once (one SELECT) and later queries on it are answered in memory. A write through a
    store drops that table. A scope that is already open is reused. Outside a scope nothing
    changes. Use it for one request or one job run, never for a long-lived loop."""
    if _SCOPE.get() is not None:
        yield
        return
    token = _SCOPE.set(_Scope(max_rows))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def scope_active() -> bool:
    return _SCOPE.get() is not None


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
        scope = _SCOPE.get()
        if scope is not None and not t.append_only:
            self._check_columns(t, where or {})
            self._check_columns(t, [i.lstrip("-") for i in order_by])
            snap = self._snapshot(scope, t)
            if snap is not None and not any(
                t.column(i.lstrip("-")).type == "json" for i in order_by
            ):
                try:
                    return snap.fetch(where, order_by, limit)
                except (TypeError, ValueError):
                    pass  # a value the snapshot cannot compare: let the database decide
        elif scope is not None:  # append-only: remember the exact query until the next append
            return self._memo_query(scope, t, where, order_by, limit)
        return self._query_sql(t, where, order_by, limit)

    def query_by(
        self,
        table: str,
        key_col: str,
        keys: Iterable[Any],
        *,
        columns: Sequence[str] | None = None,
        where: Mapping[str, Any] | None = None,
        order_by: Sequence[str] = (),
        per_key_limit: int | None = None,
    ) -> dict[Any, list[dict[str, Any]]]:
        """The rows of many keys in few statements, grouped by key: the batch form of
        ``query(table, {key_col: k, **where}, order_by, per_key_limit)`` for each k.
        ``columns`` limits what is read (it must include ``key_col``). A key with no rows maps to
        an empty list. A state table inside a read scope is answered from the snapshot."""
        t = self._table(table)
        uniq = list(dict.fromkeys(keys))
        out: dict[Any, list[dict[str, Any]]] = {k: [] for k in uniq}
        if not uniq:
            return out
        cols = list(columns) if columns else t.column_names
        self._check_columns(t, [key_col, *cols, *(where or {}), *(i.lstrip("-") for i in order_by)])
        if key_col not in cols:
            raise SqlError(f"{table}: columns must include the key column {key_col}")
        if _SCOPE.get() is not None and not t.append_only:
            for k in uniq:
                rows = self.query(table, {**(where or {}), key_col: k}, order_by, per_key_limit)
                out[k] = [{c: r[c] for c in cols} for r in rows]
            return out
        clause, wparams, wtypes = self._where(t, where)
        extra = clause.replace(" WHERE ", " AND ", 1) if clause else ""
        order = [f"{i.lstrip('-')} {'DESC' if i.startswith('-') else 'ASC'}" for i in order_by] or [
            key_col
        ]
        ctypes = {c: t.types[c] for c in cols}
        chunk = max(1, self.x.max_params - len(wparams) - 2)
        col_sql = ", ".join(cols)
        for start in range(0, len(uniq), chunk):
            part = uniq[start : start + chunk]
            params: dict[str, Any] = dict(wparams)
            types: dict[str, str] = dict(wtypes)
            marks = []
            for i, k in enumerate(part):
                params[f"k_{i}"] = k
                types[f"k_{i}"] = t.column(key_col).type
                marks.append(f":k_{i}")
            inner = f"FROM {self.x.qualify(t.name)} WHERE {key_col} IN ({', '.join(marks)}){extra}"
            if per_key_limit is None:
                sql = f"SELECT {col_sql} {inner} ORDER BY {', '.join([key_col, *order])}"
            else:
                params["n_max"] = int(per_key_limit)
                types["n_max"] = "int"
                sql = (
                    f"SELECT {col_sql} FROM (SELECT {col_sql}, ROW_NUMBER() OVER "
                    f"(PARTITION BY {key_col} ORDER BY {', '.join(order)}) AS rn_ {inner}) q_ "
                    f"WHERE rn_ <= :n_max ORDER BY {key_col}, rn_"
                )
            for r in self.x.query(sql, params, column_types=ctypes, param_types=types):
                out[r[key_col]].append({c: r[c] for c in cols})
        return out

    def _memo_query(
        self,
        scope: _Scope,
        t: Table,
        where: Mapping[str, Any] | None,
        order_by: Sequence[str],
        limit: int | None,
    ) -> list[dict[str, Any]]:
        key = (id(self.x), t.name)
        qkey = repr((sorted((where or {}).items(), key=lambda kv: kv[0]), tuple(order_by), limit))
        with scope.lock:
            hit = scope.memo.get(key, {}).get(qkey)
        if hit is None:
            hit = self._query_sql(t, where, order_by, limit)
            with scope.lock:
                if scope.memo_rows + len(hit) > _MEMO_MAX_ROWS:
                    return hit
                scope.memo.setdefault(key, {})[qkey] = hit
                scope.memo_rows += len(hit)
        json_cols = [c.name for c in t.columns if c.type == "json"]
        out = []
        for r in hit:
            c = dict(r)
            for name in json_cols:
                c[name] = deepcopy(c[name])
            out.append(c)
        return out

    def _snapshot(self, scope: _Scope, t: Table) -> _Snapshot | None:
        key = (id(self.x), t.name)
        with scope.lock:
            if key in scope.tables:
                return scope.tables[key]
            cap = scope.max_rows
            rows = self._query_sql(t, None, (), cap + 1)
            snap = _Snapshot(t, rows) if len(rows) <= cap else None
            scope.tables[key] = snap
            return snap

    def _drop_snapshot(self, table: str) -> None:
        scope = _SCOPE.get()
        if scope is None:
            return
        key = (id(self.x), table)
        with scope.lock:
            dropped = scope.memo.pop(key, None)
            if dropped:
                scope.memo_rows -= sum(len(v) for v in dropped.values())
            if key in scope.tables:
                n = scope.drops[key] = scope.drops.get(key, 0) + 1
                if n > _MAX_DROPS:
                    scope.tables[key] = None  # written often: stop loading it whole
                else:
                    del scope.tables[key]

    def _query_sql(
        self,
        t: Table,
        where: Mapping[str, Any] | None,
        order_by: Sequence[str],
        limit: int | None,
    ) -> list[dict[str, Any]]:
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
        try:
            return max(0, self.x.execute(sql, params, param_types=types))
        finally:
            self._drop_snapshot(t.name)

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
            try:
                n = self.x.execute(sql, params, param_types=types)
            finally:
                self._drop_snapshot(t.name)
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

    def _get_sql(self, t: Table, key: Mapping[str, Any]) -> dict[str, Any] | None:
        """Read one row straight from SQL (after a write, so a read scope does not reload)."""
        rows = self._query_sql(t, key, (), 2)
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
        try:
            self._insert_sql(t, table, key, target, cols, params, types)
        finally:
            self._drop_snapshot(t.name)
        return data

    def _insert_sql(
        self,
        t: Table,
        table: str,
        key: dict[str, Any],
        target: str,
        cols: list[str],
        params: dict[str, Any],
        types: dict[str, str],
    ) -> None:
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
        try:
            n = self.x.execute(sql, params, param_types=types)
        finally:
            self._drop_snapshot(t.name)
        if n < 0:
            raise SqlError(
                f"{table} {key}: the backend did not report affected rows, so the "
                f"optimistic concurrency check cannot be proven ({self.x.describe()})"
            )
        if n == 0:
            current = self._get_sql(t, key)
            if current is None:
                raise NotFoundError(f"{table} {key} does not exist")
            raise ConcurrencyError(
                f"{table} {key}: expected row_version {expected_version}, "
                f"found {current['row_version']}; re-read and retry"
            )
        row = self._get_sql(t, key)
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
