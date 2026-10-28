"""WP-G1: the definition schema. Every rule names its field; regex checks are the existing ones."""

from __future__ import annotations

import json
from typing import Any

import pytest

from supervisor.detectors.dlp_extras import regex_problems
from supervisor.guardian_factory import caps
from supervisor.guardian_factory.definition import (
    GuardianFactoryError,
    json_schema,
    validate_definition,
)
from supervisor.guardian_factory.patterns import LIBRARY

from .conftest import regex_def


def fields_of(data: dict[str, Any]) -> list[str]:
    with pytest.raises(GuardianFactoryError) as e:
        validate_definition({"created_by": "u", **data})
    assert e.value.code == "invalid_definition"
    return [p["field"] for p in e.value.problems]


def ok(**over: Any) -> Any:
    return validate_definition({"created_by": "u", **regex_def(**over)})


def test_valid_regex_definition_is_normalised() -> None:
    d = ok()
    assert d.config == {
        "pattern": r"(?<!\d)\d{9,14}(?!\d)",
        "mask_token": "<ACCOUNT>",
        "preserve_length": False,
    }
    assert d.lifecycle.state == "draft" and d.thresholds.min_tpr_pct == 90


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"id": "Bad_Id"}, "id"),
        ({"id": "x" * 65}, "id"),
        ({"id": "new"}, "id"),
        ({"name": ""}, "name"),
        ({"name": "n" * 65}, "name"),
        ({"owner_group": "nobody"}, "owner_group"),
        ({"type": "magic"}, "type"),
        ({"stage": "later"}, "stage"),
        ({"action_on_fail": "explode"}, "action_on_fail"),
        ({"sensitivity": 0}, "sensitivity"),
        ({"sensitivity": 5}, "sensitivity"),
        ({"benchmark_pack": "Bad Pack"}, "benchmark_pack"),
        ({"scope": {"agents": []}}, "scope.agents"),
        ({"scope": {"tools": ["bad tool"]}}, "scope.tools[0]"),
        ({"scope": {"data_classes": ["secret"]}}, "scope.data_classes[0]"),
        ({"thresholds": {"min_tpr_pct": 101}}, "thresholds.min_tpr_pct"),
        ({"thresholds": {"max_p95_ms": 0}}, "thresholds.max_p95_ms"),
        ({"lifecycle": {"shadow_days": 91}}, "lifecycle.shadow_days"),
        (
            {"lifecycle": {"allow_list": [{"agent_id": "a", "reason": "r", "expires": "soon"}]}},
            "lifecycle.allow_list[0].expires",
        ),
        (
            {
                "lifecycle": {
                    "allow_list": [{"agent_id": "a", "reason": "r", "expires": "2026-02-31"}]
                }
            },
            "lifecycle.allow_list[0].expires",
        ),
        ({"config": {"pattern": ""}}, "config.pattern"),
        ({"config": {"pattern": "a", "extra": 1}}, "config.extra"),
        ({"config": {"pattern": "a", "mask_token": "<PHONE:ab12>"}}, "config.mask_token"),
        ({"extra_field": 1}, "extra_field"),
    ],
)
def test_every_rule_names_its_field(over: dict[str, Any], field: str) -> None:
    assert field in fields_of(regex_def(**over))


def test_nested_repeat_is_refused_by_the_existing_checks() -> None:
    bad = r"(a+)+b"
    assert regex_problems(bad)  # the existing validator says no ...
    assert "config.pattern" in fields_of(regex_def(config={"pattern": bad}))  # ... and so does G1


def test_empty_match_and_back_reference_refused() -> None:
    assert "config.pattern" in fields_of(regex_def(config={"pattern": "a*"}))
    assert "config.pattern" in fields_of(regex_def(config={"pattern": r"(a)\1"}))


@pytest.mark.parametrize("type_", ["classifier", "judge_prompt"])
@pytest.mark.parametrize("action", ["block", "redact"])
def test_block_and_redact_refused_for_model_types(type_: str, action: str) -> None:
    cfg: dict[str, Any] = (
        {"model_ref": "guard_model", "threshold_bp": 7000}
        if type_ == "classifier"
        else {"prompt": "Is it rude?", "verdict_labels": ["ok", "rude"], "fail_labels": ["rude"]}
    )
    assert fields_of(regex_def(type=type_, action_on_fail=action, config=cfg)) == ["action_on_fail"]


@pytest.mark.parametrize("action", ["log", "require_approval"])
def test_model_types_may_log_or_ask_approval(action: str) -> None:
    ok(
        type="classifier",
        action_on_fail=action,
        config={"model_ref": "guard_model", "threshold_bp": 7000},
    )


@pytest.mark.parametrize("type_", ["regex", "keyword_list", "policy"])
@pytest.mark.parametrize("action", ["block", "redact"])
def test_deterministic_types_may_block_and_redact(type_: str, action: str) -> None:
    cfg = {
        "regex": {"pattern": "abc"},
        "keyword_list": {"words": ["abc"]},
        "policy": {
            "rules": [
                {"id": "r1", "when": [{"kind": "tool", "op": "eq", "value": "t"}], "then": "forbid"}
            ]
        },
    }[type_]
    ok(type=type_, action_on_fail=action, config=cfg)


def test_keyword_caps() -> None:
    ok(type="keyword_list", config={"words": ["a"] * 1 + ["b"]})
    f = fields_of(regex_def(type="keyword_list", config={"words": [f"w{i}" for i in range(501)]}))
    assert "config.words" in f
    assert "config.words[0]" in fields_of(
        regex_def(type="keyword_list", config={"words": ["x" * 81]})
    )
    assert "config.words" in fields_of(regex_def(type="keyword_list", config={"words": []}))
    assert "config.words[1]" in fields_of(
        regex_def(type="keyword_list", config={"words": ["a", "A"]})
    )
    ok(type="keyword_list", config={"words": [f"w{i}" for i in range(500)]})


def test_classifier_model_ref_allow_list_and_integer_threshold() -> None:
    base = {"type": "classifier", "action_on_fail": "log"}
    assert "config.model_ref" in fields_of(
        regex_def(**base, config={"model_ref": "gpt-x", "threshold_bp": 5000})
    )
    assert "config.threshold_bp" in fields_of(
        regex_def(**base, config={"model_ref": "guard_model", "threshold_bp": 0.5})
    )
    assert "config.threshold_bp" in fields_of(
        regex_def(**base, config={"model_ref": "guard_model", "threshold_bp": 10001})
    )


def test_judge_prompt_caps() -> None:
    base = {"type": "judge_prompt", "action_on_fail": "log"}
    good = {
        "prompt": "Is it a complaint?",
        "verdict_labels": ["ok", "complaint"],
        "fail_labels": ["complaint"],
    }
    ok(**base, config=good)
    long = {**good, "prompt": "word " * 2001}
    assert "config.prompt" in fields_of(regex_def(**base, config=long))
    assert "config.verdict_labels" in fields_of(
        regex_def(**base, config={**good, "verdict_labels": ["only"], "fail_labels": ["only"]})
    )
    assert "config.fail_labels[0]" in fields_of(
        regex_def(**base, config={**good, "fail_labels": ["missing"]})
    )


def test_policy_structure_and_integer_amount() -> None:
    rule = {
        "id": "big_transfer",
        "when": [
            {"kind": "tool", "op": "eq", "value": "transfer"},
            {"kind": "amount", "op": "gt", "name": "amount", "value": 50_000_000},
        ],
        "then": "forbid",
    }
    ok(type="policy", config={"rules": [rule]})
    bad = {**rule, "when": [{"kind": "amount", "op": "gt", "name": "amount", "value": 1.5}]}
    assert "config.rules[0].when[0].value" in fields_of(
        regex_def(type="policy", config={"rules": [bad]})
    )
    dup = [rule, {**rule}]
    assert "config.rules[1].id" in fields_of(regex_def(type="policy", config={"rules": dup}))
    unknown = {**rule, "when": [{"kind": "mood", "op": "eq", "value": "x"}]}
    assert fields_of(regex_def(type="policy", config={"rules": [unknown]}))
    dc = {**rule, "when": [{"kind": "data_class", "op": "eq", "value": "secret"}]}
    assert "config.rules[0].when[0].value" in fields_of(
        regex_def(type="policy", config={"rules": [dc]})
    )


def test_json_schema_export_is_json_and_lists_each_type() -> None:
    s = json_schema()
    json.dumps(s)
    assert set(s["x-config-by-type"]) == set(caps.TYPES)
    assert s["properties"]["sensitivity"]["maximum"] == 4
    assert s["x-actions-by-type"]["classifier"] == ["log", "require_approval"]


def test_library_patterns_pass_the_existing_regex_checks() -> None:
    for p in LIBRARY:
        assert regex_problems(p.pattern) == [], p.id
