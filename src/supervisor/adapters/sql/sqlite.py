"""SqlExecutor over the standard-library sqlite3 module (laptop and dev mode)."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from supervisor.core.errors import AppendOnlyError, DuplicateKeyError, SqlError
from supervisor.core.schema import cast_row, to_sqlite


class SqliteExecutor:
    dialect: Literal["sqlite"] = "sqlite"
    max_params = 900  # stay below the old SQLITE_MAX_VARIABLE_NUMBER of 999

    def __init__(self, path: str | Path, table_prefix: str = "") -> None:
        self.path = Path(path) if str(path) == ":memory:" else Path(path).resolve()
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.table_prefix = table_prefix
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(path), check_same_thread=False, isolation_level=None, timeout=10.0
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 10000")
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")

    def describe(self) -> str:
        return f"sqlite file {self.path}"

    def qualify(self, table: str) -> str:
        return f'"{self.table_prefix}{table}"'

    def _params(self, params: Mapping[str, Any] | None) -> dict[str, Any]:
        return {k: to_sqlite(v) for k, v in (params or {}).items()}

    def _error(self, exc: sqlite3.Error, sql: str) -> SqlError:
        msg = str(exc)
        where = f"{self.describe()}: {msg}. Statement: {sql.strip()[:200]}"
        if "append-only" in msg:
            return AppendOnlyError(where)
        if isinstance(exc, sqlite3.IntegrityError) and "UNIQUE" in msg.upper():
            return DuplicateKeyError(where)
        if "no such table" in msg:
            return SqlError(where + " -- fix: uv run python -m supervisor.jobs.bootstrap_schema")
        return SqlError(where)

    def execute(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        param_types: Mapping[str, str] | None = None,
    ) -> int:
        with self._lock:
            try:
                cur = self._conn.execute(sql, self._params(params))
            except sqlite3.Error as exc:
                raise self._error(exc, sql) from exc
            return cur.rowcount

    def query(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        column_types: Mapping[str, str] | None = None,
        param_types: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            try:
                rows = self._conn.execute(sql, self._params(params)).fetchall()
            except sqlite3.Error as exc:
                raise self._error(exc, sql) from exc
        types = column_types or {}
        return [cast_row(dict(r), types) for r in rows]

    def apply_ddl(self, statements: Sequence[str]) -> None:
        for stmt in statements:
            self.execute(stmt)

    def backup_to(self, dest: str | Path) -> None:
        """Online backup (sqlite3 backup API): a consistent copy while others may write."""
        dest = Path(dest)
        if dest.exists():
            raise SqlError(f"backup target exists: {dest}")
        target = sqlite3.connect(str(dest))
        try:
            with self._lock:
                self._conn.backup(target)
            target.execute("PRAGMA journal_mode = DELETE")  # one self-contained file
        except sqlite3.Error as exc:
            target.close()
            dest.unlink(missing_ok=True)
            raise SqlError(f"{self.describe()}: backup failed: {exc}") from exc
        target.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
