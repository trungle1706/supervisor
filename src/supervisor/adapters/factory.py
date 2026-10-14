"""Adapter factory: Settings -> concrete adapters. The only place that picks backends."""

from __future__ import annotations

from dataclasses import dataclass

from supervisor.adapters.clock import SystemClock
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.config import Settings
from supervisor.core.ports import ChatModel, Clock, SqlExecutor
from supervisor.core.schema import SchemaModel, load_model


@dataclass
class Adapters:
    settings: Settings
    executor: SqlExecutor
    tables: SqlTableStore
    state: SqlStateStore
    clock: Clock
    model: SchemaModel

    def close(self) -> None:
        self.executor.close()


def build_sql_executor(settings: Settings) -> SqlExecutor:
    backend = settings.effective_sql_backend
    if backend == "sqlite":
        from supervisor.adapters.sql.sqlite import SqliteExecutor

        assert settings.sqlite_path is not None
        return SqliteExecutor(settings.sqlite_path, table_prefix=settings.table_prefix)
    from supervisor.adapters.sql.databricks_rest import build_databricks_executor

    return build_databricks_executor(settings)


def build_adapters(
    settings: Settings,
    *,
    executor: SqlExecutor | None = None,
    clock: Clock | None = None,
) -> Adapters:
    executor = executor or build_sql_executor(settings)
    clock = clock or SystemClock()
    model = load_model()
    return Adapters(
        settings=settings,
        executor=executor,
        tables=SqlTableStore(executor, model),
        state=SqlStateStore(executor, clock, model),
        clock=clock,
        model=model,
    )


def make_chat_model(settings: Settings) -> ChatModel:
    """WP2: MockChat when LLM_BASE_URL is empty or LLM_MOCK=1, else the OpenAI-compatible
    adapter (httpx). Never logs the API key."""
    if not settings.llm_base_url or settings.llm_mock:
        from supervisor.adapters.llm.mock import MockChat

        return MockChat()
    from supervisor.adapters.llm.openai_compatible import OpenAICompatibleChat

    return OpenAICompatibleChat.from_settings(settings)
