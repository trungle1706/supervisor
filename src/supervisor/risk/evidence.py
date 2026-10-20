"""Evidence from runtime for the risk register (WP29, ADR D26).

A risk is linked to controls: gate rules, assurance packs and monitors. Once per window the job
counts what those controls did, for the agents the risk applies to, and writes one
``risk_evidence`` row (integers and hashes, no text) and one chain record.

What counts, per linked control, in the window [start, end):

=========  ======================================================================================
rule       ``working`` = at least one tier-0 verdict hit (action other than allow, not advisory)
           by a supervised agent; ``failing`` = the rule id is not in the deployed policy any more
           (a control that was removed); otherwise ``idle`` (no hit: it proves nothing).
pack       newest non-mock assurance result of a supervised agent: ``ok`` = working,
           ``fail`` or ``error`` = failing, ``warn``, ``skip`` or none = idle.
monitor    newest daily ``monitor_status`` of a supervised agent: ``ok`` = working; anything
           else (``not_applicable``, ``no_data``, missing) = idle.
=========  ======================================================================================

A supervised agent has ``gate_state`` RUNNING, PAUSED or QUARANTINED. A SHADOW agent only logs
what the gate would do, a RETIRED or unknown agent enforces nothing: their rows are not evidence
(they are counted in ``agents_excluded``). Mock pack results never count.

The rule that may lower a residual score (``assess``):

* Only a ``mitigate`` risk can be lowered. Other treatments keep the residual the person declared
  (``accept`` equals the inherent score by validation; ``avoid`` and ``transfer`` rest on facts
  the gate cannot see).
* The residual is the declared value only while the risk shows state ``working``: no linked
  control is failing and at least ``min_working_controls`` are working in the last window. In
  every other state the residual is the inherent score. So evidence can lower the score from the
  inherent value to the declared value, and nothing below the declared value.
* An evidence row older than two windows is stale and counts as no evidence.
* Every row stores the reason as a fixed code.

Judges and classifiers are not an input here (rule R1): only the deterministic gate verdicts,
assurance results and monitor states.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.risk.model import CONTROL_KINDS, RiskConfig

SUPERVISED_STATES = ("RUNNING", "PAUSED", "QUARANTINED")
STOP_ACTIONS = ("block", "pause")
HIT_ACTIONS = ("log", "alert", "block", "pause")
SCAN_CAP = 20000
STALE_WINDOWS = 2

STATE_WORKING = "working"
STATE_FAILING = "failing"
STATE_NONE = "no_evidence"

REASONS = (
    "controls_working",
    "control_failing",
    "no_working_control",
    "no_links",
    "no_supervised_agent",
    "treatment_declared",
    "stale_evidence",
    "no_evidence_yet",
)


@dataclass
class Counts:
    """Integer facts for one risk in one window. Nothing here is text."""

    agents_n: int = 0
    agents_excluded: int = 0
    rule_links: int = 0
    rule_hits: int = 0
    rule_stops: int = 0
    rules_missing: int = 0
    pack_links: int = 0
    pack_ok: int = 0
    pack_warn: int = 0
    pack_fail: int = 0
    pack_nodata: int = 0
    monitor_links: int = 0
    monitor_ok: int = 0
    monitor_other: int = 0
    controls_working: int = 0
    controls_failing: int = 0
    controls_idle: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)

    @property
    def control_links(self) -> int:
        return self.rule_links + self.pack_links + self.monitor_links


@dataclass(frozen=True)
class Decision:
    state: str
    reason: str
    residual: tuple[int, int]  # (likelihood, impact)


@dataclass
class Window:
    start: dt.datetime
    end: dt.datetime

    @property
    def seconds(self) -> int:
        return int((self.end - self.start).total_seconds())


def window_for(now: dt.datetime, days: int) -> Window:
    """The window that ends at the last full hour before ``now`` and spans ``days`` days."""
    end = now.astimezone(dt.UTC).replace(minute=0, second=0, microsecond=0)
    return Window(end - dt.timedelta(days=days), end)


def assess(
    treatment: str,
    inherent: tuple[int, int],
    declared: tuple[int, int],
    c: Counts,
    cfg: RiskConfig,
) -> Decision:
    """State and residual from the counts. Pure and deterministic."""
    if c.agents_n == 0 and c.control_links > 0:
        state, reason = STATE_NONE, "no_supervised_agent"
    elif c.controls_failing > 0:
        state, reason = STATE_FAILING, "control_failing"
    elif c.control_links == 0:
        state, reason = STATE_NONE, "no_links"
    elif c.controls_working >= cfg.min_working_controls:
        state, reason = STATE_WORKING, "controls_working"
    else:
        state, reason = STATE_NONE, "no_working_control"
    if treatment != "mitigate":
        return Decision(state, "treatment_declared", declared)
    return Decision(state, reason, declared if state == STATE_WORKING else inherent)


def _json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else None
    except (TypeError, ValueError):
        return None


def _ts(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return None


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


@dataclass
class Collector:
    """Reads the runtime facts. ``tables`` is the append-only store (verdict, eval_result),
    ``state`` the mutable one (agent, oversight_metric). ``rule_ids`` is the deployed policy."""

    tables: Any
    state: Any
    rule_ids: Collection[str]
    _agents: dict[str, tuple[str, str]] = field(default_factory=dict)
    _loaded: bool = False
    # One pass asks the same (agents, control) question for many risks; answer it once.
    _memo: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    # WP30: a ``control`` link is read through the runtime sources of the catalogue control
    # (control id -> [(kind, target)] of kinds rule, pack, monitor). None = such links are ignored.
    control_sources: Callable[[str], Iterable[tuple[str, str]]] | None = None

    def _agent_rows(self) -> dict[str, tuple[str, str]]:
        """lower-case id -> (id as stored, gate_state)."""
        if not self._loaded:
            self._agents = {
                str(r["agent_id"]).lower(): (str(r["agent_id"]), str(r["gate_state"]))
                for r in self.state.query("agent")
            }
            self._loaded = True
        return self._agents

    def split_agents(self, agents: Iterable[str]) -> tuple[list[str], int]:
        """(supervised agent ids as stored, number excluded)."""
        rows = self._agent_rows()
        keep: list[str] = []
        dropped = 0
        for a in sorted({x.lower() for x in agents}):
            stored, gate = rows.get(a, (a, ""))
            if gate in SUPERVISED_STATES:
                keep.append(stored)
            else:
                dropped += 1
        return keep, dropped

    def _cached(self, key: tuple[Any, ...], fn: Callable[[], Any]) -> Any:
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    # -- one control of each kind ------------------------------------------------------
    def rule_hits(self, agents: list[str], rule_id: str, w: Window) -> tuple[int, int]:
        hits = stops = 0
        for a in agents:
            rows = self.tables.query(
                "verdict",
                {"agent_id": a, "rule_id": rule_id, "tier": 0},
                order_by=("-ts",),
                limit=SCAN_CAP,
            )
            for v in rows:
                ts = _ts(v["ts"])
                if ts is None or not (w.start <= ts < w.end) or v.get("advisory"):
                    continue
                if v["action"] in HIT_ACTIONS:
                    hits += 1
                    stops += 1 if v["action"] in STOP_ACTIONS else 0
        return hits, stops

    def pack_status(self, agents: list[str], pack_id: str, w: Window) -> str:
        """``ok`` | ``warn`` | ``fail`` | ``nodata`` over the agents' newest non-mock results."""
        seen: list[str] = []
        for a in agents:
            rows = self.tables.query(
                "eval_result",
                {"target_kind": "agent", "target_id": a, "pack_id": pack_id},
                order_by=("-ts",),
                limit=50,
            )
            for r in rows:
                ts = _ts(r["ts"])
                if ts is None or not (w.start <= ts < w.end) or r.get("is_mock"):
                    continue
                seen.append(str(r["status"]))
                break
        if any(s in ("fail", "error") for s in seen):
            return "fail"
        if any(s == "ok" for s in seen):
            return "ok" if all(s in ("ok", "skip") for s in seen) else "warn"
        if any(s == "warn" for s in seen):
            return "warn"
        return "nodata"

    def monitor_ok(self, agents: list[str], monitor: str, w: Window) -> bool:
        for a in agents:
            rows = self.state.query("oversight_metric", {"agent_id": a})
            dated = [(d, r) for r in rows if (d := _date(r.get("metric_date"))) is not None]
            dated = [(d, r) for d, r in dated if w.start.date() <= d < w.end.date()]
            if not dated:
                continue
            _, newest = max(dated, key=lambda x: x[0])
            status = (_json(newest.get("monitor_status")) or {}).get(monitor) or {}
            if isinstance(status, Mapping) and status.get("status") == "ok":
                return True
        return False

    # -- one risk ------------------------------------------------------------------------
    def count(self, agents: Iterable[str], links: Iterable[tuple[str, str]], w: Window) -> Counts:
        """Counts for the agents a risk applies to and its control links (kind, target)."""
        supervised, dropped = self.split_agents(agents)
        key_agents, key_win = tuple(supervised), (w.start, w.end)
        c = Counts(agents_n=len(supervised), agents_excluded=dropped)
        pairs: set[tuple[str, str]] = set()
        for kind, target in links:
            if kind == "control":  # WP30: the control stands for its own runtime sources
                if self.control_sources is not None:
                    pairs.update(self.control_sources(target))
            else:
                pairs.add((kind, target))
        for kind, target in sorted(pairs):
            if kind not in CONTROL_KINDS or kind == "control":
                continue
            if kind == "rule":
                c.rule_links += 1
                if target not in self.rule_ids:
                    c.rules_missing += 1
                    c.controls_failing += 1
                    continue
                hits, stops = self._cached(
                    ("rule", key_agents, target, key_win),
                    lambda t=target: self.rule_hits(supervised, t, w),
                )
                c.rule_hits += hits
                c.rule_stops += stops
                if hits:
                    c.controls_working += 1
                else:
                    c.controls_idle += 1
            elif kind == "pack":
                c.pack_links += 1
                st = self._cached(
                    ("pack", key_agents, target, key_win),
                    lambda t=target: self.pack_status(supervised, t, w),
                )
                setattr(c, f"pack_{st}", getattr(c, f"pack_{st}") + 1)
                if st == "fail":
                    c.controls_failing += 1
                elif st == "ok":
                    c.controls_working += 1
                else:
                    c.controls_idle += 1
            else:
                c.monitor_links += 1
                if self._cached(
                    ("monitor", key_agents, target, key_win),
                    lambda t=target: self.monitor_ok(supervised, t, w),
                ):
                    c.monitor_ok += 1
                    c.controls_working += 1
                else:
                    c.monitor_other += 1
                    c.controls_idle += 1
        return c


def evidence_digest(risk_id: str, w: Window, c: Counts, d: Decision) -> str:
    """Hash of the facts a row states. Deterministic: the same facts give the same hash."""
    return sha256_hex(
        {
            "risk_id": risk_id,
            "window_start": format_ts(w.start),
            "window_end": format_ts(w.end),
            "counts": c.as_dict(),
            "state": d.state,
            "reason": d.reason,
            "residual_likelihood": d.residual[0],
            "residual_impact": d.residual[1],
        }
    )


def evidence_id(risk_id: str, w: Window) -> str:
    return "rev_" + sha256_hex({"risk_id": risk_id, "end": format_ts(w.end)})[:24]


def is_stale(window_end: dt.datetime, window_seconds: int, now: dt.datetime) -> bool:
    return (now - window_end).total_seconds() > STALE_WINDOWS * window_seconds
