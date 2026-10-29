"""Autonomy cap enforcement (WP-B1, docs/autonomy-levels.md section "The cap at the gate").

An accepted smart-guardian line ``max_level`` (system tag ``autonomy_limits``, JSON) becomes one
deterministic gate rule, ``GATE-AUTONOMY-CAP``. A tool call is paused when

* the autonomy level its tool risk class needs is higher than the cap (``read_only`` needs L3,
  ``money`` / ``credit`` / ``pii_export`` need L4: a person approves a consequential action before
  it runs only up to L3), or
* a money call carries an integer ``amount_minor`` above ``approval_above_vnd`` (a credit call:
  above ``credit_approval_above_vnd``). VND has no minor unit, so minor units are dong.

The result is a pause for approval, like the other pause rules: the agent is paused and a person
resumes it. Observe mode lifts it like the others (money, credit and pii_export need the two
observe approvals). Nothing here reads a model. Off (the source is ``None``) unless
``SMART_GUARDIAN`` and ``GOVERNANCE_ENABLED`` are on.

An agent on several systems gets the strictest limit of them. An agent on no system, a system
without the tag, or a tag that does not parse, changes nothing.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from supervisor.governance.model import AUTONOMY_LEVELS

log = logging.getLogger(__name__)

RULE_ID = "GATE-AUTONOMY-CAP"
CACHE_TTL_S = 5.0
# Level a tool call of this risk class needs (ILLUSTRATIVE; the bank sets the real mapping).
NEEDS_LEVEL = {
    "read_only": "l3_tool_using_supervised",
    "money": "l4_autonomous_bounded",
    "credit": "l4_autonomous_bounded",
    "pii_export": "l4_autonomous_bounded",
}
DEFAULT_NEEDS = "l4_autonomous_bounded"


@dataclass(frozen=True)
class Limits:
    max_level: str | None = None
    approval_above_vnd: int | None = None
    credit_approval_above_vnd: int | None = None

    def empty(self) -> bool:
        return (
            self.max_level is None
            and self.approval_above_vnd is None
            and self.credit_approval_above_vnd is None
        )


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def parse_limits(raw: Any) -> Limits:
    """The tag text to :class:`Limits`; anything unreadable gives empty limits."""
    try:
        doc = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return Limits()
    if not isinstance(doc, dict):
        return Limits()
    lvl = doc.get("max_level")
    return Limits(
        max_level=lvl if isinstance(lvl, str) and lvl in AUTONOMY_LEVELS[1:] else None,
        approval_above_vnd=_int(doc.get("approval_above_vnd")),
        credit_approval_above_vnd=_int(doc.get("credit_approval_above_vnd")),
    )


def merge(a: Limits, b: Limits) -> Limits:
    """The stricter of two limit sets."""

    def low(x: int | None, y: int | None) -> int | None:
        return y if x is None else x if y is None else min(x, y)

    lvl = a.max_level
    if b.max_level is not None and (
        lvl is None or AUTONOMY_LEVELS.index(b.max_level) < AUTONOMY_LEVELS.index(lvl)
    ):
        lvl = b.max_level
    return Limits(
        lvl,
        low(a.approval_above_vnd, b.approval_above_vnd),
        low(a.credit_approval_above_vnd, b.credit_approval_above_vnd),
    )


def check(limits: Limits, risk: str | None, args: Any) -> str | None:
    """The reason text of a pause, or None when the call may go on."""
    if limits.empty() or risk is None:
        return None
    if limits.max_level is not None:
        need = NEEDS_LEVEL.get(risk, DEFAULT_NEEDS)
        if AUTONOMY_LEVELS.index(need) > AUTONOMY_LEVELS.index(limits.max_level):
            return (
                f"{RULE_ID}: a {risk} tool needs autonomy level {need.split('_')[0]}, the cap is "
                f"{limits.max_level.split('_')[0]}: paused for approval"
            )
    amount = args.get("amount_minor") if hasattr(args, "get") else None
    cap = {"money": limits.approval_above_vnd, "credit": limits.credit_approval_above_vnd}.get(risk)
    if cap is not None and _int(amount) is not None and amount > cap:
        return f"{RULE_ID}: a {risk} amount above the approval limit {cap}: paused for approval"
    return None


class CapSource:
    """Read-only, cached lookup of the limits of an agent."""

    def __init__(self, state: Any) -> None:
        self.state = state
        self._cache: dict[str, tuple[float, Limits]] = {}

    def limits_for(self, agent_id: str) -> Limits:
        hit = self._cache.get(agent_id)
        now = time.monotonic()
        if hit is not None and now - hit[0] < CACHE_TTL_S:
            return hit[1]
        out = Limits()
        try:
            comps = self.state.query(
                "system_component", {"ref_kind": "agent", "ref_id": agent_id, "active": True}
            )
            for sid in sorted({str(c["system_id"]) for c in comps}):
                row = self.state.get("ai_system", {"system_id": sid})
                tags = (row or {}).get("tags") or {}
                out = merge(out, parse_limits(tags.get("autonomy_limits")))
        except Exception:  # noqa: BLE001 - a read failure leaves the call to the other rules
            log.exception("autonomy cap read failed")
            out = Limits()
        self._cache[agent_id] = (now, out)
        return out


def make_source(settings: Any, state: Any) -> CapSource | None:
    if state is None or not (
        getattr(settings, "smart_guardian", False)
        and getattr(settings, "governance_enabled", False)
    ):
        return None
    return CapSource(state)
