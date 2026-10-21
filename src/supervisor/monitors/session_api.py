"""Session routes (WP27): ``GET /v1/sessions/{id}`` and ``POST /v1/sessions/{id}/resume``.

* GET shows the masked timeline of one conversation and its scores (permission ``session.view``).
  Masked means: tools, risk classes, outcomes, amounts, flags and finding codes. There is no
  text to show: the monitor never stores any (R2).
* POST lifts a session pause with the two-person rule (permission ``agent.resume``): the agent
  owner and a reviewer, two different people, inside the resume window.

Both answer HTTP 400 with a message when ``SESSION_MONITOR_ENABLED`` is off or the input is bad.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from supervisor.adapters.auth import AuthPrincipal
from supervisor.adapters.auth.authz import needs
from supervisor.console.context import ConsoleContext, get_context
from supervisor.core.canonical import format_ts
from supervisor.core.errors import SupervisorError
from supervisor.monitors.common import MonitorContext, get_state
from supervisor.monitors.session import (
    SESSION_ID_PATTERN,
    SessionEngine,
    lookback_s,
    resolve_config,
    timeline,
)
from supervisor.monitors.session_actions import STATE_MONITOR, session_ref
from supervisor.monitors.session_batch import epoch_ms, load_turns

router = APIRouter(prefix="/v1/sessions", tags=["console"])
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_CTX = Depends(get_context)
MAX_VIEW_ROWS = 2000


class SessionInputError(SupervisorError):
    """Bad input or the monitor is off (HTTP 400)."""


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(pattern=r"^[A-Za-z0-9_.:@-]{1,128}$")
    reason: str = Field(default="", max_length=2000)


def _check(ctx: ConsoleContext, session_id: str) -> None:
    if not ctx.settings.session_monitor_enabled:
        raise SessionInputError(
            "the session monitor is off (SESSION_MONITOR_ENABLED=1 turns it on)"
        )
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise SessionInputError("invalid session id")


def _iso(value: Any) -> str | None:
    return format_ts(value) if value is not None else None


def build_view(ctx: ConsoleContext, session_id: str, agent_id: str | None) -> dict[str, Any]:
    rt = ctx.runtime
    mctx = MonitorContext.from_adapters(rt.adapters, rt.chain)
    now = ctx.clock.now()
    from datetime import timedelta

    policy = rt.gateway.policy.current()
    # the NEWEST rows, inside the look-back of the monitor, capped (a long session shows its end)
    rows = ctx.tables.query(
        "agent_event", {"session_id": session_id}, order_by=("-ts",), limit=MAX_VIEW_ROWS
    )
    rows = sorted(
        (r for r in rows if r.get("event_type") == "gate_decision"), key=lambda r: r["ts"]
    )
    if rows:
        floor = rows[-1]["ts"] - timedelta(seconds=lookback_s(ctx.settings.session_window_s))
        rows = [r for r in rows if r["ts"] >= floor]
    if agent_id:
        rows = [r for r in rows if r["agent_id"] == agent_id]
    if not rows:
        return {"session_id": session_id, "found": False, "agents": []}
    start, end = rows[0]["ts"], rows[-1]["ts"] + timedelta(seconds=1)
    loaded = {
        k: v
        for k, v in load_turns(mctx, policy, start, end).items()
        if k[1] == session_id and (not agent_id or k[0] == agent_id)
    }
    engine = SessionEngine()
    for (_, sid), turns in loaded.items():
        for t in turns:
            engine.add(sid, t)
    agents = []
    for (aid, sid), turns in sorted(loaded.items()):
        manifest = policy.doc.agents.get(aid)
        mons = manifest.monitors if manifest is not None else None
        cfg = resolve_config(ctx.settings, mons.session if mons is not None else None)
        from supervisor.monitors.session import daily_cap_minor

        a = engine.assess(sid, aid, turns[-1].ts_ms, cfg, daily_cap_minor(policy, aid))
        st = get_state(mctx, STATE_MONITOR, session_ref(aid, sid)) or {}
        pauses = [
            {
                "control_id": r["control_id"],
                "status": r["status"],
                "scope": str(r["scope"]).split(","),
                "score_bp": r["score_bp"],
                "created_at": _iso(r["created_at"]),
                "expires_at": _iso(r["expires_at"]),
                "approver_1": r.get("approver_1"),
                "lifted_by": r.get("lifted_by"),
            }
            for r in ctx.state.query("session_control", {"agent_id": aid, "session_id": sid})
        ]
        src = next((r.get("session_source") for r in rows if r["agent_id"] == aid), None)
        agents.append(
            {
                "agent_id": aid,
                "session_source": src,
                "turns": len(turns),
                "assessed_at_ms": turns[-1].ts_ms,
                "assessment": a.as_dict() if a else None,
                "config": cfg.as_dict(),
                "case_id": st.get("case_id"),
                "pauses": pauses,
                "timeline": timeline(turns),
            }
        )
    return {
        "session_id": session_id,
        "found": True,
        "as_of": format_ts(now),
        "now_ms": epoch_ms(now),
        "agents": agents,
    }


@router.get("/{session_id}", dependencies=[Depends(needs("session.view"))])
async def get_session(
    session_id: str, agent_id: str | None = None, ctx: ConsoleContext = _CTX
) -> JSONResponse:
    _check(ctx, session_id)
    if agent_id is not None and not re.fullmatch(r"^[A-Za-z0-9_.:@-]{1,128}$", agent_id):
        raise SessionInputError("invalid agent id")
    view = await run_in_threadpool(build_view, ctx, session_id, agent_id)
    return JSONResponse(content=view, status_code=200 if view["found"] else 404)


@router.post("/{session_id}/resume", dependencies=[Depends(needs("agent.resume", control=True))])
async def resume_session(
    request: Request, session_id: str, ctx: ConsoleContext = _CTX
) -> JSONResponse:
    _check(ctx, session_id)
    try:
        body = ResumeRequest.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        raise SessionInputError(f"invalid request: {type(exc).__name__}") from exc
    gate = getattr(ctx.gateway, "session_gate", None)
    if gate is None:
        raise SessionInputError("the session monitor is not running in this process")
    me = getattr(request.state, "principal", None)
    principal = me.user_id if isinstance(me, AuthPrincipal) else None
    if not principal:
        raise SessionInputError("a signed-in person is required")
    out = await run_in_threadpool(
        gate.actions.resume, body.agent_id, session_id, principal, body.reason
    )
    gate.drop_pauses(body.agent_id)
    return JSONResponse(content=out)


__all__ = ["router"]
