"""WP30 task list: sizing, stage release, the lifecycle gate, two-person waiver, chain records
(rubric: compliance officer, internal auditor under the Three Lines model)."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from supervisor.controls.harness_env import CtlEnv
from supervisor.tasks import model as tm
from supervisor.tasks.model import TaskError, load_config

from .conftest import ListSink

CFG = load_config()


def person(user: str, *roles: str) -> SimpleNamespace:
    return SimpleNamespace(user_id=user, kind="user", roles=frozenset(roles))


OWNER = person("olga", "owner")
REVIEWER = person("rene", "reviewer")
APPROVER = person("amir", "approver")
ADMIN = person("ada", "admin")


def _ids(env: CtlEnv, agent: str, stage: str | None = None) -> dict[str, dict[str, object]]:
    return {
        r["template_id"]: r
        for r in env.tasks.rows_of(agent)
        if stage is None or r["stage"] == stage
    }


def _finish_stage(env: CtlEnv, agent: str, who: SimpleNamespace = ADMIN) -> None:
    """Close every task of the current stage (documents get a reference) and take the move."""
    stage = env.tasks.current_stage(agent)
    for r in env.tasks.rows_of(agent):
        if r["stage"] != stage or r["status"] not in tm.OPEN_STATUSES or r["kind"] == "move":
            continue
        env.tasks.done(r["task_id"], who, "doc-ref" if r["evidence_kind"] == "document" else None)
    (move,) = [
        r
        for r in env.tasks.rows_of(agent)
        if r["stage"] == stage and r["kind"] == "move" and r["status"] in tm.OPEN_STATUSES
    ]
    env.tasks.done(move["task_id"], who)


# ---- sizing ----------------------------------------------------------------------------------


def test_effective_level_is_the_higher_of_band_and_class_floor() -> None:
    assert tm.effective_level(CFG, "high_risk", "low") == "high"
    assert tm.effective_level(CFG, "high_risk", "critical") == "critical"
    assert tm.effective_level(CFG, "not_high_risk", "low") == "low"
    assert tm.effective_level(CFG, "unclassified", "low") == "medium"


@pytest.mark.parametrize("cls", tm.CLASSES)
def test_a_higher_band_never_gets_fewer_tasks(cls: str) -> None:
    sizes = []
    for band in tm.LEVELS:
        p = tm.plan(CFG, cls, band)
        sizes.append(
            (sum(len(v) for v in p.values()), sum(x.required for v in p.values() for x in v))
        )
    assert sizes == sorted(sizes)


@pytest.mark.parametrize("band", tm.LEVELS)
def test_high_risk_class_never_gets_less_than_the_others(band: str) -> None:
    def n(cls: str) -> int:
        return sum(len(v) for v in tm.plan(CFG, cls, band).values())

    assert n("high_risk") >= n("unclassified") >= n("not_high_risk")


def test_low_agent_skips_validation_and_reevaluation() -> None:
    assert tm.stages_in_use(CFG, "not_high_risk", "low") == [
        "initiation",
        "design",
        "deployment",
        "operation",
        "retirement",
    ]
    assert tm.stages_in_use(CFG, "high_risk", "high") == list(tm.STAGES)


def test_class_specific_templates() -> None:
    ids = {x.template.id for v in tm.plan(CFG, "unclassified", "low").values() for x in v}
    assert "INI-D33" in ids and "DES-D33" not in ids
    ids = {x.template.id for v in tm.plan(CFG, "high_risk", "low").values() for x in v}
    assert {"DES-D33", "DEP-D33"} <= ids and "INI-D33" not in ids


def test_config_refuses_bad_templates() -> None:
    good = {"templates": [{"id": "A", "stage": "design", "title": "t"}]}
    tm.parse_config(good)
    for bad in (
        {"templates": [{"id": "A", "stage": "nope", "title": "t"}]},
        {"templates": [{"id": "A", "stage": "design", "title": ""}]},
        {"templates": [{"id": "A", "stage": "design", "title": "t"}] * 2},
        {"templates": [{"id": "MOVE-X", "stage": "design", "title": "t"}]},
        {"templates": [{"id": "A", "stage": "design", "title": "t", "min_level": "huge"}]},
        {"templates": [{"id": "A", "stage": "design", "title": "t", "classes": ["x"]}]},
        {"templates": [{"id": "A", "stage": "design", "title": "t", "due_days": 0}]},
        {"templates": [{"id": "A", "stage": "design", "title": "t", "evidence": {"kind": "pack"}}]},
        {"class_floor": {"x": "low"}, "templates": []},
        [],
    ):
        with pytest.raises(TaskError):
            tm.parse_config(bad)


# ---- generate and stage release --------------------------------------------------------------


def test_generate_makes_only_the_current_stage(env: CtlEnv, sink: ListSink) -> None:
    env.agent("pay")
    env.classify("pay", "high_risk", "critical")
    out = env.tasks.generate("pay", ADMIN)
    assert out["stage"] == "initiation" and out["level"] == "critical"
    rows = env.tasks.rows_of("pay")
    assert {r["stage"] for r in rows} == {"initiation"}
    assert {r["template_id"] for r in rows if r["kind"] == "move"} == {"MOVE-DESIGN"}
    assert out["created_n"] == len(rows) == len(sink.of("task_change"))
    again = env.tasks.generate("pay", ADMIN)
    assert again["created_n"] == 0


def test_unknown_class_and_tier_are_sized_conservatively(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", None, "nonsense")
    inputs = env.tasks.agent_inputs("pay")
    # no risk in the register, no usable tier: unknown risk is sized as high
    assert (inputs["d33_class"], inputs["band"], inputs["band_source"]) == (
        "unclassified",
        "high",
        "default",
    )
    env.classify("pay", "bogus_class", "critical")
    inputs = env.tasks.agent_inputs("pay")
    assert (inputs["d33_class"], inputs["band"], inputs["band_source"]) == (
        "unclassified",
        "critical",
        "risk_tier",
    )


def test_band_comes_from_the_register_when_there_are_risks(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.risk("big", "pay", [("matrix", "OB-1")], inherent_likelihood=5, inherent_impact=5)
    inputs = env.tasks.agent_inputs("pay")
    assert (inputs["band"], inputs["band_source"]) == ("critical", "risk_register")


# ---- the lifecycle move is a gate ------------------------------------------------------------


def test_move_is_refused_while_a_required_task_is_open(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    move = _ids(env, "pay")["MOVE-DESIGN"]
    with pytest.raises(TaskError, match="refused: required task.*INI-PURPOSE.*INI-REGISTER"):
        env.tasks.done(move["task_id"], OWNER)


def test_move_releases_the_next_stage_and_sizes_it_again(env: CtlEnv, sink: ListSink) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    _finish_stage(env, "pay", OWNER)
    assert env.tasks.current_stage("pay") == "design"
    assert {r["stage"] for r in env.tasks.rows_of("pay")} == {"initiation", "design"}
    # the class changes in the middle of the lifecycle: the next stage is sized for it
    env.classify("pay", "high_risk", "low")
    out = env.tasks.generate("pay", ADMIN)
    assert out["level"] == "high" and "DES-D33" in _ids(env, "pay", "design")
    assert out["created_n"] >= 3  # the design tasks of the larger size were added


def test_a_task_becomes_required_when_the_size_grows(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", None, "low")  # unclassified: level medium
    env.tasks.generate("pay", ADMIN)
    # INI-D33 (classify) is a reviewer task: the owner alone may not close it (review WP30)
    _finish_stage(env, "pay", REVIEWER)
    assert env.tasks.current_stage("pay") == "design"
    assert _ids(env, "pay", "design")["DES-CONTROLS"]["required"] is False
    env.classify("pay", "high_risk", "low")  # level high
    out = env.tasks.generate("pay", ADMIN)
    assert out["made_required"] >= 1
    assert _ids(env, "pay", "design")["DES-CONTROLS"]["required"] is True


def test_optional_tasks_do_not_block_the_move(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    _finish_stage(env, "pay", OWNER)
    optional = [r for r in env.tasks.rows_of("pay") if r["stage"] == "design" and not r["required"]]
    assert optional == [] or all(r["status"] == "open" for r in optional)


def test_a_high_level_move_needs_an_approver(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "high_risk", "high")
    env.tasks.generate("pay", ADMIN)
    for r in env.tasks.rows_of("pay"):
        if r["kind"] != "move":
            env.tasks.done(r["task_id"], OWNER, "doc")
    move = _ids(env, "pay")["MOVE-DESIGN"]
    assert move["owner_role"] == "approver"
    with pytest.raises(TaskError, match="needs an approver or an admin"):
        env.tasks.done(move["task_id"], OWNER)
    env.tasks.done(move["task_id"], APPROVER)
    assert env.tasks.current_stage("pay") == "design"


def test_done_by_document_needs_a_reference(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    t = _ids(env, "pay")["INI-PURPOSE"]
    with pytest.raises(TaskError, match="document reference"):
        env.tasks.done(t["task_id"], OWNER)
    with pytest.raises(TaskError, match="document reference"):
        env.tasks.done(t["task_id"], OWNER, "bad ref!")
    done = env.tasks.done(t["task_id"], OWNER, "DOC-17")
    assert done["status"] == "done" and done["evidence_ref"] == "DOC-17"
    with pytest.raises(TaskError, match="is done"):
        env.tasks.done(t["task_id"], OWNER, "DOC-17")


def test_control_task_needs_working_evidence(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", None, "low")
    env.control("CTL-PII-MASK", evidence=[("rule", "PAY-02")], agents=["pay"])
    for pack in ("owasp_agentic_redteam", "pii_canary", "indirect_injection_vi"):
        env.pack("pay", pack, "ok", env.window_time())
    env.tasks.generate("pay", ADMIN)
    for r in env.tasks.rows_of("pay"):
        if r["kind"] != "move":
            env.tasks.done(r["task_id"], ADMIN, "d" if r["evidence_kind"] == "document" else None)
    while env.tasks.current_stage("pay") != "operation":
        _finish_stage(env, "pay")
    assert env.tasks.current_stage("pay") == "operation"
    t = _ids(env, "pay", "operation")["OPS-MASK"]
    with pytest.raises(TaskError, match="CTL-PII-MASK is no_data"):
        env.tasks.done(t["task_id"], OWNER)
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.controls.run_status()
    assert env.tasks.done(t["task_id"], OWNER)["status"] == "done"


def test_sync_closes_template_tasks_whose_evidence_is_there(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", None, "low")
    env.control("CTL-PII-MASK", evidence=[("rule", "PAY-02")], agents=["pay"])
    for pack in ("owasp_agentic_redteam", "pii_canary", "indirect_injection_vi"):
        env.pack("pay", pack, "ok", env.window_time())
    env.tasks.generate("pay", ADMIN)
    while env.tasks.current_stage("pay") != "operation":
        _finish_stage(env, "pay")
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.controls.run_status()
    out = env.tasks.sync("pay")
    assert out["closed"] == 1
    t = _ids(env, "pay", "operation")["OPS-MASK"]
    assert t["status"] == "done" and t["done_by"] == "supervisor-system"


# ---- waiver: reason and a second person -------------------------------------------------------


def _task(env: CtlEnv) -> str:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    return str(_ids(env, "pay")["INI-REGISTER"]["task_id"])


def test_waiver_needs_a_reason_and_a_second_person(env: CtlEnv, sink: ListSink) -> None:
    tid = _task(env)
    with pytest.raises(TaskError, match="reason is required"):
        env.tasks.request_waive(tid, REVIEWER, "  ")
    asked = env.tasks.request_waive(tid, REVIEWER, "not needed for a pilot")
    assert asked["status"] == "open" and asked["waive_pending"] is True
    with pytest.raises(TaskError, match="already waiting"):
        env.tasks.request_waive(tid, REVIEWER, "again")
    with pytest.raises(TaskError, match="needs role approver or admin"):
        env.tasks.approve_waive(tid, OWNER)
    with pytest.raises(TaskError, match="different person"):
        env.tasks.approve_waive(tid, person("rene", "admin"))  # same person, even as admin
    done = env.tasks.approve_waive(tid, APPROVER)
    assert done["status"] == "waived" and done["waive_approved_by"] == "amir"
    assert env.tasks.integrity_problems() == []
    # the reason is in the row; only its hash is on the chain
    for p in sink.of("task_change"):
        assert "not needed" not in str(p)
    assert any(p.get("reason_sha256") for p in sink.of("task_change"))


def test_second_person_must_be_a_signed_in_person(env: CtlEnv) -> None:
    tid = _task(env)
    env.tasks.request_waive(tid, REVIEWER, "pilot")
    bot = SimpleNamespace(user_id="svc", kind="service", roles=frozenset({"admin"}))
    with pytest.raises(TaskError, match="signed-in person"):
        env.tasks.approve_waive(tid, bot)


def test_waiver_can_be_rejected_and_asked_again(env: CtlEnv) -> None:
    tid = _task(env)
    env.tasks.request_waive(tid, REVIEWER, "pilot")
    out = env.tasks.reject_waive(tid, APPROVER, "needed")
    assert out["waive_pending"] is False and out["status"] == "open"
    env.tasks.request_waive(tid, REVIEWER, "pilot, second try")


def test_waived_required_task_no_longer_blocks_the_move(env: CtlEnv) -> None:
    tid = _task(env)
    env.tasks.request_waive(tid, REVIEWER, "pilot")
    env.tasks.approve_waive(tid, APPROVER)
    assert tid not in [r["task_id"] for r in env.tasks.open_required("pay")]


def test_a_move_cannot_be_waived(env: CtlEnv) -> None:
    _task(env)
    move = _ids(env, "pay")["MOVE-DESIGN"]
    with pytest.raises(TaskError, match="cannot be waived"):
        env.tasks.request_waive(move["task_id"], REVIEWER, "skip")


def test_integrity_check_finds_a_forged_waiver(env: CtlEnv) -> None:
    tid = _task(env)
    row = env.adapters.state.get("task", {"task_id": tid})
    env.adapters.state.update(
        "task",
        {"task_id": tid},
        {"status": "waived", "waive_requested_by": "x"},
        row["row_version"],
    )
    assert env.tasks.integrity_problems() == [f"{tid}: waived without two people"]


# ---- class change mid-lifecycle -----------------------------------------------------------------


def test_class_change_is_additive_and_never_relaxes(env: CtlEnv, sink: ListSink) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    before = {r["template_id"] for r in env.tasks.rows_of("pay")}
    env.classify("pay", "high_risk", "low")
    out = env.tasks.generate("pay", ADMIN)
    after = _ids(env, "pay")
    assert before <= set(after)  # nothing removed
    assert out["level"] == "high"
    assert all(r["level"] == "high" for r in after.values())
    assert sink.of("task_resize")
    env.classify("pay", "not_high_risk", "low")  # back down: nothing is relaxed by itself
    env.tasks.generate("pay", ADMIN)
    assert set(_ids(env, "pay")) == set(after)
    assert all(
        r["required"] for t, r in _ids(env, "pay").items() if t in {"INI-PURPOSE", "INI-REGISTER"}
    )


def test_move_target_follows_the_new_size(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    while env.tasks.current_stage("pay") != "design":
        _finish_stage(env, "pay")
    assert _ids(env, "pay", "design")["MOVE-DEPLOYMENT"]["target_stage"] == "deployment"
    env.classify("pay", "high_risk", "high")
    env.tasks.generate("pay", ADMIN)
    move = next(
        r for r in env.tasks.rows_of("pay") if r["stage"] == "design" and r["kind"] == "move"
    )
    assert move["target_stage"] == "validation" and move["template_id"] == "MOVE-VALIDATION"


# ---- overdue ------------------------------------------------------------


class FakeCases:
    def __init__(self) -> None:
        self.opened: list[dict[str, object]] = []

    def linked_case(self, kind: str, ref: str) -> str | None:
        return next((c["case_id"] for c in self.opened if c["source_ref"] == ref), None)  # type: ignore[return-value]

    def open_case(self, **kw: object) -> dict[str, object]:
        self.opened.append({**kw, "case_id": f"CASE-{len(self.opened)}"})
        return self.opened[-1]


def test_overdue_required_tasks_open_one_case_each(env: CtlEnv) -> None:
    tid = _task(env)
    cases = FakeCases()
    assert env.tasks.run_due(cases)["cases_opened"] == 0
    later = env.adapters.clock.now() + dt.timedelta(days=60)
    env.tasks.clock = SimpleNamespace(now=lambda: later)
    out = env.tasks.run_due(cases)
    assert out["overdue"] >= 2 and out["cases_opened"] == out["overdue"]
    assert all(c["source_kind"] == "task" for c in cases.opened)
    assert tid in [c["source_ref"] for c in cases.opened]
    assert env.tasks.run_due(cases)["cases_opened"] == 0  # one case per task, once
    assert "overdue" in {e["action"] for e in env.tasks.events("pay")}


def test_custom_task_never_closes_by_itself(env: CtlEnv) -> None:
    _task(env)
    out = env.tasks.add_custom("pay", "Ask legal about the pilot", REVIEWER, required=True)
    assert out["kind"] == "custom" and out["required"] is True
    assert out["task_id"] in [r["task_id"] for r in env.tasks.open_required("pay")]
    assert env.tasks.sync("pay")["closed"] == 0
