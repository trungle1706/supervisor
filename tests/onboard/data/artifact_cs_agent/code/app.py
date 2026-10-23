"""FastAPI app of the customer service agent (WP-A2). Run: python -m uvicorn app:app --port 8000

    GET  /healthz
    POST /chat                  {"message", "thread_id"?, "staff_id"?}
    POST /approve/{thread_id}   {"decision": "approve"|"reject", "approver"?, "note"?}
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from csagent import approvals
from csagent.agent import build_graph, reject, with_approval
from csagent.config import load
from csagent.llm import get_llm

log = logging.getLogger("csagent")
S = load()


def _guard() -> Any:
    if not S.gate_url:
        if os.environ.get("SUPERVISOR_ALLOW_UNSUPERVISED") == "1":
            log.warning("SUPERVISOR_GATE_URL is empty: tool calls are NOT supervised (dev only)")
            return None
        raise RuntimeError("SUPERVISOR_GATE_URL is not set (set SUPERVISOR_ALLOW_UNSUPERVISED=1 for dev)")
    from csagent.supervision import build_guard

    return build_guard(S)


GUARD = _guard()
GRAPH = build_graph(get_llm(S), GUARD)
_LOCKS: dict[str, threading.Lock] = {}
_STAFF: dict[str, str] = {}
app = FastAPI(title="Bank customer service agent (synthetic)", version="0.1.0")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    staff_id: str = Field(default="staff.demo", pattern=r"^[A-Za-z0-9_.@-]{1,64}$")


class ApproveIn(BaseModel):
    decision: Literal["approve", "reject"]
    approver: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.@-]{1,64}$")
    note: str = Field(default="", max_length=300)


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": S.max_steps * 2 + 6}


def _lock(thread_id: str) -> threading.Lock:
    return _LOCKS.setdefault(thread_id, threading.Lock())


def _trace(messages: list) -> list[dict[str, Any]]:
    """Tool calls and results since the last human message."""
    start = max((i for i, m in enumerate(messages) if m.type == "human"), default=-1) + 1
    out: list[dict[str, Any]] = []
    for m in messages[start:]:
        if m.type == "ai":
            out += [{"call": c["name"], "args": c["args"]} for c in m.tool_calls]
        elif m.type == "tool":
            out.append({"result_of": m.name, "status": getattr(m, "status", "success"),
                        "content": str(m.content)[:400]})
    return out


def _reply(thread_id: str) -> dict[str, Any]:
    state = GRAPH.get_state(_cfg(thread_id))
    msgs = state.values.get("messages", [])
    body: dict[str, Any] = {"thread_id": thread_id, "tool_trace": _trace(msgs)}
    if state.next == ("sensitive_tools",):
        call = next(c for c in msgs[-1].tool_calls if c["name"] == "waive_fee")
        pend = next((a for a in [_pending(thread_id)] if a), None)
        aid = pend["approval_id"] if pend else approvals.request(thread_id, call, _STAFF.get(thread_id, "unknown"))
        body.update(status="awaiting_approval", approval_id=aid,
                    pending={"tool": call["name"], "args": call["args"]},
                    reply="A fee waiver needs a human approver. Waiting for the decision.")
        return body
    last = msgs[-1] if msgs else None
    body.update(status="done", reply=str(last.content) if last is not None and last.type == "ai" else "")
    return body


def _pending(thread_id: str) -> dict | None:
    for rec in approvals._load().values():  # noqa: SLF001 - same package
        if rec["thread_id"] == thread_id and rec["status"] == "pending":
            return rec
    return None


def _run(thread_id: str, inp: Any) -> dict[str, Any]:
    from supervisor.gateway.sdk import SupervisorPaused

    try:
        GRAPH.invoke(inp, _cfg(thread_id))
    except SupervisorPaused as exc:
        d = getattr(exc, "decision", {}) or {}
        return {"thread_id": thread_id, "status": "paused", "rule_id": d.get("rule_id"),
                "correlation_id": d.get("correlation_id"),
                "reply": "This agent is paused by Supervisor. A reviewer must resume it."}
    return _reply(thread_id)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "agent_id": S.agent_id, "supervised": GUARD is not None,
            "model": S.llm_model}


@app.post("/chat")
def chat(body: ChatIn) -> dict[str, Any]:
    tid = body.thread_id or "t-" + uuid.uuid4().hex[:10]
    with _lock(tid):
        st = GRAPH.get_state(_cfg(tid))
        if st.next:
            raise HTTPException(409, "this thread waits for an approval decision: POST /approve/{thread_id}")
        _STAFF.setdefault(tid, body.staff_id)
        return _run(tid, {"messages": [("user", body.message)]})


@app.post("/approve/{thread_id}")
def approve(thread_id: str, body: ApproveIn, x_forwarded_email: str | None = Header(default=None),
            x_forwarded_user: str | None = Header(default=None),
            x_dev_user: str | None = Header(default=None)) -> dict[str, Any]:
    approver = x_forwarded_email or x_forwarded_user
    if not approver and os.environ.get("ALLOW_DEV_APPROVER_HEADER") == "1":
        approver = x_dev_user
    approver = approver or body.approver
    if not approver:
        raise HTTPException(400, "the approver identity is missing")
    with _lock(thread_id):
        st = GRAPH.get_state(_cfg(thread_id))
        pend = _pending(thread_id)
        if st.next != ("sensitive_tools",) or pend is None:
            raise HTTPException(409, "no approval is pending for this thread")
        try:
            rec = approvals.decide(pend["approval_id"], approver, body.decision == "approve", body.note)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from None
        if rec["approved"]:
            with_approval(GRAPH, _cfg(thread_id), rec["approval_id"])
        else:
            reject(GRAPH, _cfg(thread_id), body.note)
        out = _run(thread_id, None)
        out["approval"] = {"approval_id": rec["approval_id"], "status": rec["status"], "approver": approver}
        return out
