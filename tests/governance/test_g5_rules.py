"""WP-G5: the rules file (strict schema), matching and the pure, deterministic plan."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from supervisor.governance.actions_model import (
    ACTION_KINDS,
    FORBIDDEN_ACTIONS,
    GovernanceActionsError,
    GovernanceEvent,
    SystemFacts,
    event_key,
    load_rules,
    parse_rules,
    plan,
    rules_digest,
    safe_ref,
)

from .g5_support import STARTER, only, rule

AT = datetime(2026, 10, 22, 11, 0, tzinfo=UTC)


def ev(kind: str = "alert", severity: str = "critical", **over: Any) -> GovernanceEvent:
    base: dict[str, Any] = {
        "kind": kind,
        "severity": severity,
        "agent_id": "agent-a",
        "ref": "alert:al_1",
        "at": AT,
        "system_id": "sys_1",
        "rule_id": "AL-SECRETS-OUTPUT",
    }
    return GovernanceEvent(**{**base, **over})


def test_the_starter_file_loads_and_covers_the_listed_cases() -> None:
    rules = load_rules(STARTER)
    assert len(rules) >= 20
    alert_rules = {r.alert_rule for r in rules if r.alert_rule}
    nine = {
        "AL-COVERAGE-GAP",
        "AL-DETECTOR-FAILED",
        "AL-THREAT-NOT-ENFORCED",
        "AL-SECRETS-OUTPUT",
        "AL-PII-OUTPUT",
        "AL-REDACTION-SPIKE",
        "AL-LATENCY-DEGRADATION",
        "AL-ERROR-RATE",
        "AL-INGRESS-AUTH-ANOMALY",
    }
    assert nine <= alert_rules
    kinds = {r.kind for r in rules}
    assert {"chain_break", "pack_no_go"} <= kinds
    for r in rules:  # no rule can pause or block
        assert set(r.actions) <= set(ACTION_KINDS)


def test_the_starter_alert_rules_exist_in_the_alert_rules_file() -> None:
    from supervisor.alerts import load_rules as load_alert_rules

    from .g5_support import STARTER as S

    ids = {r.id for r in load_alert_rules(S.parent / "alerts.yaml").rules}
    for r in load_rules(S):
        if r.alert_rule:
            assert r.alert_rule in ids, r.alert_rule


@pytest.mark.parametrize(
    ("doc", "text"),
    [
        ({"version": 1, "rules": [{"id": "A", "kind": "alert"}]}, "min_severity"),
        (
            {"version": 1, "rules": [rule("alert", ["create_incident"], colour="red")]},
            "unknown key 'colour'",
        ),
        ({"version": 1, "rules": [rule("weird", ["create_incident"])]}, "kind must be one of"),
        (
            {"version": 1, "rules": [rule("alert", ["create_incident"], min_severity="urgent")]},
            "min_severity",
        ),
        ({"version": 1, "rules": [rule("alert", [])]}, "actions"),
        ({"version": 1, "rules": [rule("alert", ["send_pager"])]}, "is not one of"),
        (
            {
                "version": 1,
                "rules": [rule("alert", ["create_incident"]), rule("alert", ["notify_owner"])],
            },
            "duplicate id",
        ),
        (
            {"version": 1, "rules": [rule("pack_no_go", ["create_incident"], alert_rule="AL-X")]},
            "only for kind alert",
        ),
        (
            {"version": 1, "rules": [rule("alert", ["create_incident"], controls=["CTL-1"])]},
            "reopen_control",
        ),
        (
            {
                "version": 1,
                "rules": [rule("alert", ["create_incident"], system_class={"colour": 1})],
            },
            "unknown key 'colour'",
        ),
        (
            {
                "version": 1,
                "rules": [
                    rule("alert", ["create_incident"], system_class={"autonomy_level_gte": "l9"})
                ],
            },
            "autonomy_level_gte",
        ),
        (
            {
                "version": 1,
                "rules": [
                    rule("alert", ["create_incident"], system_class={"risk_level": ["huge"]})
                ],
            },
            "risk_level",
        ),
        ({"version": 2, "rules": []}, "version must be 1"),
        ({"rules": [], "extra": 1}, "unknown top-level key"),
        ({"version": 1, "rules": "x"}, "rules must be a list"),
        ([], "mapping"),
    ],
)
def test_a_bad_rules_file_is_refused_with_a_message(doc: Any, text: str) -> None:
    with pytest.raises(GovernanceActionsError, match=text):
        parse_rules(doc)


@pytest.mark.parametrize("word", FORBIDDEN_ACTIONS)
def test_a_rule_can_never_pause_or_block(word: str) -> None:
    with pytest.raises(GovernanceActionsError, match="never pauses or blocks"):
        parse_rules({"version": 1, "rules": [rule("alert", ["create_incident", word])]})
    assert word not in ACTION_KINDS


def test_every_problem_is_listed_in_one_error() -> None:
    doc = {
        "version": 1,
        "rules": [rule("weird", []), rule("alert", ["create_incident"], rid="B", x=1)],
    }
    with pytest.raises(GovernanceActionsError) as exc:
        parse_rules(doc)
    msg = str(exc.value)
    assert "kind must be one of" in msg and "unknown key 'x'" in msg and "actions" in msg


def test_plan_is_deterministic_and_ordered() -> None:
    rules = only(
        [
            rule("alert", ["fire_webhook", "create_incident"], rid="B"),
            rule("alert", ["notify_owner", "create_incident", "reopen_control"], rid="A"),
        ]
    )
    e = ev()
    first = plan(e, rules, None)
    for _ in range(5):
        assert plan(e, list(reversed(rules)), None) == first
    assert [p.action for p in first] == [
        "create_incident",
        "notify_owner",
        "fire_webhook",
        "reopen_control",
    ]
    inc = next(p for p in first if p.action == "create_incident")
    assert inc.rules == ("A", "B")  # asked by two rules: one action, both rule ids


def test_the_rules_digest_is_stable_and_changes_with_the_rules() -> None:
    a = only([rule("alert", ["create_incident"])])
    b = only([rule("alert", ["create_incident"])])
    c = only([rule("alert", ["create_incident", "notify_owner"])])
    assert rules_digest(a) == rules_digest(b) != rules_digest(c)


def test_severity_kind_and_alert_rule_filters() -> None:
    rules = only(
        [
            rule("alert", ["create_incident"], rid="HIGH", min_severity="high"),
            rule(
                "alert", ["notify_owner"], rid="ONE", min_severity="low", alert_rule="AL-PII-OUTPUT"
            ),
            rule("chain_break", ["fire_webhook"], rid="CHAIN"),
        ]
    )
    assert [p.action for p in plan(ev(severity="medium"), rules, None)] == []
    assert [p.action for p in plan(ev(severity="high"), rules, None)] == ["create_incident"]
    pii = ev(severity="high", rule_id="AL-PII-OUTPUT")
    assert [p.action for p in plan(pii, rules, None)] == ["create_incident", "notify_owner"]
    assert plan(ev("chain_break", "critical", rule_id=""), rules, None)[0].action == "fire_webhook"


def test_a_disabled_rule_never_matches() -> None:
    rules = only([rule("alert", ["create_incident"], enabled=False)])
    assert plan(ev(), rules, None) == []


def test_actions_that_need_a_system_are_left_out_without_one() -> None:
    rules = only([rule("alert", list(ACTION_KINDS))])
    with_system = {p.action for p in plan(ev(), rules, None)}
    without = {p.action for p in plan(ev(system_id=None), rules, None)}
    assert with_system == set(ACTION_KINDS)
    assert without == {"create_incident", "notify_owner", "reopen_control"}


def test_system_class_filters() -> None:
    rules = only(
        [
            rule(
                "alert",
                ["create_incident"],
                rid="D33",
                system_class={"decision33_class": ["high_risk"]},
            ),
            rule(
                "alert",
                ["notify_owner"],
                rid="RISK",
                system_class={"risk_level": ["high", "prohibited"]},
            ),
            rule("alert", ["create_review"], rid="AUTO", system_class={"autonomy_level_gte": "l3"}),
        ]
    )

    def acts(facts: SystemFacts | None) -> list[str]:
        return [p.action for p in plan(ev(), rules, facts)]

    assert acts(None) == []  # a filter on the system needs a system
    assert acts(SystemFacts("not_high_risk", "low", 5)) == ["create_review"]
    assert acts(SystemFacts("high_risk", "high", 3)) == [
        "create_incident",
        "notify_owner",
        "create_review",
    ]
    assert acts(SystemFacts("high_risk", "low", 2)) == ["create_incident"]
    # no autonomy_level column yet (WP-G2 not merged): an autonomy filter does not match
    assert "create_review" not in acts(SystemFacts("high_risk", "high", None))


def test_event_key_and_refs() -> None:
    assert event_key("alert", "alert:a", "s1") == ev(ref="alert:a", system_id="s1").key
    assert event_key("alert", "alert:a", "s1") != event_key("alert", "alert:a", "s2")
    assert event_key("alert", "alert:a", None) != event_key("gate_stop", "alert:a", None)
    assert safe_ref("a b", "c@d") == "a_b:c@d"
    assert len(safe_ref("x" * 300)) <= 128
    with pytest.raises(GovernanceActionsError):
        GovernanceEvent("alert", "critical", "a", "bad ref", AT)
    with pytest.raises(GovernanceActionsError):
        GovernanceEvent("nope", "critical", "a", "ref", AT)
    with pytest.raises(GovernanceActionsError):
        GovernanceEvent("alert", "huge", "a", "ref", AT)
