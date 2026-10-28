"""WP-G1: the adapter turns a live definition into a detector of the existing contract."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from supervisor.core.detectors import Detector, Finding
from supervisor.guardian_factory.adapter import build, evaluate_policy, to_detector
from supervisor.guardian_factory.definition import (
    GuardianDefinition,
    GuardianFactoryError,
    validate_definition,
)

from .conftest import FakeChat, regex_def


def definition(state: str = "live", **over: Any) -> GuardianDefinition:
    data = regex_def(**over)
    data["created_by"] = "u"
    data["lifecycle"] = {**data.get("lifecycle", {}), "state": state}
    return validate_definition(data)


def payload(**parts: Any) -> dict[str, Any]:
    return {"meta": {"agent_id": "a1", "tool_name": "transfer", "risk_class": "money"}, **parts}


def run(det: Any, pl: dict[str, Any], direction: str = "input") -> list[Finding]:
    return det.evaluate(pl, {}, direction)


def test_regex_detector_masks_a_sample_and_follows_the_contract() -> None:
    det = to_detector(definition())
    assert isinstance(det, Detector)
    assert det.slug == "guardian_account_numbers" and det.sides == ("input",)
    out = run(det, payload(args={"note": "chuyen den tai khoan 190312345678 nhe", "n": 5}))
    assert len(out) == 1
    f = out[0]
    assert f.fired and f.action_hint == "transform" and f.code == "guardian.account-numbers"
    assert f.transformed_payload == {"args": {"note": "chuyen den tai khoan <ACCOUNT> nhe", "n": 5}}
    assert "190312345678" not in str(f.to_dict())  # the finding holds masked text only
    assert f.fragments[0].text == "<ACCOUNT>"
    assert run(det, payload(args={"note": "don hang 123"})) == []


def test_regex_preserve_length() -> None:
    d = definition(config={"pattern": r"\d{9,14}", "preserve_length": True})
    f = run(to_detector(d), payload(args={"x": "so 123456789 het"}))[0]
    assert f.transformed_payload == {"args": {"x": "so ********* het"}}


def test_log_and_block_hints() -> None:
    assert (
        run(to_detector(definition(action_on_fail="log")), payload(args={"x": "123456789"}))[
            0
        ].action_hint
        == "report"
    )
    f = run(to_detector(definition(action_on_fail="block")), payload(args={"x": "123456789"}))[0]
    assert f.action_hint == "block" and f.transformed_payload is None
    f = run(
        to_detector(definition(action_on_fail="require_approval")), payload(args={"x": "123456789"})
    )[0]
    assert f.action_hint == "pause"


def test_output_stage_reads_output() -> None:
    det = to_detector(definition(stage="output"))
    assert det.sides == ("output",)
    f = run(det, payload(output="so tai khoan 190312345678"), "output")[0]
    assert f.transformed_payload == {"output": "so tai khoan <ACCOUNT>"}


def test_keyword_detector() -> None:
    d = definition(
        type="keyword_list",
        config={"words": ["Chuyển khoản gấp", "mã bí mật"], "mask_token": "<WORD>"},
    )
    f = run(to_detector(d), payload(args={"m": "Cần CHUYỂN KHOẢN GẤP và mã bí mật nhé"}))[0]
    assert f.transformed_payload == {"args": {"m": "Cần <WORD> và <WORD> nhé"}}
    assert f.masked_count == 2
    assert run(to_detector(d), payload(args={"m": "xin chao"})) == []


POLICY = {
    "rules": [
        {
            "id": "big",
            "when": [
                {"kind": "tool", "op": "eq", "value": "transfer"},
                {"kind": "amount", "op": "gt", "name": "amount", "value": 50_000_000},
            ],
            "then": "forbid",
        },
        {
            "id": "vip",
            "when": [{"kind": "argument", "op": "eq", "name": "tier", "value": "vip"}],
            "then": "permit",
        },
        {
            "id": "pii",
            "when": [{"kind": "data_class", "op": "in", "value": ["pii", "pii_export"]}],
            "then": "forbid",
        },
    ]
}


def test_policy_evaluator_is_deterministic() -> None:
    d = definition(type="policy", action_on_fail="block", config=POLICY)
    meta = {"tool_name": "transfer", "risk_class": "money"}
    assert evaluate_policy(d, {"amount": 60_000_000}, meta) == (False, "big")
    assert evaluate_policy(d, {"amount": 50_000_000}, meta) == (True, None)  # not over the cap
    assert evaluate_policy(d, {"amount": 60_000_000.0}, meta)[0] is True  # a float never matches
    assert evaluate_policy(d, {"amount": True}, meta)[0] is True  # nor a bool
    assert evaluate_policy(d, {"tier": "vip"}, {"tool_name": "x"}) == (True, "vip")
    assert evaluate_policy(d, {}, {"risk_class": "pii"}) == (False, "pii")


def test_policy_detector_and_default_forbid() -> None:
    det = to_detector(definition(type="policy", action_on_fail="block", config=POLICY))
    f = run(det, payload(args={"amount": 60_000_000}))[0]
    assert f.action_hint == "block" and f.code == "guardian.account-numbers.big"
    assert run(det, payload(args={"amount": 1})) == []
    strict = {**POLICY, "default": "forbid"}
    det = to_detector(definition(type="policy", action_on_fail="log", config=strict))
    assert run(det, payload(args={"amount": 1}))[0].code.endswith(".default")


def test_classifier_delegates_with_the_threshold_and_only_reports() -> None:
    class Inner:
        parts = ("args",)

        def __init__(self) -> None:
            self.seen: dict[str, Any] = {}

        def evaluate(self, pl: Any, settings: Any, direction: str) -> list[Finding]:
            self.seen = dict(settings)
            return [
                Finding("guard_model", "guard_model@1", "x", score_bp=8000, threshold_bp=7000),
                Finding("guard_model", "guard_model@1", "y", score_bp=100, threshold_bp=7000),
            ]

    inner = Inner()
    d = definition(
        type="classifier",
        action_on_fail="require_approval",
        config={"model_ref": "guard_model", "threshold_bp": 7000},
    )
    out = run(build(d, delegates={"guard_model": inner}), payload(args={"x": "hi"}))
    assert inner.seen == {"threshold_bp": 7000}
    assert [f.score_bp for f in out] == [8000] and out[0].action_hint == "pause"
    gone = run(build(d, delegates={}), payload(args={"x": "hi"}))
    assert gone[0].not_executed_reason == "execution_failed"


def test_judge_prompt_detector() -> None:
    cfg = {
        "prompt": "Does the text threaten the customer?",
        "verdict_labels": ["ok", "threat"],
        "fail_labels": ["threat"],
    }
    d = definition(type="judge_prompt", action_on_fail="log", config=cfg)
    chat = FakeChat({"label": "threat", "score_bp": 9000})
    out = run(build(d, chat=chat), payload(args={"m": "pay or else"}))
    assert out[0].action_hint == "report" and out[0].score_bp == 9000
    assert (
        run(build(d, chat=FakeChat({"label": "ok", "score_bp": 10})), payload(args={"m": "hi"}))
        == []
    )
    bad = run(build(d, chat=FakeChat({"label": "weird", "score_bp": 1})), payload(args={"m": "x"}))
    assert bad[0].not_executed_reason == "execution_failed"  # a gap, never a pass
    none = run(build(d), payload(args={"m": "x"}))
    assert none[0].not_executed_reason == "execution_failed"


def test_only_a_live_definition_becomes_a_detector() -> None:
    for state in ("draft", "shadow", "retired"):
        with pytest.raises(GuardianFactoryError) as e:
            to_detector(definition(state=state))
        assert e.value.code == "not_live"
    assert build(definition(state="draft")) is not None  # G2 and G3 build from other states


def test_scope_and_allow_list_expiry() -> None:
    d = definition(scope={"agents": ["a1"], "tools": ["transfer"], "data_classes": ["money"]})
    det = to_detector(d)
    hit = payload(args={"x": "123456789"})
    assert run(det, hit)
    assert run(det, {**hit, "meta": {**hit["meta"], "agent_id": "other"}}) == []
    assert run(det, {**hit, "meta": {**hit["meta"], "tool_name": "other"}}) == []
    assert run(det, {**hit, "meta": {**hit["meta"], "risk_class": "credit"}}) == []

    allow = [{"agent_id": "a1", "reason": "approved test", "expires": "2026-12-31"}]
    d2 = definition(lifecycle={"allow_list": allow})
    assert run(to_detector(d2, today=lambda: dt.date(2026, 12, 31)), hit) == []  # still valid
    assert run(to_detector(d2, today=lambda: dt.date(2027, 1, 1)), hit)  # expired: it runs again


def test_a_failure_inside_is_reported_not_raised() -> None:
    det = to_detector(definition())
    det.d.config["pattern"] = "("  # cannot compile
    out = run(det, payload(args={"x": "123456789"}))
    assert out[0].not_executed_reason == "execution_failed"
