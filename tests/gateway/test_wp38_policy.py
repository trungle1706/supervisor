"""WP38 (ADR D28): observe mode per agent, per-consumer override, gate order words.

Every sentence of docs/policy.md section 'Gate order' has a test here (the test name says which).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import yaml

from supervisor.adapters.factory import Adapters
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.core.detectors import derive_status
from supervisor.gateway.detector_gate import DetectorGate
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import (
    Policy,
    PolicyError,
    StorePolicyProvider,
    deploy_policy,
    load_deployed,
    load_policy_dir,
    load_policy_texts,
    policy_json_schema,
    valid_consumer_id,
)
from tests.conftest import REPO_ROOT
from tests.detectors.conftest import make_gate
from tests.detectors.fakes import FakeDetector, boom
from tests.gateway.conftest import MemoryEvidence

# Hash of policies/*.yaml on WP37 head (before any WP38 code). It must not move.
BASELINE_HASH = "673d764142d38e0db6dd8171c8471a16dd2b662577126296f3dfe55897c5aecd"

RULES = """
  - {id: R-LOG, version: 1, description: log rule, agent_scope: "*", action: log, severity: low,
     risk_class: read_only, owner: t, when: {tool: lookup, all: [{arg: tag, op: eq, value: log}]}}
  - {id: R-ALERT, version: 1, description: alert rule, agent_scope: "*", action: alert,
     severity: low, risk_class: read_only, owner: t,
     when: {tool: lookup, all: [{arg: tag, op: eq, value: alert}]}}
  - {id: R-READ-BLOCK, version: 1, description: read block, agent_scope: "*", action: block,
     severity: medium, risk_class: read_only, owner: t, approvals: [a1, a2],
     when: {tool: lookup, all: [{arg: tag, op: eq, value: bad}]}}
  - {id: R-PAY-BLOCK, version: 1, description: big pay, agent_scope: "*", action: block,
     severity: high, risk_class: money, owner: t, approvals: [a1, a2],
     when: {tool: pay, all: [{arg: amount_minor, op: gt, value: 100}]}}
  - {id: R-PAY-PAUSE, version: 1, description: huge pay, agent_scope: "*", action: pause,
     severity: critical, risk_class: money, owner: t, approvals: [a1, a2],
     when: {tool: pay, all: [{arg: amount_minor, op: gt, value: 1000}]}}
  - {id: R-LOG2, version: 1, description: second log, agent_scope: "*", action: log,
     severity: low, risk_class: money, owner: t,
     when: {tool: pay, all: [{arg: amount_minor, op: gt, value: 5}]}}
"""

AGENT = """
  {name}:
    name: {name}
    owner_user: u@example.invalid
    owner_team: T
    initial_state: {state}
{extra}"""


# The money rules scoped to agent "payer" only: every other agent has no money rule (WP38
# review: consumer observe and unapproved observe are refused for agents with money rules).
RULES_SCOPED = (
    RULES.replace(
        'R-PAY-BLOCK, version: 1, description: big pay, agent_scope: "*"',
        "R-PAY-BLOCK, version: 1, description: big pay, agent_scope: [payer]",
    )
    .replace(
        'R-PAY-PAUSE, version: 1, description: huge pay, agent_scope: "*"',
        "R-PAY-PAUSE, version: 1, description: huge pay, agent_scope: [payer]",
    )
    .replace(
        'R-LOG2, version: 1, description: second log, agent_scope: "*"',
        "R-LOG2, version: 1, description: second log, agent_scope: [payer]",
    )
)


def policy_text(agents: dict[str, tuple[str, str]] | None = None, rules: str = RULES) -> str:
    """agents: id -> (initial_state, extra yaml lines, already indented by 4)."""
    agents = dict(agents or {"a1": ("RUNNING", "")})
    if rules is RULES_SCOPED:
        agents.setdefault("payer", ("RUNNING", ""))
    body = "".join(AGENT.format(name=n, state=s, extra=e) for n, (s, e) in agents.items())
    return (
        f"policy_version: 1\ntools: {{lookup: read_only, pay: money}}\nagents:{body}\nrules:{rules}"
    )


def make(text: str) -> Policy:
    return load_policy_texts([("t.yaml", text)])


@pytest.fixture
def gw_for(adapters: Adapters, evidence: MemoryEvidence) -> Iterator[Any]:
    made: list[Gateway] = []

    def build(policy: Policy, gate: DetectorGate | None = None) -> Gateway:
        deploy_policy(policy, adapters.state, adapters.clock)
        gw = Gateway(
            StorePolicyProvider(adapters.state, refresh_s=0),
            adapters.tables,
            adapters.state,
            evidence,
            adapters.clock,
            state_cache_ttl_s=0,
            detector_gate=gate,
        )
        made.append(gw)
        return gw

    yield build
    for gw in made:
        gw.close()


APPROVED = "    observe_approvals: [risk.lead, compliance.officer]\n"
OBSERVE = "    mode: observe\n" + APPROVED  # money rules in scope: observe needs two approvers


# ------------------------------------------------------------------ schema, hash, validation


def test_policy_hash_is_unchanged_for_files_without_the_new_keys() -> None:
    assert load_policy_dir(REPO_ROOT / "policies").policy_hash == BASELINE_HASH


def test_explicit_enforce_is_the_default_behaviour(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", "    mode: enforce\n")})))
    r = gw.check("a1", "1", "pay", {"amount_minor": 500})
    assert r["allow"] is False and r["rule_id"] == "R-PAY-BLOCK" and r["mode"] == "enforce"
    assert "observed_decision" not in r


def test_the_answer_has_no_new_key_for_an_agent_that_uses_none(gw_for: Any) -> None:
    gw = gw_for(make(policy_text()))
    r = gw.check("a1", "1", "pay", {"amount_minor": 500})
    assert r["allow"] is False and not {"mode", "observed_decision", "consumer_id"} & set(r)


def test_schema_json_lists_the_new_keys_and_is_current() -> None:
    schema = policy_json_schema()
    text = json.dumps(schema)
    for name in ("ConsumerOverride", "RuleSwitches", '"consumers"', '"mode"'):
        assert name in text
    committed = json.loads((REPO_ROOT / "policies" / "schema.json").read_text(encoding="utf-8"))
    assert committed == schema


def test_bad_mode_and_unknown_key_fail_the_load() -> None:
    with pytest.raises(PolicyError):
        make(policy_text({"a1": ("RUNNING", "    mode: dry\n")}))
    with pytest.raises(PolicyError):
        make(policy_text({"a1": ("RUNNING", "    consumers: {c1: {colour: red}}\n")}))


@pytest.mark.parametrize("cid", ["", "a b", "a/b", "x" * 129, "café", "a\nb", "<s>", "a;b"])
def test_bad_consumer_ids_fail_the_load_and_the_check(cid: str) -> None:
    assert not valid_consumer_id(cid)
    extra = "    consumers: " + json.dumps({cid: {}}) + "\n"
    with pytest.raises(PolicyError):
        make(policy_text({"a1": ("RUNNING", extra)}))


def test_consumer_id_check_accepts_the_documented_charset() -> None:
    assert valid_consumer_id("user:42@bank.vn_x-1") and valid_consumer_id("x" * 128)
    assert not valid_consumer_id(42) and not valid_consumer_id(None)


def test_rule_switch_names_must_exist() -> None:
    with pytest.raises(PolicyError, match="NOPE-1"):
        make(policy_text({"a1": ("RUNNING", "    rules: {disable: [NOPE-1]}\n")}))


def test_a_consumer_cannot_switch_off_a_money_block_rule() -> None:
    extra = "    consumers:\n      c1: {rules: {disable: [R-PAY-BLOCK]}}\n"
    with pytest.raises(PolicyError, match="cannot be switched off"):
        make(policy_text({"a1": ("RUNNING", extra)}))
    ok = "    consumers:\n      c1: {rules: {disable: [R-READ-BLOCK]}}\n"
    make(policy_text({"a1": ("RUNNING", ok)}))  # a read_only rule may be switched off


# ------------------------------------------------------------------ observe mode


def test_observe_turns_a_block_into_a_report_and_keeps_the_original(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    r = gw.check("a1", "1", "pay", {"amount_minor": 500})
    assert r["allow"] is True and r["mode"] == "observe" and r["status"] == "report"
    assert r["action"] == "log"  # a value every old client knows
    assert r["observed_decision"]["action"] == "block"
    assert r["observed_decision"]["rule_id"] == "R-PAY-BLOCK"
    assert r["observed_decision"]["allow"] is False


def test_observe_turns_a_pause_into_a_report_and_does_not_pause_the_agent(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    r = gw.check("a1", "1", "pay", {"amount_minor": 5000})
    assert r["allow"] is True and r["observed_decision"]["action"] == "pause"
    assert r["agent_paused"] is False and gw.states.get_state("a1") == "RUNNING"
    assert gw.check("a1", "1", "pay", {"amount_minor": 1})["allow"] is True


def test_enforce_still_pauses_and_blocks(gw_for: Any) -> None:
    gw = gw_for(make(policy_text()))
    r = gw.check("a1", "1", "pay", {"amount_minor": 5000})
    assert r["allow"] is False and r["action"] == "pause" and gw.states.get_state("a1") == "PAUSED"


def test_observe_leaves_an_allowed_call_alone(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    r = gw.check("a1", "1", "pay", {"amount_minor": 1})
    assert r["allow"] is True and r["action"] == "allow" and "observed_decision" not in r
    assert r["mode"] == "observe"


def test_observe_does_not_lift_a_state_block(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    gw.states.quarantine("a1", "admin.chi", "test")
    r = gw.check("a1", "1", "pay", {"amount_minor": 1})
    assert r["allow"] is False and r["rule_id"] == "GATE-QUARANTINED"
    assert "observed_decision" not in r


def test_observe_does_not_lift_an_unknown_tool_block(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    r = gw.check("a1", "1", "not_a_tool", {})
    assert r["allow"] is False and r["rule_id"] == "GATE-UNKNOWN-TOOL"


def test_shadow_keeps_precedence_over_observe(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("SHADOW", OBSERVE)})))
    r = gw.check("a1", "1", "pay", {"amount_minor": 500})
    assert r["allow"] is True and r["action"] == "log" and r["rule_id"] == "R-PAY-BLOCK"
    assert r["reason"].startswith("shadow: would block")  # the SHADOW downgrade, not observe's
    assert "observed_decision" not in r


def test_observe_records_both_in_verdict_rows_and_the_chain(
    gw_for: Any, adapters: Adapters, evidence: MemoryEvidence
) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    r = gw.check("a1", "1", "pay", {"amount_minor": 500})
    rows = adapters.tables.query("verdict", {"event_id": r["decision_id"]})
    assert {x["label"] for x in rows} >= {"observe_would_block"}
    assert {x["action"] for x in rows} == {"log"}  # the matched rule is recorded as a report
    (payload,) = [
        p for p in evidence.of_type("gate_decision") if p["decision_id"] == r["decision_id"]
    ]
    assert payload["allow"] is True and payload["mode"] == "observe"
    assert payload["observed_decision"] == {"action": "block", "rule_id": "R-PAY-BLOCK"}
    event = adapters.tables.query("agent_event", {"event_id": r["decision_id"]})[0]
    assert event["status"] == "allowed" and event["classification"] == "log"


def test_observe_is_visible_in_the_siem_event(gw_for: Any, evidence: MemoryEvidence) -> None:
    from supervisor.adapters.integrations.siem import event_from_chain

    gw = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    gw.check("a1", "1", "pay", {"amount_minor": 500}, {"consumer_id": "c1"})
    (payload,) = evidence.of_type("gate_decision")
    entry = {
        "record_type": "gate_decision",
        "ts": "2026-10-14T02:00:00.000000Z",
        "lane": "a1",
        "seq": 1,
        "entry_hash": "0" * 64,
        "record_ref": "x",
    }
    ev = event_from_chain(entry, payload)
    assert ev is not None and ev.outcome == "log"
    assert ev.attrs is not None and ev.attrs["mode"] == "observe"
    assert ev.attrs["observed_action"] == "block" and ev.attrs["observed_rule_id"] == "R-PAY-BLOCK"


def test_observe_counts_in_the_metrics(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    gw.check("a1", "1", "pay", {"amount_minor": 500})
    assert gw.metrics.snapshot()["counts"].get("observe", 0) >= 1


def test_dry_run_in_observe_does_not_say_would_pause(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    r = gw.evaluate_only("a1", "1", "pay", {"amount_minor": 5000})
    assert r["allow"] is True and r["would_pause"] is False
    assert r["observed_decision"]["action"] == "pause"
    gw2 = gw_for(make(policy_text()))
    assert gw2.evaluate_only("a1", "1", "pay", {"amount_minor": 5000})["would_pause"] is True


def test_a_rule_that_cannot_run_fails_closed_in_enforce_and_reports_in_observe(
    gw_for: Any,
) -> None:
    bad = {"amount_minor": "1000"}  # text where the rule needs an integer: the rule errors
    enforce = gw_for(make(policy_text()))
    r = enforce.check("a1", "1", "pay", bad)
    assert r["allow"] is False and r["fail_mode"] == "closed"
    obs = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    r = obs.check("a1", "1", "pay", bad)
    assert r["allow"] is True and r["observed_decision"]["action"] == "block"
    assert r["fail_mode"] is None


def _failing_gate(masker: Any) -> DetectorGate:
    base = yaml.safe_load((REPO_ROOT / "config" / "detectors.yaml").read_text(encoding="utf-8"))
    base["detectors"]["bad"] = {"enabled": True, "fail_closed": True, "settings": {}}
    return make_gate(masker, extra=[FakeDetector("bad", boom)], config_text=yaml.safe_dump(base))


def test_detector_failure_blocks_in_enforce_and_is_a_report_in_observe(gw_for: Any) -> None:
    masker = VnRegexMasker(b"test-key", "t")
    enforce = gw_for(make(policy_text()), _failing_gate(masker))
    r = enforce.check("a1", "1", "pay", {"amount_minor": 1})
    assert r["allow"] is False and r["rule_id"] == "GATE-DETECTOR-FAILED" and r["status"] == "block"
    obs = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})), _failing_gate(masker))
    r = obs.check("a1", "1", "pay", {"amount_minor": 1})
    assert r["allow"] is True and r["status"] == "report"
    assert r["observed_decision"]["rule_id"] == "GATE-DETECTOR-FAILED"
    assert r["not_executed"]  # the coverage gap stays visible


def test_per_consumer_detector_override_is_used(gw_for: Any) -> None:
    masker = VnRegexMasker(b"test-key", "t")
    extra = "    consumers:\n      quiet: {detectors: {disable: [bad]}}\n"
    gw = gw_for(make(policy_text({"a1": ("RUNNING", extra)})), _failing_gate(masker))
    slugs = [n["detector_slug"] for n in gw.check("a1", "1", "lookup", {})["not_executed"]]
    assert "bad" in slugs
    r = gw.check("a1", "1", "lookup", {}, {"consumer_id": "quiet"})
    assert r["consumer_id"] == "quiet"
    assert "bad" not in [n["detector_slug"] for n in r["not_executed"]]


def test_review_a_consumer_detector_override_never_applies_to_a_money_tool(gw_for: Any) -> None:
    """WP38 review: a caller-asserted consumer id must not switch off GATE-DETECTOR-FAILED."""
    masker = VnRegexMasker(b"test-key", "t")
    extra = "    consumers:\n      quiet: {detectors: {disable: [bad]}}\n"
    gw = gw_for(make(policy_text({"a1": ("RUNNING", extra)})), _failing_gate(masker))
    assert gw.check("a1", "1", "pay", {"amount_minor": 1})["rule_id"] == "GATE-DETECTOR-FAILED"
    r = gw.check("a1", "1", "pay", {"amount_minor": 1}, {"consumer_id": "quiet"})
    assert r["allow"] is False and r["rule_id"] == "GATE-DETECTOR-FAILED"


# ------------------------------------------------------------------ per-consumer override

BAD = {"tag": "bad"}  # R-READ-BLOCK (read_only) matches
CONSUMERS = """    consumers:
      relaxed: {mode: observe}
      strict: {mode: enforce}
      noread: {rules: {disable: [R-READ-BLOCK]}}
"""


def test_consumer_mode_wins_over_the_agent_mode(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", CONSUMERS)}, RULES_SCOPED)))
    r = gw.check("a1", "1", "lookup", BAD, {"consumer_id": "relaxed"})
    assert r["allow"] is True and r["consumer_id"] == "relaxed" and r["mode"] == "observe"
    r = gw.check("a1", "1", "lookup", BAD, {"consumer_id": "strict"})
    assert r["allow"] is False and r["consumer_id"] == "strict" and r["mode"] == "enforce"


def test_a_consumer_can_be_stricter_than_an_observing_agent(gw_for: Any) -> None:
    extra = OBSERVE + "    consumers:\n      strict: {mode: enforce}\n"
    gw = gw_for(make(policy_text({"a1": ("RUNNING", extra)})))
    assert gw.check("a1", "1", "pay", {"amount_minor": 500})["allow"] is True
    r = gw.check("a1", "1", "pay", {"amount_minor": 500}, {"consumer_id": "strict"})
    assert r["allow"] is False


def test_a_consumer_without_an_entry_gets_the_agent_settings(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", CONSUMERS)}, RULES_SCOPED)))
    r = gw.check("a1", "1", "lookup", BAD, {"consumer_id": "someone-else"})
    assert r["allow"] is False and r["mode"] == "enforce" and r["consumer_ignored"] is True
    assert "consumer_id" not in r


@pytest.mark.parametrize("cid", ["", "a b", "x" * 129, "café", 42, ["relaxed"], {"a": 1}])
def test_an_invalid_consumer_id_never_selects_an_override(gw_for: Any, cid: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", CONSUMERS)}, RULES_SCOPED)))
    r = gw.check("a1", "1", "lookup", BAD, {"consumer_id": cid})
    assert r["allow"] is False and r["mode"] == "enforce" and "consumer_id" not in r


def test_consumer_rule_switch_removes_a_rule_for_that_consumer_only(gw_for: Any) -> None:
    gw = gw_for(make(policy_text({"a1": ("RUNNING", CONSUMERS)}, RULES_SCOPED)))
    args = {"tag": "bad"}
    assert gw.check("a1", "1", "lookup", args)["rule_id"] == "R-READ-BLOCK"
    r = gw.check("a1", "1", "lookup", args, {"consumer_id": "noread"})
    assert r["allow"] is True and r["rule_id"] is None
    assert "R-READ-BLOCK" not in [m["rule_id"] for m in r["matched_rules"]]


def test_consumer_enable_undoes_the_agent_disable(gw_for: Any) -> None:
    extra = (
        "    rules: {disable: [R-READ-BLOCK]}\n"
        "    consumers:\n      back: {rules: {enable: [R-READ-BLOCK]}}\n"
    )
    gw = gw_for(make(policy_text({"a1": ("RUNNING", extra)})))
    assert gw.check("a1", "1", "lookup", {"tag": "bad"})["allow"] is True
    r = gw.check("a1", "1", "lookup", {"tag": "bad"}, {"consumer_id": "back"})
    assert r["allow"] is False and r["rule_id"] == "R-READ-BLOCK"


def test_a_consumer_entry_of_one_agent_does_not_apply_to_another(gw_for: Any) -> None:
    both = {"a1": ("RUNNING", CONSUMERS), "a2": ("RUNNING", "")}
    gw = gw_for(make(policy_text(both, RULES_SCOPED)))
    r = gw.check("a2", "1", "lookup", BAD, {"consumer_id": "relaxed"})
    assert r["allow"] is False and "mode" not in r


def test_policy_hash_changes_when_a_consumer_is_added() -> None:
    a = make(policy_text(rules=RULES_SCOPED)).policy_hash
    assert a != make(policy_text({"a1": ("RUNNING", CONSUMERS)}, RULES_SCOPED)).policy_hash


def test_deployed_policy_round_trips_the_new_keys(adapters: Adapters) -> None:
    p = make(policy_text({"a1": ("RUNNING", OBSERVE + CONSUMERS)}, RULES_SCOPED))
    deploy_policy(p, adapters.state, adapters.clock)
    back = load_deployed(adapters.state)
    assert back.policy_hash == p.policy_hash
    assert back.effective("a1", "relaxed").mode == "observe"


# ------------------------------------------------------------------ gate order words


def test_order_report_rule_logs_and_continues(gw_for: Any) -> None:
    """'A report rule (action log or alert) logs and continues.'"""
    gw = gw_for(make(policy_text()))
    r = gw.check("a1", "1", "lookup", {"tag": "log"})
    assert r["allow"] is True and r["rule_id"] == "R-LOG"
    r = gw.check("a1", "1", "lookup", {"tag": "alert"})
    assert r["allow"] is True and r["rule_id"] == "R-ALERT"
    r = gw.check("a1", "1", "pay", {"amount_minor": 50})  # only the log rule matches
    assert r["allow"] is True and r["rule_id"] == "R-LOG2"


def test_order_every_rule_is_evaluated_and_pause_comes_before_block(gw_for: Any) -> None:
    """'Rules run in a fixed order: pause, block, alert, log. The first pause or block decides.'"""
    gw = gw_for(make(policy_text()))
    r = gw.check("a1", "1", "pay", {"amount_minor": 5000})
    ids = [m["rule_id"] for m in r["matched_rules"]]
    assert ids == ["R-PAY-PAUSE", "R-PAY-BLOCK", "R-LOG2"]  # all three matched, pause first
    assert r["rule_id"] == "R-PAY-PAUSE" and r["action"] == "pause"


def test_order_a_block_beats_a_log_rule_that_matched_too(gw_for: Any) -> None:
    gw = gw_for(make(policy_text()))
    r = gw.check("a1", "1", "pay", {"amount_minor": 500})
    assert r["rule_id"] == "R-PAY-BLOCK" and r["allow"] is False
    assert [m["action"] for m in r["matched_rules"]] == ["block", "log"]


def test_order_observe_turns_block_and_pause_into_report_and_lists_every_hit(
    gw_for: Any,
) -> None:
    """'In observe mode block and pause become report.'"""
    gw = gw_for(make(policy_text({"a1": ("RUNNING", OBSERVE)})))
    r = gw.check("a1", "1", "pay", {"amount_minor": 5000})
    assert [m["action"] for m in r["matched_rules"]] == ["pause", "block", "log"]
    assert r["allow"] is True and r["status"] == "report"


def test_order_skip_still_stops_in_observe_mode() -> None:
    """'Skip still stops': skip is the skip_tools verdict of WP37 and is not a block."""
    status = derive_status(
        allow=True, action="allow", findings=[], has_transform=False, skipped=True
    )
    assert status == "skip"


def test_order_detectors_run_after_the_rules_and_never_block_alone(gw_for: Any) -> None:
    """'Detectors run after the rules and can only report, transform or, when they cannot run
    on a money, credit or PII tool, block with GATE-DETECTOR-FAILED.'"""
    from tests.detectors.fakes import hint

    masker = VnRegexMasker(b"test-key", "t")
    base = yaml.safe_load((REPO_ROOT / "config" / "detectors.yaml").read_text(encoding="utf-8"))
    base["detectors"]["hinter"] = {"enabled": True, "fail_closed": True, "settings": {}}
    gate = make_gate(masker, extra=[hint("block")], config_text=yaml.safe_dump(base))
    gw = gw_for(make(policy_text()), gate)
    r = gw.check("a1", "1", "pay", {"amount_minor": 1})
    assert r["allow"] is True and r["status"] == "report"  # a block hint is advice only (R1)
    # and a rule block is unchanged by what the detectors found
    r = gw.check("a1", "1", "pay", {"amount_minor": 500})
    assert r["allow"] is False and r["rule_id"] == "R-PAY-BLOCK" and r["status"] == "block"


def test_skip_tools_for_a_money_tool_is_refused_for_agent_and_consumer() -> None:
    agent = "    detectors: {skip_tools: [pay]}\n"
    with pytest.raises(PolicyError, match="skip_tools"):
        make(policy_text({"a1": ("RUNNING", agent)}))
    cons = "    consumers:\n      c1: {detectors: {skip_tools: [pay]}}\n"
    with pytest.raises(PolicyError, match="skip_tools"):
        make(policy_text({"a1": ("RUNNING", cons)}))
    make(policy_text({"a1": ("RUNNING", "    detectors: {skip_tools: [lookup]}\n")}))


def test_consumer_detector_overrides_go_through_the_same_validator() -> None:
    gate = make_gate(VnRegexMasker(b"test-key", "t"))
    bad = "    consumers:\n      c1: {detectors: {disable: [no_such_detector]}}\n"
    assert gate.check_policy(make(policy_text({"a1": ("RUNNING", bad)})))
    good = "    consumers:\n      c1: {detectors: {preset: lenient}}\n"
    assert gate.check_policy(make(policy_text({"a1": ("RUNNING", good)}))) == []
