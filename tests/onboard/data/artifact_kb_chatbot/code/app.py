"""Bank knowledge chatbot (A1) as a Databricks App: /healthz and /chat.
The Supervisor FastAPI middleware checks every inbound request and every response; the tool
search_policies is gated in code (supervised_tool). Shadow or enforce is decided by the Supervisor
policy, not by this app."""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "src"))  # vendored Supervisor client (stdlib only), same as PYTHONPATH=src

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from supervisor.gateway.adapters.fastapi_mw import SupervisorASGIMiddleware

import agent as ag

app = FastAPI(title="Bank KB chatbot (synthetic)")
if ag.GATE is not None:
    app.add_middleware(SupervisorASGIMiddleware, gate=ag.GATE, agent_id=ag.AGENT_ID,
                       agent_version=ag.AGENT_VERSION, fail_mode=os.environ.get("SUPERVISOR_FAIL_MODE", "closed"),
                       skip_paths=("/healthz",))


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=800)


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=10)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "documents": ag.KB.doc_count, "chunks": len(ag.KB.chunks), "gate_configured": ag.GATE is not None}


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        return ag.run_agent(req.question.strip(), [t.model_dump() for t in req.history])
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="The language model endpoint is not reachable.")
