"""HTTP routes of the gateway: ``/gate/*`` (check, pause, resume, quarantine, release, state)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from supervisor.adapters.auth import AuthPrincipal
from supervisor.adapters.auth.audit import request_id_of, snapshot_hash, write_action
from supervisor.adapters.auth.authz import needs, runtime_settings
from supervisor.core.errors import SupervisorError
from supervisor.gateway import wiring
from supervisor.gateway.engine import Gateway
from supervisor.ops.middleware import BodyTooLarge

router = APIRouter(prefix="/gate", tags=["gate"])
log = logging.getLogger("supervisor.gateway")


def gateway_dep() -> Gateway:
    return wiring.get_gateway()


_GW: Gateway = Depends(gateway_dep)


_ID = r"^[A-Za-z0-9_.:@-]{1,128}$"


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(pattern=_ID)
    agent_version: str = Field(pattern=_ID)
    tool_name: str = Field(pattern=_ID)
    args: dict[str, Any]
    context: dict[str, Any] | None = None


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(pattern=_ID)
    principal: str | None = Field(default=None, max_length=256)
    reason: str = Field(default="", max_length=2000)


def _bad(message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": message, **extra})


async def _body(request: Request) -> Any:
    try:
        return await request.json()
    except BodyTooLarge:  # the body-limit middleware answers 413
        raise
    except Exception:  # noqa: BLE001 - any malformed body is a user error
        return None


def _validation_response(exc: ValidationError, audit_warning: str | None = None) -> JSONResponse:
    errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    extra = {"audit_warning": audit_warning} if audit_warning else {}
    return _bad("invalid request", detail=errors, **extra)


@router.post("/check")
async def check(request: Request, gw: Gateway = _GW) -> JSONResponse:
    try:
        req = CheckRequest.model_validate(await _body(request))
    except ValidationError as exc:
        return _validation_response(exc)
    try:
        result = await run_in_threadpool(
            gw.check, req.agent_id, req.agent_version, req.tool_name, req.args, req.context
        )
    except SupervisorError as exc:
        return _bad(str(exc))
    return JSONResponse(content=result)


def _principal(request: Request, req: ControlRequest, gw: Gateway) -> str | None:
    """SSO header first. The body field is a laptop/dev fallback only (D04: the dev users
    file is not a real identity); with ``trust_body_principal`` off (Databricks App) the
    header is required. Real identity comes from the WP8 ``Principal`` port."""
    header = request.headers.get("x-forwarded-user", "").strip()
    if header:
        return header
    if not getattr(gw, "trust_body_principal", False):
        return None
    return (req.principal or "").strip() or None


def _audit_control(
    request: Request,
    gw: Gateway,
    action: str,
    *,
    principal: str | None,
    agent_id: str | None,
    outcome: str,
    before: str | None,
    detail: str | None,
) -> str | None:
    """One ``console_action`` row for a control call (always, unless CONSOLE_AUDIT_ENABLED=0,
    also with API_RBAC_ENABLED off). Returns a warning text when the write failed."""
    if not runtime_settings().console_audit_enabled:
        return None
    me = getattr(request.state, "principal", None)
    me = me if isinstance(me, AuthPrincipal) else None
    try:
        after = snapshot_hash(gw.states.state, "agent", agent_id) if agent_id else None
        write_action(
            gw.tables,
            gw.clock,
            request_id=request_id_of(request),
            actor=me,
            actor_fallback=(principal or "unknown", "unverified", "gate_api"),
            permission=f"agent.{action}",
            method=request.method,
            path=request.url.path,
            outcome=outcome,
            target_kind="agent" if agent_id else None,
            target_id=agent_id,
            before_hash=before,
            after_hash=after,
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001 - never a 5xx because of the audit
        log.error("console_action write failed: %s", type(exc).__name__)
        return f"the audit record failed: {type(exc).__name__}; see the server log"
    return None


async def _control(request: Request, gw: Gateway, action: str) -> JSONResponse:
    try:
        req = ControlRequest.model_validate(await _body(request))
    except ValidationError as exc:
        warn = await run_in_threadpool(
            _audit_control,
            request,
            gw,
            action,
            principal=None,
            agent_id=None,
            outcome="error",
            before=None,
            detail="invalid_request",
        )
        return _validation_response(exc, warn)
    principal = _principal(request, req, gw)
    me = getattr(request.state, "principal", None)
    if runtime_settings().api_rbac_enabled and isinstance(me, AuthPrincipal) and me.is_human:
        principal = me.user_id  # the identity that passed the role check is the actor
    before = await run_in_threadpool(snapshot_hash, gw.states.state, "agent", req.agent_id)

    async def audit(outcome: str, detail: str | None) -> str | None:
        return await run_in_threadpool(
            _audit_control,
            request,
            gw,
            action,
            principal=principal,
            agent_id=req.agent_id,
            outcome=outcome,
            before=before,
            detail=detail,
        )

    if principal is None:
        warn = await audit("error", "principal_missing")
        return _bad(
            "principal is required (X-Forwarded-User header; body field on laptop only)",
            **({"audit_warning": warn} if warn else {}),
        )
    states = gw.states
    fn = {
        "pause": states.pause,
        "resume": states.resume,
        "quarantine": states.quarantine,
        "release": states.release_quarantine,
    }[action]
    try:
        result = await run_in_threadpool(fn, req.agent_id, principal, req.reason)
    except SupervisorError as exc:
        warn = await audit("error", type(exc).__name__)
        return _bad(str(exc), **({"audit_warning": warn} if warn else {}))
    except Exception as exc:  # noqa: BLE001 - store outage etc.: 400 with a message, never 500
        warn = await audit("error", type(exc).__name__)
        return _bad(
            f"{action} failed: {type(exc).__name__}; see the server log",
            **({"audit_warning": warn} if warn else {}),
        )
    warn = await audit("ok", None)
    return JSONResponse(content={**result, "audit_warning": warn} if warn else result)


@router.post("/pause", dependencies=[Depends(needs("agent.pause", api=True))])
async def pause(request: Request, gw: Gateway = _GW) -> JSONResponse:
    return await _control(request, gw, "pause")


@router.post("/resume", dependencies=[Depends(needs("agent.resume", api=True))])
async def resume(request: Request, gw: Gateway = _GW) -> JSONResponse:
    return await _control(request, gw, "resume")


@router.post("/quarantine", dependencies=[Depends(needs("agent.quarantine", api=True))])
async def quarantine(request: Request, gw: Gateway = _GW) -> JSONResponse:
    return await _control(request, gw, "quarantine")


@router.post("/release", dependencies=[Depends(needs("agent.release", api=True))])
async def release(request: Request, gw: Gateway = _GW) -> JSONResponse:
    return await _control(request, gw, "release")


@router.get("/agents/{agent_id}/state", dependencies=[Depends(needs("gate.read", api=True))])
def agent_state(agent_id: str, gw: Gateway = _GW) -> JSONResponse:
    try:
        return JSONResponse(content=gw.states.describe(agent_id))
    except SupervisorError as exc:
        return _bad(str(exc))


@router.get("/metrics", dependencies=[Depends(needs("gate.read", api=True))])
def metrics(gw: Gateway = _GW) -> JSONResponse:
    return JSONResponse(content=gw.metrics.snapshot())
