"""WP-G2 Decision 33 classification: the flow file, the pure decision, the draft / edit / apply
steps, the segregation rule, the classifier floor and the optional AI pre-fill."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.adapters.llm.mock import MockChat
from supervisor.cases.service import PermissionDenied
from supervisor.config import load_settings
from supervisor.governance import decision33 as d33
from supervisor.governance.classification import ClassificationService
from supervisor.governance.conditions import RulesError
from supervisor.governance.model import SegregationOfDuties, SystemsError
from supervisor.governance.rules import facts_of
from supervisor.governance.rules_service import RulesService
from supervisor.governance.systems import SystemService

from .conftest import ListSink, draft, person

FLOW = Path(__file__).resolve().parents[2] / "config" / "decision33.yaml"


def _csvc(
    adapters: Adapters, sink: ListSink | None = None, chat: Any = None
) -> ClassificationService:
    return ClassificationService.from_adapters(adapters, evidence=sink, chat=chat)


def _yes(*ids: str) -> dict[str, dict[str, Any]]:
    flow = d33.load_flow(FLOW)
    out = {q: d33.entry("no", "person") for q in flow.ids}
    for i in ids:
        out[i] = d33.entry("yes", "person")
    return out


# ---- the flow file ----------------------------------------------------------------------------


def test_flow_loads_with_four_questions_and_ordered_outcomes() -> None:
    flow = d33.load_flow(FLOW)
    assert flow.ids == ("Q-MONEY", "Q-CREDIT", "Q-PRE-APPROVAL", "Q-OTHER")
    assert [o.id for o in flow.outcomes] == ["D33-TRANSACTION", "D33-CREDIT", "D33-OTHER"]
    assert flow.question("Q-OTHER").derive is None  # only a person answers it
    assert len(flow.sha256) == 64


@pytest.mark.parametrize(
    ("patch", "fragment"),
    [
        ({"version": 2}, "version must be 1"),
        ({"colour": 1}, "unknown key: colour"),
        ({"questions": []}, "non-empty list"),
        ({"default": {"complete": "maybe", "incomplete": "unclassified"}}, "default must name"),
        ({"default": {"complete": "not_high_risk", "incomplete": "high_risk"}}, "unclassified"),
        (
            {
                "outcomes": [
                    {
                        "id": "O",
                        "outcome": "high_risk",
                        "reason": "r",
                        "when": {"field": "Q-NOPE", "eq": "yes"},
                    }
                ]
            },
            "unknown field",
        ),
        (
            {
                "outcomes": [
                    {
                        "id": "O",
                        "outcome": "maybe",
                        "reason": "r",
                        "when": {"field": "Q-OTHER", "eq": "yes"},
                    }
                ]
            },
            "outcome must be one of",
        ),
        (
            {
                "outcomes": [
                    {
                        "id": "O",
                        "outcome": "high_risk",
                        "reason": "r",
                        "when": {"field": "Q-OTHER", "eq": "perhaps"},
                    }
                ]
            },
            "not one of",
        ),
    ],
)
def test_flow_schema_is_strict(patch: dict[str, Any], fragment: str, tmp_path: Path) -> None:
    import yaml

    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    doc.update(patch)
    with pytest.raises(RulesError, match=fragment):
        d33.parse_flow(doc, "0" * 64)


def test_unquoted_yes_no_in_the_flow_is_read_as_text() -> None:
    import yaml

    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    doc["outcomes"][2]["when"] = {"field": "Q-OTHER", "eq": True}  # a bare `yes` in YAML
    flow = d33.parse_flow(doc, "0" * 64)
    assert d33.decide(flow, _yes("Q-OTHER")).outcome == "high_risk"


# ---- the decision -----------------------------------------------------------------------------


def test_decision_table() -> None:
    flow = d33.load_flow(FLOW)
    row = {"human_control": "post_review", "money_movement": True, "credit_decision": False}
    facts = facts_of(row, "low", {}, ())
    derived = d33.derive(flow, facts)
    assert derived["Q-MONEY"]["answer"] == "yes" and derived["Q-MONEY"]["source"] == "rules"
    assert derived["Q-PRE-APPROVAL"]["answer"] == "no"
    assert derived["Q-OTHER"]["answer"] is None
    # money, no approval before execution -> high risk, even with one question open
    assert d33.decide(flow, derived).outcome == "high_risk"
    # approval before execution takes it out of entry 1; still open -> unclassified
    with_approval = {**derived, "Q-PRE-APPROVAL": d33.entry("yes", "person")}
    assert d33.decide(flow, with_approval).outcome == "unclassified"
    done = {**with_approval, "Q-OTHER": d33.entry("no", "person")}
    dec = d33.decide(flow, done)
    assert (dec.outcome, dec.rule_id, dec.complete) == ("not_high_risk", None, True)
    assert d33.decide(flow, _yes("Q-CREDIT")).outcome == "high_risk"
    assert d33.decide(flow, _yes("Q-CREDIT", "Q-PRE-APPROVAL")).outcome == "not_high_risk"
    assert d33.decide(flow, _yes("Q-OTHER")).rule_id == "D33-OTHER"
    assert d33.decide(flow, {}).outcome == "unclassified"


def test_decision_is_deterministic() -> None:
    flow = d33.load_flow(FLOW)
    a = _yes("Q-MONEY")
    assert d33.decide(flow, a).outcome == d33.decide(flow, dict(reversed(list(a.items())))).outcome


# ---- the steps --------------------------------------------------------------------------------


def test_draft_from_rules_does_not_change_the_system(
    gsvc: SystemService, gadapters: Adapters, sink: ListSink
) -> None:
    s = gsvc.register(draft(money_movement=True, human_control="post_review"), "owner.lan")
    c = _csvc(gadapters, sink)
    out = c.draft(s["system_id"], "owner.lan")
    assert out["outcome"] == "high_risk" and out["status"] == "draft"
    assert out["decided_by_rule"] == "D33-TRANSACTION"
    by = {a["id"]: a for a in out["answers"]}
    assert by["Q-MONEY"]["source"] == "rules" and by["Q-OTHER"]["answer"] is None
    after = gsvc.get(s["system_id"])
    assert after["decision33_class"] == "unclassified" and after["risk_level"] == "unspecified"
    rec = sink.of("classification_change")[-1]
    assert rec["action"] == "draft" and rec["outcome"] == "high_risk"
    assert rec["answers_by_source"]["rules"] == 3 and rec["ai_prefill"] is False


def test_a_benign_system_stays_unclassified_until_a_person_answers(
    gsvc: SystemService, gadapters: Adapters
) -> None:
    s = gsvc.register(draft(human_control="pre_approval"), "owner.lan")
    c = _csvc(gadapters)
    out = c.draft(s["system_id"], "owner.lan")
    assert out["outcome"] == "unclassified"
    with pytest.raises(SystemsError, match="not complete"):
        c.apply(s["system_id"], person("rev.an", "owner"))
    out = c.edit(
        s["system_id"], "owner.lan", {"Q-OTHER": {"answer": "no", "justification": "Checked."}}
    )
    assert out["outcome"] == "not_high_risk"
    other = next(a for a in out["answers"] if a["id"] == "Q-OTHER")
    assert other["source"] == "person" and other["justification"] == "Checked."


def test_edit_refuses_bad_input(gsvc: SystemService, gadapters: Adapters) -> None:
    s = gsvc.register(draft(), "owner.lan")
    c = _csvc(gadapters)
    with pytest.raises(SystemsError, match="no draft"):
        c.edit(s["system_id"], "owner.lan", {"Q-OTHER": {"answer": "no"}})
    c.draft(s["system_id"], "owner.lan")
    for bad, msg in [
        ({"Q-NOPE": {"answer": "no"}}, "unknown question"),
        ({"Q-OTHER": {"answer": "maybe"}}, "yes or no"),
        ({"Q-OTHER": {"justification": "x"}}, "answer is required"),
        ({"Q-OTHER": {"answer": "no", "colour": 1}}, "give answer"),
        ({"Q-OTHER": {"answer": "no", "justification": "x" * 600}}, "500 characters"),
        ({}, "object of question id"),
    ]:
        with pytest.raises(SystemsError, match=msg):
            c.edit(s["system_id"], "owner.lan", bad)


def test_apply_sets_the_class_and_the_floor_and_reruns_the_rules(
    gsvc: SystemService, gadapters: Adapters, sink: ListSink
) -> None:
    s = gsvc.register(draft(money_movement=True), "owner.lan")
    sid = s["system_id"]
    c = _csvc(gadapters, sink)
    c.draft(sid, "owner.lan")
    out = c.apply(sid, person("rev.an", "reviewer"))
    assert out["applied"]["outcome"] == "high_risk" and out["draft"] is None
    after = gsvc.get(sid)
    assert after["decision33_class"] == "high_risk"
    assert after["risk_level"] == "high" and after["risk_level_source"] == "classifier"
    assert after["effective_risk"]["level"] == "high"
    assert after["effective_risk"]["source"] == "classifier"
    # the update re-ran the rules: Decision 33 high risk now fires
    floor = {f["slug"] for f in RulesService.from_adapters(gadapters).guardian_floor(sid)}
    assert floor == {"dlp_vn", "injection_regex"}
    rec = sink.of("classification_change")[-1]
    assert rec["action"] == "apply" and rec["status"] == "applied"
    text = json.dumps(rec, sort_keys=True)
    assert "rev.an" not in text and "owner.lan" not in text


def test_floor_never_lowers_a_higher_level_and_apply_never_lowers(
    gsvc: SystemService, gadapters: Adapters
) -> None:
    s = gsvc.register(draft(money_movement=True), "owner.lan")
    sid = s["system_id"]
    gsvc.update_fields(sid, {"risk_level": "prohibited"}, "owner.lan")
    c = _csvc(gadapters)
    c.draft(sid, "owner.lan")
    c.apply(sid, person("rev.an", "admin"))
    assert gsvc.get(sid)["risk_level"] == "prohibited"
    # a second system: classed high, then the facts change and it is classed not high
    t = gsvc.register(draft(name="Second", money_movement=True), "owner.lan")
    tid = t["system_id"]
    c.draft(tid, "owner.lan")
    c.apply(tid, person("rev.an", "admin"))
    assert gsvc.get(tid)["risk_level"] == "high"
    gsvc.update_fields(tid, {"money_movement": False}, "owner.lan")
    c.draft(tid, "owner.lan")
    c.edit(tid, "owner.lan", {"Q-OTHER": {"answer": "no", "justification": "Reviewed."}})
    c.apply(tid, person("rev.an", "admin"))
    after = gsvc.get(tid)
    # apply never lowers the stored level (lower_risk_level does, with a reason)
    assert after["decision33_class"] == "not_high_risk" and after["risk_level"] == "high"
    assert c.get(tid)["draft"] is None
    assert c.get(tid)["history_n"] == 2


def test_segregation_of_duties_and_permission(gsvc: SystemService, gadapters: Adapters) -> None:
    s = gsvc.register(draft(money_movement=True), "owner.lan")
    sid = s["system_id"]
    gsvc.add_member(sid, "rev.an", "reviewer", "owner.lan")
    gsvc.add_member(sid, "ovs.binh", "oversight_manager", "owner.lan")
    c = _csvc(gadapters)
    c.draft(sid, "owner.lan")
    for who in ("rev.an", "ovs.binh"):
        with pytest.raises(SegregationOfDuties, match="^segregation of duties:"):
            c.apply(sid, person(who, "reviewer"))
    with pytest.raises(PermissionDenied):
        c.apply(sid, person("viewer.hoa", "viewer"))
    assert gsvc.get(sid)["decision33_class"] == "unclassified"
    c.apply(sid, person("someone.else", "reviewer"))
    assert gsvc.get(sid)["decision33_class"] == "high_risk"


def test_a_new_draft_replaces_the_open_one_and_resets_to_the_rules(
    gsvc: SystemService, gadapters: Adapters
) -> None:
    s = gsvc.register(draft(), "owner.lan")
    c = _csvc(gadapters)
    c.draft(s["system_id"], "owner.lan")
    c.edit(s["system_id"], "owner.lan", {"Q-OTHER": {"answer": "yes", "justification": "x"}})
    again = c.draft(s["system_id"], "owner.lan")
    assert again["outcome"] == "unclassified"
    assert gadapters.state.query("classification", {"system_id": s["system_id"]}).__len__() == 1


def test_archived_and_flag_off(
    gsvc: SystemService, gadapters: Adapters, adapters: Adapters
) -> None:
    s = gsvc.register(draft(), "owner.lan")
    gsvc.archive(s["system_id"], "owner.lan")
    with pytest.raises(SystemsError, match="archived"):
        _csvc(gadapters).draft(s["system_id"], "owner.lan")
    with pytest.raises(SystemsError, match="GOVERNANCE_ENABLED"):
        _csvc(adapters).draft("sys_x", "owner.lan")


# ---- the optional AI pre-fill -----------------------------------------------------------------


def _prefill_setup(tmp_path: Path, *, flag: bool) -> tuple[Adapters, MockChat]:
    from supervisor.adapters.factory import build_adapters
    from supervisor.jobs import bootstrap_schema

    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "pf",
        llm_base_url="",
        governance_enabled=True,
        classifier_ai_prefill=flag,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    chat = MockChat()
    chat.add_script(
        "pf",
        [
            {
                "answers": [
                    {"id": "Q-OTHER", "answer": "yes", "justification": "Looks like biometric ID."},
                    {"id": "Q-MONEY", "answer": "no", "justification": "must be ignored"},
                    {"id": "Q-NOPE", "answer": "yes", "justification": "unknown id"},
                ]
            }
        ],
    )
    return a, chat


def test_prefill_is_off_by_default_and_never_calls_the_model(tmp_path: Path) -> None:
    a, chat = _prefill_setup(tmp_path, flag=False)
    try:
        s = SystemService.from_adapters(a).register(draft(), "owner.lan")
        with chat.scenario("pf"):
            out = _csvc(a, chat=chat).draft(s["system_id"], "owner.lan")
        assert chat.calls == [] and out["ai_prefill"]["used"] is False
        assert all(x["source"] != "ai_prefill" for x in out["answers"])
    finally:
        a.close()


def test_prefill_tags_answers_labels_the_mock_and_a_person_must_apply(
    tmp_path: Path, sink: ListSink
) -> None:
    a, chat = _prefill_setup(tmp_path, flag=True)
    try:
        svc = SystemService.from_adapters(a, evidence=sink)
        s = svc.register(draft(human_control="pre_approval"), "owner.lan")
        sid = s["system_id"]
        c = _csvc(a, sink, chat)
        with chat.scenario("pf"):
            out = c.draft(sid, "owner.lan")
        assert out["ai_prefill"] == {
            "used": True,
            "mock": True,
            "model": "mock-chat-v1",
            "answers_n": 1,
        }
        by = {x["id"]: x for x in out["answers"]}
        assert by["Q-OTHER"]["source"] == "ai_prefill" and by["Q-OTHER"]["answer"] == "yes"
        assert by["Q-OTHER"]["mock"] is True and by["Q-OTHER"]["justification"].startswith("[mock]")
        assert by["Q-MONEY"]["source"] == "rules"  # a field answer is never overwritten
        assert out["outcome"] == "high_risk"
        # the service never applied it
        assert svc.get(sid)["decision33_class"] == "unclassified"
        rec = sink.of("classification_change")[-1]
        assert rec["ai_prefill"] is True and rec["mock"] is True
        assert rec["answers_by_source"]["ai_prefill"] == 1
        # a person must confirm the AI answers before applying
        with pytest.raises(SystemsError, match="AI pre-filled answers"):
            c.apply(sid, person("rev.an", "admin"))
        c.apply(sid, person("rev.an", "admin"), confirm_ai_prefill=True)
        assert svc.get(sid)["decision33_class"] == "high_risk"
    finally:
        a.close()


def test_a_person_editing_an_ai_answer_takes_it_over(tmp_path: Path) -> None:
    a, chat = _prefill_setup(tmp_path, flag=True)
    try:
        s = SystemService.from_adapters(a).register(
            draft(human_control="pre_approval"), "owner.lan"
        )
        c = _csvc(a, chat=chat)
        with chat.scenario("pf"):
            c.draft(s["system_id"], "owner.lan")
        out = c.edit(
            s["system_id"], "owner.lan", {"Q-OTHER": {"answer": "no", "justification": "Checked."}}
        )
        assert next(x for x in out["answers"] if x["id"] == "Q-OTHER")["source"] == "person"
        assert (
            c.apply(s["system_id"], person("rev.an", "admin"))["applied"]["outcome"]
            == "not_high_risk"
        )
    finally:
        a.close()


def test_a_failing_model_leaves_the_draft_without_a_prefill(tmp_path: Path) -> None:
    a, _ = _prefill_setup(tmp_path, flag=True)

    class Broken:
        is_mock = False
        model_id = "broken"

        def complete_json(self, *args: Any, **kw: Any) -> Any:
            raise TimeoutError("down")

    try:
        s = SystemService.from_adapters(a).register(draft(), "owner.lan")
        out = _csvc(a, chat=Broken()).draft(s["system_id"], "owner.lan")
        assert out["ai_prefill"]["used"] is False
        assert all(x["source"] != "ai_prefill" for x in out["answers"])
    finally:
        a.close()
