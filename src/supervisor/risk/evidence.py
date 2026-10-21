"""Evidence from runtime for the risk register (WP29, ADR D26).

A risk is linked to controls: gate rules, assurance packs and monitors. Once per window the job
counts what those controls did, for the agents the risk applies to, and writes one
``risk_evidence`` row (integers and hashes, no text) and one chain record.

What counts, per linked control, in the window [start, end):

=========  ======================================================================================
rule       ``working`` = at least one tier-0 verdict hit (action other than allow, not advisory,
           not mock) that the gate enforced for a supervised agent; ``failing`` = the rule id is
           not in the deployed policy any more (a control that was removed); otherwise ``idle``
           (no hit: it proves nothing). A SHADOW "would" row, a rule error and a fail-mode row
           are not hits (the label written by the gate at the time says so).
pack       newest non-mock assurance result of EVERY supervised agent, on its ``agent:`` target and
           on its ``traces:`` target (WP41): all ``ok`` (or ``skip``)
           = working; any ``fail`` or ``error`` = failing; otherwise (``warn``, an agent with no
           result, none at all) = idle.
monitor    newest daily ``monitor_status`` of EVERY supervised agent is ``ok`` = working;
           anything else (``not_applicable``, ``no_data``, missing for one agent) = idle. Only
           the deterministic monitors that write a status count (``EVIDENCE_MONITORS``); the
           ``quality`` monitor is an advisory LLM scorer (rule R1) and ``oversight`` and
           ``sweeps`` write no status, so a link to them is never evidence. ``ok`` means the
           monitor ran and produced values for the agent.
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
# Verdict labels and checkers that are not proof that a rule enforced anything (review WP29):
# a SHADOW agent's "would" rows, a rule that raised (the fail mode decided, not the rule) and
# a gate fail-mode row. The gate writes the label at the time of the call, so this also holds
# for an agent that was SHADOW then and is RUNNING now.
NON_HIT_LABEL_PREFIXES = ("shadow_",)
NON_HIT_LABELS = ("rule_error", "fail_open", "fail_closed")
NON_HIT_CHECKERS = ("gate:fail_mode",)
# Monitors whose status may count as a working control: the deterministic ones that write a
# monitor_status entry (supervisor.monitors.status.MONITORS) minus "quality", an advisory LLM
# scorer (rule R1: a judge never changes a control decision, so it never lowers a score).
EVIDENCE_MONITORS = ("fairness", "drift", "multiagent")
# Packs whose verdict comes from a judge model (hallucination and accuracy scorers). They are
# references, not evidence, unless the owner sets RISK_EVIDENCE_JUDGED_PACKS=1 (rule R1).
JUDGED_PACKS = (
    "groundedness_monitor",
    "halueval_vi",
    "ragas_rag_triad",
    "selfcheck_consistency",
    "simpleqa_vi",
    "truthfulqa_vi",
)

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
    "changed_since_evidence",
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


# WP41 (D28): the assurance targets whose id is an agent id. A `judge` target is not bound to an
# agent and never counts.
PACK_TARGET_KINDS: tuple[str, ...] = ("agent", "traces")


def source_window(kind: str, w: Window, pack_days: int | None) -> Window:
    """The window one source is read in: a pack result may be as old as ``pack_days`` (packs run
    less often than rules fire); rules and monitors use ``w``. WP30: the one definition, used by
    control status and by a risk that looks through a control."""
    if kind == "pack" and pack_days and pack_days * 86400 > w.seconds:
        return Window(w.end - dt.timedelta(days=pack_days), w.end)
    return w


def window_for(now: dt.datetime, days: int) -> Window:
    """The window that ends at the last full hour before ``now`` and spans ``days`` days.
    A naive ``now`` is read as UTC (never as the host's local time)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
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


def _true(value: Any) -> bool:
    """A stored boolean (Delta answers strings)."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def enforced_hit(v: Mapping[str, Any]) -> bool:
    """A verdict row that shows the gate enforced the rule (not shadow, error, fail or mock)."""
    label = str(v.get("label") or "")
    if _true(v.get("is_mock")) or str(v.get("checker_id") or "") in NON_HIT_CHECKERS:
        return False
    return label not in NON_HIT_LABELS and not label.startswith(NON_HIT_LABEL_PREFIXES)


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
    judged_packs: bool = False
    # One pass asks the same (agents, control) question for many risks; answer it once.
    _memo: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    # WP30: a ``control`` link is read through the runtime sources of the catalogue control
    # (control id -> [(kind, target)] of kinds rule, pack, monitor). None = such links are ignored.
    control_sources: Callable[[str], Iterable[tuple[str, str]]] | None = None
    # WP30: the agents a control applies to (``["*"]`` = all) and the pack window in days.
    control_scope: Callable[[str], list[str]] | None = None
    pack_days: int | None = None

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
                if ts is None or not (w.start <= ts < w.end) or _true(v.get("advisory")):
                    continue
                if not enforced_hit(v):
                    continue
                if v["action"] in HIT_ACTIONS:
                    hits += 1
                    stops += 1 if v["action"] in STOP_ACTIONS else 0
        return hits, stops

    def pack_status(self, agents: list[str], pack_id: str, w: Window) -> str:
        """``ok`` | ``warn`` | ``fail`` | ``nodata`` over the agents' newest non-mock results.
        ``ok`` needs a result for every supervised agent: a pack run on one agent does not show
        the control works for another agent the risk applies to."""
        if pack_id in JUDGED_PACKS and not self.judged_packs:
            return "nodata"  # a judge-scored pack is a reference, not evidence
        seen: list[str] = []
        missing = False
        for a in agents:
            found = False
            # WP41 (D28): a result on ANY target bound to the agent is evidence: the agent itself
            # and its recorded traces (target_id is the agent id for both). The newest valid
            # result of each target kind is read, so a fail on either one shows.
            for kind in PACK_TARGET_KINDS:
                rows = self.tables.query(
                    "eval_result",
                    {"target_kind": kind, "target_id": a, "pack_id": pack_id},
                    order_by=("-ts",),
                    limit=50,
                )
                for r in rows:
                    ts = _ts(r["ts"])
                    if ts is None or not (w.start <= ts < w.end) or _true(r.get("is_mock")):
                        continue
                    seen.append(str(r["status"]))
                    found = True
                    break
            missing = missing or not found
        if any(s in ("fail", "error") for s in seen):
            return "fail"
        if seen and missing:
            return "warn"  # partial coverage: not shown for every agent
        if any(s == "ok" for s in seen):
            return "ok" if all(s in ("ok", "skip") for s in seen) else "warn"
        if any(s == "warn" for s in seen):
            return "warn"
        return "nodata"

    def monitor_ok(self, agents: list[str], monitor: str, w: Window) -> bool:
        """True when the newest status in the window is ``ok`` for EVERY supervised agent."""
        if monitor not in EVIDENCE_MONITORS or not agents:
            return False
        for a in agents:
            rows = self.state.query("oversight_metric", {"agent_id": a})
            dated = [(d, r) for r in rows if (d := _date(r.get("metric_date"))) is not None]
            dated = [(d, r) for d, r in dated if w.start.date() <= d < w.end.date()]
            if not dated:
                return False
            _, newest = max(dated, key=lambda x: x[0])
            status = (_json(newest.get("monitor_status")) or {}).get(monitor) or {}
            if not (isinstance(status, Mapping) and status.get("status") == "ok"):
                return False
        return True

    # -- one risk ------------------------------------------------------------------------
    def count(self, agents: Iterable[str], links: Iterable[tuple[str, str]], w: Window) -> Counts:
        """Counts for the agents a risk applies to and its control links (kind, target).

        A ``control`` link stands for the runtime sources of the catalogue control, read for the
        agents the control applies to and in the same per-source window as control status."""
        supervised, dropped = self.split_agents(agents)
        c = Counts(agents_n=len(supervised), agents_excluded=dropped)
        entries: dict[tuple[str, str], tuple[str, ...]] = {}
        direct: set[tuple[str, str]] = set()
        for kind, target in links:
            if kind == "control":
                if self.control_sources is None:
                    continue
                scope = self.control_scope(target) if self.control_scope else ["*"]
                mine = (
                    supervised if scope == ["*"] else [a for a in supervised if a.lower() in scope]
                )
                for src in self.control_sources(target):
                    if len(mine) > len(entries.get(src, ())):
                        entries[src] = tuple(mine)
            else:
                entries[(kind, target)] = tuple(supervised)
                direct.add((kind, target))
        for (kind, target), who in sorted(entries.items()):
            if kind not in CONTROL_KINDS or kind == "control":
                continue
            ags = list(who)
            # the longer pack window applies to what a control stands for, not to a direct link
            kw = source_window(kind, w, None if (kind, target) in direct else self.pack_days)
            key_agents, key_win = who, (kw.start, kw.end)
            if not ags:  # the control does not apply to any agent of this risk: it proves nothing
                setattr(c, f"{kind}_links", getattr(c, f"{kind}_links") + 1)
                c.controls_idle += 1
                continue
            if kind == "rule":
                c.rule_links += 1
                if target not in self.rule_ids:
                    c.rules_missing += 1
                    c.controls_failing += 1
                    continue
                hits, stops = self._cached(
                    ("rule", key_agents, target, key_win),
                    lambda t=target, a=ags, k=kw: self.rule_hits(a, t, k),
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
                    lambda t=target, a=ags, k=kw: self.pack_status(a, t, k),
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
                    lambda t=target, a=ags, k=kw: self.monitor_ok(a, t, k),
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


def evidence_basis(row: Mapping[str, Any], controls: Iterable[tuple[str, str]]) -> str:
    """Hash of what an evidence row was computed for: the anchor, the treatment, the inherent
    and declared residual values and the control links. A change to any of them (an unlink, a
    move to another agent, a lower declared residual) needs a new evidence pass before the
    declared value is used again. Text fields (title, owner, review date) are not in it."""
    return sha256_hex(
        {
            "agent_id": row.get("agent_id") or "",
            "node_id": row.get("node_id") or "",
            "treatment": row["treatment"],
            "inherent": [int(row["inherent_likelihood"]), int(row["inherent_impact"])],
            "declared": [int(row["residual_likelihood"]), int(row["residual_impact"])],
            "controls": sorted(
                [k, t] for k, t in set(controls) if k in CONTROL_KINDS or k == "control_map"
            ),
        }
    )[:32]


def evidence_id(risk_id: str, w: Window, basis: str = "") -> str:
    """Row id: one row per risk, window and basis (a repeat is a no-op)."""
    key: dict[str, str] = {"risk_id": risk_id, "end": format_ts(w.end)}
    if basis:
        key["basis"] = basis
    return "rev_" + sha256_hex(key)[:24]


def is_stale(window_end: dt.datetime, window_seconds: int, now: dt.datetime) -> bool:
    return (now - window_end).total_seconds() > STALE_WINDOWS * window_seconds
