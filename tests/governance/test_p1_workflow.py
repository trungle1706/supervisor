"""WP-P1: tasks and stage approvals as console buttons (CONSOLE_WORKFLOW_ACTIONS).

Off path (flag off: every route is HTTP 400 naming the flag, the Tasks tab has no button), the
role rule, the same-person rule, the htmx fragments, the audit note and the next-action links.
Lives in tests/governance next to the other Systems console tests (the ``on`` fixture mounts the
Systems routers)."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.config import load_settings
from supervisor.console import systems_wizard
from supervisor.console.i18n import table
from supervisor.governance import next_action

from .conftest import Console, draft

CREATOR = "reviewer.an"  # reviewer: holds systems.edit, creates the tasks
SECOND = "reviewer.binh"  # reviewer and approver
APPROVER = "approver.em"  # approver only: no systems.edit
OWNER = "payops-lead@example.invalid"  # owner role: holds systems.edit
VIEWER = "viewer.hoa"
FLAG = "CONSOLE_WORKFLOW_ACTIONS"
REASON = "The vendor report covers this control already."


@pytest.fixture
def wf(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(on.ctx.settings, "console_workflow_actions", True)
    monkeypatch.setattr(on.ctx.settings, "controls_enabled", True)
    return on


def _system(c: Console, owner: str = CREATOR) -> str:
    s = c.ctx.systems.register(draft(owner_user=owner), CREATOR)
    return str(s["system_id"])


def _tasks(c: Console, sid: str) -> list[dict[str, Any]]:
    systems_wizard.open_tasks(c.ctx, sid, CREATOR)
    return c.ctx.tasks.list_tasks({"agent": sid})


def _task(c: Console, sid: str) -> dict[str, Any]:
    return _tasks(c, sid)[0]


def _url(sid: str, tail: str) -> str:
    return f"/console/systems/{sid}/{tail}"


def _audit(c: Console) -> list[dict[str, Any]]:
    rows = c.ctx.tables.query("console_action", order_by=("ts",))
    return [r for r in rows if r["outcome"] != "attempted"]


def _tab(c: Console, sid: str, user: str = CREATOR, lang: str = "en") -> Any:
    return c.get(f"/console/systems/{sid}?tab=tasks&lang={lang}", user=user)


# ------------------------------------------------------------------ the flag and the off path


def test_the_flag_is_off_by_default() -> None:
    assert load_settings(llm_base_url="").console_workflow_actions is False


def test_flag_off_every_route_is_400_and_names_the_flag(on: Console) -> None:
    sid = _system(on)
    task = _task(on, sid)
    ap_url = _url(sid, "stage/ap_x/decide")
    for tail in (
        f"tasks/{task['task_id']}/done",
        f"tasks/{task['task_id']}/waive",
        f"tasks/{task['task_id']}/waive/approve",
        "stage/request",
        "stage/move",
    ):
        r = on.post(_url(sid, tail), {"reason": REASON, "to_stage": "design"}, user=SECOND)
        assert r.status_code == 400, tail
        assert FLAG in r.text and "workflow_off" in r.text, tail
    r = on.post(ap_url, {"decision": "approve"}, user=APPROVER)
    assert r.status_code == 400 and FLAG in r.text
    assert on.ctx.tasks.get(task["task_id"])["status"] == "open"
    assert on.ctx.state.query("stage_approval") == []


def test_flag_off_the_tab_has_no_button(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(on.ctx.settings, "controls_enabled", True)
    sid = _system(on)
    _task(on, sid)
    html = _tab(on, sid).text
    assert "system-own-tasks" in html  # the page is there ...
    assert "data-act=" not in html and f"/console/systems/{sid}/tasks" not in html
    assert "Request move" not in html and ">Actions<" not in html


def test_next_action_off_path_keeps_the_old_links() -> None:
    kw: dict[str, Any] = {
        "system": {"system_id": "sys_1", "decision33_class": "not_high_risk"},
        "agents": [],
        "tasks": [],
        "waiting": {"sys_1": {"from_stage": "design", "to_stage": "deployment"}},
        "can_decide": True,
        "below_floor": [],
        "shadow_agents": [],
        "open_cases": 0,
    }
    assert next_action.recommend(**kw)["href"] == "/console/systems/sys_1"
    task = {
        "agent_id": "sys_1",
        "required": True,
        "status": "open",
        "title": "Do it",
        "task_id": "tsk_1",
        "overdue": False,
    }
    kw2 = {**kw, "waiting": {}, "tasks": [task]}
    assert next_action.recommend(**kw2)["href"] == "/console/tasks"


# ------------------------------------------------------------------ next action, flag on


def test_next_action_points_to_the_buttons_never_to_an_api_path() -> None:
    task = {
        "agent_id": "sys_1",
        "required": True,
        "status": "open",
        "title": "Do it",
        "task_id": "tsk_1",
        "overdue": True,
        "due_at": "2026-01-01",
    }
    base: dict[str, Any] = {
        "system": {"system_id": "sys_1", "decision33_class": "not_high_risk"},
        "agents": [],
        "tasks": [task],
        "waiting": {},
        "can_decide": False,
        "below_floor": [],
        "shadow_agents": [],
        "open_cases": 0,
        "workflow": True,
    }
    overdue = next_action.recommend(**base)
    assert overdue["key"] == "finish_task_overdue"
    assert overdue["href"] == "/console/systems/sys_1?tab=tasks"
    plain = next_action.recommend(**{**base, "tasks": [{**task, "overdue": False}]})
    assert plain["key"] == "finish_task" and plain["href"] == "/console/systems/sys_1?tab=tasks"
    stage = next_action.recommend(
        **{
            **base,
            "tasks": [],
            "can_decide": True,
            "waiting": {"sys_1": {"from_stage": "design", "to_stage": "deployment"}},
        }
    )
    assert stage["key"] == "approve_stage"
    assert stage["href"] == "/console/systems/sys_1?tab=tasks"
    assert "/v1/" not in json.dumps([overdue, plain, stage])


def test_recommended_action_of_an_agent_row_points_to_the_buttons() -> None:
    ctx = SimpleNamespace(settings=SimpleNamespace(console_workflow_actions=True))
    card = {"agent_id": "payments", "kind": "registered", "state": "SHADOW"}
    sysrow = {"system_id": "sys_1", "decision33_class": "x"}
    pre = {
        "tasks": [
            {
                "agent_id": "payments",
                "overdue": True,
                "title": "T",
                "task_id": "tsk_1",
                "due_at": "2026-01-01",
            }
        ],
        "stages": {},
    }
    got = next_action.recommended_action(ctx, card, sysrow, pre)
    assert got["key"] == "task" and got["href"] == "/console/systems/sys_1?tab=tasks"
    pre2 = {"tasks": [], "stages": {"sys_1": {"from_stage": "design", "to_stage": "deployment"}}}
    got = next_action.recommended_action(ctx, card, sysrow, pre2)
    assert got["key"] == "stage" and got["href"] == "/console/systems/sys_1?tab=tasks"
    ctx.settings.console_workflow_actions = False  # off: the old links
    assert next_action.recommended_action(ctx, card, sysrow, pre)["href"] == "/console/tasks"
    assert (
        next_action.recommended_action(ctx, card, sysrow, pre2)["href"] == "/console/systems/sys_1"
    )


# ------------------------------------------------------------------ tasks: Done


def test_done_returns_the_tab_fragment_and_writes_the_audit_note(wf: Console) -> None:
    sid = _system(wf)
    task = _task(wf, sid)
    html = _tab(wf, sid).text
    assert 'data-act="task-done"' in html and 'data-act="task-waive"' in html
    assert f"/console/systems/{sid}/tasks/{task['task_id']}/done" in html
    r = wf.post(_url(sid, f"tasks/{task['task_id']}/done"), {}, user=CREATOR)
    assert r.status_code == 200, r.text
    assert 'data-section="system-stage"' in r.text  # the fragment is the tab, not a page
    assert "<html" not in r.text
    assert 'id="flash" hx-swap-oob="true"' in r.text and "Task marked done." in r.text
    assert wf.ctx.tasks.get(task["task_id"])["status"] == "done"
    row = _audit(wf)[-1]
    assert row["detail"] == "task_done open>done" and row["outcome"] == "ok"
    assert row["target_kind"] == "task" and row["target_id"] == task["task_id"]
    assert row["actor"] == CREATOR and row["permission"] == "tasks.edit"
    assert row["before_hash"] and row["after_hash"] and row["before_hash"] != row["after_hash"]


def test_done_again_is_400(wf: Console) -> None:
    sid = _system(wf)
    task = _task(wf, sid)
    url = _url(sid, f"tasks/{task['task_id']}/done")
    assert wf.post(url, {}, user=CREATOR).status_code == 200
    r = wf.post(url, {}, user=CREATOR)
    assert r.status_code == 400 and "cannot be marked done" in r.text


def test_vietnamese_fragment(wf: Console) -> None:
    sid = _system(wf)
    task = _task(wf, sid)
    r = wf.post(_url(sid, f"tasks/{task['task_id']}/done") + "?lang=vi", {}, user=CREATOR)
    assert r.status_code == 200 and "Đã đánh dấu nhiệm vụ hoàn thành." in r.text


def test_role_rule_the_task_role_or_systems_edit(wf: Console) -> None:
    sid = _system(wf, owner=OWNER)
    task = _task(wf, sid)
    url = _url(sid, f"tasks/{task['task_id']}/done")
    r = wf.post(url, {}, user=APPROVER)  # neither the role "owner" nor systems.edit
    assert r.status_code == 403 and "needs the role owner or systems.edit" in r.text
    assert _audit(wf)[-1]["outcome"] == "denied"
    r = wf.post(url, {}, user=VIEWER)  # a scoped role: the system is not in its scope
    assert r.status_code == 400 and "does not exist" in r.text
    assert wf.ctx.tasks.get(task["task_id"])["status"] == "open"
    # the owner role closes an owner task
    r = wf.post(url, {}, user=OWNER)
    assert r.status_code == 200
    assert wf.ctx.tasks.get(task["task_id"])["done_by"] == OWNER


def test_buttons_follow_the_role(wf: Console) -> None:
    sid = _system(wf, owner=OWNER)
    task = _task(wf, sid)
    done = f"/console/systems/{sid}/tasks/{task['task_id']}/done"
    assert done in _tab(wf, sid, user=CREATOR).text
    assert done in _tab(wf, sid, user=OWNER).text
    assert done not in _tab(wf, sid, user=APPROVER).text


def test_a_role_bound_task_still_needs_its_role(wf: Console) -> None:
    """The task list keeps its own rule (done_refusal): systems.edit alone does not close a task
    of the approver role; the person with that role does."""
    sid = _system(wf)
    task = _task(wf, sid)
    row = wf.ctx.state.get("task", {"task_id": task["task_id"]})
    wf.ctx.state.update(
        "task", {"task_id": task["task_id"]}, {"owner_role": "approver"}, row["row_version"]
    )
    url = _url(sid, f"tasks/{task['task_id']}/done")
    r = wf.post(url, {}, user=CREATOR)
    assert r.status_code == 400 and "belongs to role approver" in r.text
    assert wf.post(url, {}, user=APPROVER).status_code == 200


def test_a_task_of_another_system_is_400(wf: Console) -> None:
    sid = _system(wf)
    other = str(
        wf.ctx.systems.register(draft(owner_user=CREATOR, name="Other"), CREATOR)["system_id"]
    )
    task = _task(wf, other)
    r = wf.post(_url(sid, f"tasks/{task['task_id']}/done"), {}, user=CREATOR)
    assert r.status_code == 400 and "task_not_found" in r.text
    assert wf.ctx.tasks.get(task["task_id"])["status"] == "open"


# ------------------------------------------------------------------ tasks: Waive


def test_waive_needs_a_reason_of_ten_characters(wf: Console) -> None:
    sid = _system(wf)
    task = _task(wf, sid)
    url = _url(sid, f"tasks/{task['task_id']}/waive")
    for reason in ("", "too short", "   short   "):
        r = wf.post(url, {"reason": reason}, user=SECOND)
        assert r.status_code == 400 and "reason_too_short" in r.text, reason
    assert wf.ctx.tasks.get(task["task_id"])["waive_pending"] is False


def test_the_creator_cannot_waive_the_task_same_person(wf: Console) -> None:
    sid = _system(wf)
    task = _task(wf, sid)
    assert task["created_by"] == CREATOR
    r = wf.post(_url(sid, f"tasks/{task['task_id']}/waive"), {"reason": REASON}, user=CREATOR)
    assert r.status_code == 400 and "same_person" in r.text
    assert wf.ctx.tasks.get(task["task_id"])["waive_pending"] is False
    assert _audit(wf)[-1]["outcome"] == "error"


def test_waive_then_a_second_person_approves(wf: Console) -> None:
    sid = _system(wf)
    task = _task(wf, sid)
    tid = task["task_id"]
    r = wf.post(_url(sid, f"tasks/{tid}/waive"), {"reason": REASON}, user=SECOND)
    assert r.status_code == 200 and "Waiver asked." in r.text
    got = wf.ctx.tasks.get(tid)
    assert got["waive_pending"] is True and got["waive_reason"] == REASON
    assert "Waiver waits for a second person" in r.text
    # audit: action name, status before and after, the hash of the reason, never the reason
    sha = hashlib.sha256(REASON.encode()).hexdigest()[:12]
    row = _audit(wf)[-1]
    assert row["detail"] == f"task_waive open>waive_pending reason_sha={sha}"
    assert row["before_hash"] != row["after_hash"]
    assert REASON not in json.dumps(wf.ctx.tables.query("console_action"), default=str)
    # the person who asked cannot answer: same_person (he holds the approver role)
    r = wf.post(_url(sid, f"tasks/{tid}/waive/approve"), {}, user=SECOND)
    assert r.status_code == 400 and "same_person" in r.text
    # a person without tasks.approve is refused at the route
    assert wf.post(_url(sid, f"tasks/{tid}/waive/approve"), {}, user=CREATOR).status_code == 403
    r = wf.post(_url(sid, f"tasks/{tid}/waive/approve"), {}, user=APPROVER)
    assert r.status_code == 200 and "Waiver approved." in r.text
    assert wf.ctx.tasks.get(tid)["status"] == "waived"
    assert _audit(wf)[-1]["detail"] == "task_waive_approve waive_pending>waived"


def test_waiver_can_be_rejected_with_a_reason(wf: Console) -> None:
    sid = _system(wf)
    tid = _task(wf, sid)["task_id"]
    wf.post(_url(sid, f"tasks/{tid}/waive"), {"reason": REASON}, user=SECOND)
    url = _url(sid, f"tasks/{tid}/waive/reject")
    r = wf.post(url, {"reason": "no"}, user=APPROVER)
    assert r.status_code == 400 and "reason_too_short" in r.text
    r = wf.post(url, {"reason": "The report does not cover it."}, user=APPROVER)
    assert r.status_code == 200 and "Waiver rejected." in r.text
    assert wf.ctx.tasks.get(tid)["status"] == "open"


def test_waive_buttons_show_to_the_second_person(wf: Console) -> None:
    sid = _system(wf)
    tid = _task(wf, sid)["task_id"]
    wf.post(_url(sid, f"tasks/{tid}/waive"), {"reason": REASON}, user=SECOND)
    assert 'data-act="waive-approve"' in _tab(wf, sid, user=APPROVER).text
    assert 'data-act="waive-approve"' not in _tab(wf, sid, user=SECOND).text
    assert 'data-act="waive-approve"' not in _tab(wf, sid, user=CREATOR).text


# ------------------------------------------------------------------ stage


def _request(c: Console, sid: str, to: str = "deployment", user: str = CREATOR) -> Any:
    return c.post(_url(sid, "stage/request"), {"to_stage": to, "reason": REASON}, user=user)


def test_stage_request_approve_move(wf: Console) -> None:
    sid = _system(wf)
    html = _tab(wf, sid).text
    assert 'data-act="stage-request"' in html and "Request a move" in html
    r = _request(wf, sid)
    assert r.status_code == 200 and "Move requested." in r.text
    assert 'data-section="system-stage"' in r.text and REASON in r.text  # the pending reason
    ap = wf.ctx.lifecycle.approvals(sid)[0]
    assert ap["status"] == "pending" and ap["requested_by"] == CREATOR and ap["reason"] == REASON
    sha = hashlib.sha256(REASON.encode()).hexdigest()[:12]
    assert _audit(wf)[-1]["detail"] == f"stage_request initiation>deployment reason_sha={sha}"
    assert wf.ctx.tables.query("chain_entry", {"record_type": "stage_change"})
    # the requester cannot answer: same_person, also with the approver role
    r = wf.post(
        _url(sid, f"stage/{ap['approval_id']}/decide"), {"decision": "approve"}, user=CREATOR
    )
    assert r.status_code == 400 and "same_person" in r.text
    # the second person sees the buttons and answers
    assert 'data-act="stage-approve"' in _tab(wf, sid, user=APPROVER).text
    assert 'data-act="stage-approve"' not in _tab(wf, sid, user=CREATOR).text
    r = wf.post(
        _url(sid, f"stage/{ap['approval_id']}/decide"), {"decision": "approve"}, user=APPROVER
    )
    assert r.status_code == 200 and "Request approved." in r.text
    assert 'data-act="stage-move"' not in r.text  # the approver holds no systems.edit
    assert 'data-act="stage-move"' in _tab(wf, sid, user=CREATOR).text
    assert _audit(wf)[-1]["detail"] == "stage_approve pending>approved"
    # Move: by the person with systems.edit
    r = wf.post(_url(sid, "stage/move"), {"to_stage": "deployment"}, user=CREATOR)
    assert r.status_code == 200 and "The system moved" in r.text
    assert wf.ctx.systems.get(sid)["lifecycle_stage"] == "deployment"
    assert _audit(wf)[-1]["detail"] == "stage_move initiation>deployment"
    assert "Stage of the system: Deployment" in r.text


def test_stage_requester_with_the_approver_role_is_same_person(wf: Console) -> None:
    sid = _system(wf)
    assert _request(wf, sid, user=SECOND).status_code == 200
    ap = wf.ctx.lifecycle.approvals(sid)[0]
    r = wf.post(
        _url(sid, f"stage/{ap['approval_id']}/decide"), {"decision": "approve"}, user=SECOND
    )
    assert r.status_code == 400 and "same_person" in r.text
    assert wf.ctx.lifecycle.approvals(sid)[0]["status"] == "pending"
    assert "Waits for a second person" in _tab(wf, sid, user=SECOND).text


def test_stage_reject_needs_a_reason_and_the_move_stays_blocked(wf: Console) -> None:
    sid = _system(wf)
    _request(wf, sid)
    ap = wf.ctx.lifecycle.approvals(sid)[0]
    url = _url(sid, f"stage/{ap['approval_id']}/decide")
    r = wf.post(url, {"decision": "reject", "reason": ""}, user=APPROVER)
    assert r.status_code == 400 and "reason is required" in r.text
    r = wf.post(url, {"decision": "reject", "reason": "The risk review is open."}, user=APPROVER)
    assert r.status_code == 200 and "Request rejected." in r.text
    r = wf.post(_url(sid, "stage/move"), {"to_stage": "deployment"}, user=CREATOR)
    assert r.status_code == 400 and "needs an approved stage approval" in r.text
    assert wf.ctx.systems.get(sid)["lifecycle_stage"] == "initiation"


def test_stage_request_rules(wf: Console) -> None:
    sid = _system(wf)
    url = _url(sid, "stage/request")
    r = wf.post(url, {"to_stage": "deployment", "reason": "short"}, user=CREATOR)
    assert r.status_code == 400 and "reason_too_short" in r.text
    r = wf.post(url, {"to_stage": "nowhere", "reason": REASON}, user=CREATOR)
    assert r.status_code == 400
    # a stage that needs no approval: the text points to the Move button, not to an API path
    r = wf.post(url, {"to_stage": "design", "reason": REASON}, user=CREATOR)
    assert r.status_code == 400 and "/v1/" not in r.text and "Move" in r.text
    assert _request(wf, sid).status_code == 200
    r = _request(wf, sid)  # one pending request per target stage
    assert r.status_code == 400 and "already waiting" in r.text
    assert wf.post(url, {"to_stage": "operation", "reason": REASON}, user=VIEWER).status_code == 403


def test_move_without_an_approval_never_names_an_api_path(wf: Console) -> None:
    sid = _system(wf)
    r = wf.post(_url(sid, "stage/move"), {"to_stage": "deployment"}, user=CREATOR)
    assert r.status_code == 400
    assert "/v1/" not in r.text and "Request move" in r.text


def test_direct_move_to_a_stage_without_approval(wf: Console) -> None:
    sid = _system(wf)
    assert 'data-act="stage-move-direct"' in _tab(wf, sid).text
    r = wf.post(_url(sid, "stage/move"), {"to_stage": "design"}, user=CREATOR)
    assert r.status_code == 200
    assert wf.ctx.systems.get(sid)["lifecycle_stage"] == "design"


def test_decide_unknown_approval_is_400(wf: Console) -> None:
    sid = _system(wf)
    r = wf.post(_url(sid, "stage/ap_none/decide"), {"decision": "approve"}, user=APPROVER)
    assert r.status_code == 400 and "approval_not_found" in r.text


# ------------------------------------------------------------------ plain post, scope


def test_a_plain_form_post_redirects_and_a_foreign_one_is_refused(wf: Console) -> None:
    sid = _system(wf)
    tid = _task(wf, sid)["task_id"]
    url = _url(sid, f"tasks/{tid}/done")
    r = wf.post(url, {}, user=CREATOR, htmx=False)  # no HX-Request, no Origin: refused
    assert r.status_code == 400 and "must come from the console page" in r.text
    r = wf.post(
        url,
        {},
        user=CREATOR,
        htmx=False,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/console/systems/{sid}?tab=tasks"
    assert wf.ctx.tasks.get(tid)["status"] == "done"


def test_an_unknown_system_is_400_not_500(wf: Console) -> None:
    r = wf.post(
        "/console/systems/sys_nope/stage/request", {"to_stage": "deployment", "reason": REASON}
    )
    assert r.status_code == 400


# ------------------------------------------------------------------ the service


def test_lifecycle_request_keeps_the_reason_and_the_old_call_is_unchanged(wf: Console) -> None:
    life = wf.ctx.lifecycle
    a = _system(wf)
    plain = life.request(a, "deployment", CREATOR)  # the API call: no reason
    assert plain["reason"] is None
    b = str(wf.ctx.systems.register(draft(owner_user=CREATOR, name="B"), CREATOR)["system_id"])
    with_reason = life.request(b, "deployment", CREATOR, REASON)
    assert with_reason["reason"] == REASON
    chain = wf.ctx.tables.query("chain_entry", {"record_type": "stage_change"})
    assert len(chain) == 2


def test_wf_labels_have_both_languages() -> None:
    labels = {k: v for k, v in table().items() if k.startswith("wf_")}
    assert len(labels) >= 25
    assert all(en and vi for en, vi in labels.values())
