"""WP-G2 assignment rules: strict schema, pure evaluator, determinism, the assignment table, the
chain record, and the runs on register, update, link and unlink."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.adapters.factory import Adapters
from supervisor.config import load_settings
from supervisor.governance import rules as R
from supervisor.governance.conditions import RulesError
from supervisor.governance.rules_service import RulesService, build_catalogue
from supervisor.governance.systems import SystemService

from .conftest import ListSink, add_agent, draft

CUSTOMER = {"user_segment": "customer", "personal_data": "identifiable"}
STARTER = Path(__file__).resolve().parents[2] / "config" / "assignment_rules.yaml"


def _rules(adapters: Adapters) -> RulesService:
    return RulesService.from_adapters(adapters)


def _kinds(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["kind"], []).append(r["ref_id"])
    return out


# ---- the file ---------------------------------------------------------------------------------


def test_starter_file_loads_and_names_only_known_ids() -> None:
    s = load_settings(sql_backend="sqlite", llm_base_url="")
    rs = R.load_rules(STARTER)
    assert {r.id for r in rs.rules} >= {
        "AR-PDPL-CUSTOMER",
        "AR-C53-MONEY",
        "AR-D33-HIGH",
        "AR-BASELINE",
    }
    assert len(rs.sha256) == 64
    assert R.problems(rs, build_catalogue(s)) == []


def test_starter_example_matches_the_spec_shape() -> None:
    rs = R.load_rules(STARTER)
    pdpl = next(r for r in rs.rules if r.id == "AR-PDPL-CUSTOMER")
    assert pdpl.title == "Customer personal data duties"
    assert set(pdpl.assign) == {"obligation", "control", "risk", "task", "guardian"}


def _doc(**over: Any) -> list[dict[str, Any]]:
    rule: dict[str, Any] = {
        "id": "AR-T",
        "when": {"field": "personal_data", "eq": "none"},
        "assign": {"controls": ["CTL-X"]},
    }
    rule.update(over)
    return [rule]


@pytest.mark.parametrize(
    ("doc", "fragment"),
    [
        ({"id": "x"}, "list of rules"),
        (_doc(colour="red"), "unknown key: colour"),
        (_doc(id="bad id"), "id must be"),
        (_doc(when={"field": "nope", "eq": 1}), "unknown field nope"),
        (_doc(when={"field": "personal_data", "eq": "weird"}), "not one of"),
        (_doc(when={"field": "personal_data", "gte": "none"}), "gte works on ordered"),
        (_doc(when={"field": "money_movement", "eq": True, "in": [True]}), "exactly one operator"),
        (_doc(when={"field": "personal_data", "is_true": True}), "not a yes/no"),
        (_doc(when={"all": []}), "non-empty list"),
        (_doc(when={"all": [{"field": "status", "eq": "draft"}], "any": []}), "other keys"),
        (_doc(when={"field": "status", "eq": "draft", "extra": 1}), "unknown key: extra"),
        (_doc(assign={"controls": ["CTL-X"], "colour": ["a"]}), "unknown assign key"),
        (_doc(assign={"controls": []}), "non-empty list"),
        (_doc(assign={"controls": ["*"]}), "is not an id"),
        (_doc(assign={"controls": ["bad id"]}), "is not an id"),
        (_doc(assign={}), "assign is required"),
        (_doc(when={"field": "component.nope.count", "gte": 1}), "unknown field"),
        (_doc(when={"field": "component.tool.count", "gte": "x"}), "whole number"),
    ],
)
def test_strict_schema_refuses(doc: Any, fragment: str) -> None:
    with pytest.raises(RulesError, match=fragment):
        R.parse_rules(doc)


def test_duplicate_rule_id_and_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="used twice"):
        R.parse_rules(_doc() + _doc())
    with pytest.raises(RulesError, match="missing"):
        R.load_rules(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("- id: [unclosed", encoding="utf-8")
    with pytest.raises(RulesError, match="cannot read"):
        R.load_rules(bad)


def test_nesting_depth_is_capped() -> None:
    node: dict[str, Any] = {"field": "status", "eq": "draft"}
    for _ in range(12):
        node = {"not": node}
    with pytest.raises(RulesError, match="deeper"):
        R.parse_rules(_doc(when=node))


# ---- the evaluator ----------------------------------------------------------------------------

CAT = R.Catalogue(
    obligation=frozenset({"VN-A-1", "VN-A-2", "VN-B-1"}),
    control=frozenset({"CTL-X"}),
    task=frozenset({"T1"}),
)


def _set(*rules: dict[str, Any]) -> R.RuleSet:
    return R.RuleSet(R.parse_rules(list(rules)), "0" * 64)


def _facts(**over: Any) -> dict[str, Any]:
    row = {
        "personal_data": "none",
        "user_segment": "internal",
        "money_movement": False,
        "credit_decision": False,
        "human_control": "post_review",
        "decision33_class": "unclassified",
        "lifecycle_stage": "design",
        "business_impact": "unspecified",
        "risk_level": "unspecified",
        "status": "draft",
    }
    return R.facts_of({**row, **over}, over.get("effective", "low"), {"tool": 1}, ["money"])


def test_operators_all_any_not_and_ordered() -> None:
    rs = _set(
        {
            "id": "R1",
            "when": {
                "all": [
                    {"field": "personal_data", "in": ["identifiable", "special"]},
                    {
                        "any": [
                            {"field": "money_movement", "is_true": True},
                            {"field": "lifecycle_stage", "gte": "design"},
                        ]
                    },
                    {"not": {"field": "user_segment", "eq": "partner"}},
                ]
            },
            "assign": {"obligations": ["VN-A-*"], "controls": ["CTL-X"]},
        }
    )
    ev = R.evaluate(rs, _facts(personal_data="special"), CAT)
    assert ev.fired == ("R1",)
    assert [(a.kind, a.ref_id) for a in ev.assignments] == [
        ("obligation", "VN-A-1"),
        ("obligation", "VN-A-2"),
        ("control", "CTL-X"),
    ]
    assert ev.assignments[0].rules == (
        ("R1", ("lifecycle_stage", "personal_data", "user_segment")),
    )
    assert R.evaluate(rs, _facts(personal_data="none"), CAT).assignments == ()
    assert R.evaluate(rs, _facts(personal_data="special", user_segment="partner"), CAT).fired == ()
    assert (
        R.evaluate(rs, _facts(personal_data="special", lifecycle_stage="initiation"), CAT).fired
        == ()
    )


def test_derived_fields_counts_tool_class_and_effective_risk() -> None:
    rs = _set(
        {
            "id": "R-TOOL",
            "when": {"field": "component.tool.risk_class", "in": ["money", "credit"]},
            "assign": {"tasks": ["T1"]},
        },
        {
            "id": "R-COUNT",
            "when": {"field": "component.tool.count", "gte": 2},
            "assign": {"tasks": ["T1"]},
        },
        {
            "id": "R-EFF",
            "when": {"field": "effective_risk_level", "gte": "high"},
            "assign": {"controls": ["CTL-X"]},
        },
    )
    low = R.evaluate(rs, _facts(), CAT)
    assert low.fired == ("R-TOOL",)  # one tool, class money; not 2 tools; effective low
    assert low.of("task")[0].rule_id == "R-TOOL"
    high = R.evaluate(rs, _facts(effective="high"), CAT)
    assert high.fired == ("R-EFF", "R-TOOL")


def test_two_rules_give_one_assignment_with_both_reasons() -> None:
    rs = _set(
        {"id": "B", "when": {"field": "status", "eq": "draft"}, "assign": {"controls": ["CTL-X"]}},
        {
            "id": "A",
            "when": {"field": "status", "in": ["draft"]},
            "assign": {"controls": ["CTL-X"]},
        },
    )
    (a,) = R.evaluate(rs, _facts(), CAT).assignments
    assert a.rule_id == "A" and [r for r, _ in a.rules] == ["A", "B"]


def test_exact_id_not_in_catalogue_passes_through_but_is_reported() -> None:
    rs = _set(
        {
            "id": "R",
            "when": {"field": "status", "eq": "draft"},
            "assign": {"controls": ["CTL-BANK-ONLY", "NOPE-*"]},
        }
    )
    ev = R.evaluate(rs, _facts(), CAT)
    assert [a.ref_id for a in ev.assignments] == ["CTL-BANK-ONLY"]
    notes = R.problems(rs, CAT)
    assert any("CTL-BANK-ONLY" in n for n in notes) and any("matches nothing" in n for n in notes)


def test_evaluation_and_explanation_are_deterministic() -> None:
    rs = R.load_rules(STARTER)
    cat = build_catalogue(load_settings(sql_backend="sqlite", llm_base_url=""))
    facts = _facts(personal_data="identifiable", user_segment="customer", money_movement=True)
    runs = [R.evaluate(rs, dict(reversed(list(facts.items()))), cat) for _ in range(3)]
    assert runs[0].assignments == runs[1].assignments == runs[2].assignments
    texts = [R.explain_lines(rs, e) for e in runs]
    assert texts[0] == texts[1] == texts[2]
    assert all(line.isascii() for line in texts[0])
    assert any("AR-PDPL-CUSTOMER: FIRED" in ln for ln in texts[0])
    assert any("AR-D33-HIGH: no" in ln for ln in texts[0])


def test_starter_rules_for_each_family() -> None:
    rs = R.load_rules(STARTER)
    cat = build_catalogue(load_settings(sql_backend="sqlite", llm_base_url=""))
    ev = R.evaluate(rs, _facts(personal_data="identifiable", user_segment="customer"), cat)
    assert ev.fired == ("AR-BASELINE", "AR-PDPL-CUSTOMER")
    assert len(ev.of("obligation")) == 35 and ev.of("guardian")[0].ref_id == "dlp_vn"
    ev = R.evaluate(rs, _facts(money_movement=True), cat)
    assert "AR-C53-MONEY" in ev.fired and len(ev.of("obligation")) == 55
    ev = R.evaluate(rs, _facts(decision33_class="high_risk"), cat)
    assert "AR-D33-HIGH" in ev.fired
    assert {a.ref_id for a in ev.of("guardian")} == {"dlp_vn", "injection_regex"}
    ev = R.evaluate(rs, _facts(status="archived"), cat)
    assert ev.assignments == ()  # nothing, not even the baseline, for an archived system


# ---- the service: table, chain, hooks ---------------------------------------------------------


def test_register_runs_the_rules_and_writes_a_rule_run_record(
    gsvc: SystemService, gadapters: Adapters, sink: ListSink
) -> None:
    s = gsvc.register(draft(**CUSTOMER), "owner.lan")
    rows = _rules(gadapters).assignments(s["system_id"])
    kinds = _kinds(rows)
    assert "CTL-PII-MASK" in kinds["control"] and "dlp_vn" in kinds["guardian"]
    assert len(kinds["obligation"]) == 35
    runs = sink.of("rule_run")
    assert len(runs) == 1
    rec = runs[0]
    assert rec["trigger"] == "register" and rec["system_id"] == s["system_id"]
    assert rec["rules_sha256"] == R.load_rules(STARTER).sha256
    assert rec["rules_fired"] == ["AR-BASELINE", "AR-PDPL-CUSTOMER"]
    assert rec["assigned_n"] == len(rows) and rec["added_n"] == len(rows)
    assert rec["by_kind"]["obligation"] == 35
    # canonical JSON: no floats, no name, no user id
    text = json.dumps(rec, sort_keys=True)
    assert "owner.lan" not in text and "Payments" not in text
    assert not _has_float(rec)
    assert rec["actor_ref"].startswith("act_")


def _has_float(v: Any) -> bool:
    if isinstance(v, float):
        return True
    if isinstance(v, dict):
        return any(_has_float(x) for x in v.values())
    if isinstance(v, list):
        return any(_has_float(x) for x in v)
    return False


def test_update_deactivates_never_deletes_and_reactivates(
    gsvc: SystemService, gadapters: Adapters, sink: ListSink
) -> None:
    s = gsvc.register(draft(**CUSTOMER), "owner.lan")
    sid = s["system_id"]
    state = gadapters.state
    n0 = len(state.query("assignment", {"system_id": sid}))
    gsvc.update_fields(sid, {"user_segment": "internal"}, "owner.lan")
    rows = state.query("assignment", {"system_id": sid})
    assert len(rows) == n0  # never deleted
    active = _rules(gadapters).assignments(sid)
    assert "CTL-PII-MASK" in _kinds(active)["control"]  # AR-PDPL-STAFF now gives it
    assert "CTL-PII-SWEEP" not in _kinds(active)["control"]
    off = [r for r in rows if not r["active"]]
    assert off and {r["kind"] for r in off} >= {"control", "task", "risk"}
    assert sink.of("rule_run")[-1]["trigger"] == "update"
    assert sink.of("rule_run")[-1]["deactivated_n"] == len(off)
    gsvc.update_fields(sid, {"user_segment": "customer"}, "owner.lan")
    assert len(state.query("assignment", {"system_id": sid})) == n0
    assert all(
        r["active"]
        for r in state.query("assignment", {"system_id": sid})
        if r["kind"] != "obligation" or True
    )
    assert sink.of("rule_run")[-1]["reactivated_n"] == len(off)


def test_link_and_unlink_run_the_rules(
    gsvc: SystemService, gadapters: Adapters, sink: ListSink
) -> None:
    add_agent(gadapters, "pay-agent")
    s = gsvc.register(draft(), "owner.lan")
    n = len(sink.of("rule_run"))
    out = gsvc.link(s["system_id"], "agent", "pay-agent", "owner.lan")
    assert [r["trigger"] for r in sink.of("rule_run")][n:] == ["link"]
    gsvc.unlink(s["system_id"], out["components"][0]["component_id"], "owner.lan")
    assert [r["trigger"] for r in sink.of("rule_run")][n:] == ["link", "unlink"]
    facts = _rules(gadapters).system_facts(s["system_id"])
    assert facts["component.agent.count"] == 0


def test_facts_count_agents_and_tool_classes_from_the_inventory(
    gsvc: SystemService, gadapters: Adapters
) -> None:
    from supervisor.inventory.graph import Graph
    from supervisor.inventory.model import Node
    from supervisor.inventory.store import InventoryStore

    add_agent(gadapters, "pay-agent")
    g = Graph()
    agent = Node("system", "pay-agent", attrs={"role": "agent"})
    t1 = Node("tool", "pay-agent:transfer", own_risk="critical", attrs={"risk_class": "money"})
    t2 = Node("tool", "pay-agent:export", own_risk="high", attrs={"risk_class": "pii_export"})
    m = Node("model", "qwen", own_risk="medium")
    for tgt in (t1, t2, m):
        g.link(agent, "uses", tgt, "manifest", "m:1")
    for n in (agent, t1, t2, m):
        g.add_node(n)
    InventoryStore(gadapters.state, gadapters.clock).apply(g, source="manifest")
    s = gsvc.register(draft(), "owner.lan")
    gsvc.link(s["system_id"], "agent", "pay-agent", "owner.lan")
    facts = _rules(gadapters).system_facts(s["system_id"])
    assert facts["component.agent.count"] == 1
    assert facts["component.tool.count"] == 2 and facts["component.model.count"] == 1
    assert facts["component.tool.risk_class"] == ("money", "pii_export")
    refs = {a["ref_id"] for a in _rules(gadapters).assignments(s["system_id"])}
    assert "CTL-PII-SWEEP" in refs  # AR-TOOL-PII-EXPORT fired from the tool class


def test_same_system_same_file_same_assignments_and_explanation(tmp_path: Path) -> None:
    def build(name: str) -> tuple[list[dict[str, Any]], list[str]]:
        settings = load_settings(
            sql_backend="sqlite", data_dir=tmp_path / name, llm_base_url="", governance_enabled=True
        )
        from supervisor.adapters.factory import build_adapters
        from supervisor.jobs import bootstrap_schema

        a = build_adapters(settings)
        bootstrap_schema.run(a.settings, a)
        try:
            svc = SystemService.from_adapters(a)
            s = svc.register(draft(**CUSTOMER, money_movement=True), "owner.lan")
            rules = _rules(a)
            first = rules.assignments(s["system_id"])
            rules.run(s["system_id"], "owner.lan")
            rules.run(s["system_id"], "owner.lan")
            again = rules.assignments(s["system_id"])
            strip = lambda rows: [  # noqa: E731
                {k: v for k, v in r.items() if k not in ("first_seen", "last_seen")} for r in rows
            ]
            assert strip(first) == strip(again)
            return strip(again), rules.explain(s["system_id"])
        finally:
            a.close()

    one, text_one = build("one")
    two, text_two = build("two")
    assert one == two and text_one == text_two


def test_a_broken_rules_file_does_not_stop_a_change(tmp_path: Path, sink: ListSink) -> None:
    bad = tmp_path / "rules.yaml"
    bad.write_text(yaml.safe_dump([{"id": "X", "colour": 1}]), encoding="utf-8")
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "d",
        llm_base_url="",
        governance_enabled=True,
        assignment_rules_config=bad,
    )
    from supervisor.adapters.factory import build_adapters
    from supervisor.jobs import bootstrap_schema

    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        s = SystemService.from_adapters(a, evidence=sink).register(draft(), "owner.lan")
        assert s["status"] == "draft" and sink.of("rule_run") == []
        with pytest.raises(RulesError, match="unknown key"):
            _rules(a).run(s["system_id"], "owner.lan")
    finally:
        a.close()


def test_guardian_floor_lists_slugs_with_rule_ids(gsvc: SystemService, gadapters: Adapters) -> None:
    s = gsvc.register(draft(**CUSTOMER, money_movement=True), "owner.lan")
    floor = _rules(gadapters).guardian_floor(s["system_id"])
    assert floor == [
        {"slug": "dlp_vn", "rules": ["AR-PDPL-CUSTOMER"]},
        {"slug": "injection_regex", "rules": ["AR-C53-MONEY"]},
    ]
