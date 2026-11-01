"""W2: fact-decidable checklist items, executive text per item, hitl without a verdict stop,
version 0.2 seeding beside 0.1, golden sets of all eight starters."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from supervisor.factory import caps, golden, linter, registry, starters, store
from supervisor.factory.__main__ import main
from supervisor.factory.schemas.agent_definition_v1 import (
    EXEC_OWNERS,
    AgentDefinitionV1,
    ChecklistItem,
)
from tests.factory.f3_helpers import FakeChat, make_env

DIR = starters.STARTERS_DIR
EIGHT = (*starters.STARTER_IDS, *starters.TEMPLATE_IDS)
ROOT = Path(starters.__file__).parents[3]

# The shared vocabulary of executive finding keys (agents -> keys it must cover).
KEY_MATRIX: dict[str, set[str]] = {
    "money_tool_no_gate": {"cyber-assessor", "ethics-assessor", "legal-compliance-assessor"},
    "declared_control_mismatch": {"legal-compliance-assessor", "ethics-assessor"},
    "personal_data_fields": {"data-governance-assessor"},
    "personal_data_mismatch": {"data-governance-assessor", "legal-compliance-assessor"},
    "pii_export_tool": {"data-governance-assessor", "cyber-assessor"},
    "model_unknown": {"model-risk-assessor", "supply-chain-assessor", "third-party-assessor"},
    "no_tracing": {"model-risk-assessor", "cyber-assessor"},
    "hardcoded_secret": {"cyber-assessor"},
    "external_endpoint": {"third-party-assessor", "cyber-assessor"},
    "risk_level_mismatch": {"legal-compliance-assessor"},
}
HIGH_KEYS = {
    "money_tool_no_gate",
    "declared_control_mismatch",
    "hardcoded_secret",
    "personal_data_mismatch",
    "risk_level_mismatch",
}
FORBIDDEN_WORDS = re.compile(
    r"\b(pack|hitl|flag|dimension|orchestrator|payload|schema|endpoint|row|record row|"
    r"leverage|seamless|robust|empower|unlock)\b",
    re.IGNORECASE,
)


def load(agent_id: str) -> dict[str, Any]:
    doc = yaml.safe_load((DIR / f"{agent_id}.yaml").read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def keyed(agent_id: str) -> dict[str, dict[str, Any]]:
    return {c["executive"]["key"]: c for c in load(agent_id)["checklist"]}


# ------------------------------------------------------------------------------ definitions


@pytest.mark.parametrize("agent_id", EIGHT)
def test_version_02_validates_with_and_without_executive(agent_id: str) -> None:
    d = load(agent_id)
    assert d["lifecycle"]["version"] == "0.2" and d["lifecycle"]["state"] == "draft"
    model = store.validate_definition(d, registry.load_tools(), registry.load_groups())
    assert all(c.executive is not None for c in model.checklist)
    # the off path: the same definition without any executive block still validates, and an item
    # without it dumps exactly as it did before the block existed
    bare = copy.deepcopy(d)
    for c in bare["checklist"]:
        c.pop("executive")
    plain = store.validate_definition(bare, registry.load_tools(), registry.load_groups())
    assert all(c.executive is None for c in plain.checklist)
    assert all("executive" not in c for c in plain.model_dump(mode="json")["checklist"])
    assert all("executive" in c for c in model.model_dump(mode="json")["checklist"])
    issues = linter.lint_definition(d)
    assert linter.is_ready(issues) and not linter.has_errors(issues)


def test_executive_block_is_strict() -> None:
    base = {
        "id": "X-1",
        "question": "q",
        "evidence": ["fact"],
        "severity": "low",
        "pass_rule": "p",
    }
    text = {"en": "a", "vi": "b"}
    good = {
        "key": "some_key",
        "headline_fail": text,
        "headline_open": text,
        "impact": text,
        "action": text,
        "owner": "security",
    }
    assert ChecklistItem.model_validate({**base, "executive": good}).executive is not None
    for bad in (
        {**good, "owner": "ceo"},
        {**good, "key": "Not A Key"},
        {**good, "extra": 1},
        {**good, "impact": {"en": "a"}},
        {k: v for k, v in good.items() if k != "action"},
    ):
        with pytest.raises(ValidationError):
            ChecklistItem.model_validate({**base, "executive": bad})
    assert set(EXEC_OWNERS) == {
        "system_owner",
        "risk_team",
        "security",
        "data_owner",
        "legal",
        "model_validation",
    }


@pytest.mark.parametrize("agent_id", EIGHT)
def test_every_item_has_plain_bilingual_executive_text(agent_id: str) -> None:
    d = AgentDefinitionV1.model_validate(load(agent_id))
    keys = [c.executive.key for c in d.checklist if c.executive]
    assert len(keys) == len(d.checklist) == len(set(keys)), "one unique key per item"
    for c in d.checklist:
        ex = c.executive
        assert ex is not None
        for field in (ex.headline_fail, ex.headline_open, ex.impact, ex.action):
            assert not FORBIDDEN_WORDS.search(field.en), (c.id, field.en)
            assert field.en.endswith(".") and field.vi.endswith("."), (c.id, field)
            assert any(ord(ch) > 127 for ch in field.vi), (c.id, field.vi)  # real Vietnamese
            assert len(field.en.split()) <= 30, (c.id, field.en)
        # an open item says what could not be confirmed; it never claims a missing control
        assert not re.search(r"\b(no protection|not protected|unprotected)\b", ex.headline_open.en)


def test_the_pii_canary_item_uses_the_owner_wording() -> None:
    ex = next(c for c in load("data-governance-assessor")["checklist"] if c["id"] == "DG-09")[
        "executive"
    ]
    assert ex["headline_open"]["en"] == (
        "No test has shown that the agent keeps personal data out of its answers."
    )
    assert ex["impact"]["en"].startswith("A leak of national ID or account numbers would breach")
    assert ex["action"]["en"].startswith("Run the personal-data leak test before go-live")
    assert ex["owner"] == "system_owner"


@pytest.mark.parametrize("key", sorted(KEY_MATRIX))
def test_every_shared_key_is_covered_where_it_fits(key: str) -> None:
    for agent_id in KEY_MATRIX[key]:
        item = keyed(agent_id).get(key)
        assert item is not None, (key, agent_id)
        assert "fact" in item["evidence"], (key, agent_id)
        assert re.search(r"Art\. \d+", item["question"]), item["id"]
        if key in HIGH_KEYS:
            assert item["severity"] == "high", (key, agent_id)


@pytest.mark.parametrize("agent_id", EIGHT)
def test_no_verdict_stop_and_the_locked_rule_stays(agent_id: str) -> None:
    d = load(agent_id)
    assert d["harness"]["hitl"]["approval_points"] == []
    # fail on a high item still needs a person: the locked rule is in the runtime, not the list
    assert any(c["severity"] == "high" for c in d["checklist"])


# ------------------------------------------------------------------------------ the fact rules


def source_text(path: str) -> str:
    return (ROOT / "src" / "supervisor" / "onboard" / path).read_text(encoding="utf-8")


def test_pass_rules_quote_what_the_scanner_writes() -> None:
    """A pass rule names the exact words of the scanner; if the scanner text changes, this fails."""
    understand, facts = source_text("understand.py"), source_text("facts.py")
    rules = " ".join(
        [c["pass_rule"] for a in EIGHT for c in load(a)["checklist"]]
        + [load(a)["instructions"] for a in EIGHT]
    )
    for phrase, where in (
        ("tools with side effects and no human approval step in code", understand),
        ("No tracing found", understand),
        ("every tool with a side effect has a human approval step in the same code", understand),
        ("human_gate_in_code=", facts),
        ("risk_class=", facts),
        ("approved=", facts),
        ("family=", facts),
        ("Handles personal data field", understand + facts + source_text("codefacts.py")),
        ("secret_use", facts),
        ("approval_point", facts),
    ):
        base = phrase.rstrip("=")
        assert base in where or base.replace("_", " ") in where, phrase
        assert base in rules, f"no pass rule names {phrase!r}"
    assert "'transactions triggered'" in rules and "triggered" in understand


def test_fact_items_name_their_fact_kinds() -> None:
    expect = {
        "money_tool_no_gate": ("risk_class=money", "autonomy", "human_gate_in_code=False"),
        "pii_export_tool": ("risk_class=pii_export", "approval_point"),
        "no_tracing": ("weak_spot", "No tracing found"),
        "hardcoded_secret": ("secret_use",),
        "external_endpoint": ("external_url", "loopback", "FILL-ME"),
        "model_unknown": ("family=unknown",),
        "declared_control_mismatch": ("human_control", "pre_approval", "approval_point"),
        "risk_level_mismatch": ("high_risk", "risk_level"),
        "personal_data_mismatch": ("personal_data", "Handles personal data field"),
        "personal_data_fields": ("Handles personal data field", "approved=no"),
    }
    for key, agents in KEY_MATRIX.items():
        for agent_id in agents:
            rule = keyed(agent_id)[key]["pass_rule"]
            if key == "money_tool_no_gate" and agent_id == "legal-compliance-assessor":
                continue  # the legal wording reads the decision33 fact (checked below)
            for needle in expect[key]:
                assert needle in rule, (agent_id, key, needle)
    legal = keyed("legal-compliance-assessor")["money_tool_no_gate"]["pass_rule"]
    assert "transactions triggered" in legal
    for agent_id in EIGHT:
        for c in load(agent_id)["checklist"]:
            if c["executive"]["key"] in KEY_MATRIX:
                assert len(c["pass_rule"]) <= caps.PASS_RULE_MAX
                assert (
                    "approved=yes" in c["pass_rule"]
                    or c["executive"]["key"] not in ("money_tool_no_gate",)
                    or agent_id == "legal-compliance-assessor"
                )


# ------------------------------------------------------------------------------ golden sets


@pytest.mark.parametrize("agent_id", EIGHT)
def test_golden_counts_and_new_items_covered(agent_id: str) -> None:
    d = load(agent_id)
    ids = [c["id"] for c in d["checklist"]]
    cases = json.loads((DIR / "golden" / agent_id / "cases.json").read_text(encoding="utf-8"))
    labels = json.loads(
        (DIR / "golden" / agent_id / "calibration.json").read_text(encoding="utf-8")
    )
    assert len(cases) >= caps.GOLDEN_MIN_CASES and len(labels) >= caps.CALIBRATION_MIN_LABELS
    ok, bad = golden.check_gate_cases(cases, ids)
    assert not bad and len(ok) == len(cases)
    strat = golden.gate_stratification(ok, ids)
    assert strat["ready"], strat["problems"]
    assert all(n >= 3 for n in strat["per_item"].values())
    # a case of a fact item carries a fact in its inputs
    fact_items = {c["id"] for c in d["checklist"] if c["executive"]["key"] in KEY_MATRIX}
    for case in ok:
        cid = next(iter(case["expected"]))
        if cid in fact_items and case["expected"][cid] in ("pass", "fail"):
            assert case["inputs"].get("facts", {}).get("facts"), case["case_id"]


# ------------------------------------------------------------------------------ seeding


def as_old_version(agent_id: str) -> dict[str, Any]:
    """A version 0.1 row of the agent, made from the 0.2 file (what an older catalogue holds):
    the first checklist items only and no executive block."""
    d = copy.deepcopy(load(agent_id))
    d["checklist"] = d["checklist"][:8]
    for c in d["checklist"]:
        c.pop("executive")
    d["harness"]["hitl"]["approval_points"] = [{"kind": "verdict", "ref": "question"}]
    d["instructions"] = d["instructions"].split("Fact items")[0] + "\n".join(
        c["id"] for c in d["checklist"]
    )
    d["lifecycle"]["version"] = "0.1"
    return d


def put_old(env: Any, agent_id: str) -> dict[str, Any]:
    model = store.validate_definition(as_old_version(agent_id), env.store.tools, env.store.groups)
    env.store.state.insert(
        store.AGENT_TABLE,
        {
            "id": agent_id,
            "version": "0.1",
            "owner_group": model.owner_group,
            "dimension_id": model.dimension_id,
            "definition_json": model.model_dump(mode="json"),
            "state": "draft",
            "created_by": "starter.seed",
        },
    )
    return env.store.get(agent_id, "0.1")


@pytest.fixture
def env(adapters: Any, sink: Any, tmp_path: Path) -> Any:
    return make_env(adapters, sink, FakeChat(), tmp_path)


def test_seed_adds_02_beside_01_and_leaves_01_alone(env: Any) -> None:
    old = {a: put_old(env, a) for a in ("cyber-assessor", "ethics-assessor")}
    first = starters.seed(env.store, env.data_dir)
    assert sorted(first["added"]) == ["cyber-assessor@0.2", "ethics-assessor@0.2"]
    assert "cyber-assessor" not in first["created"] and first["created"]
    for agent_id, before in old.items():
        versions = [r["version"] for r in env.store.versions(agent_id)]
        assert versions == ["0.1", "0.2"]
        after = env.store.get(agent_id, "0.1")
        assert after == before  # the 0.1 row is byte for byte what it was
        new = env.store.get(agent_id, "0.2")
        assert new["state"] == "draft"
        assert all(c.get("executive") for c in new["definition"]["checklist"])
        assert new["definition"]["harness"]["hitl"]["approval_points"] == []
        assert len(golden.load_gate_cases(env.data_dir, agent_id)) >= 50
    events = [e for e in env.store.events("cyber-assessor", "0.2") if e["kind"] == "created"]
    assert events and "beside 0.1" in events[0]["detail"]
    # a second call changes nothing
    snapshot = [(r["id"], r["version"], r["row_version"]) for r in env.store.list_agents()]
    second = starters.seed(env.store, env.data_dir)
    assert second["created"] == [] and second["added"] == []
    assert snapshot == [(r["id"], r["version"], r["row_version"]) for r in env.store.list_agents()]


def test_seed_never_replaces_a_team_version(env: Any) -> None:
    put_old(env, "cyber-assessor")
    env.store.retire("cyber-assessor", "0.1", "reviewer.an", "replaced by the team's version")
    row = env.store.new_version("cyber-assessor", "0.1", "reviewer.an")  # the team's own 0.2
    assert row["version"] == "0.2"
    result = starters.seed(env.store, env.data_dir)
    assert "cyber-assessor" in result["skipped"] and result["added"] == []
    assert (
        env.store.get("cyber-assessor", "0.2")["definition"]["checklist"][0].get("executive")
        is None
    )  # still the team's copy of 0.1


def test_seed_cli_reports_an_added_version(env: Any, capsys: pytest.CaptureFixture[str]) -> None:
    put_old(env, "model-risk-assessor")
    assert main(["seed"], gate_env=env) == 0
    out = capsys.readouterr().out
    assert "[OK] added model-risk-assessor@0.2 (draft, beside the older version)" in out
    assert out.count("[OK] created") == 7


@pytest.mark.parametrize("agent_id", starters.TEMPLATE_IDS)
def test_full_gate_with_fake_model_for_supply_chain_and_reputation(
    env: Any, agent_id: str, capsys: pytest.CaptureFixture[str]
) -> None:
    from supervisor.factory import gate

    starters.seed(env.store, env.data_dir)
    main(["gate", agent_id, "--kind", "full", "--model", "fake"], gate_env=env)
    run = gate.latest_runs(env, agent_id, None, 1)[0]
    assert run["status"] == "done", capsys.readouterr().out
    assert run["layer1"]["percent"] == 100 and run["layer1"]["ok"], run["layer1"]
