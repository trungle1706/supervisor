"""Supervisor wiring: HttpGate + the LangGraph tool-call middleware (every tool call is checked).

The agent starts in SHADOW on the Supervisor side (policy `initial_state: SHADOW`): the gate
answers allow with action `log` and says what it WOULD have stopped. The decision to enforce is
taken on the Supervisor, not in this app. No gate URL means no supervision: the app then refuses
to start unless SUPERVISOR_ALLOW_UNSUPERVISED=1 (dev only).
"""
from __future__ import annotations

import os
from typing import Any

from .config import Settings
from .tools import RISK_CLASSES


def build_guard(s: Settings) -> Any:
    from supervisor.gateway.adapters.langgraph import SupervisorToolMiddleware
    from supervisor.gateway.ingress_sign import IngressCredential
    from supervisor.gateway.sdk import HttpGate

    cred = None
    secret = s.credential
    if not secret and s.credential_file:
        with open(s.credential_file, encoding="utf-8") as fh:
            secret = fh.readline().strip()
    if secret:
        cred = IngressCredential(s.agent_id, secret)
    elif os.environ.get("SUPERVISOR_OAUTH_BEARER") == "1":  # Databricks: App service principal token
        cred = IngressCredential(bearer=_databricks_token)
    gate = HttpGate(s.gate_url, credential=cred)
    return SupervisorToolMiddleware(
        gate, s.agent_id, s.agent_version,
        fail_mode=s.fail_mode,                 # "closed": gate unreachable stops the call
        consumer_id=s.consumer_id,
        risk_classes=RISK_CLASSES,
        on_block="message",                    # a block becomes a tool error the model can read
    )


def _databricks_token() -> str:  # pragma: no cover - needs a workspace
    from databricks.sdk.core import Config

    return Config().authenticate()["Authorization"].split(" ", 1)[1]
