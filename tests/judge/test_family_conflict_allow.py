"""WP-L2: JUDGE_FAMILY_CONFLICT_ALLOW, an opt-in for single-model workspaces."""

from __future__ import annotations

import logging

import pytest

from supervisor.adapters.guard.factory import check_guard_family
from supervisor.config import load_settings
from supervisor.judge.router import (
    FamilyConflictError,
    JudgeModel,
    JudgeRouter,
    check_family_independence,
)
from supervisor.judge.service import JudgeService
from supervisor.monitors.quality import QualityScorer
from tests.judge.conftest import assert_no_floats, make_events
from tests.judge.test_router import FakeChat
from tests.judge.test_service import BENIGN, chat


def _judge() -> JudgeModel:
    return JudgeModel(1, "primary", FakeChat("glm-5-1", "glm"), "local")


def test_off_path_still_raises() -> None:
    assert load_settings(_env_file=None).judge_family_conflict_allow is False
    with pytest.raises(FamilyConflictError, match="same as agent"):
        check_family_independence([_judge()], {"payments": "glm"})
    with pytest.raises(FamilyConflictError):
        check_guard_family("glm-5-1", "glm", {"payments": "glm"})


def test_on_path_no_raise_one_warning_per_pair(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="supervisor.judge.router"):
        got = check_family_independence(
            [_judge()], {"a": "glm", "b": ["glm"], "c": "llama"}, allow_conflict=True
        )
    assert got == [("judge.t1.primary", "a"), ("judge.t1.primary", "b")]
    msgs = [r.getMessage() for r in caplog.records if "family conflict allowed" in r.getMessage()]
    assert len(msgs) == 2


def test_unknown_family_still_raises_when_allowed() -> None:
    j = JudgeModel(1, "primary", FakeChat("bank-7b", "unknown"), "local")
    with pytest.raises(FamilyConflictError):
        check_family_independence([j], {"a": "glm"}, allow_conflict=True)


def test_guard_and_quality_allowed(caplog: pytest.LogCaptureFixture, clock) -> None:
    with caplog.at_level(logging.WARNING):
        check_guard_family("glm-5-1", "glm", {"payments": "glm"}, allow_conflict=True)
        QualityScorer(
            FakeChat("glm-5-1", "glm"),
            clock,
            agent_families={"payments": "glm"},
            allow_family_conflict=True,
        )
    assert sum("family conflict allowed" in r.getMessage() for r in caplog.records) == 2


def test_setting_from_env_and_databricks_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_FAMILY_CONFLICT_ALLOW", "1")
    s = load_settings(_env_file=None)
    assert s.judge_family_conflict_allow is True
    s2 = load_settings(_env_file=None, supervisor_mode="databricks_app")
    assert s2.judge_family_conflict_allow is True


def _svc(clock, tables, evidence, allow: bool) -> JudgeService:
    s = load_settings(_env_file=None, judge_t2_sample_bp=0, judge_family_conflict_allow=allow)
    chats = {"t1": chat(1, "t1"), "t2": chat(2, "t2")}
    router = JudgeRouter.from_settings(s, chats=chats, agent_families={"payments": "mock"})
    return JudgeService(router, clock, tables=tables, evidence=evidence)


def test_verdict_evidence_carries_reduced_independence(clock, tables, evidence) -> None:
    with pytest.raises(FamilyConflictError):
        _svc(clock, tables, evidence, False)
    svc = _svc(clock, tables, evidence, True)
    svc.evaluate_trace(make_events(BENIGN))
    (payload,) = evidence.of_type("judge_verdict")
    assert payload["independence"] == "reduced" and payload["family_conflict"] is True
    assert_no_floats(payload)


def test_no_conflict_fields_when_families_differ(clock, tables, evidence) -> None:
    s = load_settings(_env_file=None, judge_t2_sample_bp=0, judge_family_conflict_allow=True)
    router = JudgeRouter.from_settings(
        s, chats={"t1": chat(1, "t1"), "t2": chat(2, "t2")}, agent_families={"payments": "llama"}
    )
    JudgeService(router, clock, tables=tables, evidence=evidence).evaluate_trace(
        make_events(BENIGN)
    )
    (payload,) = evidence.of_type("judge_verdict")
    assert "independence" not in payload and "family_conflict" not in payload
