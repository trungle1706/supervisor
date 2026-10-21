"""JSON routes of the task list (WP30): ``/v1/tasks/...``.

* ``GET /v1/tasks`` (tasks.view): list; filters agent, stage, status, required, overdue, q.
* ``GET /v1/tasks/agents/{agent_id}`` (tasks.view): stage, sizing inputs, counts and tasks.
* ``GET /v1/tasks/export.csv`` (tasks.view): CSV of the list (formula-safe, at most 5000 rows).
* ``GET /v1/tasks/{task_id}`` (tasks.view): one task with its events.
* ``POST /v1/tasks`` (tasks.edit): add a custom task (agent_id, title).
* ``POST /v1/tasks/agents/{agent_id}/generate`` (tasks.edit): make or complete the current stage.
* ``POST /v1/tasks/{task_id}/start`` (tasks.edit): open to in_progress.
* ``POST /v1/tasks/{task_id}/done`` (tasks.edit): finish; body evidence_ref for a document task.
  A lifecycle move is a gate: it is refused while a required task of the stage is open.
  A reviewer or approver task needs that role (or admin).
* ``POST /v1/tasks/{task_id}/approve`` (tasks.approve): an approver closes a lifecycle move
  (stage approval at high level) or an approver task; same rules as done (review WP30).
* ``POST /v1/tasks/{task_id}/waive`` (tasks.edit): ask to waive; body reason.
* ``POST /v1/tasks/{task_id}/waive/approve`` (tasks.approve): the second person, an approver or
  an admin who is not the person who asked.
* ``POST /v1/tasks/{task_id}/waive/reject`` (tasks.approve): body reason.

Every POST writes two ``console_action`` audit rows, a ``task_event`` row and a ``task_change``
chain record. Off unless CONTROLS_ENABLED=1: HTTP 400 with a message. Bad input or a refused
transition is HTTP 400 with the reason, an unknown task 404; never 500.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import audited
from supervisor.core.errors import NotFoundError
from supervisor.tasks.model import TaskError, check_id, ensure_on

router = APIRouter(prefix="/v1/tasks", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
MAX_BODY = 16_000


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise TaskError("request body is too large")
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise TaskError("request body must be JSON") from None
    if not isinstance(data, dict):
        raise TaskError("request body must be a JSON object")
    return data


def _service(ctx: ConsoleContext) -> Any:
    ensure_on(ctx.settings)
    return ctx.tasks


def _not_found(exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": str(exc)})


def _person(me: AuthPrincipal) -> AuthPrincipal:
    if me.kind != "user":
        raise PermissionDenied("changing the task list needs a signed-in person")
    return me


@router.get("", dependencies=[Depends(needs("tasks.view"))])
def list_tasks(request: Request, ctx: ConsoleContext = _CTX) -> Any:
    svc = _service(ctx)
    rows = svc.list_tasks(dict(request.query_params))
    return {"count": len(rows), "illustrative": svc.cfg.illustrative, "tasks": rows}


@router.get("/export.csv", dependencies=[Depends(needs("tasks.view"))])
def export_tasks(request: Request, ctx: ConsoleContext = _CTX) -> Any:
    from fastapi.responses import Response

    svc = _service(ctx)
    agent = request.query_params.get("agent") or None
    if agent:
        check_id(agent, "agent id")
    raw = request.query_params.get("limit", "5000")
    if not raw.isdigit() or int(raw) < 1:
        raise TaskError("limit must be a whole number from 1")
    text, truncated = svc.export_csv(agent, int(raw))
    return Response(
        text,
        media_type="text/csv; charset=utf-8",
        headers={"X-Rows-Truncated": "true" if truncated else "false"},
    )


@router.get("/agents/{agent_id}", dependencies=[Depends(needs("tasks.view"))])
def agent_tasks(agent_id: str, ctx: ConsoleContext = _CTX) -> Any:
    svc = _service(ctx)
    try:
        return svc.agent_summary(agent_id)
    except NotFoundError as exc:
        return _not_found(exc)


@router.get("/{task_id}", dependencies=[Depends(needs("tasks.view"))])
def get_task(task_id: str, ctx: ConsoleContext = _CTX) -> Any:
    svc = _service(ctx)
    try:
        return svc.get(task_id)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("", dependencies=[Depends(needs("tasks.edit"))])
@audited("tasks.edit")
async def add_task(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _service(ctx)
    data = await _body(request)
    try:
        out = svc.add_custom(
            str(data.get("agent_id", "")),
            data.get("title"),
            _person(me),
            owner_role=data.get("owner_role", "owner"),
            required=bool(data.get("required", False)),
            due_days=data.get("due_days", 14),
        )
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"custom:{out['task_id']}"
    return JSONResponse(status_code=201, content=out)


@router.post("/agents/{agent_id}/generate", dependencies=[Depends(needs("tasks.edit"))])
@audited("tasks.edit")
async def generate(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    try:
        return svc.generate(agent_id, _person(me))
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{task_id}/start", dependencies=[Depends(needs("tasks.edit"))])
@audited("tasks.edit")
async def start_task(
    task_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_id(task_id)
    try:
        return svc.start(task_id, _person(me))
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{task_id}/done", dependencies=[Depends(needs("tasks.edit"))])
@audited("tasks.edit")
async def done_task(
    task_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_id(task_id)
    data = await _body(request)
    ref = data.get("evidence_ref")
    if ref is not None and not isinstance(ref, str):
        raise TaskError("evidence_ref must be text")
    try:
        return svc.done(task_id, _person(me), ref)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{task_id}/approve", dependencies=[Depends(needs("tasks.approve"))])
@audited("tasks.approve")
async def approve_task(
    task_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_id(task_id)
    data = await _body(request)
    ref = data.get("evidence_ref")
    if ref is not None and not isinstance(ref, str):
        raise TaskError("evidence_ref must be text")
    try:
        return svc.approve(task_id, _person(me), ref)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{task_id}/waive", dependencies=[Depends(needs("tasks.edit"))])
@audited("tasks.edit")
async def waive_task(
    task_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_id(task_id)
    data = await _body(request)
    try:
        return svc.request_waive(task_id, _person(me), data.get("reason"))
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{task_id}/waive/approve", dependencies=[Depends(needs("tasks.approve"))])
@audited("tasks.approve")
async def approve_waive(
    task_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_id(task_id)
    try:
        return svc.approve_waive(task_id, _person(me))
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{task_id}/waive/reject", dependencies=[Depends(needs("tasks.approve"))])
@audited("tasks.approve")
async def reject_waive(
    task_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_id(task_id)
    data = await _body(request)
    try:
        return svc.reject_waive(task_id, _person(me), data.get("reason"))
    except NotFoundError as exc:
        return _not_found(exc)
