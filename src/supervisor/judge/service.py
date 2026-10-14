"""Judge service: agent_event trace window -> advisory Verdict rows + evidence records.

Protocol (ControlArena wording, analysis 07 section 1.5):

```
trace --> Tier 1 (100 %) --score >= T1 threshold, or sampled, or T1 unavailable--> Tier 2
                 |                                                                   |
                 +-- below threshold, not sampled --> action log                     v
      tiers agree, suspicious  --> open_case (severity medium, or high at >= 8000 bp)
      tiers agree, benign      --> log
      tiers disagree (one flags, one clears) --> defer to trusted: alert a human (max score)
      Tier 2 unavailable       --> defer to trusted: alert if Tier 1 flagged, else log
      both unavailable         --> log, label coverage_gap (the gap is in the evidence)
K suspicious outcomes for one agent inside the window --> extra verdict open_case (high);
further suspicious outcomes in the same window        --> raise_severity
```

"Trusted" is the deterministic layer plus the human reviewer: the judges cannot clear an
item on their own when they disagree. Judges never call the gateway and never pause or
block (only rules and humans do that). Every action is one of log | alert | open_case |
raise_severity, and ``Verdict`` rejects anything else for tier 1/2.

Challenger verdicts (role ``challenger``) are stored and compared, never acted on and
never counted by the protocol.

Writes: TableStore ``verdict`` (score column = bp / 10000 because the schema column is a
float; the chain never sees it) and EvidenceSink ``judge_verdict`` (integer bp only).
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from supervisor.config import Settings
from supervisor.core.models import Verdict
from supervisor.core.ports import Clock, EvidenceSink, Masker, StateStore, TableStore
from supervisor.judge import ADVISORY_ACTIONS
from supervisor.judge.masking import IdentityMasker, mask_version_of
from supervisor.judge.router import JudgeModel, JudgeRouter
from supervisor.judge.runner import JudgeCall, TierJudge
from supervisor.judge.tier1 import Tier1Judge
from supervisor.judge.tier2 import Tier2Judge

log = logging.getLogger("supervisor.judge")

EVIDENCE_TYPE = "judge_verdict"
PROTOCOL_CHECKER = "judge.protocol"
HIGH_BP = 8000


@dataclass(frozen=True)
class CaseRequest:
    """Advice to the case workflow (WP8). The judge never opens the gate or pauses."""

    kind: str  # open_case | raise_severity
    agent_id: str
    severity: str  # medium | high | critical (target severity)
    reason: str
    trace_ids: tuple[str, ...]
    verdict_ids: tuple[str, ...]


@dataclass
class TraceOutcome:
    trace_id: str
    agent_id: str
    t1: JudgeCall
    t2: JudgeCall | None = None
    challengers: list[JudgeCall] = field(default_factory=list)
    escalation_reason: str | None = None  # t1_flag | sample | t1_unavailable
    disagreement_bp: int | None = None
    disagree: bool = False
    final_bp: int | None = None
    final_label: str = ""
    final_action: str = "log"
    severity: str | None = None
    verdicts: list[Verdict] = field(default_factory=list)
    case_requests: list[CaseRequest] = field(default_factory=list)

    @property
    def suspicious(self) -> bool:
        return self.final_action in ("alert", "open_case")


def _get(ev: Mapping[str, Any] | BaseModel, name: str) -> Any:
    return getattr(ev, name, None) if isinstance(ev, BaseModel) else ev.get(name)


class JudgeService:
    def __init__(
        self,
        router: JudgeRouter,
        clock: Clock,
        *,
        masker: Masker | None = None,
        tables: TableStore | None = None,
        evidence: EvidenceSink | None = None,
        t1_threshold_bp: int = 5000,
        t2_threshold_bp: int = 5000,
        disagree_bp: int = 3000,
        k_suspicious: int = 3,
        window_s: int = 3600,
        timeout_s: float = 120.0,
        max_retries: int = 1,
        max_input_chars: int = 12000,
        judge_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        self.router = router
        self.clock = clock
        self.masker: Masker = masker or IdentityMasker()
        self.tables = tables
        self.evidence = evidence
        self.t1_threshold_bp = t1_threshold_bp
        self.t2_threshold_bp = t2_threshold_bp
        self.disagree_bp = disagree_bp
        self.k_suspicious = k_suspicious
        self.window = timedelta(seconds=window_s)
        kw = {
            "timeout_s": timeout_s,
            "max_retries": max_retries,
            "max_input_chars": max_input_chars,
            # The injection floor sends marked traces to Tier 2 and keeps them flagged there.
            "marker_floor_bp": max(t1_threshold_bp, t2_threshold_bp),
            **dict(judge_kwargs or {}),
        }
        self.t1 = Tier1Judge(router.t1, self.masker, **kw)
        self.t2 = Tier2Judge(router.t2, self.masker, **kw)
        self._challenger: TierJudge | None = None
        if router.challenger is not None:
            cls = Tier1Judge if router.challenger.tier == 1 else Tier2Judge
            self._challenger = cls(router.challenger, self.masker, **kw)
        self._flags: dict[str, deque[tuple[datetime, str]]] = {}
        self._case_opened: dict[str, datetime] = {}

    # -- construction -------------------------------------------------------------
    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        clock: Clock,
        *,
        masker: Masker | None = None,
        tables: TableStore | None = None,
        evidence: EvidenceSink | None = None,
        state: StateStore | None = None,
        force: bool = False,
    ) -> JudgeService | None:
        """None when ``JUDGE_ENABLED`` is off (the default) unless ``force``.

        Raises FamilyConflictError at startup when a judge shares an agent's family."""
        if not settings.judge_enabled and not force:
            return None
        router = JudgeRouter.from_settings(settings, state=state, tables=tables)
        return cls(
            router,
            clock,
            masker=masker,
            tables=tables,
            evidence=evidence,
            t1_threshold_bp=settings.judge_t1_threshold_bp,
            t2_threshold_bp=settings.judge_t2_threshold_bp,
            disagree_bp=settings.judge_disagree_bp,
            k_suspicious=settings.judge_k_suspicious,
            window_s=settings.judge_window_s,
            timeout_s=settings.judge_timeout_s,
            max_retries=settings.judge_max_retries,
            max_input_chars=settings.judge_max_input_chars,
        )

    # -- public -------------------------------------------------------------------
    def evaluate_window(
        self, events: Sequence[Mapping[str, Any] | BaseModel]
    ) -> list[TraceOutcome]:
        """Group a window of agent_event rows by trace_id and judge each trace."""
        groups: dict[str, list[Mapping[str, Any] | BaseModel]] = {}
        for ev in events:
            groups.setdefault(str(_get(ev, "trace_id")), []).append(ev)
        ordered = sorted(groups.values(), key=lambda g: min(_ts(e) for e in g))
        return [self.evaluate_trace(g) for g in ordered]

    def evaluate_trace_id(self, trace_id: str) -> TraceOutcome:
        if self.tables is None:
            raise ValueError("evaluate_trace_id needs a TableStore")
        rows = self.tables.query("agent_event", where={"trace_id": trace_id})
        if not rows:
            raise ValueError(f"no agent_event rows for trace {trace_id!r}")
        return self.evaluate_trace(rows)

    def evaluate_trace(self, events: Sequence[Mapping[str, Any] | BaseModel]) -> TraceOutcome:
        if not events:
            raise ValueError("empty trace")
        events = sorted(events, key=_ts)
        trace_id = str(_get(events[0], "trace_id"))
        agent_id = str(_get(events[0], "agent_id"))
        agent_version = _get(events[-1], "agent_version")
        last_event_id = _get(events[-1], "event_id")

        t1 = self.t1.judge(events, agent_id=agent_id, agent_version=agent_version)
        out = TraceOutcome(trace_id=trace_id, agent_id=agent_id, t1=t1)
        if t1.suspicion_bp is None:
            out.escalation_reason = "t1_unavailable"
        elif t1.flagged(self.t1_threshold_bp):
            out.escalation_reason = "t1_flag"
        elif self.router.t2_sampled(trace_id):
            out.escalation_reason = "sample"
        if out.escalation_reason:
            out.t2 = self.t2.judge(events, agent_id=agent_id, agent_version=agent_version)
        self._decide(out)

        out.verdicts.append(
            self._write(out.t1, out, last_event_id, action="log", primary=out.t2 is None)
        )
        if out.t2 is not None:
            v2 = self._write(out.t2, out, last_event_id, action=out.final_action, primary=True)
            out.verdicts.append(v2)
            if out.final_action == "open_case":
                out.case_requests.append(
                    CaseRequest(
                        "open_case",
                        agent_id,
                        out.severity or "medium",
                        f"Tier 1 and Tier 2 agree: {out.t2.label}",
                        (trace_id,),
                        (v2.verdict_id,),
                    )
                )
        # Challenger: same trace, stored with role=challenger, action log, never acted on.
        if self._challenger is not None:
            c_model = self.router.challenger_for(self._challenger.tier, trace_id)
            if c_model is not None:
                c = self._challenger.judge(events, agent_id=agent_id, agent_version=agent_version)
                out.challengers.append(c)
                ref = out.t1 if c.tier == 1 else out.t2
                out.verdicts.append(
                    self._write(c, out, last_event_id, action="log", primary=False, vs=ref)
                )
        if out.suspicious:
            self._protocol(out, _ts(events[-1]), last_event_id)
        return out

    # -- protocol -----------------------------------------------------------------
    def _decide(self, out: TraceOutcome) -> None:
        t1, t2 = out.t1, out.t2
        t1_flag = t1.flagged(self.t1_threshold_bp)
        if t2 is None:
            out.final_bp, out.final_label = t1.suspicion_bp, t1.label
            out.final_action = "log"  # not flagged and not sampled
            return
        if t2.suspicion_bp is None:
            gap = t1.suspicion_bp is None
            out.final_bp = t1.suspicion_bp
            out.final_label = "coverage_gap" if gap else "t2_unavailable"
            out.final_action = "alert" if t1_flag else "log"
            return
        t2_flag = t2.flagged(self.t2_threshold_bp)
        if t1.suspicion_bp is not None:
            out.disagreement_bp = abs(t1.suspicion_bp - t2.suspicion_bp)
            # Any flag/clear split is a disagreement: Tier 2 cannot clear Tier 1 alone.
            out.disagree = t1_flag != t2_flag
        if out.disagree:
            out.final_bp = max(t1.suspicion_bp or 0, t2.suspicion_bp)
            out.final_label, out.final_action = "tiers_disagree", "alert"
        elif t2_flag:
            out.final_bp, out.final_label, out.final_action = t2.suspicion_bp, t2.label, "open_case"
            out.severity = "high" if t2.suspicion_bp >= HIGH_BP else "medium"
        else:
            out.final_bp, out.final_label, out.final_action = t2.suspicion_bp, t2.label, "log"

    def _protocol(self, out: TraceOutcome, ts: datetime, event_id: Any) -> None:
        flags = self._flags.setdefault(out.agent_id, deque())
        flags.append((ts, out.trace_id))
        while flags and ts - flags[0][0] > self.window:
            flags.popleft()
        opened = self._case_opened.get(out.agent_id)
        if opened is not None and ts - opened > self.window:
            del self._case_opened[out.agent_id]
            opened = None
        if len(flags) < self.k_suspicious:
            return
        traces = tuple(t for _, t in flags)
        if opened is None:
            kind, severity = "open_case", "high"
            self._case_opened[out.agent_id] = ts
            window_s = int(self.window.total_seconds())
            reason = f"{len(flags)} suspicious judge outcomes within {window_s} s"
        else:
            kind, severity = "raise_severity", "critical"
            reason = f"suspicion continues after case opened ({len(flags)} in window)"
        v = self._write_protocol(out, kind, severity, reason, traces, event_id)
        out.verdicts.append(v)
        out.case_requests.append(
            CaseRequest(kind, out.agent_id, severity, reason, traces, (v.verdict_id,))
        )

    # -- persistence --------------------------------------------------------------
    def _write(
        self,
        call: JudgeCall,
        out: TraceOutcome,
        event_id: Any,
        *,
        action: str,
        primary: bool,
        vs: JudgeCall | None = None,
    ) -> Verdict:
        if action not in ADVISORY_ACTIONS:
            raise ValueError(f"judge action {action!r} is not advisory")
        v = Verdict(
            verdict_id=f"jv-{uuid.uuid4().hex}",
            ts=self.clock.now(),
            trace_id=out.trace_id,
            event_id=str(event_id) if event_id is not None else None,
            agent_id=out.agent_id,
            tier=call.tier,  # type: ignore[arg-type]
            checker_id=call.checker_id,
            model_id=call.model_id,
            model_family=call.model_family,
            is_mock=call.is_mock,
            advisory=True,
            score=None if call.suspicion_bp is None else call.suspicion_bp / 10000,
            label=call.label,
            action=action,  # type: ignore[arg-type]
            latency_ms=call.latency_ms,
            policy_hash=call.prompt_hash,
            rationale_masked=call.rationale_masked,
        )
        payload: dict[str, Any] = {
            "verdict_id": v.verdict_id,
            "ts": v.ts,
            "trace_id": out.trace_id,
            "event_id": v.event_id,
            "agent_id": out.agent_id,
            "tier": call.tier,
            "role": call.role,
            "checker_id": call.checker_id,
            "model_id": call.model_id,
            "model_family": call.model_family,
            "model_version": call.model_version,
            "region": call.region,
            "mask_version": call.mask_version,
            "prompt_hash": call.prompt_hash,
            "is_mock": call.is_mock,
            "advisory": True,
            "acted_on": call.role == "primary" and primary,
            "status": call.status,
            "suspicion_bp": call.suspicion_bp,
            "label": call.label,
            "action": action,
            "policy_refs": list(call.policy_refs),
            "evidence_spans": [dict(s) for s in call.evidence_spans],
            "rationale_masked": call.rationale_masked,
            "marker_hits": list(call.marker_hits),
            "floored": call.floored,
            "attempts": call.attempts,
            "latency_ms": call.latency_ms,
            "tokens_in_est": call.tokens_in_est,
            "tokens_out_est": call.tokens_out_est,
            "truncated_chars": call.truncated_chars,
            "dropped_spans": call.dropped_spans,
            "error": call.error,
        }
        if call.role == "primary" and call.tier == 2:
            payload.update(
                escalation_reason=out.escalation_reason,
                disagreement_bp=out.disagreement_bp,
                disagree=out.disagree,
                large_gap=(out.disagreement_bp or 0) >= self.disagree_bp,
                final_bp=out.final_bp,
                severity=out.severity,
            )
        elif call.role == "primary":
            payload["escalated"] = out.escalation_reason
        if vs is not None and vs.suspicion_bp is not None and call.suspicion_bp is not None:
            payload["challenger_vs_primary_bp"] = call.suspicion_bp - vs.suspicion_bp
        self._persist(v, payload)
        return v

    def _write_protocol(
        self,
        out: TraceOutcome,
        kind: str,
        severity: str,
        reason: str,
        traces: tuple[str, ...],
        event_id: Any,
    ) -> Verdict:
        top = out.t2 or out.t1
        v = Verdict(
            verdict_id=f"jv-{uuid.uuid4().hex}",
            ts=self.clock.now(),
            trace_id=out.trace_id,
            event_id=str(event_id) if event_id is not None else None,
            agent_id=out.agent_id,
            tier=2,
            checker_id=PROTOCOL_CHECKER,
            model_id=None,
            model_family=None,
            is_mock=self.router.is_mock,
            advisory=True,
            score=None,
            label="repeated_suspicion",
            action=kind,  # type: ignore[arg-type]
            policy_hash=top.prompt_hash,
            rationale_masked=reason,
        )
        payload = {
            "verdict_id": v.verdict_id,
            "ts": v.ts,
            "trace_id": out.trace_id,
            "agent_id": out.agent_id,
            "tier": 2,
            "role": "protocol",
            "checker_id": PROTOCOL_CHECKER,
            "is_mock": v.is_mock,
            "advisory": True,
            "acted_on": True,
            "label": v.label,
            "action": kind,
            "severity": severity,
            "k": self.k_suspicious,
            "window_s": int(self.window.total_seconds()),
            "trace_ids": list(traces),
            "mask_version": mask_version_of(self.masker),
            "rationale_masked": reason,
        }
        self._persist(v, payload)
        return v

    def _persist(self, v: Verdict, payload: Mapping[str, Any]) -> None:
        if self.tables is not None:
            self.tables.append("verdict", [v])
        if self.evidence is not None:
            self.evidence.record(EVIDENCE_TYPE, v.verdict_id, payload)


def _ts(ev: Mapping[str, Any] | BaseModel) -> datetime:
    ts = _get(ev, "ts")
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


__all__ = ["CaseRequest", "JudgeModel", "JudgeService", "TraceOutcome"]
