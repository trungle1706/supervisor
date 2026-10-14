"""Review findings: canary/echo never in evidence, small-gap disagreement, tier-2 challenger,
coverage gap."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.adapters.factory import make_judge_chat_model
from supervisor.adapters.llm.errors import LLMTimeoutError
from supervisor.config import load_settings
from supervisor.judge.mockjudge import SCENARIOS, MockJudgeChat
from supervisor.judge.router import JudgeRouter
from supervisor.judge.service import JudgeService
from tests.judge.conftest import make_events
from tests.judge.test_service import BENIGN, chat, make_service


class Fixed(MockJudgeChat):
    """Returns one fixed reply (may be schema-invalid) on every call."""

    def __init__(self, reply: Mapping[str, Any], **kw: Any) -> None:
        super().__init__(1, **kw)
        self.reply = reply

    def complete_json(self, messages: Sequence[Mapping[str, str]], json_schema, timeout_s=None):  # type: ignore[override]
        return dict(self.reply)


def test_small_gap_flag_and_clear_still_defers_to_trusted(clock, evidence) -> None:
    base = SCENARIOS["clean"][0]
    t1 = chat(1, "t1", [{**base, "suspicion_bp": 5200, "label": "policy_violation"}])
    t2 = chat(2, "t2", [{**base, "suspicion_bp": 4900}])
    out = make_service(clock, evidence=evidence, t1=t1, t2=t2).evaluate_trace(make_events(BENIGN))
    assert out.disagree and out.final_action == "alert" and out.disagreement_bp == 300
    assert evidence.of_type("judge_verdict")[1]["large_gap"] is False


def test_canary_in_invalid_reply_is_still_manipulation(clock) -> None:
    t1 = Fixed({"verdict": "CANARY-0123456789ABCDEF"}, model_id="mock-raw")
    svc = make_service(
        clock, t1=t1, judge_kwargs={"canary_factory": lambda: "CANARY-0123456789ABCDEF"}
    )
    out = svc.evaluate_trace(make_events(BENIGN))
    assert out.t1.status == "canary_leak" and out.t1.label == "judge_manipulation"


def test_error_field_never_echoes_model_output(clock, evidence) -> None:
    echo = {**SCENARIOS["clean"][0], "label": "CANARY-0123456789ABCDEF Nguyễn Văn An"}
    svc = make_service(
        clock,
        evidence=evidence,
        t1=Fixed(echo, model_id="mock-bad"),
        judge_kwargs={"canary_factory": lambda: "CANARY-FFFF0000FFFF0000"},
    )
    out = svc.evaluate_trace(make_events(BENIGN))
    assert out.t1.status == "invalid_output" and out.t1.error == "JudgeOutputError"
    blob = str(evidence.entries)
    assert "Nguyễn" not in blob and "0123456789ABCDEF" not in blob


def test_challenger_on_tier2(clock, evidence) -> None:
    settings = load_settings(
        judge_t2_sample_bp=10000, judge_challenger_tier=2, judge_challenger_sample_bp=10000
    )
    chats = {"t1": chat(1, "t1"), "t2": chat(2, "t2"), "challenger": chat(2, "c2", family="x")}
    router = JudgeRouter.from_settings(settings, chats=chats)
    out = JudgeService(router, clock, evidence=evidence).evaluate_trace(make_events(BENIGN))
    assert out.t2 is not None and out.challengers[0].tier == 2
    row = [p for p in evidence.of_type("judge_verdict") if p["role"] == "challenger"][0]
    assert row["checker_id"] == "judge.t2.challenger" and row["acted_on"] is False
    assert "challenger_vs_primary_bp" in row


def test_mock_challenger_tier_follows_settings() -> None:
    chat2 = make_judge_chat_model(load_settings(judge_challenger_tier=2), "challenger")
    assert isinstance(chat2, MockJudgeChat) and chat2.tier == 2


def test_both_tiers_unavailable_is_a_logged_gap(clock, evidence) -> None:
    down = [LLMTimeoutError("down")] * 4
    svc = make_service(clock, evidence=evidence, t1=chat(1, "t1", down), t2=chat(2, "t2", down))
    out = svc.evaluate_trace(make_events(BENIGN))
    assert out.final_label == "coverage_gap" and out.final_action == "log"
    statuses = [p["status"] for p in evidence.of_type("judge_verdict")]
    assert statuses == ["unavailable", "unavailable"]
    assert all(p["error"] == "LLMTimeoutError" for p in evidence.of_type("judge_verdict"))
