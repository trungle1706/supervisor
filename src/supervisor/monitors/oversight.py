"""Daily oversight metrics per agent -> ``oversight_metric`` (feeds the console panel, WP8).

Column definitions are in ``docs/metrics.md``. Every value is an integer (basis points,
milliseconds, seconds, counts); the legacy float columns hold the same bp / 10000 for
older readers and never enter the chain. Each run recomputes today and yesterday (UTC
days), so late events and late human actions are picked up.

``chain_ok`` comes from an incremental walk of the agent's chain lane in the store:
sequence continuity, ``prev_hash`` links and the recomputed ``entry_hash``. The walk
resumes from the last verified entry (``monitor_state``). It is a quick health check;
the offline ``supervisor-verify`` over an export (signatures, roots, anchors) remains the
proof.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.evidence.verify import GENESIS_HASH, detect_entry_version, entry_hash
from supervisor.judge.mrm.agreement import agree_bp, agreement_pairs
from supervisor.monitors.common import (
    MonitorContext,
    as_dt,
    get_state,
    median,
    put_state,
    rate_bp,
    read_range,
    upsert_metric,
)

log = logging.getLogger("supervisor.monitors.oversight")

MONITOR = "metrics"
FLAG_ACTIONS = ("alert", "block", "pause", "open_case", "raise_severity")
JUDGE_ROLES = ("primary", "challenger")
GATED_STATUS_DENIED = ("denied", "blocked", "paused")


def load_eval_report(path: Path | None) -> dict[str, int | None]:
    """catch / false-alarm bp from the judge eval report (held-out set first, else dev)."""
    out: dict[str, int | None] = {"catch_rate_bp": None, "false_alarm_bp": None}
    if path is None or not Path(path).is_file():
        return out
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        metrics = doc.get("metrics") or {}
        section = metrics.get("heldout") or metrics.get("dev") or {}
    except (OSError, ValueError, AttributeError):
        return out
    for key in out:
        v = section.get(key) if isinstance(section, Mapping) else None
        out[key] = v if isinstance(v, int) and not isinstance(v, bool) else None
    return out


@dataclass
class ChainCheck:
    ok: bool
    checked: int
    last_seq: int | None
    problem: str | None = None


def check_lane(ctx: MonitorContext, lane: str) -> ChainCheck:
    """Walk ``lane`` from the last verified entry. Stores the resume point."""
    mark = get_state(ctx, MONITOR, f"chain:{lane}") or {}
    if mark.get("ok") is False:  # a broken lane stays broken until a human looks
        return ChainCheck(False, 0, mark.get("seq"), mark.get("problem"))
    seq = mark.get("seq")
    prev = mark.get("entry_hash") or GENESIS_HASH
    t = ctx.model.table("chain_entry")
    sql = (
        f"SELECT {', '.join(t.column_names)} FROM {ctx.executor.qualify(t.name)} "  # noqa: S608 - names from model.yaml
        "WHERE lane = :lane AND seq > :seq ORDER BY seq"
    )
    rows = ctx.executor.query(
        sql,
        {"lane": lane, "seq": -1 if seq is None else int(seq)},
        column_types=t.types,
        param_types={"lane": "string", "seq": "int"},
    )
    expected = 0 if seq is None else int(seq) + 1
    problem = None
    n = 0
    for row in rows:
        if row["seq"] != expected:
            problem = f"seq gap: expected {expected}, found {row['seq']}"
        elif row["prev_hash"] != prev:
            problem = f"seq {row['seq']}: prev_hash does not link"
        else:
            fields = {**row, "ts": format_ts(as_dt(row["ts"]))}
            version = detect_entry_version(fields)
            if entry_hash({**fields, "chain_spec_version": version}) != row["entry_hash"]:
                problem = f"seq {row['seq']}: entry_hash does not match"
        if problem:
            break
        prev, seq, expected = row["entry_hash"], row["seq"], row["seq"] + 1
        n += 1
    state = {"seq": seq, "entry_hash": prev, "ok": problem is None, "problem": problem}
    put_state(ctx, MONITOR, f"chain:{lane}", state)
    return ChainCheck(problem is None, n, seq, problem)


class OversightMetrics:
    def __init__(
        self,
        ctx: MonitorContext,
        *,
        eval_report: Path | None = None,
        min_agreement_bp: int = 8000,
        min_agreement_pairs: int = 5,
        holidays: frozenset[date] = frozenset(),
    ) -> None:
        self.ctx = ctx
        self.holidays = holidays  # incident clock calendar for the agreement case (WP19)
        self.min_bp, self.min_pairs = min_agreement_bp, min_agreement_pairs
        self.eval = load_eval_report(eval_report)

    def agents(self, day: date) -> list[str]:
        start = datetime.combine(day, time(0), tzinfo=UTC)
        ids = {str(r["agent_id"]) for r in self.ctx.state.query("agent")}
        sql = (
            f"SELECT DISTINCT agent_id FROM {self.ctx.executor.qualify('agent_event')} "  # noqa: S608 - names from model.yaml
            "WHERE ts >= :f AND ts < :t"
        )
        rows = self.ctx.executor.query(
            sql,
            {"f": start, "t": start + timedelta(days=1)},
            column_types={"agent_id": "string"},
            param_types={"f": "timestamp", "t": "timestamp"},
        )
        return sorted(ids | {str(r["agent_id"]) for r in rows})

    def compute(self, agent_id: str, day: date, chain_ok: bool | None) -> dict[str, Any]:
        start = datetime.combine(day, time(0), tzinfo=UTC)
        end = start + timedelta(days=1)
        events = read_range(self.ctx, "agent_event", start, end, {"agent_id": agent_id})
        verdicts = read_range(self.ctx, "verdict", start, end, {"agent_id": agent_id})
        tool_calls = sum(1 for e in events if e["event_type"] == "tool_call")
        gate = [e for e in events if e["event_type"] == "gate_decision"]
        seen = tool_calls or len(gate)
        coverage = None if seen == 0 else min(10000, len(gate) * 10000 // seen)

        # time to detect: flagging verdict ts - flagged event ts
        ev_ts = {e["event_id"]: as_dt(e["ts"]) for e in events}
        ttd: list[int] = []
        for v in verdicts:
            if v["action"] not in FLAG_ACTIONS or not v.get("event_id"):
                continue
            ts = ev_ts.get(v["event_id"]) or self._event_ts(v["event_id"])
            if ts is not None:
                ttd.append(max(0, _ms(as_dt(v["ts"]) - ts)))

        judges = [v for v in verdicts if v["tier"] >= 1 and v.get("role") in JUDGE_ROLES]
        t2 = [v for v in verdicts if v["tier"] == 2 and v.get("role") == "primary"]
        disagree = sum(1 for v in t2 if v["label"] == "tiers_disagree")
        grounded = [
            int(v["score_bp"])
            for v in verdicts
            if v["checker_id"] == "quality.groundedness" and isinstance(v.get("score_bp"), int)
        ]
        cases = [
            c
            for c in self.ctx.state.query("cases", {"agent_id": agent_id})
            if start <= as_dt(c["opened_at"]) < end
        ]
        tth: list[int] = []
        for c in cases:
            human = [
                e
                for e in self.ctx.tables.query("case_event", {"case_id": c["case_id"]})
                if e["actor_kind"] == "user"
            ]
            if human:
                first = min(as_dt(e["ts"]) for e in human)
                tth.append(max(0, int((first - as_dt(c["opened_at"])).total_seconds())))

        out: dict[str, Any] = {
            "events_seen": seen,
            "events_gated": len(gate),
            "coverage_bp": coverage,
            "ttd_ms": median(ttd) if ttd else None,
            "tth_s": median(tth) if tth else None,
            "catch_rate_bp": self.eval["catch_rate_bp"],
            "false_alarm_bp": self.eval["false_alarm_bp"],
            "chain_ok": chain_ok,
            "judge_verdicts": len(judges),
            "judge_disagree_bp": rate_bp(disagree, len(t2)),
            "groundedness_bp": median(grounded) if grounded else None,
            "cases_opened": len(cases),
            "blocks": sum(1 for e in gate if str(e.get("status")) in GATED_STATUS_DENIED),
            "llm_calls": sum(1 for e in events if e["event_type"] == "llm_call"),
            "judge_latency_ms": sum(int(v["latency_ms"] or 0) for v in judges),
        }
        # WP19: judge-vs-human agreement of the cases a reviewer closed that day.
        pairs = [
            p
            for p in agreement_pairs(self.ctx.tables, since=start, until=end)
            if p["agent_id"] == agent_id
        ]
        out["judge_human_pairs"] = len(pairs)
        out["judge_human_agree_bp"] = agree_bp(sum(1 for p in pairs if p["agrees"]), len(pairs))
        # Legacy float columns (same value / 10000), never recorded on the chain.
        for float_col, bp_col in (
            ("coverage", "coverage_bp"),
            ("catch_rate", "catch_rate_bp"),
            ("false_alarm_rate", "false_alarm_bp"),
            ("groundedness", "groundedness_bp"),
        ):
            out[float_col] = None if out[bp_col] is None else out[bp_col] / 10000
        return out

    def _event_ts(self, event_id: str) -> datetime | None:
        rows = self.ctx.tables.query("agent_event", {"event_id": event_id}, limit=1)
        return as_dt(rows[0]["ts"]) if rows else None

    def run(self, now: datetime | None = None, days: Sequence[date] | None = None) -> int:
        """Recompute the rows of ``days`` (default: yesterday and today). Returns rows."""
        now = now or self.ctx.clock.now()
        today = now.astimezone(UTC).date()
        days = list(days) if days is not None else [today - timedelta(days=1), today]
        written = 0
        chain_cache: dict[str, bool | None] = {}
        for day in days:
            for agent_id in self.agents(day):
                lane = f"agent:{agent_id}"
                if lane not in chain_cache:
                    chk = check_lane(self.ctx, lane)
                    chain_cache[lane] = None if chk.last_seq is None and chk.ok else chk.ok
                values = self.compute(agent_id, day, chain_cache[lane])
                upsert_metric(self.ctx, day, agent_id, values)
                written += 1
                self._record(agent_id, day, values)
                self.agreement_case(agent_id, day, values)
        return written

    def agreement_case(self, agent_id: str, day: date, values: Mapping[str, Any]) -> str | None:
        """WP19: one medium case per agent and day when judge-human agreement drops.

        Advice to a human only: no gate call, no pause. Settings come from ``agreement_*``
        (set by the job; defaults match ``MRM_MIN_AGREEMENT_*``)."""
        pairs, bp = values.get("judge_human_pairs"), values.get("judge_human_agree_bp")
        if not pairs or bp is None or pairs < self.min_pairs or bp >= self.min_bp:
            return None
        key = f"agreement_case:{agent_id}:{day.isoformat()}"
        if get_state(self.ctx, MONITOR, key):
            return None
        # Through the case service (incident clock, case_link, evidence), never the gate.
        from supervisor.cases.service import CaseService

        cases = CaseService(
            self.ctx.state,
            self.ctx.tables,
            self.ctx.evidence,
            self.ctx.clock,
            holidays=self.holidays,
        )
        case = cases.open_from_monitor(
            agent_id=agent_id,
            monitor_id="judge_human_agreement",
            finding_ref=f"{agent_id}:{day.isoformat()}",
            severity="medium",
            summary=(
                f"Judge-human agreement for {agent_id} on {day.isoformat()} is {bp} bp over "
                f"{pairs} closed cases (minimum {self.min_bp} bp). Check re-validation "
                "triggers: python -m supervisor.judge.mrm triggers"
            ),
        )
        case_id = str(case["case_id"])
        put_state(self.ctx, MONITOR, key, {"case_id": case_id})
        return case_id

    def _record(self, agent_id: str, day: date, values: Mapping[str, Any]) -> None:
        """Integer columns on the chain, only when they changed since the last record."""
        ints = {k: v for k, v in values.items() if not isinstance(v, float)}
        digest = sha256_hex(ints)
        key = f"recorded:{agent_id}:{day.isoformat()}"
        prev = get_state(self.ctx, MONITOR, key)
        if prev and prev.get("digest") == digest:
            return
        self.ctx.evidence.record(
            "oversight_metric",
            f"oversight_metric:{day.isoformat()}:{agent_id}",
            {
                **ints,
                "agent_id": agent_id,
                "metric_date": day.isoformat(),
                "ts": format_ts(self.ctx.clock.now()),
            },  # fmt: skip
        )
        put_state(self.ctx, MONITOR, key, {"digest": digest})


def _ms(delta: timedelta) -> int:
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


__all__ = ["ChainCheck", "OversightMetrics", "check_lane", "load_eval_report"]
