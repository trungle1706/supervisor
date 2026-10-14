from __future__ import annotations

import json

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.gateway.policy import (
    Policy,
    PolicyError,
    StorePolicyProvider,
    deploy_policy,
    load_deployed,
    load_policy_dir,
    load_policy_texts,
    parse_policy_text,
    policy_json_schema,
)
from tests.gateway.conftest import POLICY_DIR

MINI = """
policy_version: 1
tools: {pay: money, read: read_only}
agents:
  a1: {name: A1, owner_user: o1, owner_team: t1}
rules:
  - id: R-1
    version: 1
    description: limit
    agent_scope: [a1]
    when:
      tool: pay
      all: [{arg: amount_minor, op: gt, value: 10}]
    action: block
    severity: high
    risk_class: money
    owner: team
    approvals: [x, y]
"""


def test_baseline_loads_and_has_the_incident_rules(baseline: Policy) -> None:
    ids = {r.id for r in baseline.rules}
    for rid in (
        "PAY-07",
        "SVC-07",
        "CRD-07",
        "PAY-02",
        "PAY-03",
        "PAY-04",
        "PAY-05",
        "SVC-01",
        "SVC-02",
        "CRD-01",
        "PII-01",
    ):
        assert rid in ids
    assert len(baseline.policy_hash) == 64


def test_hash_is_stable_and_independent_of_file_order() -> None:
    a = load_policy_dir(POLICY_DIR)
    b = load_policy_dir(POLICY_DIR)
    assert a.policy_hash == b.policy_hash
    second = MINI.replace("R-1", "R-2")
    h1 = load_policy_texts([("x.yaml", MINI), ("y.yaml", second)]).policy_hash
    h2 = load_policy_texts([("y.yaml", second), ("x.yaml", MINI)]).policy_hash
    assert h1 == h2
    changed = load_policy_texts([("x.yaml", MINI.replace("value: 10", "value: 11"))])
    assert changed.policy_hash != load_policy_texts([("x.yaml", MINI)]).policy_hash


def test_default_fail_mode_by_risk_class(baseline: Policy) -> None:
    by_id = {r.id: r for r in baseline.rules}
    assert by_id["PAY-02"].effective_fail_mode == "closed"
    assert by_id["CRD-01"].effective_fail_mode == "closed"
    assert by_id["PII-01"].effective_fail_mode == "closed"
    text = MINI.replace("action: block", "action: alert").replace(
        "risk_class: money", "risk_class: read_only"
    )
    assert load_policy_texts([("m.yaml", text)]).rules[0].effective_fail_mode == "open"


@pytest.mark.parametrize(
    ("old", "new", "msg"),
    [
        ("approvals: [x, y]", "approvals: [x]", "two distinct approver"),
        ("approvals: [x, y]", "approvals: [x, x]", "two distinct approver"),
        ("value: 10", "value: 10.5", "integer"),
        ("op: gt", "op: eval", "op"),
        ("tool: pay", "tool: nope", "not in the tools section"),
        ("agent_scope: [a1]", "agent_scope: [zz]", "not in the agents section"),
        ("severity: high", "severity: high\n    extra_key: 1", "xtra"),
        ("arg: amount_minor", "arg: \"__import__('os')\"", "bad arg path"),
        ("id: R-1", "id: r 1", "id"),
    ],
)
def test_invalid_policies_are_rejected(old: str, new: str, msg: str) -> None:
    text = MINI.replace(old, new)
    assert text != MINI
    with pytest.raises(PolicyError, match=msg):
        load_policy_texts([("bad.yaml", text)])


def test_untrusted_yaml_is_safe_and_size_limited() -> None:
    with pytest.raises(PolicyError):
        parse_policy_text("!!python/object/apply:os.system ['echo hi']")
    with pytest.raises(PolicyError, match="larger than"):
        parse_policy_text("a: '" + "x" * 300_000 + "'")
    with pytest.raises(PolicyError, match="mapping"):
        parse_policy_text("- 1\n- 2\n")


def test_duplicate_rule_ids_rejected() -> None:
    with pytest.raises(PolicyError, match="appears twice"):
        load_policy_texts([("a.yaml", MINI), ("b.yaml", MINI)])


def test_schema_json_is_current() -> None:
    committed = json.loads((POLICY_DIR / "schema.json").read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(policy_json_schema())), (
        "regenerate policies/schema.json from supervisor.gateway.policy.policy_json_schema()"
    )


def test_deploy_round_trip_and_idempotent(adapters: Adapters, baseline: Policy) -> None:
    counts = deploy_policy(baseline, adapters.state, adapters.clock, git_sha="abc")
    assert counts["inserted"] == len(baseline.rules) + 1
    again = deploy_policy(baseline, adapters.state, adapters.clock, git_sha="abc")
    assert again == {"inserted": 0, "updated": 0, "retired": 0}
    deployed = load_deployed(adapters.state)
    assert deployed.policy_hash == baseline.policy_hash
    row = adapters.state.get("rule", {"rule_id": "PAY-02", "version": 1})
    assert row is not None and row["fail_mode"] == "closed"
    assert row["approved_by_1"] == "risk.lead" and row["policy_hash"] == baseline.policy_hash


def test_deploy_requires_version_bump_and_retires_old_rules(adapters: Adapters) -> None:
    p1 = load_policy_texts([("m.yaml", MINI)])
    deploy_policy(p1, adapters.state, adapters.clock)
    changed = load_policy_texts([("m.yaml", MINI.replace("value: 10", "value: 20"))])
    with pytest.raises(PolicyError, match="bump the version"):
        deploy_policy(changed, adapters.state, adapters.clock)
    bumped = load_policy_texts(
        [("m.yaml", MINI.replace("value: 10", "value: 20").replace("version: 1", "version: 2"))]
    )
    counts = deploy_policy(bumped, adapters.state, adapters.clock)
    assert counts["retired"] == 2  # R-1 v1 and the manifest (policy_version also changed)
    assert load_deployed(adapters.state).policy_hash == bumped.policy_hash


def test_store_provider_raises_when_store_fails(adapters: Adapters, baseline: Policy) -> None:
    deploy_policy(baseline, adapters.state, adapters.clock)
    provider = StorePolicyProvider(adapters.state, refresh_s=0)
    assert provider.current().policy_hash == baseline.policy_hash

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("store down")

    adapters.state.query = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        provider.current()
    assert provider.last_known() is not None


def test_empty_rule_table_is_an_error(adapters: Adapters) -> None:
    with pytest.raises(PolicyError, match="no deployed policy"):
        load_deployed(adapters.state)
