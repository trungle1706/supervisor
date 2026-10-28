"""Request and approve RUNNING on the agent page (WP-P2 of phase 8, ``CONSOLE_STATE_ACTIONS``).

The two-person rule lives in ``gateway/state.py`` (``change_mode``): the first person asks, a
second and different person who is the agent owner or listed in the policy ``reviewers:``
approves. This module does not repeat that rule. It adds what the console needs around it: the
reason is required, an error carries a short code (``same_person``, ``request_pending``,
``no_request``, ``reason_required``), and the page shows the would-block count of the last 7
days next to the button (the same query as the Guardians tab, ``agent_guardians._gate_results``).

With the flag off nothing here runs: the agent card has no ``mode`` key and the route answers
HTTP 400 with the flag name.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from supervisor.console import agent_guardians
from supervisor.core.errors import SupervisorError
from supervisor.gateway.state import SamePersonError

WINDOW_DAYS = 7
STEPS = ("request", "approve")
FLAG_MESSAGE = "changing the gate mode in the console is off (CONSOLE_STATE_ACTIONS=1 turns it on)"


class ModeError(SupervisorError):
    """A refused step. The message starts with a short code (HTTP 400 at the route)."""


def enabled(ctx: Any) -> bool:
    return bool(getattr(ctx.settings, "console_state_actions", False))


def mode_data(ctx: Any, me: Any, card: Mapping[str, Any]) -> dict[str, Any]:
    """The panel of one agent card: the open request, who may approve, and the would-block count
    of the last 7 days. Only for a registered agent in SHADOW (or with a request waiting)."""
    agent_id = str(card["agent_id"])
    states = ctx.gateway.states
    shadow = card.get("state") == "SHADOW"
    try:
        pending = states.pending_mode(agent_id) if shadow else []
    except SupervisorError:
        pending = []
    would = 0
    if shadow:
        since = ctx.clock.now() - dt.timedelta(days=WINDOW_DAYS)
        would = int(agent_guardians._gate_results(ctx, agent_id, since)["would_block"])
    me_requested = any(p["principal"] == me.user_id for p in pending)
    role = card.get("me_role")
    out = {
        "shadow": shadow,
        "pending": [
            {"principal": p["principal"], "reason": p.get("reason") or ""} for p in pending
        ],
        "me_requested": me_requested,
        "me_role": role,
        "can_approve": bool(pending) and role is not None and not me_requested,
        "would_block_7d": would,
        "window_days": WINDOW_DAYS,
    }
    if getattr(ctx.settings, "onboard_postdeploy", False):  # WP-O5: link to the Post-deploy tab
        out["postdeploy"] = True
    return out


def run_step(ctx: Any, me: Any, agent_id: str, step: str, reason: str) -> dict[str, Any]:
    """One click of Request RUNNING or Approve RUNNING. Returns the state service result."""
    if step not in STEPS:
        raise ModeError("unknown step")
    reason = (reason or "").strip()
    if not reason:
        raise ModeError("reason_required: give the reason for this step")
    states = ctx.gateway.states
    if ctx.state.get("agent", {"agent_id": agent_id}) is None:
        raise ModeError(f"agent {agent_id} is not registered")
    pending = states.pending_mode(agent_id)
    if step == "request" and pending:
        raise ModeError(
            "request_pending: a request to move this agent to RUNNING is already waiting; "
            "a second person approves it"
        )
    if step == "approve" and not pending:
        raise ModeError("no_request: nobody asked to move this agent to RUNNING")
    try:
        return dict(
            states.change_mode(
                agent_id,
                "RUNNING",
                me.user_id,
                reason,
                auth_method=me.auth_method,
                actor_kind=me.kind,
            )
        )
    except SamePersonError as exc:
        raise ModeError(f"{exc.code}: {exc}") from None
