"""WP30 review: five independent scenarios written by the reviewer as a compliance officer, with
every expected number computed by hand from config/tasks.yaml and docs/controls.md (not from the
author's generator), plus regression tests for the review findings (REVIEW_WP30.md).

Hand computation of the figures:

* S1: four controls in scope of ``pay``. C1 product, enforced rule hit = working. C2 product, rule
  hit AND a failing pack = failing (a failing source beats a working one). C3 product, document
  only = no_data / reference_only. C4 bank, rule hit = no_data / bank_owned (the product cannot
  observe a bank process). compliance = 1 * 10000 // 4 = 2500 bp; product = 1 * 10000 // 3 =
  3333 bp; bank_in_scope = 1.
* S2: pack ok 20 days ago (pack window 30) = working; rule hit 10 days ago (rule window 7) =
  no_data / no_working_source; pack ok 40 days ago = no_data. 1 of 3 = 3333 bp.
* S3: risk 4 x 5 = 20 (inherent), declared 2 x 5 = 10. Working control -> residual 10; a map
  change -> both read changed_since_evidence and the risk is back at 20; the control turned bank
  -> no runtime source for the risk either -> 20.
* S4: task sets from config/tasks.yaml (27 templates):
  high_risk + band low -> level high: 26 tasks (all but INI-D33), all required, 7 stages.
  not_high_risk + low -> level low: INI-REGISTER, INI-PURPOSE, DES-TOOLS, DEP-SHADOW, DEP-LAUNCH,
  OPS-OVERSIGHT, RET-ARCHIVE, RET-ACCESS = 8, all required; 5 stages (no validation, no
  re_evaluation). unclassified + low -> level medium: 20 tasks, 18 required (DES-CONTROLS and
  VAL-INJECT are required only from high); 6 stages (no re_evaluation).
* S5: segregation of duties and the launch hook on a high-risk agent.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.controls.harness_env import CtlEnv
from supervisor.onboard.launch import _with_tasks
from supervisor.onboard.models import LaunchReport
from supervisor.tasks import model as tm
from supervisor.tasks.model import TaskError


def person(user: str, *roles: str) -> SimpleNamespace:
    return SimpleNamespace(user_id=user, kind="user", roles=frozenset(roles))


OWNER = person("olga", "owner")
REVIEWER = person("rene", "reviewer")
APPROVER = person("amir", "approver")
ADMIN = person("ada", "admin")


def _days_ago(env: CtlEnv, days: int) -> dt.datetime:
    return env.window_time(hours_before_end=days * 24)


def _rows(env: CtlEnv, stage: str | None = None) -> dict[str, dict[str, Any]]:
    return {
        str(r["template_id"]): r
        for r in env.tasks.rows_of("pay")
        if stage is None or r["stage"] == stage
    }


def _close_stage(env: CtlEnv, who: Any = ADMIN, keep: tuple[str, ...] = ()) -> None:
    stage = env.tasks.current_stage("pay")
    for tid, r in _rows(env, stage).items():
        if r["kind"] == "move" or r["status"] not in tm.OPEN_STATUSES or tid in keep:
            continue
        env.tasks.done(r["task_id"], who, "doc-1" if r["evidence_kind"] == "document" else None)


def _move(env: CtlEnv, who: Any = ADMIN) -> None:
    stage = env.tasks.current_stage("pay")
    (mv,) = [r for r in _rows(env, stage).values() if r["kind"] == "move"]
    env.tasks.done(mv["task_id"], who)


def _packs_ok(env: CtlEnv) -> None:
    for pack in ("owasp_agentic_redteam", "pii_canary", "indirect_injection_vi"):
        env.pack("pay", pack, "ok", env.window_time())


def _report() -> LaunchReport:
    return LaunchReport.model_construct(go=True, reasons=["all integration checks pass"])


# ---- S1: the figure ---------------------------------------------------------------------------


def test_s1_compliance_figure_by_hand(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("C1", evidence=[("rule", "PAY-02")])
    env.control("C2", evidence=[("rule", "PAY-03"), ("pack", "pack_a")])
    env.control("C3", evidence=[("document", "procedure-7")])
    env.control("C4", evidence=[("rule", "PAY-02")], implemented_by="bank")
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.verdict("pay", "PAY-03", "block", env.window_time())
    env.pack("pay", "pack_a", "fail", env.window_time())
    env.controls.run_status()
    comp = env.controls.agent_compliance("pay")
    got = {c["control_id"]: (c["status"], c["reason"]) for c in comp["controls"]}
    assert got == {
        "C1": ("working", "sources_working"),
        "C2": ("failing", "source_failing"),
        "C3": ("no_data", "reference_only"),
        "C4": ("no_data", "bank_owned"),
    }
    assert (comp["in_scope"], comp["working"], comp["failing"], comp["no_data"]) == (4, 1, 1, 2)
    assert comp["compliance_bp"] == 2500
    assert (comp["product_in_scope"], comp["product_working"], comp["product_bp"]) == (3, 1, 3333)
    assert comp["bank_in_scope"] == 1


# ---- S2: windows per source kind ------------------------------------------------------------


def test_s2_pack_window_30_days_rule_window_7_days(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("P20", evidence=[("pack", "pack_b")])
    env.control("R10", evidence=[("rule", "PAY-02")])
    env.control("P40", evidence=[("pack", "pack_a")])
    env.pack("pay", "pack_b", "ok", _days_ago(env, 20))
    env.verdict("pay", "PAY-02", "block", _days_ago(env, 10))
    env.pack("pay", "pack_a", "ok", _days_ago(env, 40))
    env.controls.run_status()
    comp = env.controls.agent_compliance("pay")
    got = {c["control_id"]: (c["status"], c["reason"]) for c in comp["controls"]}
    assert got == {
        "P20": ("working", "sources_working"),
        "R10": ("no_data", "no_working_source"),
        "P40": ("no_data", "no_working_source"),
    }
    assert comp["compliance_bp"] == 3333


# ---- S3: chain of effects risk -> control -> source ---------------------------------------------


def test_s3_chain_of_effects_risk_control_source(env: CtlEnv) -> None:
    env.agent("pay")
    rid = env.risk("payment over the limit", "pay", [("matrix", "OB-1")])
    env.control(
        "CTL-R",
        covers=[("matrix", "OB-1"), ("risk", rid)],
        evidence=[("rule", "PAY-02"), ("document", "doc-1")],
    )
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.controls.run_status()
    env.svc.run_evidence()
    risk = env.svc.get(rid)
    assert (risk["inherent_score"], risk["residual_score"], risk["evidence_state"]) == (
        20,
        10,
        "working",
    )
    # remove the only runtime source: both views stop counting the old pass at once
    env.controls.remove_map("CTL-R", "rule", "PAY-02", "u")
    c = env.controls.agent_compliance("pay")["controls"][0]
    assert (c["status"], c["reason"]) == ("no_data", "changed_since_evidence")
    risk = env.svc.get(rid)
    assert (risk["evidence_reason"], risk["residual_score"]) == ("changed_since_evidence", 20)
    env.controls.run_status()
    env.svc.run_evidence()
    c = env.controls.agent_compliance("pay")["controls"][0]
    assert (c["status"], c["reason"]) == ("no_data", "reference_only")
    assert env.svc.get(rid)["residual_score"] == 20
    # another enforced rule: working again; then the control becomes bank-owned
    env.controls.add_map("CTL-R", "rule", "PAY-03", "u")
    env.verdict("pay", "PAY-03", "block", env.window_time())
    env.controls.run_status()
    env.svc.run_evidence()
    assert env.svc.get(rid)["residual_score"] == 10
    env.controls.update("CTL-R", {"implemented_by": "bank"}, "u")
    c = env.controls.agent_compliance("pay")["controls"][0]
    assert (c["status"], c["reason"]) == ("no_data", "changed_since_evidence")
    assert env.svc.get(rid)["evidence_reason"] == "changed_since_evidence"
    env.controls.run_status()
    env.svc.run_evidence()
    c = env.controls.agent_compliance("pay")["controls"][0]
    assert (c["status"], c["reason"]) == ("no_data", "bank_owned")
    risk = env.svc.get(rid)
    assert risk["evidence_state"] != "working" and risk["residual_score"] == 20


# ---- S4: task sets and a class change in the middle ------------------------------------------


def test_s4_task_sets_by_hand(env: CtlEnv) -> None:
    p = env.tasks.preview("high_risk", "low")
    assert (p["level"], p["total_n"], p["required_n"], len(p["stages"])) == ("high", 26, 26, 7)
    assert "INI-D33" not in [t["id"] for t in p["tasks"]["initiation"]]
    p = env.tasks.preview("not_high_risk", "low")
    ids = sorted(t["id"] for s in tm.STAGES for t in p["tasks"][s])
    assert ids == sorted(
        [
            "INI-REGISTER",
            "INI-PURPOSE",
            "DES-TOOLS",
            "DEP-SHADOW",
            "DEP-LAUNCH",
            "OPS-OVERSIGHT",
            "RET-ARCHIVE",
            "RET-ACCESS",
        ]
    )
    assert (p["level"], p["required_n"]) == ("low", 8)
    assert p["stages"] == ["initiation", "design", "deployment", "operation", "retirement"]
    p = env.tasks.preview("unclassified", "low")
    assert (p["level"], p["total_n"], p["required_n"], len(p["stages"])) == ("medium", 20, 18, 6)
    optional = {t["id"] for s in tm.STAGES for t in p["tasks"][s] if not t["required"]}
    assert optional == {"DES-CONTROLS", "VAL-INJECT"}


def test_s4_a_downgrade_in_the_middle_never_relaxes(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "high_risk", "high")
    env.tasks.generate("pay", ADMIN)
    _close_stage(env)
    _move(env, APPROVER)
    assert env.tasks.current_stage("pay") == "design"
    before = {k: (r["required"], r["level"]) for k, r in _rows(env, "design").items()}
    # the class and the band go down (a reclassification, or a register edit)
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    design = _rows(env, "design")
    move = design["MOVE-VALIDATION"]  # still the move into validation: no stage is skipped
    assert (move["level"], move["owner_role"], move["target_stage"]) == (
        "high",
        "approver",
        "validation",
    )
    assert {k: (r["required"], r["level"]) for k, r in design.items()} == before
    _close_stage(env)
    with pytest.raises(TaskError, match="needs an approver or an admin"):
        env.tasks.done(move["task_id"], OWNER)
    env.tasks.done(move["task_id"], APPROVER)
    assert env.tasks.current_stage("pay") == "validation"
    val = _rows(env, "validation")
    # the validation stage is released with the high set, not the low one
    assert {"VAL-FAIR", "VAL-SECOND", "VAL-INJECT"} <= set(val)
    assert all(r["required"] for r in val.values())
    assert env.tasks.agent_summary("pay")["level"] == "high"


# ---- S5: segregation of duties and the launch hook ---------------------------------------------


def test_s5_template_role_decides_who_may_mark_done(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "high_risk", "high")
    _packs_ok(env)
    env.tasks.generate("pay", ADMIN)
    for _ in range(2):
        _close_stage(env)
        _move(env, APPROVER)
    assert env.tasks.current_stage("pay") == "validation"
    second = _rows(env, "validation")["VAL-SECOND"]  # owner_role approver (second line)
    fair = _rows(env, "validation")["VAL-FAIR"]  # owner_role reviewer
    for who in (OWNER, REVIEWER):
        with pytest.raises(TaskError, match="approver"):
            env.tasks.done(second["task_id"], who, "doc-1")
    with pytest.raises(TaskError, match="reviewer"):
        env.tasks.done(fair["task_id"], OWNER, "doc-1")
    assert env.tasks.done(fair["task_id"], REVIEWER, "doc-1")["status"] == "done"
    assert env.tasks.done(second["task_id"], APPROVER, "doc-1")["done_by"] == "amir"


def test_s5_launch_hook_follows_the_lifecycle(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "high_risk", "high")
    _packs_ok(env)
    # no task list: NO-GO with a clear reason (owner question 2)
    out = _with_tasks(_report(), "pay", None, env.settings)
    assert out.go is False and "no task list" in out.task_reasons[0]
    env.tasks.generate("pay", ADMIN)
    for _ in range(2):
        _close_stage(env)
        out = _with_tasks(_report(), "pay", None, env.settings)
        # the stage is clean, but the agent has not reached deployment yet
        assert out.go is False and "deployment stage" in out.task_reasons[-1]
        _move(env, APPROVER)
    _close_stage(env)  # validation
    _move(env, APPROVER)
    assert env.tasks.current_stage("pay") == "deployment"
    out = _with_tasks(_report(), "pay", None, env.settings)
    assert out.go is False and any("DEP-OVERSIGHT" in r for r in out.task_reasons)
    _close_stage(env, keep=("DEP-LAUNCH",))
    out = _with_tasks(_report(), "pay", None, env.settings)
    # DEP-LAUNCH ("obtain a GO from the launch report") and the move out of the stage are
    # done after the launch: they do not block it
    assert out.go is True and out.task_reasons == [], out.task_reasons
    assert _rows(env, "deployment")["DEP-LAUNCH"]["status"] == "open"


def test_launch_gate_flag_without_the_catalogue_is_no_go(env: CtlEnv) -> None:
    env.settings.controls_enabled = False
    env.settings.tasks_launch_gate_enabled = True
    out = _with_tasks(_report(), "pay", None, env.settings)
    assert out.go is False and "CONTROLS_ENABLED" in out.task_reasons[0]


# ---- review findings ---------------------------------------------------------------------------


def test_same_person_with_another_letter_case_is_the_same_person(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    tid = _rows(env)["INI-REGISTER"]["task_id"]
    env.tasks.request_waive(tid, person("Binh@Bank.vn", "reviewer"), "pilot")
    with pytest.raises(TaskError, match="different person"):
        env.tasks.approve_waive(tid, person("binh@bank.vn", "approver"))


def test_judged_pack_switch_reaches_the_control_status(env: CtlEnv) -> None:
    env.agent("pay")
    env.refs.catalogue._src["pack"] = lambda: ["pack_a", "groundedness_monitor"]  # noqa: SLF001
    env.refs.clear()
    rid = env.risk("ungrounded answer", "pay", [("matrix", "OB-1")])
    env.control(
        "CTL-J",
        covers=[("matrix", "OB-1"), ("risk", rid)],
        evidence=[("pack", "groundedness_monitor")],
    )
    env.pack("pay", "groundedness_monitor", "ok", env.window_time())
    # the owner switch is on: the control and the risk that looks through it must agree
    env.settings.risk_evidence_judged_packs = True
    env.controls.run_status()
    env.svc.run_evidence()
    assert env.controls.agent_compliance("pay")["controls"][0]["status"] == "working"
    assert env.svc.get(rid)["evidence_state"] == "working"


def test_bootstrap_on_a_wp29_store_adds_the_wp30_tables_and_keeps_rows(env: CtlEnv) -> None:
    from supervisor.core.errors import AppendOnlyError
    from supervisor.jobs import bootstrap_schema

    env.agent("keep")
    rid = env.risk("kept", "keep", [("rule", "PAY-02")])
    env.agent("pay")
    x = env.adapters.executor
    for trg in (
        "trg_control_status_no_update",
        "trg_control_status_no_delete",
        "trg_task_event_no_update",
        "trg_task_event_no_delete",
    ):
        x.execute(f"DROP TRIGGER {trg}")
    for table in ("task_event", "task", "control_status", "control_map", "control"):
        x.execute(f"DROP TABLE {table}")  # a store from the WP29 head
    bootstrap_schema.run(env.settings, env.adapters)
    bootstrap_schema.run(env.settings, env.adapters)  # idempotent
    assert env.svc.get(rid)["title"] == "kept"
    env.control("CTL-AFTER", evidence=[("rule", "PAY-02")])
    env.controls.run_status()
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    for table in ("control_status", "task_event"):
        with pytest.raises(AppendOnlyError):
            x.execute(f"DELETE FROM {table}")
        with pytest.raises(AppendOnlyError):
            x.execute(f"UPDATE {table} SET agent_id = 'x'")


def test_a_map_changed_and_changed_back_finds_its_first_row(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-A", evidence=[("rule", "PAY-02")])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.controls.run_status()
    env.controls.add_map("CTL-A", "pack", "pack_b", "u")
    env.controls.run_status()  # a row for the second map (pack idle, rule works)
    env.controls.remove_map("CTL-A", "pack", "pack_b", "u")
    c = env.controls.agent_compliance("pay")["controls"][0]
    assert (c["status"], c["reason"]) == ("working", "sources_working")
    env.controls.update("CTL-A", {"implemented_by": "bank"}, "u")
    c = env.controls.agent_compliance("pay")["controls"][0]
    assert (c["status"], c["reason"]) == ("no_data", "changed_since_evidence")
