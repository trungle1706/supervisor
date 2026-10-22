"""Drift monitor (ADR D09): baseline band per agent version; a case opens with no rule broken.

Per (agent_id, agent_version):

1. Baseline. The first ``baseline_windows`` whole windows (``window_s``, default one day,
   epoch-aligned) after the version's first event form the baseline. For every tracked
   metric with a value in at least ``min_baseline_windows`` of them:
   ``center`` = median, ``mad`` = max(scaled MAD, floor), band = center +- k * mad.
   All integers. Stored in ``policy_baseline`` and recorded as ``drift_baseline`` evidence.
2. Watch. Each later whole window is compared with the band. A metric outside its band
   adds 1 to its breach streak; inside resets it to 0; no value (too few samples) leaves it.
3. Case. When any metric's streak reaches ``consecutive`` (M) and the version has no open
   drift case, a case opens (severity medium, ``case_type`` drift) with an integer-only
   evidence payload. No rule needs to have fired.

Tracked metrics (all ints):

==========================  ========================================================
``tool_share_bp:<tool>``    share of tool events for each tool seen in the baseline
``amount_p50`` / ``_p90``   nearest-rank percentiles of ``amount_minor``
``block_rate_bp``           gate decisions not allowed / gate decisions
``judge_p50_bp`` / ``_p90`` Tier 1 primary judge suspicion (``verdict.score_bp``)
``latency_p50_ms`` / ``_p90`` agent ``llm_call`` + ``tool_call`` latency
==========================  ========================================================

A metric needs ``min_n`` samples in a window to have a value there; a window without a
value leaves the streak as it is (a data gap does not break or extend a streak). A window
is judged ``settle_s`` after it closes (late ingest). When a human closes the drift case,
the streaks restart from zero.
Thresholds can be overridden per agent in ``policy_threshold``: ``drift.k``,
``drift.consecutive`` (agent ``*`` = every agent).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.monitors.common import (
    MonitorContext,
    as_dt,
    find_open_case,
    floor_window,
    median,
    open_case,
    percentile,
    rate_bp,
    read_range,
    scaled_mad,
    threshold,
)
from supervisor.monitors.status import (
    NO_DATA,
    NOT_APPLICABLE,
    OK,
    known_agents,
    observed_tools,
    set_status,
)

log = logging.getLogger("supervisor.monitors.drift")

ACTOR = "monitor:drift"
TOOL_EVENT_TYPES = ("tool_call", "gate_decision")
LATENCY_EVENT_TYPES = ("llm_call", "tool_call")
DENIED = ("denied", "blocked", "paused")


@dataclass
class DriftConfig:
    window_s: int = 86400
    baseline_windows: int = 7
    min_baseline_windows: int = 3
    k: int = 3
    consecutive: int = 3
    min_n: int = 20
    rel_floor_bp: int = 500  # band half-width at least 5 % of the center ...
    abs_floor: Mapping[str, int] = field(
        default_factory=lambda: {"bp": 100, "ms": 5, "amount": 1}
    )  # ... and at least this, by unit
    max_windows_per_run: int = 400  # catch-up cap per version per run
    settle_s: int = 600  # a window is judged only this long after it closes (late ingest)

    @classmethod
    def from_settings(cls, settings: Any) -> DriftConfig:
        return cls(
            window_s=int(getattr(settings, "drift_window_s", 86400)),
            baseline_windows=int(getattr(settings, "drift_baseline_windows", 7)),
            k=int(getattr(settings, "drift_k", 3)),
            consecutive=int(getattr(settings, "drift_consecutive", 3)),
            min_n=int(getattr(settings, "drift_min_n", 20)),
        )


def _unit(metric: str) -> str:
    if metric.endswith("_bp") or metric.startswith("tool_share_bp:"):
        return "bp"
    if metric.endswith("_ms"):
        return "ms"
    return "amount"


def window_metrics(
    events: Sequence[Mapping[str, Any]],
    verdicts: Sequence[Mapping[str, Any]],
    *,
    min_n: int,
    tools: Sequence[str] | None = None,
) -> dict[str, int]:
    """Integer metrics of one window. ``tools``: tool shares to report (default: seen)."""
    out: dict[str, int] = {}
    gate = [e for e in events if e.get("event_type") == "gate_decision"]
    tool_events = gate or [
        e for e in events if e.get("event_type") == "tool_call" and e.get("tool_name")
    ]
    if len(tool_events) >= min_n:
        counts = Counter(str(e.get("tool_name")) for e in tool_events)
        for tool in tools if tools is not None else sorted(counts):
            out[f"tool_share_bp:{tool}"] = counts.get(tool, 0) * 10000 // len(tool_events)
    amounts = [
        int(e["amount_minor"])
        for e in tool_events
        if isinstance(e.get("amount_minor"), int) and not isinstance(e.get("amount_minor"), bool)
    ]
    if len(amounts) >= min_n:
        out["amount_p50"] = percentile(amounts, 50)
        out["amount_p90"] = percentile(amounts, 90)
    if len(gate) >= min_n:
        denied = sum(1 for e in gate if str(e.get("status")) in DENIED)
        out["block_rate_bp"] = rate_bp(denied, len(gate)) or 0
    scores = [
        int(v["score_bp"])
        for v in verdicts
        if v.get("tier") == 1 and v.get("role") == "primary" and isinstance(v.get("score_bp"), int)
    ]
    if len(scores) >= min_n:
        out["judge_p50_bp"] = percentile(scores, 50)
        out["judge_p90_bp"] = percentile(scores, 90)
    lat = [
        int(e["latency_ms"])
        for e in events
        if e.get("event_type") in LATENCY_EVENT_TYPES and isinstance(e.get("latency_ms"), int)
    ]
    if len(lat) >= min_n:
        out["latency_p50_ms"] = percentile(lat, 50)
        out["latency_p90_ms"] = percentile(lat, 90)
    return out


@dataclass(frozen=True)
class Band:
    metric: str
    center: int
    mad: int
    low: int
    high: int
    windows: int


def make_band(metric: str, values: Sequence[int], k: int, cfg: DriftConfig) -> Band:
    center = median(values)
    floor = max(cfg.abs_floor.get(_unit(metric), 1), abs(center) * cfg.rel_floor_bp // 10000)
    mad = max(scaled_mad(values, center), floor)
    return Band(metric, center, mad, center - k * mad, center + k * mad, len(values))


@dataclass
class DriftResult:
    baselines_built: list[str] = field(default_factory=list)
    windows_checked: int = 0
    cases_opened: list[str] = field(default_factory=list)
    collecting: list[str] = field(default_factory=list)


class DriftMonitor:
    def __init__(
        self,
        ctx: MonitorContext,
        cfg: DriftConfig | None = None,
        resolver: Any | None = None,
    ) -> None:
        """``resolver``: a ``BindingResolver`` (WP1b-B). With it an agent may set its own
        window length and baseline size (``monitors.drift``), and every known agent gets a
        drift status (ok, no_data while the baseline is collecting, not_applicable)."""
        self.ctx = ctx
        self.cfg = cfg or DriftConfig()
        self.resolver = resolver

    def _switched_off(self, agent_id: str) -> bool:
        """WP-S1: drift is switched off for the agent's AI system (guardian binding)."""
        return self.resolver is not None and "monitor_drift" in getattr(
            self.resolver.resolve(agent_id), "off", ()
        )

    def _cfg_for(self, agent_id: str) -> DriftConfig:
        if self.resolver is None:
            return self.cfg
        b = self.resolver.resolve(agent_id).drift
        if b is None:
            return self.cfg
        changes = {
            k: v
            for k, v in (
                ("window_s", b.window_s),
                ("baseline_windows", b.baseline_windows),
                ("min_baseline_windows", b.min_baseline_windows),
                ("min_n", b.min_n),
            )
            if v is not None
        }
        cfg = replace(self.cfg, **changes)
        if cfg.min_baseline_windows > cfg.baseline_windows:
            cfg = replace(cfg, min_baseline_windows=cfg.baseline_windows)
        return cfg

    # -- reads ------------------------------------------------------------------
    def versions(self) -> list[tuple[str, str]]:
        sql = (
            "SELECT DISTINCT agent_id, agent_version FROM "  # noqa: S608 - names from model.yaml
            f"{self.ctx.executor.qualify('agent_event')} WHERE agent_version IS NOT NULL"
        )
        rows = self.ctx.executor.query(
            sql, column_types={"agent_id": "string", "agent_version": "string"}
        )
        return sorted((str(r["agent_id"]), str(r["agent_version"])) for r in rows)

    def first_ts(self, agent_id: str, version: str) -> datetime | None:
        sql = (
            f"SELECT MIN(ts) AS first_ts FROM {self.ctx.executor.qualify('agent_event')} "  # noqa: S608 - names from model.yaml
            "WHERE agent_id = :a AND agent_version = :v"
        )
        rows = self.ctx.executor.query(
            sql,
            {"a": agent_id, "v": version},
            column_types={"first_ts": "timestamp"},
            param_types={"a": "string", "v": "string"},
        )
        return as_dt(rows[0]["first_ts"]) if rows and rows[0]["first_ts"] is not None else None

    def _window(
        self, agent_id: str, version: str, start: datetime, end: datetime
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        events = read_range(
            self.ctx, "agent_event", start, end, {"agent_id": agent_id, "agent_version": version}
        )
        ids = {e["event_id"] for e in events}
        verdicts = [
            v
            for v in read_range(self.ctx, "verdict", start, end, {"agent_id": agent_id})
            if v.get("event_id") in ids
        ]
        return events, verdicts

    # -- run --------------------------------------------------------------------
    def run(self, now: datetime | None = None) -> DriftResult:
        now = now or self.ctx.clock.now()
        res = DriftResult()
        versions = self.versions()
        for agent_id, version in versions:
            if self._switched_off(agent_id):  # WP-S1: the product owner switched drift off
                continue
            mon = self
            cfg = self._cfg_for(agent_id)
            if cfg is not self.cfg:
                mon = DriftMonitor(self.ctx, cfg)
            mon._run_version(agent_id, version, now, res)
        if self.resolver is not None:
            self._write_status(now, versions, res)
        return res

    def _write_status(
        self, now: datetime, versions: Sequence[tuple[str, str]], res: DriftResult
    ) -> None:
        day = now.date()
        seen = {a for a, _ in versions}
        collecting = {c.split("@", 1)[0] for c in res.collecting}
        observed = observed_tools(self.ctx, now - timedelta(days=self.cfg.baseline_windows + 1))
        for agent_id in known_agents(self.ctx, self.resolver, observed):
            cfg = self._cfg_for(agent_id)
            if self._switched_off(agent_id):
                set_status(
                    self.ctx, day, agent_id, "drift", NOT_APPLICABLE, code="switched_off",
                    reason="drift is switched off for the AI system (guardian binding)",
                )  # fmt: skip
                continue
            if agent_id not in seen:
                set_status(
                    self.ctx, day, agent_id, "drift", NOT_APPLICABLE, code="no_versioned_events",
                    reason="no agent_event rows with an agent_version for this agent "
                    "(drift groups by version)",
                )  # fmt: skip
                continue
            bands = self.ctx.state.query("policy_baseline", {"agent_id": agent_id})
            if bands:
                set_status(self.ctx, day, agent_id, "drift", OK, n=len(bands))
            elif agent_id in collecting:
                need = cfg.baseline_windows * cfg.window_s
                set_status(
                    self.ctx, day, agent_id, "drift", NO_DATA, code="collecting_baseline",
                    reason=f"baseline needs {cfg.baseline_windows} whole windows of "
                    f"{cfg.window_s} s ({need} s) after the first event; "
                    "set monitors.drift.window_s to shorten it",
                )  # fmt: skip
            else:
                set_status(
                    self.ctx, day, agent_id, "drift", NO_DATA, code="no_band",
                    reason=f"no metric had min_n={cfg.min_n} samples in "
                    f"{cfg.min_baseline_windows} baseline windows",
                )  # fmt: skip

    def _run_version(self, agent_id: str, version: str, now: datetime, res: DriftResult) -> None:
        cfg = self.cfg
        k = threshold(self.ctx, agent_id, "drift.k", cfg.k)
        m = threshold(self.ctx, agent_id, "drift.consecutive", cfg.consecutive)
        rows = {
            r["metric"]: r
            for r in self.ctx.state.query(
                "policy_baseline", {"agent_id": agent_id, "agent_version": version}
            )
        }
        if not rows:
            rows = self._build_baseline(agent_id, version, now, k, res)
            if not rows:
                return
        base_to = min(as_dt(r["window_to"]) for r in rows.values())
        checked = [as_dt(r["last_checked_to"]) for r in rows.values() if r["last_checked_to"]]
        cursor = max([base_to, *checked])
        step = timedelta(seconds=cfg.window_s)
        tools = sorted(name.split(":", 1)[1] for name in rows if name.startswith("tool_share_bp:"))
        streak = {name: int(r["breach_streak"]) for name, r in rows.items()}
        last_value: dict[str, int | None] = {name: r["last_value"] for name, r in rows.items()}
        case_id = next((r["open_case_id"] for r in rows.values() if r["open_case_id"]), None)
        if case_id and find_open_case(self.ctx, agent_id, "drift", case_id) is None:
            case_id = None  # a human closed it: start counting again from zero
            streak = dict.fromkeys(streak, 0)
        n = 0
        settle = timedelta(seconds=cfg.settle_s)
        while cursor + step + settle <= now and n < cfg.max_windows_per_run:
            w_from, w_to = cursor, cursor + step
            events, verdicts = self._window(agent_id, version, w_from, w_to)
            values = window_metrics(events, verdicts, min_n=cfg.min_n, tools=tools)
            for name, r in rows.items():
                if name not in values:
                    continue
                v = values[name]
                last_value[name] = v
                outside = v < r["band_low"] or v > r["band_high"]
                streak[name] = streak[name] + 1 if outside else 0
            breaching = sorted(name for name in rows if streak[name] >= m)
            if breaching and find_open_case(self.ctx, agent_id, "drift", case_id) is None:
                case_id = self._open(agent_id, version, rows, breaching, last_value, streak,
                                     w_from, w_to, k, m)  # fmt: skip
                res.cases_opened.append(case_id)
            cursor = w_to
            n += 1
        res.windows_checked += n
        for name, r in rows.items():
            self.ctx.state.update(
                "policy_baseline",
                {"agent_id": agent_id, "agent_version": version, "metric": name},
                {
                    "breach_streak": streak[name],
                    "last_value": last_value[name],
                    "last_checked_to": cursor,
                    "open_case_id": case_id,
                },
                expected_version=r["row_version"],
            )

    def _build_baseline(
        self, agent_id: str, version: str, now: datetime, k: int, res: DriftResult
    ) -> dict[str, dict[str, Any]]:
        cfg = self.cfg
        first = self.first_ts(agent_id, version)
        if first is None:
            return {}
        start = floor_window(first, cfg.window_s)
        end = start + timedelta(seconds=cfg.window_s * cfg.baseline_windows)
        if now < end + timedelta(seconds=cfg.settle_s):
            res.collecting.append(f"{agent_id}@{version}")
            return {}
        per_window: list[dict[str, int]] = []
        w = start
        while w < end:
            events, verdicts = self._window(
                agent_id, version, w, w + timedelta(seconds=cfg.window_s)
            )
            per_window.append(window_metrics(events, verdicts, min_n=cfg.min_n))
            w += timedelta(seconds=cfg.window_s)
        tools = sorted(
            {
                name.split(":", 1)[1]
                for wm in per_window
                for name in wm
                if name.startswith("tool_share_bp:")
            }
        )
        if tools:  # fill zero shares where a window had tool events but not this tool
            for wm in per_window:
                if any(name.startswith("tool_share_bp:") for name in wm):
                    for t in tools:
                        wm.setdefault(f"tool_share_bp:{t}", 0)
        names = sorted({name for wm in per_window for name in wm})
        baseline_id = f"drift:{agent_id}@{version}:{format_ts(start)}"
        now_ts = self.ctx.clock.now()
        bands: list[Band] = []
        for name in names:
            values = [wm[name] for wm in per_window if name in wm]
            if len(values) >= cfg.min_baseline_windows:
                bands.append(make_band(name, values, k, cfg))
        out: dict[str, dict[str, Any]] = {}
        for b in bands:
            row = self.ctx.state.insert(
                "policy_baseline",
                {
                    "agent_id": agent_id,
                    "agent_version": version,
                    "metric": b.metric,
                    "baseline_id": baseline_id,
                    "center": b.center,
                    "mad": b.mad,
                    "band_low": b.low,
                    "band_high": b.high,
                    "k": k,
                    "windows": b.windows,
                    "window_s": cfg.window_s,
                    "window_from": start,
                    "window_to": end,
                    "breach_streak": 0,
                    "last_value": None,
                    "last_checked_to": None,
                    "open_case_id": None,
                    "computed_at": now_ts,
                },
            )
            out[b.metric] = row
        if bands:
            self.ctx.evidence.record(
                "drift_baseline",
                baseline_id,
                {
                    "agent_id": agent_id,
                    "agent_version": version,
                    "baseline_id": baseline_id,
                    "window_from": format_ts(start),
                    "window_to": format_ts(end),
                    "window_s": cfg.window_s,
                    "k": k,
                    "bands": [
                        {
                            "metric": b.metric,
                            "center": b.center,
                            "mad": b.mad,
                            "band_low": b.low,
                            "band_high": b.high,
                            "windows": b.windows,
                        }
                        for b in bands
                    ],
                    "ts": format_ts(now_ts),
                },
            )
            res.baselines_built.append(baseline_id)
        return out

    def _open(
        self,
        agent_id: str,
        version: str,
        rows: Mapping[str, Mapping[str, Any]],
        breaching: Sequence[str],
        last_value: Mapping[str, int | None],
        streak: Mapping[str, int],
        w_from: datetime,
        w_to: datetime,
        k: int,
        m: int,
    ) -> str:
        detail = [
            {
                "metric": name,
                "center": rows[name]["center"],
                "mad": rows[name]["mad"],
                "band_low": rows[name]["band_low"],
                "band_high": rows[name]["band_high"],
                "value": last_value[name],
                "streak": streak[name],
            }
            for name in breaching
        ]
        summary = (
            f"Drift: {agent_id}@{version} outside its baseline band for {m} consecutive "
            f"windows on {', '.join(breaching)} (no rule fired)"
        )
        return open_case(
            self.ctx,
            agent_id=agent_id,
            severity="medium",
            case_type="drift",
            summary=summary,
            actor=ACTOR,
            evidence_payload={
                "monitor": "drift",
                "agent_version": version,
                "baseline_id": next(iter(rows.values()))["baseline_id"],
                "window_from": format_ts(w_from),
                "window_to": format_ts(w_to),
                "window_s": self.cfg.window_s,
                "k": k,
                "consecutive": m,
                "metrics": detail,
            },
        )


__all__ = ["Band", "DriftConfig", "DriftMonitor", "DriftResult", "make_band", "window_metrics"]
