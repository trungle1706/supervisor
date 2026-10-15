"""Adapter factory: Settings -> concrete adapters. The only place that picks backends."""

from __future__ import annotations

from dataclasses import dataclass

from supervisor.adapters.clock import SystemClock
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.config import Settings
from supervisor.core.ports import ChatModel, Clock, Masker, SqlExecutor
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
    if settings.llm_uses_workspace_auth:
        # WP10: the bound serving endpoint, authenticated as the App's own identity.
        from supervisor.databricks.serving import DatabricksServingChat

        return DatabricksServingChat.from_settings(settings)
    from supervisor.adapters.llm.openai_compatible import OpenAICompatibleChat

    return OpenAICompatibleChat.from_settings(settings)


def make_masker(settings: Settings) -> Masker | None:
    """WP4: the Masker for capture and judges. ``vn_regex`` (default) uses the HMAC key from
    MASK_HMAC_KEY (dev key when unset, mask_version ``vn_regex-2:dev``); ``presidio`` is an
    optional extra; ``none`` returns None (recorder then stores digests only)."""
    if settings.masker_kind == "none":
        return None
    if settings.masker_kind == "presidio":
        from supervisor.adapters.masking.presidio import PresidioMasker

        return PresidioMasker()
    from supervisor.adapters.masking.vn_regex import VnRegexMasker

    key, key_id = settings.mask_key
    return VnRegexMasker(key, key_id)


def make_judge_chat_model(settings: Settings, role: str) -> ChatModel:
    """WP5: ChatModel for one judge role (``t1``, ``t2`` or ``challenger``).

    MockJudge (deterministic, ``mock`` in model_id) when ``JUDGE_<ROLE>_MODEL`` is empty
    or ``LLM_MOCK=1``; else the OpenAI-compatible adapter at ``JUDGE_<ROLE>_BASE_URL``
    (default ``LLM_BASE_URL``) with ``JUDGE_API_KEY`` (default ``LLM_API_KEY``)."""
    if role not in ("t1", "t2", "challenger"):
        raise ValueError(f"unknown judge role {role!r}")
    model = getattr(settings, f"judge_{role}_model")
    family = getattr(settings, f"judge_{role}_family")
    if not model or settings.llm_mock:
        from supervisor.judge.mockjudge import MockJudgeChat

        tier = (
            settings.judge_challenger_tier if role == "challenger" else (2 if role == "t2" else 1)
        )
        return MockJudgeChat(
            tier=tier,
            family=family or "mock",
            model_id=f"mock-judge-{role}-v1",
        )
    from supervisor.adapters.llm.openai_compatible import OpenAICompatibleChat

    base_url = getattr(settings, f"judge_{role}_base_url") or settings.llm_base_url
    secret = settings.judge_api_key or settings.llm_api_key
    return OpenAICompatibleChat(
        base_url,
        model,
        api_key=secret.get_secret_value() if secret else None,
        timeout_s=settings.judge_timeout_s,
        max_tokens=min(settings.llm_max_tokens, 2048),
        family=family,
    )
