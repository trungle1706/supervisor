"""Tasks and stage approvals as console buttons (WP-P1, ``CONSOLE_WORKFLOW_ACTIONS``).

The routes are in ``systems_routes.py``. This module holds the rules the buttons add; every other
rule stays in the services and is reused, not copied:

* Tasks: ``TaskService.done`` / ``request_waive`` / ``approve_waive`` / ``reject_waive``
  (``tasks/service.py``). The console adds the role check (the role of the task, or
  ``systems.edit``), the waiver reason of at least 10 characters and the rule that the person who
  created a task does not waive it (``same_person``).
* Stage: ``LifecycleService.request`` / ``decide`` / ``move`` (``governance/lifecycle.py``). The
  console adds the reason of the request and the ``same_person`` answer for the requester.

A refusal is HTTP 400 and the message starts with a code (``same_person``, ``reason_too_short``,
``workflow_off``). A missing role is HTTP 403. The audit note (``audit_note``) is fixed text plus
the first 12 characters of the SHA-256 of the typed reason; the reason itself is never written
to ``console_action``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import PermissionDenied
from supervisor.core import rbac
from supervisor.core.errors import NotFoundError, SupervisorError
from supervisor.governance.lifecycle import same
from supervisor.governance.model import LIFECYCLE_STAGES
from supervisor.tasks import model as tm

MIN_REASON = 10
OPEN = ("open", "in_progress")


class WorkflowError(SupervisorError):
    """A refusal of a workflow button (HTTP 400). The message starts with ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def ensure_on(ctx: Any) -> None:
    if not getattr(ctx.settings, "console_workflow_actions", False):
        raise WorkflowError(
            "workflow_off",
            "the task and stage buttons are off (CONSOLE_WORKFLOW_ACTIONS=1 turns them on)",
        )


def is_on(ctx: Any) -> bool:
    return bool(getattr(ctx.settings, "console_workflow_actions", False))


def person(me: Any) -> str:
    if getattr(me, "kind", "") != "user":
        raise PermissionDenied("this action needs a signed-in person")
    return str(me.user_id)


def reason_of(value: Any, what: str = "reason") -> str:
    text = (value or "").strip() if isinstance(value, str) else ""
    if len(text) < MIN_REASON:
        raise WorkflowError(
            "reason_too_short", f"the {what} needs at least {MIN_REASON} characters"
        )
    return text


def audit_note(action: str, before: str, after: str, reason: str | None = None) -> str:
    """``action before>after`` and, when a reason was typed, ``reason_sha=<12 hex>``."""
    note = f"{action} {before}>{after}"
    if reason:
        note += " reason_sha=" + hashlib.sha256(reason.encode("utf-8")).hexdigest()[:12]
    return note


_API_TEXT = (
    (
        re.compile(r"\(POST /v1/systems/\S+/approvals, then an approver answers it\)"),
        "(use Request move, then a second person answers it)",
    ),
    (re.compile(r"use POST /v1/systems/\S+/stage"), "use the Move button"),
)


def console_text(message: str) -> str:
    """The service text without an API path (the console never points to one)."""
    for pattern, repl in _API_TEXT:
        message = pattern.sub(repl, message)
    return message


# ------------------------------------------------------------------------------------ tasks


def system_task(ctx: Any, system: Mapping[str, Any], task_id: str) -> dict[str, Any]:
    """The task, if it belongs to this system (its own or one of its agents)."""
    tm.ensure_on(ctx.settings)
    sid = str(system["system_id"])
    owners = {sid} | {str(c["ref_id"]) for c in system["components"] if c["ref_kind"] == "agent"}
    try:
        task: dict[str, Any] = ctx.tasks.get(tm.check_id(task_id))
    except NotFoundError:
        raise WorkflowError("task_not_found", f"task {task_id[:64]} does not exist") from None
    if str(task["agent_id"]) not in owners:
        raise WorkflowError("task_not_found", f"task {task_id[:64]} is not a task of this system")
    return task


def may_act_on_task(me: Any, task: Mapping[str, Any]) -> bool:
    """The role of the task, an admin, or a holder of ``systems.edit``."""
    roles = set(getattr(me, "roles", ()) or ())
    return bool(
        getattr(me, "kind", "") == "user"
        and (
            str(task["owner_role"]) in roles
            or "admin" in roles
            or rbac.allowed(roles, "systems.edit")
        )
    )


def _need_role(me: Any, task: Mapping[str, Any]) -> None:
    if not may_act_on_task(me, task):
        raise PermissionDenied(
            f"task {task['task_id']} needs the role {task['owner_role']} or systems.edit"
        )


def task_done(
    ctx: Any, me: Any, system: Mapping[str, Any], task_id: str, evidence_ref: str | None
) -> tuple[dict[str, Any], str]:
    ensure_on(ctx)
    person(me)
    task = system_task(ctx, system, task_id)
    _need_role(me, task)
    out = ctx.tasks.done(task["task_id"], me, (evidence_ref or "").strip() or None)
    return out, audit_note("task_done", str(task["status"]), str(out["status"]))


def task_waive(
    ctx: Any, me: Any, system: Mapping[str, Any], task_id: str, reason: Any
) -> tuple[dict[str, Any], str]:
    """Ask to waive. The existing rule stays: a second person (role approver or admin) closes
    the waiver (``task_waive_approve``)."""
    ensure_on(ctx)
    uid = person(me)
    task = system_task(ctx, system, task_id)
    _need_role(me, task)
    text = reason_of(reason, "waiver reason")
    if task.get("created_by") and tm.same_person(str(task["created_by"]), uid):
        raise WorkflowError("same_person", "the person who created the task cannot ask to waive it")
    out = ctx.tasks.request_waive(task["task_id"], me, text)
    return out, audit_note("task_waive", str(task["status"]), "waive_pending", text)


def task_waive_answer(
    ctx: Any,
    me: Any,
    system: Mapping[str, Any],
    task_id: str,
    approve: bool,
    reason: Any = None,
) -> tuple[dict[str, Any], str]:
    ensure_on(ctx)
    uid = person(me)
    task = system_task(ctx, system, task_id)
    if task.get("waive_requested_by") and tm.same_person(str(task["waive_requested_by"]), uid):
        raise WorkflowError("same_person", "the person who asked for the waiver cannot answer it")
    if approve:
        out = ctx.tasks.approve_waive(task["task_id"], me)
        return out, audit_note("task_waive_approve", "waive_pending", str(out["status"]))
    text = reason_of(reason, "reason")
    out = ctx.tasks.reject_waive(task["task_id"], me, text)
    return out, audit_note("task_waive_reject", "waive_pending", str(out["status"]), text)


# ------------------------------------------------------------------------------------ stage


def stage_request(
    ctx: Any, me: Any, system: Mapping[str, Any], to_stage: str, reason: Any
) -> tuple[dict[str, Any], str]:
    ensure_on(ctx)
    uid = person(me)
    text = reason_of(reason, "reason for the move")
    out = ctx.lifecycle.request(str(system["system_id"]), to_stage, uid, text)
    return out, audit_note("stage_request", str(out["from_stage"]), str(out["to_stage"]), text)


def stage_decide(
    ctx: Any,
    me: Any,
    system: Mapping[str, Any],
    approval_id: str,
    decision: str,
    reason: Any,
) -> tuple[dict[str, Any], str]:
    ensure_on(ctx)
    uid = person(me)
    sid = str(system["system_id"])
    found = [a for a in ctx.lifecycle.approvals(sid) if a["approval_id"] == approval_id]
    if not found:
        raise WorkflowError("approval_not_found", f"approval {approval_id[:64]} does not exist")
    if same(uid, found[0]["requested_by"]):
        raise WorkflowError("same_person", "the person who asked for the move cannot answer it")
    text = (reason or "").strip() if isinstance(reason, str) else ""
    out = ctx.lifecycle.decide(sid, approval_id, decision, me, text or None)
    return out, audit_note(
        "stage_" + ("approve" if decision == "approve" else "reject"),
        "pending",
        str(out["status"]),
        text or None,
    )


def stage_move(
    ctx: Any, me: Any, system: Mapping[str, Any], to_stage: str
) -> tuple[dict[str, Any], str]:
    ensure_on(ctx)
    uid = person(me)
    before = str(system["lifecycle_stage"])
    out = ctx.lifecycle.move(str(system["system_id"]), to_stage, uid)
    return out, audit_note("stage_move", before, str(out["lifecycle_stage"]))


# ------------------------------------------------------------------------------------ page data


def tab_data(ctx: Any, me: Any, system: Mapping[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """The buttons of the Tasks tab: what this person may press. Marks each task row with
    ``wf`` (done, waive, waive_answer) and each approval with ``wf`` (decide, wait, move)."""
    roles = set(getattr(me, "roles", ()) or ())
    user = getattr(me, "kind", "") == "user"
    uid = str(getattr(me, "user_id", ""))
    can_edit = user and rbac.allowed(roles, "systems.edit")
    can_approve_waiver = user and rbac.allowed(roles, "tasks.approve")
    for group in extra.get("task_agents", []):
        for row in group.get("tasks", []):
            is_open = row["status"] in OPEN
            mine = may_act_on_task(me, row)
            pending = bool(row.get("waive_pending"))
            row["wf"] = {
                "done": is_open and mine,
                "waive": is_open and mine and row["kind"] != "move" and not pending,
                "waive_answer": pending
                and can_approve_waiver
                and not same(uid, row.get("waive_requested_by")),
                "evidence": row.get("evidence_kind") == "document",
            }
    life = extra["lifecycle"]
    current = str(system["lifecycle_stage"])
    approvals = []
    for ap in life["approvals"]:
        pending = ap["status"] == "pending"
        decide = False
        if pending and user and rbac.allowed(roles, "systems.approve"):
            try:
                decide = bool(ctx.lifecycle.can_decide(system, uid, roles))
            except Exception:  # noqa: BLE001 - a convenience flag; the service decides on POST
                decide = False
        ap = dict(ap)
        ap["wf"] = {
            "decide": decide and not same(uid, ap["requested_by"]),
            "wait": pending and same(uid, ap["requested_by"]),
            "move": bool(
                can_edit
                and ap["status"] == "approved"
                and not ap.get("applied_at")
                and ap["from_stage"] == current
            ),
        }
        approvals.append(ap)
    open_to = {a["to_stage"] for a in approvals if a["status"] == "pending"}
    needs = list(life["needs_approval"])
    retired = current == "retirement"
    return {
        "on": True,
        "can_edit": can_edit and not retired,
        "request_stages": [s for s in needs if s != current and s not in open_to],
        "direct_stages": [s for s in LIFECYCLE_STAGES if s not in needs and s != current],
        "approvals": approvals,
    }
