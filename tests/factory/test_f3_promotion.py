"""WP-F3: the promotion workflow: every transition rule and refusal code, the two-person rule, the
author rule, immutable versions, rollback, definition-change detection, the chain records."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.factory import caps, gate, promotion
from supervisor.factory.store import TRANSITIONS, FactoryError, definition_sha256, permits
from tests.factory.f3_helpers import (
    ADMIN,
    AUTHOR,
    BINH,
    LEAD,
    SECOND,
    FakeChat,
    create_agent,
    load_golden,
    make_env,
    to_live,
    to_tested,
)


@pytest.fixture
def env(adapters: Any, sink: Any, tmp_path: Path) -> gate.GateEnv:
    return make_env(adapters, sink, FakeChat(), tmp_path)


def code(exc: pytest.ExceptionInfo[FactoryError]) -> str:
    return exc.value.code


def row_of(env: gate.GateEnv, v: str = "0.1", agent_id: str = "mr-agent") -> dict[str, Any]:
    r = env.store.get(agent_id, v)
    assert r is not None
    return r


def submit_ready(env: gate.GateEnv, agent_id: str = "mr-agent", v: str = "0.1") -> dict[str, Any]:
    to_tested(env, agent_id, v)
    promotion.submit(env.store, env.sink, row_of(env, v, agent_id), AUTHOR)
    return row_of(env, v, agent_id)


# ------------------------------------------------------------------------------ the wall


def test_transition_table_is_the_lifecycle() -> None:
    assert TRANSITIONS == {
        "draft": ("tested", "retired"),
        "tested": ("approved", "draft", "retired"),
        "approved": ("live", "draft", "retired"),
        "live": ("retired",),
        "retired": ("live",),
    }
    assert set(TRANSITIONS) == set(caps.LIFECYCLE_STATES)


def test_every_illegal_move_is_refused(env: gate.GateEnv) -> None:
    row = create_agent(env)
    for src, allowed in TRANSITIONS.items():
        for dst in caps.LIFECYCLE_STATES:
            if dst in allowed or dst == src:
                continue
            fake = {**row, "state": src}
            with pytest.raises(FactoryError) as exc:
                env.store.transition(fake, dst, "x", "saved", "t")
            assert code(exc) == "bad_transition"


def test_draft_cannot_skip_to_live_or_approved(env: gate.GateEnv) -> None:
    row = create_agent(env)
    for dst in ("approved", "live"):
        with pytest.raises(FactoryError) as exc:
            env.store.transition(row, dst, "x", "saved", "t")
        assert code(exc) == "bad_transition"


# ------------------------------------------------------------------------------ draft -> tested


def test_tested_only_by_a_passed_full_run_of_this_exact_definition(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    sample = gate.start(env, "mr-agent", "0.1", "sample", "x", background=False)
    with pytest.raises(FactoryError) as exc:
        promotion.mark_tested(env.store, env.sink, row_of(env), sample)
    assert code(exc) == "gate_not_passed"
    full = gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    assert row_of(env)["state"] == "tested"
    # a run of another definition sha never tests the version
    env2 = row_of(env)
    other = {**full, "definition_sha256": "0" * 64}
    with pytest.raises(FactoryError) as exc2:
        promotion.mark_tested(env.store, env.sink, {**env2, "state": "draft"}, other)
    assert code(exc2) == "gate_not_passed"
    assert not promotion.passed_full_run(
        env.store, {**env2, "definition": {**env2["definition"], "instructions": "x"}}
    )


def test_a_failed_full_run_leaves_a_draft_a_draft(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    env.chat.agent_answer = lambda u: {"findings": []}  # type: ignore[attr-defined]
    run = gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    assert run["verdict"] == "fail" and row_of(env)["state"] == "draft"


def test_a_failed_full_run_sends_a_tested_version_back_to_draft(env: gate.GateEnv) -> None:
    to_tested(env)
    env.chat.agent_answer = lambda u: {"findings": []}  # type: ignore[attr-defined]
    run = gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    assert run["verdict"] == "fail"
    r = row_of(env)
    assert r["state"] == "draft" and r["definition"]["lifecycle"]["state"] == "draft"
    assert [e["kind"] for e in env.store.events("mr-agent", "0.1")][-1] == "reopened"


def test_a_tested_version_is_immutable(env: gate.GateEnv) -> None:
    to_tested(env)
    row = row_of(env)
    with pytest.raises(FactoryError) as exc:
        env.store.save_draft(
            "mr-agent", "0.1", row["definition"], "reviewer.an", row["row_version"]
        )
    assert code(exc) == "not_draft"


# ------------------------------------------------------------------------------ submit


def test_submit_needs_a_tested_version(env: gate.GateEnv) -> None:
    row = create_agent(env)
    with pytest.raises(FactoryError) as exc:
        promotion.submit(env.store, env.sink, row, AUTHOR)
    assert code(exc) == "not_tested"


def test_unreferenced_checklist_items_block_submit_not_the_draft_save(env: gate.GateEnv) -> None:
    row = create_agent(env)
    d = copy.deepcopy(row["definition"])
    d["instructions"] = "Answer each item from the evidence only."
    saved = env.store.save_draft("mr-agent", "0.1", d, "reviewer.an", row["row_version"])
    assert saved["definition"]["instructions"].startswith("Answer each item")  # the save works
    load_golden(env, saved)
    with pytest.raises(gate.GateError) as exc:  # the full gate refuses
        gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    assert exc.value.code == "lint_not_ready" and "MR-01" in str(exc.value)
    # a tested version whose instructions lost the names cannot be submitted either
    d["instructions"] = row["definition"]["instructions"]
    env.store.save_draft("mr-agent", "0.1", d, "reviewer.an", row_of(env)["row_version"])
    to_tested(env)
    tested = row_of(env)
    env.state.update(
        "factory_agent",
        {"id": "mr-agent", "version": "0.1"},
        {"definition_json": {**tested["definition"], "instructions": "no names"}},
        tested["row_version"],
    )
    with pytest.raises(FactoryError) as exc2:
        promotion.submit(env.store, env.sink, row_of(env), AUTHOR)
    assert code(exc2) == "lint_not_ready"


def test_submit_records_an_event_and_a_chain_record(env: gate.GateEnv, sink: Any) -> None:
    submit_ready(env)
    assert promotion.is_submitted(env.store, row_of(env))
    assert any(r["action"] == "submitted" for r in sink.of("factory_promotion"))


# ------------------------------------------------------------------------------ approvals


def test_approval_needs_a_submitted_tested_version(env: gate.GateEnv) -> None:
    to_tested(env)
    with pytest.raises(FactoryError) as exc:
        promotion.approve(env.store, env.sink, row_of(env), LEAD, "owner_lead")
    assert code(exc) == "not_submitted"
    draft = create_agent(env, "other-agent")
    with pytest.raises(FactoryError) as exc2:
        promotion.approve(env.store, env.sink, draft, LEAD, "owner_lead")
    assert code(exc2) == "not_tested"


def test_high_tier_needs_owner_lead_and_second_line(env: gate.GateEnv) -> None:
    submit_ready(env)
    assert promotion.tier_of(row_of(env)["definition"]) == "high"
    need = promotion.required_approvals(env.store, row_of(env))
    assert need["kinds"] == ["owner_lead", "second_line"]
    after_lead = promotion.approve(env.store, env.sink, row_of(env), LEAD, "owner_lead", "ok")
    assert after_lead["state"] == "tested"  # one approval is not enough
    assert after_lead["definition"]["lifecycle"]["approvals"][0]["role"] == "owner_lead"
    done = promotion.approve(env.store, env.sink, row_of(env), SECOND, "second_line")
    assert done["state"] == "approved"
    assert [a["role"] for a in done["definition"]["lifecycle"]["approvals"]] == [
        "owner_lead",
        "second_line",
    ]


def test_the_two_approvals_need_two_different_people(env: gate.GateEnv) -> None:
    submit_ready(env)
    promotion.approve(env.store, env.sink, row_of(env), ADMIN, "owner_lead")
    with pytest.raises(FactoryError) as exc:  # the admin can be either role, never both
        promotion.approve(env.store, env.sink, row_of(env), ADMIN, "second_line")
    assert code(exc) == "same_person"
    assert row_of(env)["state"] == "tested"


def test_the_author_cannot_approve(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    # BINH saved the draft: BINH is an author even with the approver role and the group
    d = row_of(env)
    env.store.record_event("mr-agent", "0.1", "saved", BINH.user_id, "edited")
    promotion.submit(env.store, env.sink, d, AUTHOR)
    with pytest.raises(FactoryError) as exc:
        promotion.approve(env.store, env.sink, row_of(env), BINH, "owner_lead")
    assert code(exc) == "author_cannot_approve"
    created = row_of(env)["created_by"]
    assert created == "reviewer.an"
    creator = promotion.Actor(created, frozenset({"approver"}), frozenset({"model_risk"}))
    with pytest.raises(FactoryError) as exc2:
        promotion.approve(env.store, env.sink, row_of(env), creator, "owner_lead")
    assert code(exc2) == "author_cannot_approve"


def test_eligibility_per_kind(env: gate.GateEnv) -> None:
    submit_ready(env)
    cyber = promotion.Actor("lead.cyber", frozenset({"approver"}), frozenset({"cyber"}))
    reviewer = promotion.Actor("rev.x", frozenset({"reviewer"}), frozenset({"model_risk"}))
    for who, kind in ((cyber, "owner_lead"), (reviewer, "owner_lead"), (LEAD, "second_line")):
        with pytest.raises(FactoryError) as exc:
            promotion.approve(env.store, env.sink, row_of(env), who, kind)
        assert code(exc) == "not_eligible", (who.user_id, kind)


def test_a_given_approval_is_not_given_twice_and_the_kind_must_be_known(env: gate.GateEnv) -> None:
    submit_ready(env)
    promotion.approve(env.store, env.sink, row_of(env), LEAD, "owner_lead")
    lead2 = promotion.Actor("lead.two", frozenset({"approver"}), frozenset({"model_risk"}))
    with pytest.raises(FactoryError) as exc:
        promotion.approve(env.store, env.sink, row_of(env), lead2, "owner_lead")
    assert code(exc) == "already_approved"
    with pytest.raises(FactoryError) as exc2:
        promotion.approve(env.store, env.sink, row_of(env), LEAD, "boss")
    assert code(exc2) == "bad_kind"


def test_a_standard_tier_agent_needs_the_owner_lead_only(env: gate.GateEnv) -> None:
    row = create_agent(env, "eth-agent", "ethics")
    d = copy.deepcopy(row["definition"])
    for c in d["checklist"]:
        c["severity"] = "medium"
    row = env.store.save_draft("eth-agent", "0.1", d, "reviewer.an", row["row_version"])
    assert promotion.tier_of(row["definition"]) == "standard"
    to_tested(env, "eth-agent")
    promotion.submit(env.store, env.sink, row_of(env, "0.1", "eth-agent"), AUTHOR)
    need = promotion.required_approvals(env.store, row_of(env, "0.1", "eth-agent"))
    assert need["kinds"] == ["owner_lead"]
    lead = promotion.Actor("lead.eth", frozenset({"approver"}), frozenset({"ethics"}))
    done = promotion.approve(
        env.store, env.sink, row_of(env, "0.1", "eth-agent"), lead, "owner_lead"
    )
    assert done["state"] == "approved"


def test_a_kind_the_change_does_not_need_is_refused(env: gate.GateEnv) -> None:
    to_live(env)
    row = env.store.new_version("mr-agent", "0.1", "reviewer.an")
    d = copy.deepcopy(row["definition"])
    d["instructions"] += " MR-01 MR-02 are the items; answer briefly."
    env.store.save_draft("mr-agent", "0.2", d, "reviewer.an", row["row_version"])
    to_tested(env, "mr-agent", "0.2")
    promotion.submit(env.store, env.sink, row_of(env, "0.2"), AUTHOR)
    need = promotion.required_approvals(env.store, row_of(env, "0.2"))
    assert need["change"] == "content" and need["kinds"] == ["owner_lead"]
    with pytest.raises(FactoryError) as exc:
        promotion.approve(env.store, env.sink, row_of(env, "0.2"), SECOND, "second_line")
    assert code(exc) == "kind_not_required"
    assert (
        promotion.approve(env.store, env.sink, row_of(env, "0.2"), LEAD, "owner_lead")["state"]
        == "approved"
    )


def test_a_critical_change_needs_the_full_approval_again(env: gate.GateEnv) -> None:
    to_live(env)
    row = env.store.new_version("mr-agent", "0.1", "reviewer.an")
    d = copy.deepcopy(row["definition"])
    for t in d["tools"]:
        if t["tool_id"] == "read_regkb":
            t["scope"] = "regkb:SBV-TT53-2025"  # a different scope is a change of the tools
    env.store.save_draft("mr-agent", "0.2", d, "reviewer.an", row["row_version"])
    to_tested(env, "mr-agent", "0.2")
    need = promotion.required_approvals(env.store, row_of(env, "0.2"))
    assert need["change"] == "critical" and need["kinds"] == ["owner_lead", "second_line"]


def test_classify_change_flags_each_critical_field() -> None:
    base: dict[str, Any] = {
        "dimension_id": "ethics",
        "tools": [{"tool_id": "read_facts", "mode": "read"}],
        "guardians": ["a"],
        "output_schema": {"type": "assessment_report_v1"},
        "harness": {"hitl": {"permissions": []}},
        "checklist": [{"id": "A", "severity": "low"}],
        "instructions": "A",
        "lifecycle": {"version": "0.1", "state": "live", "approvals": []},
    }
    assert promotion.classify_change(None, base) == "new"
    assert promotion.classify_change(base, copy.deepcopy(base)) == "none"
    for mutate in (
        lambda d: d["tools"].append({"tool_id": "read_regkb", "mode": "read"}),
        lambda d: d["guardians"].append("b"),
        lambda d: d["output_schema"].update(type="other"),
        lambda d: d["harness"]["hitl"].update(
            permissions=[{"tool_id": "read_facts", "mode": "read"}]
        ),
        lambda d: d["checklist"][0].update(severity="high"),  # the tier changes
        lambda d: d.update(dimension_id="model"),  # the tier changes
    ):
        new = copy.deepcopy(base)
        mutate(new)
        assert promotion.classify_change(base, new) == "critical"
    new = copy.deepcopy(base)
    new["instructions"] = "B"
    new["checklist"].append({"id": "B", "severity": "low"})
    assert promotion.classify_change(base, new) == "content"


# ------------------------------------------------------------------------------ reject and reopen


def test_reject_needs_a_reason_of_twenty_characters_and_clears_the_approvals(
    env: gate.GateEnv,
) -> None:
    submit_ready(env)
    promotion.approve(env.store, env.sink, row_of(env), LEAD, "owner_lead")
    with pytest.raises(FactoryError) as exc:
        promotion.reject(env.store, env.sink, row_of(env), SECOND, "too short")
    assert code(exc) == "reason_too_short"
    out = promotion.reject(
        env.store, env.sink, row_of(env), SECOND, "The checklist misses the drift item."
    )
    assert out["state"] == "draft" and out["definition"]["lifecycle"]["approvals"] == []
    ev = env.store.events("mr-agent", "0.1")[-1]
    assert ev["kind"] == "rejected" and "drift" in ev["detail"]


def test_reject_is_for_approvers(env: gate.GateEnv) -> None:
    submit_ready(env)
    with pytest.raises(FactoryError) as exc:
        promotion.reject(
            env.store, env.sink, row_of(env), AUTHOR, "A reason that is long enough here."
        )
    assert code(exc) == "not_eligible"


def test_reject_works_on_an_approved_version_too(env: gate.GateEnv) -> None:
    submit_ready(env)
    promotion.approve(env.store, env.sink, row_of(env), LEAD, "owner_lead")
    promotion.approve(env.store, env.sink, row_of(env), SECOND, "second_line")
    assert row_of(env)["state"] == "approved"
    out = promotion.reject(
        env.store, env.sink, row_of(env), ADMIN, "Found a gap after the approval round."
    )
    assert out["state"] == "draft"


def test_reopen_by_the_author(env: gate.GateEnv) -> None:
    to_tested(env)
    with pytest.raises(FactoryError) as exc:
        promotion.reopen(env.store, env.sink, row_of(env), AUTHOR, "no")
    assert code(exc) == "reason_needed"
    stranger = promotion.Actor("v.hoa", frozenset({"viewer"}))
    with pytest.raises(FactoryError) as exc2:
        promotion.reopen(env.store, env.sink, row_of(env), stranger, "I want to change it.")
    assert code(exc2) == "not_eligible"
    out = promotion.reopen(
        env.store, env.sink, row_of(env), AUTHOR, "I want to change the checklist."
    )
    assert out["state"] == "draft"
    # a draft can be edited again and tested again
    assert promotion.passed_full_run(env.store, out) is not None  # same sha still tested


# ------------------------------------------------------------------------------ live and rollback


def test_activate_needs_an_approved_version_and_an_owner_lead(env: gate.GateEnv) -> None:
    submit_ready(env)
    with pytest.raises(FactoryError) as exc:
        promotion.activate(env.store, env.sink, row_of(env), LEAD)
    assert code(exc) == "not_approved"
    promotion.approve(env.store, env.sink, row_of(env), LEAD, "owner_lead")
    promotion.approve(env.store, env.sink, row_of(env), SECOND, "second_line")
    with pytest.raises(FactoryError) as exc2:
        promotion.activate(env.store, env.sink, row_of(env), AUTHOR)
    assert code(exc2) == "not_eligible"
    live = promotion.activate(env.store, env.sink, row_of(env), LEAD)
    assert live["state"] == "live"
    assert env.store.live_agent_for("model")["id"] == "mr-agent"
    assert env.store.portfolio()[0]["kind"] == "live_agent"


def test_one_live_version_per_agent_id_and_the_old_one_stays_readable(env: gate.GateEnv) -> None:
    to_live(env)
    row = env.store.new_version("mr-agent", "0.1", "reviewer.an")
    d = copy.deepcopy(row["definition"])
    d["instructions"] += " MR-01 MR-02 again."
    env.store.save_draft("mr-agent", "0.2", d, "reviewer.an", row["row_version"])
    to_live(env, "mr-agent", "0.2")
    states = {r["version"]: r["state"] for r in env.store.versions("mr-agent")}
    assert states == {"0.1": "retired", "0.2": "live"}
    assert env.store.get("mr-agent", "0.1")["definition"]["id"] == "mr-agent"  # readable
    assert env.store.live_agent_for("model")["version"] == "0.2"
    assert env.store.live_version("mr-agent")["version"] == "0.2"


def test_rollback_sets_the_previous_version_live_again(env: gate.GateEnv, sink: Any) -> None:
    to_live(env)
    row = env.store.new_version("mr-agent", "0.1", "reviewer.an")
    d = copy.deepcopy(row["definition"])
    d["instructions"] += " MR-01 MR-02 once more."
    env.store.save_draft("mr-agent", "0.2", d, "reviewer.an", row["row_version"])
    to_live(env, "mr-agent", "0.2")
    for who in (LEAD, AUTHOR):
        with pytest.raises(FactoryError) as exc:
            promotion.rollback(env.store, sink, "mr-agent", who, "The new version misses cases.")
        assert code(exc) == "not_admin"
    with pytest.raises(FactoryError) as exc2:
        promotion.rollback(env.store, sink, "mr-agent", ADMIN, "short")
    assert code(exc2) == "reason_needed"
    out = promotion.rollback(env.store, sink, "mr-agent", ADMIN, "Version 0.2 misses drift cases.")
    assert out["version"] == "0.1" and out["state"] == "live"
    assert row_of(env, "0.2")["state"] == "retired"
    assert env.store.live_version("mr-agent")["version"] == "0.1"
    assert any(r["action"] == "rollback" for r in sink.of("factory_promotion"))
    kinds = [e["kind"] for e in env.store.events("mr-agent", "0.1")]
    assert kinds[-1] == "rolled_back"


def test_rollback_needs_an_earlier_live_version(env: gate.GateEnv, sink: Any) -> None:
    to_live(env)
    with pytest.raises(FactoryError) as exc:
        promotion.rollback(env.store, sink, "mr-agent", ADMIN, "Nothing before this one exists.")
    assert code(exc) == "no_previous_version"
    draft = env.store.new_version("mr-agent", "0.1", "reviewer.an")
    with pytest.raises(FactoryError) as exc2:
        promotion.rollback(
            env.store,
            sink,
            "mr-agent",
            ADMIN,
            "Try a draft version as the target.",
            draft["version"],
        )
    assert code(exc2) == "not_rollbackable"
    with pytest.raises(FactoryError) as exc3:
        promotion.rollback(env.store, sink, "nope-agent", ADMIN, "An agent that does not exist.")
    assert code(exc3) == "not_found"


def test_retire_a_live_version(env: gate.GateEnv) -> None:
    to_live(env)
    out = env.store.retire("mr-agent", "0.1", "admin.chi", "No longer needed by the team.")
    assert out["state"] == "retired" and env.store.live_agent_for("model") is None


# ------------------------------------------------------------------------------ change detection


def test_a_changed_definition_goes_back_to_draft(env: gate.GateEnv, sink: Any) -> None:
    submit_ready(env)
    tested = row_of(env)
    changed = {**tested["definition"], "tools": tested["definition"]["tools"][:1]}
    env.state.update(
        "factory_agent",
        {"id": "mr-agent", "version": "0.1"},
        {"definition_json": changed},
        tested["row_version"],
    )
    assert definition_sha256(changed) != definition_sha256(tested["definition"])
    with pytest.raises(FactoryError) as exc:
        promotion.approve(env.store, sink, row_of(env), LEAD, "owner_lead")
    assert code(exc) == "definition_changed"
    assert row_of(env)["state"] == "draft"
    assert any(r["action"] == "definition_changed" for r in sink.of("factory_promotion"))


def test_activate_checks_the_sha_again(env: gate.GateEnv) -> None:
    submit_ready(env)
    promotion.approve(env.store, env.sink, row_of(env), LEAD, "owner_lead")
    promotion.approve(env.store, env.sink, row_of(env), SECOND, "second_line")
    r = row_of(env)
    env.state.update(
        "factory_agent",
        {"id": "mr-agent", "version": "0.1"},
        {
            "definition_json": {
                **r["definition"],
                "guardians": r["definition"]["guardians"][:3] + ["x_guard"],
            }
        },
        r["row_version"],
    )
    with pytest.raises(FactoryError) as exc:
        promotion.activate(env.store, env.sink, row_of(env), LEAD)
    assert code(exc) == "definition_changed" and row_of(env)["state"] == "draft"


def test_the_sha_ignores_lifecycle_state_and_approvals() -> None:
    a = {"id": "x", "lifecycle": {"version": "0.1", "state": "draft", "approvals": []}}
    b = {"id": "x", "lifecycle": {"version": "0.1", "state": "live", "approvals": [{"by": "p"}]}}
    c = {"id": "x", "lifecycle": {"version": "0.2", "state": "draft", "approvals": []}}
    assert definition_sha256(a) == definition_sha256(b) != definition_sha256(c)


# ------------------------------------------------------------------------------ chain and events


def test_every_move_writes_an_event_and_a_chain_record_without_floats(
    env: gate.GateEnv, sink: Any
) -> None:
    to_live(env)
    actions = [r["action"] for r in sink.of("factory_promotion")]
    for a in ("tested", "submitted", "approval", "approved", "live"):
        assert a in actions, actions
    kinds = {e["kind"] for e in env.store.events("mr-agent", "0.1")}
    assert {"tested", "submitted", "approval", "approved", "live"} <= kinds
    for rec in sink.of("factory_promotion"):
        assert "factory_agent_id" in rec and "agent_id" not in rec  # root lane, no per-agent lane
        assert len(rec["definition_sha256"]) == 64 and rec["actor_ref"].startswith("p-")
        assert "reviewer.an" not in json.dumps(rec) and "lead.model" not in json.dumps(rec)
        assert all(not isinstance(v, float) for v in rec.values())


def test_summary_for_the_panel(env: gate.GateEnv) -> None:
    submit_ready(env)
    s = promotion.summary(env.store, row_of(env))
    assert s["state"] == "tested" and s["submitted"] and s["tier"] == "high"
    assert s["required"] == ["owner_lead", "second_line"] and s["missing"] == s["required"]


# ------------------------------------------------------------------------------ groups


def test_permits_prefers_user_groups_over_the_role_mapping(env: gate.GateEnv) -> None:
    g = env.store.groups
    assert permits(["reviewer"], "cyber", g)  # role mapping: a reviewer edits cyber
    assert not permits(["reviewer"], "cyber", g, ["model_risk"])  # user groups win
    assert permits(["reviewer"], "model_risk", g, ["model_risk"])
    assert not permits(["approver"], "cyber", g, [])  # empty = no groups: role mapping
    assert permits(["reviewer"], "cyber", g, None)
    assert permits(["admin"], "platform", g, ["cyber"])  # admin edits all groups
    assert not permits(["reviewer"], "nope", g, ["nope"])
