"""JSON routes of the control catalogue (WP30): ``/v1/controls/...``.

* ``GET /v1/controls`` (controls.view): list; filters type, implemented_by, status, owner, agent, q.
* ``GET /v1/controls/agents/{agent_id}`` (controls.view): controls in scope of one agent, their
  status, the compliance bp and the obligations they hold.
* ``GET /v1/controls/{control_id}`` (controls.view): one control with its map and status by agent.
* ``POST /v1/controls`` (controls.edit): create; body control_id, fields, maps [{kind, target}].
* ``POST /v1/controls/{control_id}`` (controls.edit): update; optional ``row_version``.
* ``POST /v1/controls/{control_id}/maps`` (controls.edit): body action add or remove, kind, target.

Viewer reads; reviewer, owner and admin edit. Every POST writes two ``console_action`` audit rows
and a ``control_change`` chain record. Off unless CONTROLS_ENABLED=1: HTTP 400 with a message. A
bad input is HTTP 400 with the reason, an unknown control 404; never 500.
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
from supervisor.controls.model import ControlError, check_id, ensure_on
from supervisor.core.errors import NotFoundError

router = APIRouter(prefix="/v1/controls", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
MAX_BODY = 64_000


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ControlError("request body is too large")
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise ControlError("request body must be JSON") from None
    if not isinstance(data, dict):
        raise ControlError("request body must be a JSON object")
    return data


def _service(ctx: ConsoleContext) -> Any:
    ensure_on(ctx.settings)
    return ctx.controls


def _not_found(exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": str(exc)})


def _actor(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("changing the control catalogue needs a signed-in person")
    return str(me.user_id)


@router.get("", dependencies=[Depends(needs("controls.view"))])
def list_controls(request: Request, ctx: ConsoleContext = _CTX) -> Any:
    svc = _service(ctx)
    rows = svc.list_controls(dict(request.query_params))
    return {"count": len(rows), "controls": rows}


@router.get("/agents/{agent_id}", dependencies=[Depends(needs("controls.view"))])
def agent_controls(agent_id: str, ctx: ConsoleContext = _CTX) -> Any:
    svc = _service(ctx)
    out = svc.agent_compliance(agent_id)
    out["obligations"] = svc.obligation_coverage(agent_id)
    return out


@router.get("/{control_id}", dependencies=[Depends(needs("controls.view"))])
def get_control(control_id: str, ctx: ConsoleContext = _CTX) -> Any:
    svc = _service(ctx)
    try:
        return svc.get(control_id)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("", dependencies=[Depends(needs("controls.edit"))])
@audited("controls.edit")
async def create_control(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    data = await _body(request)
    maps = data.pop("maps", [])
    if not isinstance(maps, list) or not all(
        isinstance(x, dict) and "kind" in x and "target" in x for x in maps
    ):
        raise ControlError("maps must be a list of {kind, target}")
    out = svc.create(
        data,
        _actor(me),
        control_id=data.pop("control_id", None),
        maps=[(str(x["kind"]), str(x["target"])) for x in maps],
    )
    request.state.audit_detail = f"create:{out['control_id']}"
    return JSONResponse(status_code=201, content=out)


@router.post("/{control_id}", dependencies=[Depends(needs("controls.edit"))])
@audited("controls.edit")
async def update_control(
    control_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_id(control_id)
    data = await _body(request)
    version = data.pop("row_version", None)
    if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
        raise ControlError("row_version must be a whole number")
    try:
        return svc.update(control_id, data, _actor(me), version)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{control_id}/maps", dependencies=[Depends(needs("controls.edit"))])
@audited("controls.edit")
async def map_control(
    control_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_id(control_id)
    data = await _body(request)
    action = data.get("action", "add")
    kind, target = str(data.get("kind", "")), data.get("target", "")
    try:
        if action == "add":
            return svc.add_map(control_id, kind, target, _actor(me))
        if action == "remove":
            return svc.remove_map(control_id, kind, target, _actor(me))
        raise ControlError("action must be add or remove")
    except NotFoundError as exc:
        return _not_found(exc)
