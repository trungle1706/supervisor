"""Facts of a product: onboard, policy, answers, profile files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from supervisor.adapters.llm.mock import MockChat
from supervisor.adapters.repo import LocalGitRepoReader
from supervisor.advisory.compliance.demo import AGENTS_DIR, demo_product
from supervisor.advisory.compliance.facts import (
    CAPABILITY_MONITOR,
    CONTROLS_YAML,
    ProfileInputError,
    apply_answers,
    from_onboard,
    from_questionnaire,
    load_profile_input,
    policy_facts,
)
from supervisor.advisory.compliance.model import ProductProfile
from supervisor.advisory.compliance.questionnaire import QuestionnaireError
from supervisor.catalogue import load_catalogue
from supervisor.onboard.discover import discover
from supervisor.onboard.plan import plan
from supervisor.onboard.understand import understand
from tests.conftest import REPO_ROOT

BASELINE = REPO_ROOT / "policies" / "baseline.yaml"


def test_payments_sets_are_lower_bounds_with_pointers() -> None:
    p = demo_product("payments")
    assert p.agent_classes == ("payment",)
    assert p.agent_classes_complete is False
    assert p.data_classes == ("personal", "financial")
    assert p.data_classes_complete is False
    assert p.roles == ("deployer",) and p.roles_complete is False
    assert p.autonomy == "acts_autonomously"
    for name in ("agent_classes", "data_classes", "autonomy", "executes_payments"):
        assert p.provenance[name], name
    first = p.provenance["agent_classes"][0]
    assert first.kind == "file" and first.ref.startswith("src/supervisor_agents/payments/")


def test_unknown_facts_stay_none() -> None:
    for agent in ("credit_prequal", "customer_service"):
        p = demo_product(agent)
        assert p.cross_border is None
        assert p.model_hosting is None
        assert p.customer_types is None
        assert p.decisions_affecting_customers is None
        assert p.in_operation_since is None
        assert "sensitive_personal" not in (p.data_classes or ())
        assert "core_data" not in (p.data_classes or ())


def test_customer_service_has_no_payment_and_no_limit_guess() -> None:
    p = demo_product("customer_service")
    assert p.executes_payments is None  # not found in code is a question, not False
    assert p.max_transaction_vnd is None  # no payment tool; never an invented limit
    assert p.max_daily_vnd is None


def test_onboard_decision33_reused() -> None:
    p = demo_product("payments")
    assert p.onboard_decision33 is not None
    assert p.onboard_decision33["classification"] == "high_risk"
    assert p.executes_payments is True and p.human_approval_before_execution is False
    c = demo_product("credit_prequal")
    assert c.credit_decisions is True and c.independent_credit_approval is False


def test_only_blocking_rules_are_limits_and_ge_is_exact() -> None:
    """A log or alert rule limits nothing; 'ge N' allows at most N - 1 (review fix)."""
    from supervisor.advisory.compliance.facts import policy_facts

    text = """
tools: {transfer: money}
rules:
  - id: X-LOG
    agent_scope: [a]
    when: {tool: transfer, all: [{arg: amount_minor, op: gt, value: 5}]}
    action: log
  - id: X-GE
    agent_scope: [a]
    when: {tool: transfer, all: [{arg: amount_minor, op: ge, value: 1000}]}
    action: block
"""
    rules, limits = policy_facts([("p.yaml", text)], "a")
    assert {r.id for r in rules} == {"X-LOG", "X-GE"}  # both rules are present as controls
    assert [(x.id, x.value_vnd) for x in limits] == [("X-GE", 999)]


def test_policy_facts_scope_and_line_numbers() -> None:
    text = BASELINE.read_text(encoding="utf-8")
    rules, limits = policy_facts([("policies/baseline.yaml", text)], "payments")
    ids = {r.id for r in rules}
    assert {"PAY-02", "PAY-03", "PAY-07"} <= ids
    assert not any(i.startswith("SVC-") or i.startswith("CRD-") for i in ids)
    lines = text.splitlines()
    for r in rules:
        file, _, num = r.pointer.ref.rpartition(":")
        assert file == "policies/baseline.yaml"
        assert lines[int(num) - 1].strip().startswith(f"- id: {r.id}")
    by_id = {x.id: x for x in limits}
    assert by_id["PAY-02"].period == "per_transaction" and by_id["PAY-02"].value_vnd == 100_000_000
    assert by_id["PAY-03"].period == "daily" and by_id["PAY-03"].scope == "per_customer"
    assert all(type(x.value_vnd) is int for x in limits)
    assert "PAY-08" not in by_id  # one-hour split-payment window is not a daily cap


def test_policy_facts_rejects_bad_yaml() -> None:
    with pytest.raises(ProfileInputError):
        policy_facts([("x.yaml", "rules: [unclosed")], "payments")


def test_max_values_come_from_covering_limits() -> None:
    p = demo_product("payments")
    assert p.max_transaction_vnd == 100_000_000
    assert p.max_daily_vnd == 150_000_000  # smallest daily per-customer limit (PAY-03)
    assert demo_product("credit_prequal").max_credit_vnd == 2_000_000_000


def test_no_limit_means_none_not_unlimited() -> None:
    disc = discover(LocalGitRepoReader(AGENTS_DIR / "payments"))
    prof = understand(disc, MockChat(model_id="mock-onboarding-v1"))
    mp, _ = plan(disc.inventory, prof, load_catalogue())
    inv = disc.inventory.model_copy(update={"limits": []})
    p = from_onboard(inv, prof, plan=mp)  # no policy, no manifest limits
    assert p.max_transaction_vnd is None and p.max_daily_vnd is None and p.limits == ()


def test_controls_unknown_without_plan_or_policy() -> None:
    disc = discover(LocalGitRepoReader(AGENTS_DIR / "payments"))
    prof = understand(disc, MockChat(model_id="mock-onboarding-v1"))
    p = from_onboard(disc.inventory, prof)
    assert p.controls.known is False and p.controls.supervised is None
    assert p.controls.catalogue_on == () and p.controls.evidence == ()


def test_planned_basis_marks_pointers() -> None:
    disc = discover(LocalGitRepoReader(AGENTS_DIR / "payments"))
    prof = understand(disc, MockChat(model_id="mock-onboarding-v1"))
    mp, _ = plan(disc.inventory, prof, load_catalogue())
    p = from_onboard(disc.inventory, prof, plan=mp)
    assert p.controls.basis == "planned" and p.controls.supervised is True
    assert "onboard_plan" in p.controls.evidence and "onboard_profile" in p.controls.evidence
    assert "launch_report" not in p.controls.evidence  # artefact does not exist
    ptr = p.controls.pointers["evidence:evidence_chain"]
    assert "planned" in ptr.note


def test_capability_monitor_names_exist() -> None:
    spec = yaml.safe_load(CONTROLS_YAML.read_text(encoding="utf-8"))
    assert set(CAPABILITY_MONITOR.values()) <= set(spec["monitors"])
    assert set(CAPABILITY_MONITOR) <= set(load_catalogue().ids())


def test_evidence_only_when_its_source_is_on() -> None:
    pay = demo_product("payments").controls
    cred = demo_product("credit_prequal").controls
    assert "fairness_slice" not in pay.evidence
    assert "oversight_metric" not in pay.evidence
    assert ("fairness" in cred.monitors) == ("fairness_slice" in cred.evidence)


def test_answers_override_and_complete_sets() -> None:
    base = demo_product("credit_prequal")
    p = apply_answers(
        base,
        {
            "customer_types": ["organisation"],
            "agent_classes": ["credit_decision", "customer_facing"],
            "cross_border": False,
            "max_credit_vnd": 30_000_000,
        },
    )
    assert p.customer_types == ("organisation",) and p.customer_types_complete
    assert p.agent_classes == ("credit_decision", "customer_facing") and p.agent_classes_complete
    assert p.cross_border is False
    assert p.max_credit_vnd == 30_000_000
    assert p.provenance["cross_border"][0].kind == "questionnaire"
    assert p.provenance["cross_border"][0].ref == "product.yaml#cross_border"
    assert base.cross_border is None  # input untouched


def test_answers_reject_floats() -> None:
    with pytest.raises(QuestionnaireError):
        apply_answers(demo_product("payments"), {"max_daily_vnd": 1.5e8})


def test_from_questionnaire_with_policy_file(tmp_path: Path) -> None:
    (tmp_path / "policy.yaml").write_text(BASELINE.read_text(encoding="utf-8"), encoding="utf-8")
    p = from_questionnaire(
        {
            "product_id": "payments",
            "name": "Payments",
            "controls": {"supervised": True, "policy_files": ["policy.yaml"]},
        },
        base_dir=tmp_path,
    )
    assert p.source == "questionnaire" and p.controls.known and p.controls.basis == "declared"
    assert "PAY-03" in {r.id for r in p.controls.rules}
    assert "rule:PAY-03" in p.controls.pointers
    assert p.max_daily_vnd == 150_000_000
    assert p.max_transaction_vnd is None  # tools unknown: a question, not a guess


def test_questionnaire_without_controls_block_is_unknown() -> None:
    p = from_questionnaire({"product_id": "x", "name": "X"})
    assert p.controls.known is False and p.agent_classes is None and p.autonomy is None


def test_load_profile_input_from_onboard_files(tmp_path: Path) -> None:
    disc = discover(LocalGitRepoReader(AGENTS_DIR / "payments"))
    prof = understand(disc, MockChat(model_id="mock-onboarding-v1"))
    mp, _ = plan(disc.inventory, prof, load_catalogue())
    (tmp_path / "profile.json").write_text(prof.model_dump_json(), encoding="utf-8")
    (tmp_path / "inventory.json").write_text(disc.inventory.model_dump_json(), encoding="utf-8")
    (tmp_path / "plan.json").write_text(mp.model_dump_json(), encoding="utf-8")
    (tmp_path / "policy.yaml").write_text(BASELINE.read_text(encoding="utf-8"), encoding="utf-8")
    p = load_profile_input(tmp_path / "profile.json", answers={"customer_types": ["individual"]})
    assert isinstance(p, ProductProfile) and p.product_id == "payments"
    assert p.controls.known and "PAY-02" in {r.id for r in p.controls.rules}
    assert p.customer_types == ("individual",)
    (tmp_path / "inventory.json").unlink()
    with pytest.raises(ProfileInputError):
        load_profile_input(tmp_path / "profile.json")


def test_load_profile_input_product_yaml(tmp_path: Path) -> None:
    f = tmp_path / "product.yaml"
    f.write_text(json.dumps({"product_id": "p1", "name": "P one", "autonomy": "advisory"}))
    p = load_profile_input(f)
    assert p.autonomy == "advisory" and p.provenance["autonomy"][0].ref == "product.yaml#autonomy"
    with pytest.raises(ProfileInputError):
        load_profile_input(tmp_path / "missing.yaml")
