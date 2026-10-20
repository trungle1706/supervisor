"""Cursor sweeps over new ``agent_event`` rows: judge sweep and quality sweep.

* ``JudgeSweep`` (``JUDGE_ENABLED``): runs the judge service (WP5) over events that are
  older than ``settle_s`` and newer than the cursor, grouped by trace. The judge's
  ``CaseRequest`` advice becomes a case (``case_type`` judge) or raises the severity of
  the agent's open judge case. Judges never block or pause (CLAUDE.md).
* ``QualitySweep`` (``QUALITY_ENABLED``): sampled groundedness / guideline scores of
  customer replies (advisory verdicts only).

Gate decisions are skipped: they repeat the tool calls at digest level. A trace that
crosses the cursor is judged in two parts (v0 limit, see BACKLOG).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.monitors.bindings import BindingResolver
from supervisor.monitors.common import (
    MonitorContext,
    as_dt,
    find_open_case,
    get_state,
    open_case,
    put_state,
    raise_severity,
    read_range,
)
from supervisor.monitors.quality import CHECKER_GROUNDED
from supervisor.monitors.status import (
    NO_DATA,
    NOT_APPLICABLE,
    OK,
    count_events,
    count_verdicts,
    day_bounds,
    known_agents,
    observed_tools,
    set_status,
)

log = logging.getLogger("supervisor.monitors.sweeps")

FIRST_RUN_LOOKBACK_S = 86400
OBSERVE_DAYS = 7  # tool names seen in this many days feed the derived bindings


@dataclass
class SweepResult:
    events: int = 0
    traces: int = 0
    cases_opened: list[str] = field(default_factory=list)
    cases_raised: list[str] = field(default_factory=list)


def _window(
    ctx: MonitorContext, monitor: str, now: datetime, settle_s: int
) -> tuple[datetime, datetime]:
    state = get_state(ctx, monitor, "cursor")
    cursor = (
        as_dt(state["ts"])
        if state and state.get("ts")
        else now - timedelta(seconds=FIRST_RUN_LOOKBACK_S)
    )
    return cursor, max(cursor, now - timedelta(seconds=settle_s))


def _agent_events(ctx: MonitorContext, start: datetime, end: datetime) -> list[dict[str, Any]]:
    if end <= start:
        return []
    rows = read_range(ctx, "agent_event", start, end)
    return [r for r in rows if r["event_type"] != "gate_decision"]


class JudgeSweep:
    MONITOR = "judge_sweep"
    ACTOR = "judge:protocol"

    def __init__(self, ctx: MonitorContext, service: Any, *, settle_s: int = 60) -> None:
        self.ctx, self.service, self.settle_s = ctx, service, settle_s

    def run(self, now: datetime | None = None) -> SweepResult:
        now = now or self.ctx.clock.now()
        start, end = _window(self.ctx, self.MONITOR, now, self.settle_s)
        events = _agent_events(self.ctx, start, end)
        res = SweepResult(events=len(events))
        if events:
            outcomes = self.service.evaluate_window(events)
            res.traces = len(outcomes)
            for out in outcomes:
                for cr in out.case_requests:
                    self._handle(cr, res)
        put_state(self.ctx, self.MONITOR, "cursor", {"ts": format_ts(end)})
        return res

    def _handle(self, cr: Any, res: SweepResult) -> None:
        existing = find_open_case(self.ctx, cr.agent_id, "judge")
        if existing is not None:
            if raise_severity(
                self.ctx, existing["case_id"], cr.severity, actor=self.ACTOR, reason=cr.reason
            ):
                res.cases_raised.append(existing["case_id"])
            return
        res.cases_opened.append(
            open_case(
                self.ctx,
                agent_id=cr.agent_id,
                severity=cr.severity,
                case_type="judge",
                summary=f"Judge (advisory): {cr.reason}",
                actor=self.ACTOR,
                evidence_payload={
                    "monitor": "judge_sweep",
                    "advice": cr.kind,
                    "trace_ids": list(cr.trace_ids),
                    "verdict_ids": list(cr.verdict_ids),
                },
            )
        )


class QualitySweep:
    MONITOR = "quality_sweep"

    def __init__(
        self,
        ctx: MonitorContext,
        scorer: Any,
        *,
        settle_s: int = 60,
        resolver: Any | None = None,
        sample_bp: int | None = None,
    ) -> None:
        """``resolver``: a ``BindingResolver``. With it the scorer reads each agent's bound
        reply tools and every agent gets a quality status (WP1b-B); without it the legacy
        ``reply`` tool is scored and no status is written."""
        self.ctx, self.scorer, self.settle_s = ctx, scorer, settle_s
        self.resolver = resolver
        self.sample_bp = sample_bp
        self._observed: dict[str, set[str]] = {}
        if resolver is not None:
            scorer.reply_binding = self._reply_binding

    def _reply_binding(self, agent_id: str) -> tuple[Sequence[str], str]:
        q = self.resolver.resolve(agent_id, self._observed.get(agent_id, ())).quality
        return q.reply_tools, q.text_arg

    def run(self, now: datetime | None = None) -> SweepResult:
        now = now or self.ctx.clock.now()
        if self.resolver is not None:
            self._observed = observed_tools(self.ctx, now - timedelta(days=OBSERVE_DAYS))
        start, end = _window(self.ctx, self.MONITOR, now, self.settle_s)
        events: Sequence[dict[str, Any]] = _agent_events(self.ctx, start, end)
        res = SweepResult(events=len(events))
        res.traces = len(self.scorer.sweep(events)) if events else 0
        put_state(self.ctx, self.MONITOR, "cursor", {"ts": format_ts(end)})
        if self.resolver is not None:
            self._write_status(now)
        return res

    def _write_status(self, now: datetime) -> None:
        day = now.astimezone(UTC).date()
        d0, d1 = day_bounds(day)
        for agent_id in known_agents(self.ctx, self.resolver, self._observed):
            q = self.resolver.resolve(agent_id, self._observed.get(agent_id, ())).quality
            if not q.bound:
                set_status(
                    self.ctx,
                    day,
                    agent_id,
                    "quality",
                    NOT_APPLICABLE,
                    code="no_binding",
                    reason=q.gap or "",
                )
                continue
            scored = count_verdicts(self.ctx, agent_id, CHECKER_GROUNDED, d0, d1)
            if scored:
                set_status(self.ctx, day, agent_id, "quality", OK, n=scored)
                continue
            replies = count_events(
                self.ctx, agent_id, d0, d1, event_types=("tool_call",), tools=q.reply_tools
            )
            if replies == 0:
                set_status(
                    self.ctx,
                    day,
                    agent_id,
                    "quality",
                    NO_DATA,
                    code="no_reply_calls",
                    reason=f"no call of {', '.join(q.reply_tools)} on {day.isoformat()}",
                )
            else:
                rate = f" (sample {self.sample_bp} bp)" if self.sample_bp is not None else ""
                set_status(
                    self.ctx,
                    day,
                    agent_id,
                    "quality",
                    NO_DATA,
                    code="not_sampled",
                    reason=f"{replies} reply call(s) today, none scored yet{rate}",
                    n=replies,
                )


def build_judge_sweep(ctx: MonitorContext, settings: Any) -> JudgeSweep | None:
    """None when JUDGE_ENABLED is off. Raises FamilyConflictError on a family clash."""
    from supervisor.adapters.factory import make_masker
    from supervisor.judge.service import JudgeService

    service = JudgeService.from_settings(
        settings,
        ctx.clock,
        masker=make_masker(settings),
        tables=ctx.tables,
        evidence=ctx.evidence,
        state=ctx.state,
    )
    if service is None:
        return None
    return JudgeSweep(ctx, service, settle_s=settings.judge_sweep_settle_s)


def build_quality_sweep(ctx: MonitorContext, settings: Any) -> QualitySweep | None:
    """None when QUALITY_ENABLED is off. Uses the Tier 1 judge model (family-checked)."""
    if not settings.quality_enabled:
        return None
    from supervisor.adapters.factory import make_judge_chat_model, make_masker
    from supervisor.judge.router import load_manifest_families
    from supervisor.monitors.quality import QualityScorer

    families: dict[str, str] = dict(load_manifest_families())
    for row in ctx.state.query("agent"):
        families.setdefault(str(row["agent_id"]), str(row.get("model_family") or ""))
    scorer = QualityScorer(
        make_judge_chat_model(settings, "t1"),
        ctx.clock,
        masker=make_masker(settings),
        tables=ctx.tables,
        evidence=ctx.evidence,
        agent_families=families,
        sample_bp=settings.quality_sample_bp,
        timeout_s=settings.judge_timeout_s,
        region=settings.judge_region,
    )
    return QualitySweep(
        ctx,
        scorer,
        settle_s=settings.judge_sweep_settle_s,
        resolver=BindingResolver.from_settings(settings),
        sample_bp=settings.quality_sample_bp,
    )


__all__ = [
    "JudgeSweep",
    "QualitySweep",
    "SweepResult",
    "build_judge_sweep",
    "build_quality_sweep",
]
