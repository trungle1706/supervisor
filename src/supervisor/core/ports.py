"""Ports (interfaces). Adapters in ``supervisor.adapters`` implement them.

Core and domain code depend only on these Protocols. WP1 implements SqlExecutor
(sqlite, databricks_rest), TableStore, StateStore and Clock. Later work packages
implement the rest.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

Row = dict[str, Any]
Params = Mapping[str, Any]


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...


@runtime_checkable
class SqlExecutor(Protocol):
    """Run SQL with named ``:param`` markers. Values come back as Python types."""

    dialect: Literal["sqlite", "databricks"]
    max_params: int

    def qualify(self, table: str) -> str:
        """Fully qualified, quoted table name (adds catalog.schema and prefix)."""
        ...

    def execute(
        self, sql: str, params: Params | None = None, param_types: Mapping[str, str] | None = None
    ) -> int:
        """Run one statement. Return affected rows, or -1 when unknown."""
        ...

    def query(
        self,
        sql: str,
        params: Params | None = None,
        column_types: Mapping[str, str] | None = None,
        param_types: Mapping[str, str] | None = None,
    ) -> list[Row]:
        """Run one SELECT. Cast values by ``column_types`` (portable type names)."""
        ...

    def apply_ddl(self, statements: Sequence[str]) -> None:
        """Run DDL statements in order (idempotent statements only)."""
        ...

    def describe(self) -> str:
        """Target for error messages (backend, host, schema). No secrets."""
        ...

    def close(self) -> None: ...


@runtime_checkable
class TableStore(Protocol):
    """Append-only tables (events, verdicts, chain). No update, no delete."""

    def append(self, table: str, rows: Iterable[Mapping[str, Any] | Any]) -> int: ...

    def query(
        self,
        table: str,
        where: Mapping[str, Any] | None = None,
        order_by: Sequence[str] = (),
        limit: int | None = None,
    ) -> list[Row]: ...

    def count_due(
        self, table: str, columns: Sequence[str], time_column: str, before_ts: datetime
    ) -> int:
        """Rows older than ``before_ts`` that still hold a value in one of ``columns``."""
        ...

    def redact_columns(
        self,
        table: str,
        columns: Sequence[str],
        time_column: str,
        before_ts: datetime,
        now: datetime | None = None,
    ) -> int:
        """Retention (ADR D13): set ``columns`` to NULL ('' if NOT NULL) on old rows; no row is
        deleted. Returns the rows changed. ``now`` is needed for state tables."""
        ...


@runtime_checkable
class StateStore(Protocol):
    """Mutable tables with optimistic concurrency on ``row_version``."""

    def get(self, table: str, key: Mapping[str, Any]) -> Row | None: ...

    def insert(self, table: str, row: Mapping[str, Any] | Any) -> Row: ...

    def update(
        self, table: str, key: Mapping[str, Any], changes: Mapping[str, Any], expected_version: int
    ) -> Row: ...

    def upsert(
        self, table: str, row: Mapping[str, Any] | Any, expected_version: int | None
    ) -> Row: ...

    def query(
        self,
        table: str,
        where: Mapping[str, Any] | None = None,
        order_by: Sequence[str] = (),
        limit: int | None = None,
    ) -> list[Row]: ...


class TraceSource(Protocol):
    """Source of agent spans (otel_inprocess, otlp_receiver, mlflow_export). WP4."""

    def read(self, since: datetime | None = None) -> Iterable[Mapping[str, Any]]: ...


class ChatModel(Protocol):
    """OpenAI-compatible chat model or a mock. WP2/WP5."""

    family: str
    model_id: str
    is_mock: bool

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float,
    ) -> Mapping[str, Any]: ...


class Signer(Protocol):
    """Signs chain heads (ed25519_file, secret_env). WP6."""

    key_id: str

    def sign(self, data: bytes) -> bytes: ...

    def verify(self, data: bytes, signature: bytes) -> bool: ...


class Anchor(Protocol):
    """Writes an anchor receipt to an immutable target (worm_dir, uc_volume). WP6."""

    target: str

    def put(self, name: str, data: bytes) -> str:
        """Store ``data``; return a receipt string."""
        ...


class Masker(Protocol):
    """PII masking (vn_regex default, presidio optional). WP4."""

    def mask(self, text: str) -> str: ...


class Principal(Protocol):
    """Who is acting (dev_header, databricks_app). WP8."""

    user_id: str
    kind: Literal["user", "service_principal", "system"]
    auth_method: str


class Notifier(Protocol):
    """Sends notices (inbox, webhook). WP8."""

    def notify(self, channel: str, subject: str, body: str) -> None: ...


class RepoReader(Protocol):
    """Reads an agent repository read-only (local_git, databricks_repo). WP9."""

    def list_files(self, pattern: str = "**/*") -> Sequence[str]: ...

    def read_text(self, path: str, max_bytes: int = 1_000_000) -> str: ...


class WorkspaceReader(Protocol):
    """Reads workspace metadata (fixtures, databricks_sdk). WP9."""

    def list_serving_endpoints(self) -> Sequence[Mapping[str, Any]]: ...

    def list_tables(self, catalog: str, schema: str) -> Sequence[str]: ...


class EvidenceSink(Protocol):
    """Where every decision is recorded (chain writer in WP6; in-memory list in tests).

    ``payload`` must be canonicalisable (no floats; scores as integer basis points).
    Returns the entry hash (hex)."""

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str: ...


class GateHook(Protocol):
    """Pre-call hook an agent's tool router calls before every tool call (gateway in WP3).

    Return mapping keys: ``allow`` (bool), ``action`` (allow|log|alert|block|pause),
    ``rule_id`` (str|None), ``reason`` (str), ``latency_ms`` (int). Must never raise:
    on internal failure return the rule's fail mode (closed for money/credit/PII export)."""

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...
