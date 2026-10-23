"""SqlExecutor over the Databricks SQL Statement Execution API (REST) via databricks-sdk.

Why REST: the bank's TLS appliance drops the thrift protocol of the SQL connector.
Rules applied here (docs/BANK_DEPLOY_GUIDE.md section 3):

* every value arrives as a string; cast by schema/model.yaml types (or the result
  manifest when no model types are given);
* follow result chunks;
* one overall deadline per statement (default 120 s); cancel on expiry;
* SDK retry budget capped inside ``Config`` (60-120 s), not as a client kwarg;
* OAuth only (CLI profile on the laptop, platform service principal on the App);
* truststore is injected by ``supervisor.bootstrap`` before this module runs.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

from supervisor.config import Settings, is_placeholder
from supervisor.core.errors import (
    AppendOnlyError,
    ConcurrencyError,
    ConfigError,
    SqlError,
)
from supervisor.core.schema import DATABRICKS_TYPE_NAMES, from_db, to_param

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

# Time budget per statement: the first call waits at most min(30 s, deadline/4) server side;
# SDK transport retries are capped in Config (60-120 s). The deadline is checked again as
# soon as the first call returns, so a slow first call is cancelled, not polled further.
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED", "CLOSED"}
LOGIN_HINT = "databricks auth login --host {host} --profile {profile}"


def _state_name(state: Any) -> str:
    return getattr(state, "value", None) or getattr(state, "name", None) or str(state)


class DatabricksRestExecutor:
    dialect: Literal["databricks"] = "databricks"
    max_params = 250

    def __init__(
        self,
        statement_execution: Any,
        *,
        warehouse_id: str,
        catalog: str,
        schema: str,
        table_prefix: str = "",
        deadline_s: float = 120.0,
        host: str | None = None,
        identity: str = "unknown",
        user_api_factory: Callable[[str], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if is_placeholder(warehouse_id):
            raise ConfigError(
                "DATABRICKS_WAREHOUSE_ID (or _NAME) is not configured; set it in .env or "
                "bind the sql-warehouse resource in databricks.yml"
            )
        if is_placeholder(catalog) or is_placeholder(schema):
            raise ConfigError("DATABRICKS_CATALOG and DATABRICKS_SCHEMA must be set (not FILL-ME)")
        self._api = statement_execution
        self.warehouse_id = warehouse_id
        self.catalog = catalog
        self.schema = schema
        self.table_prefix = table_prefix
        self.deadline_s = deadline_s
        self.host = host
        self.identity = identity
        # WP-P5 (sandbox-only): builds a fresh statement API for one user token. None = off.
        self._user_api_factory = user_api_factory
        self._sleep = sleep
        self._monotonic = monotonic

    # ------------------------------------------------------------------ info
    def describe(self, identity: str | None = None) -> str:
        identity = identity or self.identity
        return (
            f"databricks host={self.host or '(default)'} warehouse={self.warehouse_id} "
            f"schema={self.catalog}.{self.schema} transport=rest identity={identity}"
        )

    def qualify(self, table: str) -> str:
        return f"`{self.catalog}`.`{self.schema}`.`{self.table_prefix}{table}`"

    # ------------------------------------------------------------------ core
    def _parameters(
        self, params: Mapping[str, Any] | None, param_types: Mapping[str, str] | None
    ) -> list[Any]:
        from databricks.sdk.service.sql import StatementParameterListItem

        out = []
        for name, value in (params or {}).items():
            text, db_type = to_param(value, (param_types or {}).get(name))
            out.append(StatementParameterListItem(name=name, value=text, type=db_type))
        return out

    def _error(
        self,
        sql: str,
        state: str,
        message: str,
        sql_state: str | None,
        identity: str | None = None,
        secret: str | None = None,
    ) -> SqlError:
        if secret:  # WP-P5: the forwarded token never reaches an error text
            message = message.replace(secret, "[REDACTED]")
            sql = sql.replace(secret, "[REDACTED]")
        where = (
            f"Databricks SQL {state} on {self.describe(identity)}: {message}"
            f"{f' (sql_state={sql_state})' if sql_state else ''}. "
            f"Statement: {sql.strip()[:200]}"
        )
        upper = message.upper()
        if "CONCURRENT" in upper:
            return ConcurrencyError(where + " -- the row changed under us; re-read and retry")
        if "APPEND" in upper and ("ONLY" in upper or "APPENDONLY" in upper):
            return AppendOnlyError(where)
        if "TABLE_OR_VIEW_NOT_FOUND" in upper:
            return SqlError(
                where + " -- fix: uv run python -m supervisor.jobs.bootstrap_schema; tables in "
                "one workspace are invisible from another, so check the host"
            )
        if "REFRESH TOKEN" in upper or "DEFAULT CREDENTIALS" in upper:
            return SqlError(where + " -- fix: " + LOGIN_HINT.format(host=self.host, profile="<p>"))
        return SqlError(where)

    def _cancel(self, statement_id: str | None, api: Any = None) -> None:
        if not statement_id:
            return
        try:
            (api or self._api).cancel_execution(statement_id)
        except Exception:  # noqa: S110 - best effort; the timeout error matters more
            pass

    def _run(
        self,
        sql: str,
        params: Mapping[str, Any] | None,
        param_types: Mapping[str, str] | None,
    ) -> tuple[list[tuple[str, str]], list[list[Any]]]:
        """Run one statement; return ([(column, type_name)], rows of raw strings)."""
        api: Any = self._api
        identity = self.identity
        secret: str | None = None
        if self._user_api_factory is not None:  # WP-P5, sandbox-only, per statement
            from supervisor.adapters.auth.user_token import current_forwarded_token

            forwarded = current_forwarded_token()
            if forwarded is not None:
                secret = forwarded.reveal()
                identity = "user_forwarded"
                try:
                    api = self._user_api_factory(secret)
                except Exception as exc:
                    # from None: the cause could carry the raw token
                    raise self._error(
                        sql,
                        "REQUEST_FAILED",
                        f"{type(exc).__name__}: {exc}",
                        None,
                        identity,
                        secret,
                    ) from None
        try:
            return self._run_on(api, identity, secret, sql, params, param_types)
        finally:
            if secret is not None:  # the per-call client is never reused: close its session
                close = getattr(api, "_supervisor_close", None)
                if close is not None:
                    try:
                        close()
                    except Exception:  # noqa: S110 - best effort
                        pass

    def sp_only(self) -> DatabricksRestExecutor:
        """WP-P5: the same executor without the user-token switch. For the evidence chain."""
        import copy

        twin = copy.copy(self)
        twin._user_api_factory = None
        return twin

    def _run_on(
        self,
        api: Any,
        identity: str,
        secret: str | None,
        sql: str,
        params: Mapping[str, Any] | None,
        param_types: Mapping[str, str] | None,
    ) -> tuple[list[tuple[str, str]], list[list[Any]]]:
        from databricks.sdk.service.sql import (
            Disposition,
            ExecuteStatementRequestOnWaitTimeout,
            Format,
        )

        def fail(state: str, message: str, sql_state: str | None = None) -> SqlError:
            return self._error(sql, state, message, sql_state, identity, secret)

        start = self._monotonic()
        try:
            resp = api.execute_statement(
                statement=sql,
                warehouse_id=self.warehouse_id,
                catalog=self.catalog,
                schema=self.schema,
                parameters=self._parameters(params, param_types) or None,
                wait_timeout=f"{max(5, min(30, int(self.deadline_s) // 4))}s",
                on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
                disposition=Disposition.INLINE,
                format=Format.JSON_ARRAY,
            )
        except SqlError:
            raise
        except Exception as exc:  # SDK auth/transport errors
            raise fail("REQUEST_FAILED", f"{type(exc).__name__}: {exc}") from (
                None if secret else exc
            )

        delay = 0.5
        while _state_name(resp.status.state) not in TERMINAL:
            if self._monotonic() - start > self.deadline_s:
                self._cancel(resp.statement_id, api)
                raise SqlError(
                    f"Databricks SQL timed out after {self.deadline_s:.0f} s on "
                    f"{self.describe(identity)} (statement cancelled). A cold warehouse takes "
                    f"about 30 s to start; retry, or check the warehouse is running. "
                    f"Statement: {sql.strip()[:200]}"
                )
            self._sleep(delay)
            delay = min(delay * 2, 5.0)
            try:
                resp = api.get_statement(resp.statement_id)
            except Exception as exc:
                raise fail("POLL_FAILED", f"{type(exc).__name__}: {exc}") from (
                    None if secret else exc
                )

        state = _state_name(resp.status.state)
        if state != "SUCCEEDED":
            err = resp.status.error
            message = getattr(err, "message", None) or "no error message"
            raise fail(state, message, getattr(resp.status, "sql_state", None))

        columns: list[tuple[str, str]] = []
        manifest = resp.manifest
        if manifest is not None and manifest.schema is not None and manifest.schema.columns:
            columns = [
                (c.name, (c.type_name and _state_name(c.type_name)) or "STRING")
                for c in manifest.schema.columns
            ]
        rows: list[list[Any]] = []
        chunk = resp.result
        while chunk is not None:
            rows.extend(chunk.data_array or [])
            nxt = chunk.next_chunk_index
            if nxt is None:
                break
            if self._monotonic() - start > self.deadline_s:
                self._cancel(resp.statement_id, api)
                raise SqlError(
                    f"Databricks SQL result fetch exceeded {self.deadline_s:.0f} s on "
                    f"{self.describe(identity)} (statement cancelled)"
                )
            chunk = api.get_statement_result_chunk_n(resp.statement_id, nxt)
        return columns, rows

    # ------------------------------------------------------------------ port
    def execute(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        param_types: Mapping[str, str] | None = None,
    ) -> int:
        columns, rows = self._run(sql, params, param_types)
        names = [c for c, _ in columns]
        if rows and "num_affected_rows" in names:
            raw = rows[0][names.index("num_affected_rows")]
            return int(raw) if raw is not None else -1
        return -1

    def query(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        column_types: Mapping[str, str] | None = None,
        param_types: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        columns, rows = self._run(sql, params, param_types)
        types = dict(column_types or {})
        for name, type_name in columns:
            types.setdefault(name, DATABRICKS_TYPE_NAMES.get(type_name.upper(), "string"))
        names = [c for c, _ in columns]
        return [{n: from_db(v, types.get(n)) for n, v in zip(names, r, strict=False)} for r in rows]

    def apply_ddl(self, statements: Sequence[str]) -> None:
        for stmt in statements:
            self.execute(stmt)

    def close(self) -> None:  # stateless HTTP client
        return None


# ---------------------------------------------------------------------- wiring


def config_kwargs(settings: Settings) -> dict[str, Any]:
    """Keyword arguments for the SDK ``Config`` (besides the retry caps). OAuth only."""
    kwargs: dict[str, Any] = {}
    if not is_placeholder(settings.databricks_host):
        kwargs["host"] = settings.databricks_host
    if not is_placeholder(settings.databricks_config_profile):
        kwargs["profile"] = settings.databricks_config_profile
    if not is_placeholder(settings.databricks_auth_type):
        kwargs["auth_type"] = settings.databricks_auth_type
    if settings.databricks_auth_kind == "service_principal":
        # Databricks App: the platform injects the service principal (OAuth M2M). Pass it
        # explicitly so a stray profile or auth type cannot win. Never logged.
        if settings.databricks_client_secret is None:  # pragma: no cover - kind implies it
            raise ConfigError("DATABRICKS_CLIENT_SECRET is not set")
        kwargs["client_id"] = settings.databricks_client_id
        kwargs["client_secret"] = settings.databricks_client_secret.get_secret_value()
        kwargs["auth_type"] = "oauth-m2m"
    return kwargs


def make_workspace_client(settings: Settings) -> WorkspaceClient:
    """WorkspaceClient with the retry budget capped inside Config. OAuth only."""
    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.core import Config
    except ImportError as exc:
        raise ConfigError(
            "databricks-sdk is not installed. Fix: uv sync --extra databricks"
        ) from exc
    kwargs = config_kwargs(settings)
    try:
        cfg = Config(
            retry_timeout_seconds=settings.databricks_retry_timeout_s,
            http_timeout_seconds=60,
            **kwargs,
        )
        if getattr(cfg, "token", None) and cfg.auth_type == "pat":
            raise ConfigError("personal access token auth is not allowed (OAuth only)")
        return WorkspaceClient(config=cfg)
    except ConfigError:
        raise
    except Exception as exc:
        hint = LOGIN_HINT.format(
            host=settings.databricks_host or "<host>",
            profile=settings.databricks_config_profile or "<profile>",
        )
        raise ConfigError(
            f"cannot configure Databricks credentials ({type(exc).__name__}: {exc}). Fix: {hint}"
        ) from exc


def resolve_warehouse_id(client: Any, settings: Settings) -> str:
    if not is_placeholder(settings.databricks_warehouse_id):
        return str(settings.databricks_warehouse_id)
    name = settings.databricks_warehouse_name
    if is_placeholder(name):
        raise ConfigError("set DATABRICKS_WAREHOUSE_ID or DATABRICKS_WAREHOUSE_NAME")
    for wh in client.warehouses.list():
        if wh.name == name:
            return str(wh.id)
    raise ConfigError(f"SQL warehouse named {name!r} not found or not visible to this identity")


def _make_user_api_factory(settings: Settings, host: str | None) -> Callable[[str], Any]:
    """WP-P5: a fresh, uncached statement API for one user token (Bearer). Same host and
    retry budget as the service principal path; the token lives only in this call's Config."""

    def factory(token: str) -> Any:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.core import Config

        cfg = Config(
            host=host,
            token=token,
            auth_type="pat",
            retry_timeout_seconds=settings.databricks_retry_timeout_s,
            http_timeout_seconds=60,
        )
        client = WorkspaceClient(config=cfg)
        api = client.statement_execution

        def close() -> None:
            base = getattr(getattr(client, "api_client", None), "_api_client", None)
            session = getattr(base, "_session", None)
            if session is not None:
                session.close()

        api._supervisor_close = close  # noqa: SLF001 - closed by the executor after the call
        return api

    return factory


def build_databricks_executor(
    settings: Settings, client: Any | None = None
) -> DatabricksRestExecutor:
    client = client or make_workspace_client(settings)
    identity = (
        "service_principal"
        if settings.supervisor_mode == "databricks_app"
        or settings.databricks_auth_kind == "service_principal"
        else "user"
    )
    host = getattr(getattr(client, "config", None), "host", None) or settings.databricks_host
    return DatabricksRestExecutor(
        client.statement_execution,
        warehouse_id=resolve_warehouse_id(client, settings),
        catalog=str(settings.databricks_catalog),
        schema=str(settings.databricks_schema),
        table_prefix=settings.table_prefix,
        deadline_s=float(settings.databricks_statement_deadline_s),
        host=host,
        identity=identity,
        user_api_factory=(
            _make_user_api_factory(settings, host) if settings.sql_user_token_forward else None
        ),
    )
