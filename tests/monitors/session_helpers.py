"""Shared builders for the WP27 session monitor tests (policy with a session section, gateway)."""

from __future__ import annotations

from typing import Any

import yaml

from supervisor.adapters.factory import Adapters
from supervisor.config import load_settings
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import (
    Policy,
    StorePolicyProvider,
    deploy_policy,
    load_policy_texts,
)
from supervisor.gateway.session_gate import SessionGate
from supervisor.monitors.common import MonitorContext
from tests.conftest import REPO_ROOT

BASELINE_TEXT = (REPO_ROOT / "policies" / "baseline.yaml").read_text(encoding="utf-8")


def policy_with(session: dict[str, Any] | None, agent: str = "payments") -> Policy:
    """The baseline policy with ``agents.<agent>.monitors.session`` set to ``session``."""
    doc = yaml.safe_load(BASELINE_TEXT)
    if session is not None:
        doc["agents"][agent]["monitors"] = {"session": session}
    return load_policy_texts([("baseline.yaml", yaml.safe_dump(doc, allow_unicode=True))])


def make_session_gateway(
    adapters: Adapters, evidence: Any, policy: Policy, **settings: Any
) -> tuple[Gateway, SessionGate]:
    deploy_policy(policy, adapters.state, adapters.clock)
    s = load_settings(session_monitor_enabled=True, **settings)
    sg = SessionGate(s, MonitorContext.from_adapters(adapters, evidence))
    sg.sync_reload = True  # deterministic tests; production reloads in a background thread
    gw = Gateway(
        StorePolicyProvider(adapters.state, refresh_s=0),
        adapters.tables,
        adapters.state,
        evidence,
        adapters.clock,
        state_cache_ttl_s=0,
        session_gate=sg,
    )
    return gw, sg
