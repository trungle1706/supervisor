"""HTTP routes of the gateway: ``/gate/*`` (check, pause, resume, quarantine, release, state)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from supervisor.core.errors import SupervisorError
from supervisor.gateway import wiring
from supervisor.gateway.engine import Gateway

router = APIRouter(prefix="/gate", tags=["gate"])


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
    except Exception:  # noqa: BLE001 - any malformed body is a user error
        return None


def _validation_response(exc: ValidationError) -> JSONResponse:
    errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    return _bad("invalid request", detail=errors)


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


async def _control(request: Request, gw: Gateway, action: str) -> JSONResponse:
    try:
        req = ControlRequest.model_validate(await _body(request))
    except ValidationError as exc:
        return _validation_response(exc)
    principal = _principal(request, req, gw)
    if principal is None:
        return _bad("principal is required (X-Forwarded-User header; body field on laptop only)")
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
        return _bad(str(exc))
    except Exception as exc:  # noqa: BLE001 - store outage etc.: 400 with a message, never 500
        return _bad(f"{action} failed: {type(exc).__name__}; see the server log")
    return JSONResponse(content=result)


@router.post("/pause")
async def pause(request: Request, gw: Gateway = _GW) -> JSONResponse:
    return await _control(request, gw, "pause")


@router.post("/resume")
async def resume(request: Request, gw: Gateway = _GW) -> JSONResponse:
    return await _control(request, gw, "resume")


@router.post("/quarantine")
async def quarantine(request: Request, gw: Gateway = _GW) -> JSONResponse:
    return await _control(request, gw, "quarantine")


@router.post("/release")
async def release(request: Request, gw: Gateway = _GW) -> JSONResponse:
    return await _control(request, gw, "release")


@router.get("/agents/{agent_id}/state")
def agent_state(agent_id: str, gw: Gateway = _GW) -> JSONResponse:
    try:
        return JSONResponse(content=gw.states.describe(agent_id))
    except SupervisorError as exc:
        return _bad(str(exc))


@router.get("/metrics")
def metrics(gw: Gateway = _GW) -> JSONResponse:
    return JSONResponse(content=gw.metrics.snapshot())
