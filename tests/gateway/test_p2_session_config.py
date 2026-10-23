"""WP-P2: an inconsistent monitors.session block fails at policy load, not at run time."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from supervisor.gateway.policy import PolicyError, load_policy_texts

WEIGHTS = {
    "findings": 600, "refusals": 1500, "expand": 1300, "drift": 800, "money": 2000,
    "near_dup": 800, "timing": 100, "cross_agent": 1300, "memory": 1400, "split_cue": 200,
}  # fmt: skip


def load(session: dict[str, Any]) -> Any:
    doc = {
        "policy_version": 1,
        "tools": {"pay": "money"},
        "agents": {
            "payops": {
                "name": "Payops",
                "owner_user": "u",
                "owner_team": "t",
                "monitors": {"session": session},
            }
        },
    }
    return load_policy_texts([("p.yaml", yaml.safe_dump(doc))])


BASE = {"k": 3, "case_threshold_bp": 1800, "pause_threshold_bp": 2000, "pause_scope": ["money"]}


def test_a3_fragment_shape_loads() -> None:
    assert load({**BASE, "weights": WEIGHTS}).doc.agents["payops"].monitors is not None


def test_findings_weight_at_or_above_the_pause_threshold_fails_at_load() -> None:
    with pytest.raises(PolicyError, match="findings weight .* below pause_threshold_bp"):
        load({**BASE, "weights": {**WEIGHTS, "findings": 2000, "money": 600}})


def test_default_weights_are_checked_when_weights_are_left_out() -> None:
    # default findings weight is 1800; a pause threshold of 1700 is below it
    with pytest.raises(PolicyError, match="findings weight"):
        load({"case_threshold_bp": 1000, "pause_threshold_bp": 1700, "pause_scope": ["money"]})


def test_pause_threshold_below_the_default_case_threshold_fails_at_load() -> None:
    with pytest.raises(PolicyError, match="must not be below case_threshold_bp"):
        load({"pause_threshold_bp": 2000, "pause_scope": ["money"]})


def test_case_only_block_is_not_constrained_by_the_pause_rules() -> None:
    assert load({"pause_threshold_bp": 300, "case_threshold_bp": 200})  # no pause_scope
