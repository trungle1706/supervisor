"""Batch path of the session monitor (WP27, ADR D29): replays stored gate decisions.

The in-request path (``gateway/session_gate.py``) sees turns as they happen. This path reads the
same turns back from ``agent_event`` (rows with ``session_id``), adds the Tier 0b verdict labels
that arrived after the decision, and runs the SAME engine and the SAME actions, so a restart, a
second replica or a missed call cannot hide a session. It also lifts pauses whose cool-down ran
out. Because actions are idempotent per session, both paths can run at once.

``load_turns`` is shared with the gate (cold start) and the harness.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from supervisor.monitors.common import MonitorContext, as_dt, read_range
from supervisor.monitors.session import (
    SessionConfig,
    SessionEngine,
    Turn,
    daily_cap_minor,
    decode_sig,
    resolve_config,
    timeline,
)
from supervisor.monitors.session_actions import SessionActions
from supervisor.monitors.status import NO_DATA, OK, known_agents, observed_tools, set_status

log = logging.getLogger("supervisor.monitors.session")

TIER0B_PREFIX = "gate:tier0b:"


def epoch_ms(ts: datetime) -> int:
    return int(as_dt(ts).timestamp() * 1000)


def turn_from_row(row: Mapping[str, Any], risk: str, extra_codes: Iterable[str] = ()) -> Turn:
    """A ``Turn`` from one ``agent_event`` gate_decision row."""
    feats = row.get("session_json") or {}
    if isinstance(feats, str):
        import json

        feats = json.loads(feats)
    codes = tuple(dict.fromkeys([*(f"d:{c}" for c in feats.get("f", [])), *extra_codes]))
    amount = row.get("amount_minor")
    return Turn(
        event_id=str(row["event_id"]),
        ts_ms=epoch_ms(row["ts"]),
        agent_id=str(row["agent_id"]),
        tool=str(row.get("tool_name") or ""),
        risk=risk,
        refused=str(row.get("status")) != "allowed",
        amount_minor=amount if isinstance(amount, int) else None,
        codes=codes,
        expand=bool(feats.get("x")),
        rare=bool(feats.get("d")),
        sig=decode_sig(feats.get("s")),
        consumer=feats.get("c"),
        assert_=bool(feats.get("a")),
        recall=bool(feats.get("r")),
        toks=decode_sig(feats.get("k")),
    )


def load_turns(
    ctx: MonitorContext, policy: Any, start: datetime, end: datetime
) -> dict[tuple[str, str], list[Turn]]:
    """Turns of every session with a gate decision in [start, end), in time order."""
    t0b: dict[str, list[str]] = {}
    for v in read_range(ctx, "verdict", start, end):
        if str(v.get("checker_id", "")).startswith(TIER0B_PREFIX) and v.get("event_id"):
            t0b.setdefault(str(v["event_id"]), []).append(f"t:{v['label']}")
    out: dict[tuple[str, str], list[Turn]] = {}
    for row in read_range(ctx, "agent_event", start, end, {"event_type": "gate_decision"}):
        sid = row.get("session_id")
        if not sid:
            continue
        risk = policy.risk_class(str(row.get("tool_name") or "")) or "unknown"
        t = turn_from_row(row, risk, t0b.get(str(row["event_id"]), ()))
        out.setdefault((t.agent_id, str(sid)), []).append(t)
    return out


@dataclass
class BatchResult:
    sessions: int = 0
    assessed: int = 0
    cases_opened: list[str] = field(default_factory=list)
    pauses_set: list[str] = field(default_factory=list)
    expired: list[str] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)


class SessionMonitor:
    def __init__(
        self,
        ctx: MonitorContext,
        settings: Any,
        policy: Any,
        *,
        actions: SessionActions | None = None,
    ) -> None:
        self.ctx = ctx
        self.settings = settings
        self.policy = policy
        self.actions = actions or SessionActions(ctx)

    def config_for(self, agent_id: str) -> tuple[SessionConfig, int | None]:
        manifest = self.policy.doc.agents.get(agent_id)
        mons = manifest.monitors if manifest is not None else None
        binding = mons.session if mons is not None else None
        return resolve_config(self.settings, binding), daily_cap_minor(self.policy, agent_id)

    def run(self, now: datetime | None = None) -> BatchResult:
        now = now or self.ctx.clock.now()
        res = BatchResult()
        res.expired = self.actions.expire()
        agents = known_agents(self.ctx, None, observed_tools(self.ctx, now - timedelta(days=1)))
        agents = sorted(set(agents) | set(self.policy.doc.agents))
        cfgs = {a: self.config_for(a) for a in agents}
        longest = max((c.window_s for c, _ in cfgs.values()), default=1800)
        by_session = load_turns(self.ctx, self.policy, now - timedelta(seconds=longest), now)
        engine = SessionEngine()
        for (_, sid), turns in sorted(by_session.items()):
            for t in turns:
                engine.add(sid, t)
        now_ms = epoch_ms(now)
        per_agent: dict[str, int] = {}
        for agent_id, sid in sorted(by_session):
            cfg, cap = cfgs.get(agent_id) or self.config_for(agent_id)
            res.sessions += 1
            if not cfg.enabled:
                continue
            a = engine.assess(sid, agent_id, now_ms, cfg, cap)
            if a is None:
                continue
            res.assessed += 1
            per_agent[agent_id] = per_agent.get(agent_id, 0) + 1
            if not (a.case_due or a.pause_due):
                continue
            rows = timeline(engine.turns(sid, agent_id))
            r = self.actions.act(a, cfg, rows, source="batch")
            if r.case_opened and r.case_id:
                res.cases_opened.append(r.case_id)
            if r.pause_set and r.pause_id:
                res.pauses_set.append(r.pause_id)
            if r.skipped:
                res.skipped[r.skipped] = res.skipped.get(r.skipped, 0) + 1
        day = now.date()
        for agent_id in agents:
            cfg, _ = cfgs[agent_id]
            if not cfg.enabled:
                continue
            n = per_agent.get(agent_id, 0)
            try:
                if n:
                    set_status(self.ctx, day, agent_id, "session", OK, n=n)
                else:
                    set_status(
                        self.ctx,
                        day,
                        agent_id,
                        "session",
                        NO_DATA,
                        code="no_session_turns",
                        reason="no gate decision with a session id in the window",
                    )
            except Exception:  # noqa: BLE001 - a status write must not stop the run
                log.exception("session monitor status write failed")
        return res


__all__ = ["BatchResult", "SessionMonitor", "epoch_ms", "load_turns", "turn_from_row"]
