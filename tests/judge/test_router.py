"""Router: family independence (CI check on committed manifests), pinning, sampling."""

from __future__ import annotations

import pytest

from supervisor.adapters.factory import make_judge_chat_model
from supervisor.adapters.llm.mock import MockChat
from supervisor.config import load_settings
from supervisor.core.errors import ConfigError
from supervisor.judge.mockjudge import MockJudgeChat
from supervisor.judge.router import (
    FamilyConflictError,
    JudgeModel,
    JudgeRouter,
    check_family_independence,
    load_manifest_families,
    load_registry_families,
    normalize_family,
    sample_hit,
)
from tests.judge.conftest import MemoryTables


class FakeChat:
    """A non-mock ChatModel stand-in (never called in these tests)."""

    is_mock = False

    def __init__(self, model_id: str, family: str) -> None:
        self.model_id, self.family = model_id, family

    def complete_json(self, messages, json_schema, timeout_s):  # pragma: no cover
        raise AssertionError("not called")


def test_ci_family_check_on_committed_manifests_and_settings() -> None:
    """CI gate: the committed manifests + default settings must pass the family rule."""
    families = load_manifest_families()
    assert {"payments", "customer_service", "credit_prequal"} <= set(families)
    assert all(families.values()), "every manifest must declare model_family"
    router = JudgeRouter.from_settings(load_settings())
    check_family_independence([router.t1, router.t2], families)
    for j in (router.t1, router.t2):
        assert j.family not in {normalize_family(f) for f in families.values()}


def test_ci_family_check_on_env_configured_judges(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the owner configures real judges, the same rule runs on their names."""
    monkeypatch.setenv("JUDGE_T1_MODEL", "gpt-5.4-mini-2026-08-01")
    monkeypatch.setenv("JUDGE_T2_MODEL", "claude-opus-5-5")
    router = JudgeRouter.from_settings(load_settings())
    assert (router.t1.family, router.t2.family) == ("openai", "anthropic")
    assert not router.is_mock and router.t1.model_version == "gpt-5.4-mini-2026-08-01"


def test_same_family_as_agent_raises_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_T1_MODEL", "qwen3:8b")  # agents run qwen3:4b
    with pytest.raises(FamilyConflictError, match="same as agent"):
        JudgeRouter.from_settings(load_settings())


def test_family_aliases_count_as_same() -> None:
    j = JudgeModel(1, "primary", FakeChat("claude-haiku-5-5", "claude"), "local")
    with pytest.raises(FamilyConflictError):
        check_family_independence([j], {"a": "anthropic"})
    check_family_independence([j], {"a": "qwen", "b": ["openai", "meta"]})


def test_unknown_family_needs_explicit_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_T2_MODEL", "bank-judge-7b-v3")
    with pytest.raises(FamilyConflictError, match="JUDGE_T2_FAMILY"):
        JudgeRouter.from_settings(load_settings())
    monkeypatch.setenv("JUDGE_T2_FAMILY", "mistral")
    assert JudgeRouter.from_settings(load_settings()).t2.family == "mistral"


def test_registry_rows_are_checked_too() -> None:
    tables = MemoryTables()
    tables.append("agent_version", [{"agent_id": "new_agent", "model_family": "mock"}])
    assert load_registry_families(tables=tables) == {"new_agent": {"mock"}}
    with pytest.raises(FamilyConflictError, match="new_agent"):
        JudgeRouter.from_settings(load_settings(), tables=tables)


def test_latest_alias_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_T1_MODEL", "llama3.1:latest")
    with pytest.raises(ConfigError, match="not pinned"):
        JudgeRouter.from_settings(load_settings())


def test_mock_when_unset_and_labelled() -> None:
    s = load_settings()
    for role in ("t1", "t2", "challenger"):
        chat = make_judge_chat_model(s, role)
        assert isinstance(chat, MockJudgeChat) and chat.is_mock and "mock" in chat.model_id
    with pytest.raises(ValueError):
        make_judge_chat_model(s, "t3")


def test_remote_judge_url_needs_opt_in() -> None:
    with pytest.raises(ConfigError):
        load_settings(judge_t1_base_url="https://judge.example.invalid/v1")
    load_settings(judge_t1_base_url="https://judge.example.invalid/v1", llm_allow_remote=True)


def test_judge_disabled_by_default() -> None:
    assert load_settings().judge_enabled is False


def test_sample_hit_rate_and_determinism() -> None:
    hits = [sample_hit("s", f"trace-{i}", 500) for i in range(20000)]
    assert hits == [sample_hit("s", f"trace-{i}", 500) for i in range(20000)]
    assert 800 <= sum(hits) <= 1200  # about 5 %
    assert not sample_hit("s", "x", 0) and sample_hit("s", "x", 10000)


def test_challenger_sampling_default_five_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    challenger = MockChat(family="mock-challenger", model_id="mock-challenger-v1")
    router = JudgeRouter.from_settings(load_settings(), chats={"challenger": challenger})
    assert router.challenger is not None and router.challenger.role == "challenger"
    assert router.challenger.checker_id == "judge.t1.challenger"
    picked = [t for t in (f"tr-{i}" for i in range(4000)) if router.challenger_for(1, t)]
    assert 140 <= len(picked) <= 260
    assert router.challenger_for(2, picked[0]) is None  # challenger is bound to its tier
