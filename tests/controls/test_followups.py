"""WP30 follow-ups after review: a risk looks through a control exactly as control status does
(agent scope, per-source window), a pack task needs a fresh non-judged ok result, a change that is
changed back keeps its evidence, the tasks CSV export, segregation of duties across a stage."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from supervisor.controls.harness_env import CtlEnv
from supervisor.tasks.model import TaskError


def person(user: str, *roles: str) -> SimpleNamespace:
    return SimpleNamespace(user_id=user, kind="user", roles=frozenset(roles))


OWNER = person("olga", "owner")
REVIEWER = person("rene", "reviewer")
APPROVER = person("amir", "approver")
ADMIN = person("ada", "admin")


# ---- L3: one definition of scope and window --------------------------------------------------


def test_risk_through_a_control_respects_the_control_agent_scope(env: CtlEnv) -> None:
    env.agent("pay")
    env.agent("svc")
    rid = env.risk("on pay", "pay", [("matrix", "OB-1")])
    # the control applies to svc only; a pack that passed for pay must not make it work for pay
    env.control("CTL-S", covers=[("matrix", "OB-1"), ("risk", rid)], evidence=[("pack", "pack_a")],
                agents=["svc"])  # fmt: skip
    env.pack("pay", "pack_a", "ok", env.window_time())
    env.svc.run_evidence()
    assert env.svc.get(rid)["evidence_state"] == "no_evidence"


def test_risk_through_a_control_uses_the_pack_window_of_the_control(env: CtlEnv) -> None:
    env.agent("pay")
    rid = env.risk("pack age", "pay", [("matrix", "OB-1")])
    env.control("CTL-P", covers=[("matrix", "OB-1"), ("risk", rid)], evidence=[("pack", "pack_a")])
    env.pack("pay", "pack_a", "ok", env.window_time() - dt.timedelta(days=20))
    env.controls.run_status()
    assert env.controls.agent_compliance("pay")["controls"][0]["status"] == "working"
    env.svc.run_evidence()
    assert env.svc.get(rid)["evidence_state"] == "working"  # the same 30-day window
    # a pack linked directly to the risk keeps the 7-day risk window
    rid2 = env.risk("direct", "pay", [("pack", "pack_a")])
    env.svc.run_evidence()
    assert env.svc.get(rid2)["evidence_state"] == "no_evidence"


def test_the_window_helper_is_shared() -> None:
    from supervisor.risk import evidence as ev

    now = dt.datetime(2026, 10, 20, 12, tzinfo=dt.UTC)
    w = ev.window_for(now, 7)
    assert ev.source_window("rule", w, 30) is w and ev.source_window("pack", w, None) is w
    wp = ev.source_window("pack", w, 30)
    assert wp.end == w.end and wp.seconds == 30 * 86400


# ---- L2 on the risk side ---------------------------------------------------------------------


def test_a_risk_edit_changed_back_keeps_its_evidence(env: CtlEnv) -> None:
    env.agent("pay")
    rid = env.risk("flip", "pay", [("rule", "PAY-02")])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.svc.run_evidence()
    assert env.svc.get(rid)["evidence_state"] == "working"
    env.svc.update(rid, {"residual_likelihood": 3}, "u")
    assert env.svc.get(rid)["evidence_reason"] == "changed_since_evidence"
    env.svc.run_evidence()  # a second row, for the other basis, in the same window
    env.svc.update(rid, {"residual_likelihood": 2}, "u")  # back to the first basis
    got = env.svc.get(rid)
    assert got["evidence_state"] == "working" and got["evidence_reason"] != "changed_since_evidence"
    assert got["residual_score"] == 10


def test_a_control_map_changed_back_keeps_the_risk_evidence(env: CtlEnv) -> None:
    env.agent("pay")
    rid = env.risk("r", "pay", [("matrix", "OB-1")])
    env.control("CTL-A", covers=[("matrix", "OB-1"), ("risk", rid)])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.svc.run_evidence()
    env.controls.add_map("CTL-A", "pack", "pack_b", "u")
    env.svc.run_evidence()
    env.controls.remove_map("CTL-A", "pack", "pack_b", "u")
    assert env.svc.get(rid)["evidence_state"] == "working"


# ---- L4: pack tasks ----------------------------------------------------------------------------


def _pack_row(ref: str) -> dict[str, str]:
    return {"evidence_kind": "pack", "evidence_ref": ref, "agent_id": "pay"}


def test_pack_task_needs_a_fresh_ok_result(env: CtlEnv) -> None:
    env.agent("pay")
    t = env.tasks
    env.pack("pay", "pack_a", "ok", env.adapters.clock.now() - dt.timedelta(days=45))
    assert "older than 30 days" in t._evidence_problem(_pack_row("pack_a"))
    env.pack("pay", "pack_b", "ok", env.adapters.clock.now() - dt.timedelta(days=10))
    assert t._evidence_problem(_pack_row("pack_b")) is None


def test_judge_scored_pack_does_not_close_a_task_unless_the_owner_allows(env: CtlEnv) -> None:
    env.agent("pay")
    env.pack("pay", "groundedness_monitor", "ok", env.adapters.clock.now())
    problem = env.tasks._evidence_problem(_pack_row("groundedness_monitor"))
    assert problem and "scored by a judge" in problem
    env.settings.risk_evidence_judged_packs = True
    assert env.tasks._evidence_problem(_pack_row("groundedness_monitor")) is None


# ---- L6: CSV ------------------------------------------------------------------------------------


def test_tasks_csv_is_formula_safe_and_capped(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    env.tasks.add_custom("pay", '=HYPERLINK("http://x","y")', REVIEWER)
    text, truncated = env.tasks.export_csv()
    lines = text.splitlines()
    assert lines[0].startswith("task_id,agent_id") and not truncated
    assert any("'=HYPERLINK" in ln for ln in lines) and "\n=" not in text
    text, truncated = env.tasks.export_csv(limit=3)
    assert len(text.splitlines()) == 4 and truncated
    assert text.isascii()


# ---- segregation of duties across the stage ------------------------------------------------------


def _task(env: CtlEnv, template: str):
    return next(r for r in env.tasks.rows_of("pay") if r["template_id"] == template)


def test_who_worked_on_the_stage_cannot_answer_its_waiver(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    env.tasks.done(_task(env, "INI-REGISTER")["task_id"], person("amir", "approver", "owner"))
    tid = _task(env, "INI-PURPOSE")["task_id"]
    env.tasks.request_waive(tid, REVIEWER, "pilot")
    with pytest.raises(TaskError, match="segregation of duties: amir worked on task.*INI-REGISTER"):
        env.tasks.approve_waive(tid, APPROVER)
    with pytest.raises(TaskError, match="segregation of duties"):
        env.tasks.reject_waive(tid, person("AMIR", "approver"), "no")  # case does not matter
    other = person("ben", "approver")
    assert env.tasks.approve_waive(tid, other)["status"] == "waived"


def test_who_worked_on_the_stage_cannot_approve_its_high_level_move(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "high_risk", "high")
    env.tasks.generate("pay", ADMIN)
    for r in env.tasks.rows_of("pay"):
        if r["kind"] != "move":
            env.tasks.done(
                r["task_id"], APPROVER if r["template_id"] == "INI-REGISTER" else OWNER, "doc"
            )
    move = next(r for r in env.tasks.rows_of("pay") if r["kind"] == "move")
    with pytest.raises(TaskError, match="segregation of duties: amir"):
        env.tasks.done(move["task_id"], APPROVER)
    assert env.tasks.done(move["task_id"], person("ben", "approver"))["status"] == "done"


def test_the_refusal_is_ascii(env: CtlEnv) -> None:
    env.agent("pay")
    env.classify("pay", "not_high_risk", "low")
    env.tasks.generate("pay", ADMIN)
    env.tasks.done(_task(env, "INI-REGISTER")["task_id"], person("amir", "approver"))
    tid = _task(env, "INI-PURPOSE")["task_id"]
    env.tasks.request_waive(tid, REVIEWER, "pilot")
    with pytest.raises(TaskError) as e:
        env.tasks.approve_waive(tid, APPROVER)
    assert str(e.value).isascii()
