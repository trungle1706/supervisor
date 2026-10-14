"""Multi-agent pattern (ADR D10): split payment across callers.

Stream: gateway ``gate_decision`` events for the transfer tool (no new bus, no Spark).
Each event carries the hashed grouping keys in ``args_masked`` (``{"keys": {...}}``,
written by the gateway), the amount (integer minor units) and ``caller_agent_id``.

Pattern: per (customer key, payee key), the sum of transfer attempts inside a sliding
window of ``window_s`` is above ``limit_minor`` AND the attempts came through at least
two different callers (``caller_agent_id``; a direct call counts as caller ``-``).
One finding opens one case (severity high, ``case_type`` multiagent) that names every
agent involved. The same (customer, payee) does not open a second case inside the window.

The gateway rule PAY-08 already blocks the same pattern inline for the agents in its
scope; this monitor is the detective control over all gateway events (shadow agents,
agents outside the rule scope, attempts that the gate blocked).

``SplitPaymentScanner`` is the streaming core: ``feed(row)`` one event at a time, in
time order. ``MultiAgentMonitor.run`` re-reads the last window before its cursor so the
scan state is rebuilt after a restart.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.monitors.common import (
    MonitorContext,
    as_dt,
    get_state,
    open_case,
    put_state,
    read_range,
)

ACTOR = "monitor:multiagent"
MONITOR = "multiagent"
DIRECT = "-"


@dataclass
class SplitPaymentConfig:
    tool: str = "transfer"
    customer_key: str = "from_account_id"
    payee_key: str = "payee_id"
    window_s: int = 3600
    limit_minor: int = 100_000_000
    min_callers: int = 2
    first_run_lookback_s: int = 86400
    settle_s: int = 120  # events newer than this may still be in the ingest spool

    @classmethod
    def from_settings(cls, settings: Any) -> SplitPaymentConfig:
        return cls(
            window_s=int(getattr(settings, "multiagent_window_s", 3600)),
            limit_minor=int(getattr(settings, "multiagent_limit_minor", 100_000_000)),
        )


@dataclass(frozen=True)
class _Hit:
    ts: datetime
    amount: int
    caller: str
    agent_id: str
    event_id: str
    allowed: bool


@dataclass
class Finding:
    customer_key: str
    payee_key: str
    ts: datetime
    agent_id: str  # executing agent of the event that crossed the limit
    callers: list[str]
    agents: list[str]
    total_minor: int
    allowed_minor: int
    events: list[str]


def _keys(row: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        doc = json.loads(row.get("args_masked") or "")
    except ValueError:
        return {}
    keys = doc.get("keys") if isinstance(doc, Mapping) else None
    return keys if isinstance(keys, Mapping) else {}


class SplitPaymentScanner:
    def __init__(self, cfg: SplitPaymentConfig) -> None:
        self.cfg = cfg
        self.window = timedelta(seconds=cfg.window_s)
        self._hits: dict[tuple[str, str], deque[_Hit]] = {}
        self._flagged: dict[tuple[str, str], datetime] = {}

    def feed(self, row: Mapping[str, Any]) -> Finding | None:
        if row.get("event_type") != "gate_decision" or row.get("tool_name") != self.cfg.tool:
            return None
        amount = row.get("amount_minor")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            return None
        keys = _keys(row)
        c, p = keys.get(self.cfg.customer_key), keys.get(self.cfg.payee_key)
        if not isinstance(c, str) or not isinstance(p, str):
            return None
        ts = as_dt(row["ts"])
        caller = row.get("caller_agent_id")
        hit = _Hit(
            ts,
            amount,
            caller if isinstance(caller, str) and caller else DIRECT,
            str(row["agent_id"]),
            str(row["event_id"]),
            str(row.get("status")) == "allowed",
        )
        key = (c, p)
        if len(self._hits) > 10_000:  # drop idle (customer, payee) keys
            self._hits = {k: d for k, d in self._hits.items() if d and ts - d[-1].ts <= self.window}
        hits = self._hits.setdefault(key, deque())
        hits.append(hit)
        while hits and ts - hits[0].ts > self.window:
            hits.popleft()
        total = sum(h.amount for h in hits)
        callers = sorted({h.caller for h in hits})
        if total <= self.cfg.limit_minor or len(callers) < self.cfg.min_callers:
            return None
        last = self._flagged.get(key)
        if last is not None and ts - last <= self.window:
            return None
        self._flagged[key] = ts
        agents = sorted({h.agent_id for h in hits} | {x for x in callers if x != DIRECT})
        return Finding(
            customer_key=c,
            payee_key=p,
            ts=ts,
            agent_id=hit.agent_id,
            callers=callers,
            agents=agents,
            total_minor=total,
            allowed_minor=sum(h.amount for h in hits if h.allowed),
            events=[h.event_id for h in hits],
        )


@dataclass
class MultiAgentResult:
    events_scanned: int = 0
    findings: list[Finding] = field(default_factory=list)
    cases_opened: list[str] = field(default_factory=list)


class MultiAgentMonitor:
    def __init__(self, ctx: MonitorContext, cfg: SplitPaymentConfig | None = None) -> None:
        self.ctx = ctx
        self.cfg = cfg or SplitPaymentConfig()

    def run(self, now: datetime | None = None) -> MultiAgentResult:
        now = now or self.ctx.clock.now()
        state = get_state(self.ctx, MONITOR, "cursor")
        cursor = (
            as_dt(state["ts"])
            if state and state.get("ts")
            else now - timedelta(seconds=self.cfg.first_run_lookback_s)
        )
        window = timedelta(seconds=self.cfg.window_s)
        # Scan only settled time: a late-ingested event older than the cursor would
        # otherwise be read but its finding skipped forever.
        end = max(cursor, now - timedelta(seconds=self.cfg.settle_s))
        rows = read_range(
            self.ctx,
            "agent_event",
            cursor - window,
            end,
            {"event_type": "gate_decision", "tool_name": self.cfg.tool},
        )
        scanner = SplitPaymentScanner(self.cfg)
        res = MultiAgentResult()
        for row in rows:
            res.events_scanned += 1
            f = scanner.feed(row)
            if f is None or f.ts < cursor:
                continue  # found (or not new) in an earlier run
            res.findings.append(f)
            mark = f"case:{f.customer_key}:{f.payee_key}"
            prev = get_state(self.ctx, MONITOR, mark)
            if prev and f.ts - as_dt(prev["ts"]) <= window:
                continue
            case_id = self._open(f)
            put_state(self.ctx, MONITOR, mark, {"ts": format_ts(f.ts), "case_id": case_id})
            res.cases_opened.append(case_id)
        put_state(self.ctx, MONITOR, "cursor", {"ts": format_ts(end)})
        return res

    def _open(self, f: Finding) -> str:
        summary = (
            f"Split payment across callers: {f.total_minor} minor units to one payee within "
            f"{self.cfg.window_s} s via {', '.join(f.callers)}; agents {', '.join(f.agents)}"
        )
        return open_case(
            self.ctx,
            agent_id=f.agent_id,
            severity="high",
            case_type="multiagent",
            summary=summary,
            actor=ACTOR,
            regulation_refs=["AML structuring control - split payment (ADR D10)"],
            evidence_payload={
                "monitor": "multiagent",
                "pattern": "split_payment_across_callers",
                "customer_key_hash": f.customer_key,
                "payee_key_hash": f.payee_key,
                "callers": f.callers,
                "agents": f.agents,
                "total_minor": f.total_minor,
                "allowed_minor": f.allowed_minor,
                "limit_minor": self.cfg.limit_minor,
                "window_s": self.cfg.window_s,
                "event_ids": f.events,
                "detected_at": format_ts(f.ts),
            },
        )


__all__ = [
    "Finding",
    "MultiAgentMonitor",
    "MultiAgentResult",
    "SplitPaymentConfig",
    "SplitPaymentScanner",
]
