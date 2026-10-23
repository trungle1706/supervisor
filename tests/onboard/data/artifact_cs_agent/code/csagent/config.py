"""Environment configuration. No secret has a default; none is written to a file."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_tool_mode: str
    gate_url: str
    agent_id: str
    agent_version: str
    credential: str          # HMAC secret (or empty: unsigned client / bearer from OAuth)
    credential_file: str
    fail_mode: str
    consumer_id: str
    max_steps: int


def load() -> Settings:
    e = os.environ.get
    return Settings(
        llm_base_url=os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8001/v1"),
        llm_model=os.environ.get("LLM_MODEL", "qwen3.8-27b-int4"),
        llm_api_key=e("LLM_API_KEY", ""),
        llm_tool_mode=e("LLM_TOOL_MODE", "auto"),
        gate_url=e("SUPERVISOR_GATE_URL", ""),
        agent_id=e("SUPERVISOR_AGENT_ID", "cs_agent"),
        agent_version=e("SUPERVISOR_AGENT_VERSION", "1"),
        credential=e("SUPERVISOR_CREDENTIAL", ""),
        credential_file=e("SUPERVISOR_CREDENTIAL_FILE", ""),
        fail_mode=e("SUPERVISOR_FAIL_MODE", "closed"),
        consumer_id=e("SUPERVISOR_CONSUMER_ID", "cs-desk"),
        max_steps=int(e("AGENT_MAX_STEPS", "8")),
    )
