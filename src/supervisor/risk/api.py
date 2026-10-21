"""JSON routes of the risk register (WP29): ``/v1/risks/...``.

=======  =============================  ===============  ==========================================
method   path                           permission       does
=======  =============================  ===============  ==========================================
GET      /v1/risks                      risks.view       list, filters agent category band owner
                                                         status treatment q
GET      /v1/risks/agents/{agent_id}    risks.view       register level and risks of one agent
GET      /v1/risks/{risk_id}            risks.view       one risk: scores, links, evidence trend
GET      /v1/risks/{risk_id}/evidence   risks.view       the evidence rows (newest first)
POST     /v1/risks                      risks.edit       create
POST     /v1/risks/{risk_id}            risks.edit       update (optional ``row_version``)
POST     /v1/risks/{risk_id}/links      risks.edit       body: action add or remove, kind, target
=======  =============================  ===============  ==========================================

Viewer reads; reviewer, owner and admin edit. Every POST writes two ``console_action`` audit rows
(attempted, then the outcome with the hash of the risk row before and after) and a ``risk_change``
chain record. Off unless RISK_REGISTER_ENABLED=1: HTTP 400 with a message. A bad input is HTTP
400 with the reason, an unknown risk 404; never 500.
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
from supervisor.risk.model import RiskError, check_id, ensure_on

router = APIRouter(prefix="/v1/risks", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
MAX_BODY = 64_000


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise RiskError("request body is too large")
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise RiskError("request body must be JSON") from None
    if not isinstance(data, dict):
        raise RiskError("request body must be a JSON object")
    return data


def _service(ctx: ConsoleContext) -> Any:
    ensure_on(ctx.settings)
    return ctx.risks


def _not_found(exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": str(exc)})


def _actor(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("changing the risk register needs a signed-in person")
    return str(me.user_id)


@router.get("", dependencies=[Depends(needs("risks.view"))])
def list_risks(request: Request, ctx: ConsoleContext = _CTX) -> Any:
    svc = _service(ctx)
    rows = svc.list_risks(dict(request.query_params))
    return {
        "count": len(rows),
        "illustrative_bands": svc.cfg.thresholds.illustrative,
        "risks": rows,
    }


@router.get("/agents/{agent_id}", dependencies=[Depends(needs("risks.view"))])
def agent_risks(agent_id: str, ctx: ConsoleContext = _CTX) -> Any:
    return _service(ctx).agent_summary(agent_id)


@router.get("/{risk_id}", dependencies=[Depends(needs("risks.view"))])
def get_risk(risk_id: str, ctx: ConsoleContext = _CTX) -> Any:
    svc = _service(ctx)
    try:
        return svc.get(risk_id)
    except NotFoundError as exc:
        return _not_found(exc)


@router.get("/{risk_id}/evidence", dependencies=[Depends(needs("risks.view"))])
def risk_evidence(risk_id: str, ctx: ConsoleContext = _CTX) -> Any:
    svc = _service(ctx)
    try:
        return {"risk_id": risk_id, "evidence": svc.get(risk_id)["evidence"]}
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("", dependencies=[Depends(needs("risks.edit"))])
@audited("risks.edit")
async def create_risk(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _service(ctx)
    data = await _body(request)
    links = data.pop("links", [])
    if not isinstance(links, list) or not all(
        isinstance(x, dict) and "kind" in x and "target" in x for x in links
    ):
        raise RiskError("links must be a list of {kind, target}")
    rid = data.pop("risk_id", None)
    out = svc.create(
        data,
        _actor(me),
        risk_id=rid,
        links=[(str(x["kind"]), str(x["target"])) for x in links],
    )
    request.state.audit_detail = f"create:{out['risk_id']}"
    return JSONResponse(status_code=201, content=out)


@router.post("/{risk_id}", dependencies=[Depends(needs("risks.edit"))])
@audited("risks.edit")
async def update_risk(
    risk_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_id(risk_id)
    data = await _body(request)
    version = data.pop("row_version", None)
    if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
        raise RiskError("row_version must be a whole number")
    try:
        return svc.update(risk_id, data, _actor(me), version)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{risk_id}/links", dependencies=[Depends(needs("risks.edit"))])
@audited("risks.edit")
async def link_risk(
    risk_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_id(risk_id)
    data = await _body(request)
    action = data.get("action", "add")
    kind, target = str(data.get("kind", "")), data.get("target", "")
    try:
        if action == "add":
            out = svc.add_link(risk_id, kind, target, _actor(me))
        elif action == "remove":
            out = svc.remove_link(risk_id, kind, target, _actor(me))
        else:
            raise RiskError("action must be add or remove")
    except NotFoundError as exc:
        return _not_found(exc)
    return out
