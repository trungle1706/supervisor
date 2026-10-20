"""WP38 review (Opus): observe mode and consumer overrides seen by an application-security
engineer. Each test names the attack or the failure it closes. See REVIEW_WP38.md."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import yaml

from supervisor.adapters.factory import Adapters
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.gateway.detector_gate import DetectorGate
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import (
    Policy,
    PolicyError,
    StorePolicyProvider,
    deploy_policy,
    load_policy_texts,
    money_agent,
)
from supervisor.gateway.sdk import InProcessGate
from supervisor_agents.common.gate import safe_check
from tests.conftest import REPO_ROOT
from tests.detectors.conftest import make_gate
from tests.detectors.fakes import FakeDetector, boom
from tests.gateway.conftest import MemoryEvidence

NAME = "Nguyen Van An"
RULES = """
  - {id: R-READ-BLOCK, version: 1, description: read block, agent_scope: "*", action: block,
     severity: medium, risk_class: read_only, owner: t, approvals: [a1, a2],
     when: {tool: lookup, all: [{arg: tag, op: eq, value: bad}]}}
  - {id: R-PAY-BLOCK, version: 1, description: big pay, agent_scope: [payer], action: block,
     severity: high, risk_class: money, owner: t, approvals: [a1, a2],
     when: {tool: pay, all: [{arg: amount_minor, op: gt, value: 100}]}}
  - {id: R-PAY-PAUSE, version: 1, description: huge pay, agent_scope: [payer], action: pause,
     severity: critical, risk_class: money, owner: t, approvals: [a1, a2],
     when: {tool: pay, all: [{arg: amount_minor, op: gt, value: 1000}]}}
  - {id: R-EXP-BLOCK, version: 1, description: export block, agent_scope: [payer],
     action: block, severity: high, risk_class: pii_export, owner: t, approvals: [a1, a2],
     when: {tool: export, all: [{arg: tag, op: eq, value: bad}]}}
"""
AGENT = """
  {name}:
    name: {name}
    owner_user: u@example.invalid
    owner_team: T
    initial_state: {state}
{extra}"""
APPROVED = "    observe_approvals: [risk.lead, compliance.officer]\n"
OBSERVE = "    mode: observe\n"


def text(
    payer: tuple[str, str] = ("RUNNING", ""), helper: tuple[str, str] = ("RUNNING", "")
) -> str:
    body = AGENT.format(name="payer", state=payer[0], extra=payer[1])
    body += AGENT.format(name="helper", state=helper[0], extra=helper[1])
    return (
        "policy_version: 1\ntools: {lookup: read_only, pay: money, export: pii_export}\n"
        f"agents:{body}\nrules:{RULES}"
    )


def make(t: str) -> Policy:
    return load_policy_texts([("t.yaml", t)])


@pytest.fixture
def gw_for(adapters: Adapters, evidence: MemoryEvidence) -> Iterator[Any]:
    made: list[Gateway] = []

    def build(policy: Policy, gate: DetectorGate | None = None, **kw: Any) -> Gateway:
        deploy_policy(policy, adapters.state, adapters.clock)
        gw = Gateway(
            StorePolicyProvider(adapters.state, refresh_s=0),
            adapters.tables,
            adapters.state,
            evidence,
            adapters.clock,
            state_cache_ttl_s=0,
            detector_gate=gate,
            **kw,
        )
        made.append(gw)
        return gw

    yield build
    for gw in made:
        gw.close()


def _failing_gate() -> DetectorGate:
    base = yaml.safe_load((REPO_ROOT / "config" / "detectors.yaml").read_text(encoding="utf-8"))
    base["detectors"]["bad"] = {"enabled": True, "fail_closed": True, "settings": {}}
    masker = VnRegexMasker(b"test-key", "t")
    return make_gate(masker, extra=[FakeDetector("bad", boom)], config_text=yaml.safe_dump(base))


# ------------------------------------------------------------------ loader refusals


def test_money_agent_is_an_agent_with_a_money_credit_or_pii_rule_in_scope() -> None:
    doc = make(text()).doc
    assert money_agent(doc, "payer") is True and money_agent(doc, "helper") is False


def test_observe_on_a_running_money_agent_without_two_approvers_is_refused() -> None:
    with pytest.raises(PolicyError, match="observe_approvals") as e:
        make(text(payer=("RUNNING", OBSERVE)))
    str(e.value).encode("ascii")  # the message is ASCII
    make(text(payer=("SHADOW", OBSERVE)))  # SHADOW: accepted
    make(text(payer=("RUNNING", OBSERVE + APPROVED)))  # two approvers: accepted
    with pytest.raises(PolicyError, match="two distinct"):
        make(text(payer=("RUNNING", OBSERVE + "    observe_approvals: [x.y, x.y]\n")))


def test_consumer_observe_on_a_money_agent_is_refused_even_with_approvers() -> None:
    extra = OBSERVE + APPROVED + "    consumers:\n      pilot: {mode: observe}\n"
    with pytest.raises(PolicyError, match="asserted by the caller") as e:
        make(text(payer=("RUNNING", extra)))
    str(e.value).encode("ascii")
    make(text(helper=("RUNNING", "    consumers:\n      pilot: {mode: observe}\n")))


def test_a_consumer_cannot_switch_off_a_pii_export_block_rule() -> None:
    with pytest.raises(PolicyError, match="cannot be switched off"):
        make(
            text(payer=("RUNNING", "    consumers:\n      c: {rules: {disable: [R-EXP-BLOCK]}}\n"))
        )


def test_policy_hash_unchanged_by_the_new_observe_approvals_field() -> None:
    from supervisor.gateway.policy import load_policy_dir
    from tests.gateway.test_wp38_policy import BASELINE_HASH

    assert load_policy_dir(REPO_ROOT / "policies").policy_hash == BASELINE_HASH


# ------------------------------------------------------------------ runtime guards


def test_unapproved_observe_never_lifts_a_money_block_after_shadow_ends(gw_for: Any) -> None:
    gw = gw_for(make(text(payer=("SHADOW", OBSERVE))))
    r = gw.check("payer", "1", "pay", {"amount_minor": 500})
    assert r["allow"] is True and r["reason"].startswith("shadow:")  # SHADOW precedence
    gw.states.set_mode("payer", "RUNNING", "admin.chi")
    r = gw.check("payer", "1", "pay", {"amount_minor": 500})
    assert r["allow"] is False and r["rule_id"] == "R-PAY-BLOCK" and "observed_decision" not in r
    r = gw.check("payer", "1", "lookup", {"tag": "bad"})  # a read_only rule: observe acts
    assert r["allow"] is True and r["observed_decision"]["rule_id"] == "R-READ-BLOCK"
    r = gw.check("payer", "1", "pay", {"amount_minor": 5000})  # a money pause rule pauses
    assert r["allow"] is False and gw.states.get_state("payer") == "PAUSED"


def test_a_guessed_observe_consumer_gets_no_free_pass_on_a_money_tool(gw_for: Any) -> None:
    """Attack: an agent with no money rule names an observe consumer and calls a money tool
    whose detectors cannot run. GATE-DETECTOR-FAILED must hold."""
    extra = "    consumers:\n      pilot: {mode: observe, detectors: {disable: [bad]}}\n"
    gw = gw_for(make(text(helper=("RUNNING", extra))), _failing_gate())
    r = gw.check("helper", "1", "pay", {"amount_minor": 1}, {"consumer_id": "pilot"})
    assert r["allow"] is False and r["rule_id"] == "GATE-DETECTOR-FAILED"
    assert r["status"] == "block" and "observed_decision" not in r
    # the same consumer on a read_only tool: the override and observe apply
    r = gw.check("helper", "1", "lookup", {"tag": "bad"}, {"consumer_id": "pilot"})
    assert r["allow"] is True and r["observed_decision"]["rule_id"] == "R-READ-BLOCK"


@pytest.mark.parametrize("cid", ["pi​lot", "pilot‍", "pіlot", "pilot\r\nX: 1", "pilot "])
def test_confusable_or_injected_consumer_ids_never_select_the_override(
    gw_for: Any, cid: str
) -> None:
    extra = "    consumers:\n      pilot: {mode: observe}\n"
    gw = gw_for(make(text(helper=("RUNNING", extra))))
    r = gw.check("helper", "1", "lookup", {"tag": "bad"}, {"consumer_id": cid})
    assert r["allow"] is False and r["consumer_ignored"] is True and "consumer_id" not in r


def test_approved_observe_on_a_pii_export_block_still_masks_the_arguments(gw_for: Any) -> None:
    """Before the review the lifted block skipped the redaction: raw PII reached the tool."""
    masker = VnRegexMasker(b"test-key", "t")
    gw = gw_for(
        make(text(payer=("RUNNING", OBSERVE + APPROVED))), masker=masker, inline_redaction=True
    )
    r = gw.check("payer", "1", "export", {"tag": "bad", "payee_name": f"Ong {NAME}"})
    assert r["allow"] is True and r["observed_decision"]["rule_id"] == "R-EXP-BLOCK"
    assert NAME not in json.dumps(r["transformed_args"], ensure_ascii=False)
    assert r["status"] == "transform"  # a client must still apply the masked values


def test_observe_keeps_gate_redaction_a_block(gw_for: Any) -> None:
    class Broken:
        mask_version = "broken"

        def mask(self, text: str) -> str:
            raise RuntimeError("boom")

    gw = gw_for(
        make(text(payer=("RUNNING", OBSERVE + APPROVED))), masker=Broken(), inline_redaction=True
    )
    r = gw.check("payer", "1", "export", {"tag": "bad", "payee_name": NAME})
    assert r["allow"] is False and r["rule_id"] == "GATE-REDACTION" and r["status"] == "block"
    assert gw.states.get_state("payer") == "RUNNING"


def test_approved_observe_keeps_detector_failure_on_pii_export_a_block(gw_for: Any) -> None:
    gw = gw_for(make(text(payer=("RUNNING", OBSERVE + APPROVED))), _failing_gate())
    r = gw.check("payer", "1", "export", {"tag": "ok"})
    assert r["allow"] is False and r["rule_id"] == "GATE-DETECTOR-FAILED"


def test_a_lifted_detector_failure_has_an_auditable_verdict_row(
    gw_for: Any, adapters: Adapters, evidence: MemoryEvidence
) -> None:
    gw = gw_for(make(text(payer=("RUNNING", OBSERVE + APPROVED))), _failing_gate())
    r = gw.check("payer", "1", "pay", {"amount_minor": 1})
    assert r["allow"] is True and r["observed_decision"]["rule_id"] == "GATE-DETECTOR-FAILED"
    rows = adapters.tables.query("verdict", {"event_id": r["decision_id"]})
    labels = {(x["label"], x["rule_id"], x["action"]) for x in rows}
    assert ("observe_would_block", "GATE-DETECTOR-FAILED", "log") in labels
    ev = adapters.tables.query("agent_event", {"event_id": r["decision_id"]})[0]
    assert ev["verdict_status"] == "report" and ev["status"] == "allowed"
    (payload,) = [
        p for p in evidence.of_type("gate_decision") if p["decision_id"] == r["decision_id"]
    ]
    assert payload["observed_decision"]["rule_id"] == "GATE-DETECTOR-FAILED"


def test_threat_not_enforced_is_computable_from_verdict_rows(
    gw_for: Any, adapters: Adapters
) -> None:
    """WP39 AL-THREAT-NOT-ENFORCED: verdict rows with label observe_would_* joined on event_id."""
    gw = gw_for(make(text(payer=("RUNNING", OBSERVE + APPROVED))))
    r = gw.check("payer", "1", "pay", {"amount_minor": 500})
    gw.check("payer", "1", "pay", {"amount_minor": 1})
    rows = [
        v
        for v in adapters.tables.query("verdict", {"tier": 0})
        if str(v["label"]).startswith("observe_would_")
    ]
    assert [v["event_id"] for v in rows] == [r["decision_id"]]


def test_old_clients_accept_the_observe_answer(gw_for: Any) -> None:
    gw = gw_for(make(text(payer=("RUNNING", OBSERVE + APPROVED))))
    out = safe_check(InProcessGate(gw), "payer", "1", "pay", {"amount_minor": 500}, {}, "money")
    assert out["allow"] is True and out["action"] == "log"
