"""Build a case file from case rows. Pure functions plus a loader and a chain recorder."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from supervisor.core.canonical import sha256_bytes_hex
from supervisor.core.models import (
    Case,
    CaseEvent,
    ChainEntry,
    Severity,
    Signoff,
    UtcDatetime,
    Verdict,
)
from supervisor.core.ports import EvidenceSink, StateStore, TableStore

GENERATOR_VERSION = "casefile/1"
REPORT_WINDOW = timedelta(hours=24)
REMEDIATION_WINDOW = timedelta(days=5)
_CLOSED_STATES = ("resolved", "closed")

_M = TypeVar("_M", bound=BaseModel)


class CaseFileError(ValueError):
    """The case file cannot be built or written."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TimelineItem(_Frozen):
    ts: UtcDatetime
    source: Literal["case_event", "verdict", "signoff"]
    actor: str
    actor_kind: str
    action: str
    text: str | None = None
    ref: str


class RuleBroken(_Frozen):
    rule_id: str | None
    verdict_id: str
    ts: UtcDatetime
    label: str
    action: str
    tier: int
    checker_id: str
    regulation_refs: list[str]


class JudgeFinding(_Frozen):
    verdict_id: str
    ts: UtcDatetime
    checker_id: str
    model_id: str | None
    is_mock: bool
    label: str
    score_bp: int | None
    rationale_masked: str | None


class SignoffItem(_Frozen):
    signoff_id: str
    reviewer_id: str
    decision: str
    reason: str
    ts: UtcDatetime
    auth_method: str


class SbvClocks(_Frozen):
    """SBV clocks. ``incident_detected_at`` is the earliest related verdict ts, else the
    case ``opened_at``. Report due = detected + 24 h; remediation due = detected + 5 days.

    OPEN QUESTION: the draft circular may mean 5 *working* days. We use calendar days
    (``remediation_basis``) until bank counsel confirms.
    """

    incident_detected_at: UtcDatetime
    report_due_at: UtcDatetime
    remediation_due_at: UtcDatetime
    remediation_basis: Literal["calendar_days"] = "calendar_days"
    report_overdue: bool
    remediation_overdue: bool


class ChainRef(_Frozen):
    lane: str
    seq_from: int
    seq_to: int
    head_hash: str
    entry_count: int


class CaseFile(_Frozen):
    case_id: str
    agent_id: str
    severity: Severity
    status: str
    summary: str
    opened_at: UtcDatetime
    closed_at: UtcDatetime | None
    assignee: str | None
    itsm_ref: str | None
    regulation_refs: list[str]
    decision33_classification: str
    sbv: SbvClocks
    # Draft SBV circular may mean working days; calendar days are earlier (conservative).
    remediation_due_basis: Literal["calendar_days"] = "calendar_days"
    timeline: list[TimelineItem]
    rules_broken: list[RuleBroken]
    judge_findings: list[JudgeFinding]
    signoffs: list[SignoffItem]
    chain: ChainRef | None
    mask_version: str
    generated_at: UtcDatetime
    generator_version: str = GENERATOR_VERSION


def score_to_bp(score: float | None) -> int | None:
    """Score in 0..1 to integer basis points 0..10000 (round-half-even, clamped)."""
    if score is None:
        return None
    bp = int((Decimal(repr(score)) * 10000).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    return max(0, min(10000, bp))


def _coerce(model: type[_M], item: Any) -> _M:
    return item if isinstance(item, model) else model.model_validate(item)


def case_chain_refs(
    case_id: str,
    case_events: Iterable[CaseEvent | Mapping[str, Any]],
    verdicts: Iterable[Verdict | Mapping[str, Any]],
    signoffs: Iterable[Signoff | Mapping[str, Any]],
) -> set[str]:
    """Chain ``record_ref`` values that belong to this case."""
    refs = {f"case:{case_id}"}
    refs |= {f"case_event:{case_id}:{_coerce(CaseEvent, e).seq}" for e in case_events}
    refs |= {f"verdict:{_coerce(Verdict, v).verdict_id}" for v in verdicts}
    refs |= {f"signoff:{_coerce(Signoff, s).signoff_id}" for s in signoffs}
    return refs


def _chain_ref(entries: list[ChainEntry]) -> ChainRef | None:
    if not entries:
        return None
    lanes = {e.lane for e in entries}
    if len(lanes) > 1:
        raise ValueError(f"chain entries span more than one lane: {sorted(lanes)}")
    head = max(entries, key=lambda e: e.seq)
    return ChainRef(
        lane=head.lane,
        seq_from=min(e.seq for e in entries),
        seq_to=head.seq,
        head_hash=head.entry_hash,
        entry_count=len(entries),
    )


def build_case_file(
    case: Case | Mapping[str, Any],
    case_events: Iterable[CaseEvent | Mapping[str, Any]],
    verdicts: Iterable[Verdict | Mapping[str, Any]],
    signoffs: Iterable[Signoff | Mapping[str, Any]],
    chain_entries: Iterable[ChainEntry | Mapping[str, Any]],
    *,
    decision33_text: str,
    mask_version: str,
    generated_at: datetime,
    rule_regulation_refs: Mapping[str, list[str]] | None = None,
) -> CaseFile:
    c = _coerce(Case, case)
    evs = [_coerce(CaseEvent, e) for e in case_events]
    vds = [_coerce(Verdict, v) for v in verdicts]
    sos = [_coerce(Signoff, s) for s in signoffs]
    chain = _chain_ref([_coerce(ChainEntry, e) for e in chain_entries])
    gen = generated_at.astimezone(UTC)
    rule_refs = rule_regulation_refs or {}

    detected = min((v.ts for v in vds), default=c.opened_at)
    report_due = detected + REPORT_WINDOW
    remed_due = detected + REMEDIATION_WINDOW
    open_case = c.status not in _CLOSED_STATES
    sbv = SbvClocks(
        incident_detected_at=detected,
        report_due_at=report_due,
        remediation_due_at=remed_due,
        report_overdue=open_case and gen > report_due,
        remediation_overdue=open_case and gen > remed_due,
    )

    timeline = [
        TimelineItem(
            ts=e.ts,
            source="case_event",
            actor=e.actor,
            actor_kind=e.actor_kind,
            action=e.action,
            text=e.comment_masked,
            ref=f"case_event:{c.case_id}:{e.seq}",
        )
        for e in evs
    ]
    timeline += [
        TimelineItem(
            ts=v.ts,
            source="verdict",
            actor=v.checker_id,
            actor_kind="system",
            action=f"{v.label}/{v.action}",
            text=v.rationale_masked,
            ref=f"verdict:{v.verdict_id}",
        )
        for v in vds
    ]
    timeline += [
        TimelineItem(
            ts=s.ts,
            source="signoff",
            actor=s.reviewer_id,
            actor_kind="user",
            action=s.decision,
            text=s.reason,
            ref=f"signoff:{s.signoff_id}",
        )
        for s in sos
    ]
    timeline.sort(key=lambda t: (t.ts, t.source, t.ref))

    # Tier 0 verdicts with action "allow" are passed checks, not broken rules.
    ordered = sorted(vds, key=lambda v: (v.ts, v.verdict_id))
    rules = [
        RuleBroken(
            rule_id=v.rule_id,
            verdict_id=v.verdict_id,
            ts=v.ts,
            label=v.label,
            action=v.action,
            tier=v.tier,
            checker_id=v.checker_id,
            regulation_refs=list(rule_refs.get(v.rule_id or "") or c.regulation_refs),
        )
        for v in ordered
        if v.tier == 0 and v.action != "allow"
    ]
    judges = [
        JudgeFinding(
            verdict_id=v.verdict_id,
            ts=v.ts,
            checker_id=v.checker_id,
            model_id=v.model_id,
            is_mock=v.is_mock,
            label=v.label,
            score_bp=score_to_bp(v.score),
            rationale_masked=v.rationale_masked,
        )
        for v in ordered
        if v.tier > 0
    ]
    signoff_items = [
        SignoffItem(
            signoff_id=s.signoff_id,
            reviewer_id=s.reviewer_id,
            decision=s.decision,
            reason=s.reason,
            ts=s.ts,
            auth_method=s.auth_method,
        )
        for s in sorted(sos, key=lambda s: (s.ts, s.signoff_id))
    ]
    return CaseFile(
        case_id=c.case_id,
        agent_id=c.agent_id,
        severity=c.severity,
        status=c.status,
        summary=c.summary,
        opened_at=c.opened_at,
        closed_at=c.closed_at,
        assignee=c.assignee,
        itsm_ref=c.itsm_ref,
        regulation_refs=list(c.regulation_refs),
        decision33_classification=decision33_text,
        sbv=sbv,
        timeline=timeline,
        rules_broken=rules,
        judge_findings=judges,
        signoffs=signoff_items,
        chain=chain,
        mask_version=mask_version,
        generated_at=gen,
    )


def load_case_inputs(
    tables: TableStore, state: StateStore, case_id: str, *, now: datetime | None = None
) -> dict[str, Any]:
    """Read everything a case file needs.

    Verdict selection heuristic: verdict.agent_id == case.agent_id and
    case.opened_at - 1 day <= verdict.ts <= (case.closed_at or now). Chain entries: lane
    ``agent:<agent_id>`` with record_ref in ``case_chain_refs``.
    """
    row = state.get("cases", {"case_id": case_id})
    if row is None:
        raise CaseFileError(f"case not found: {case_id}")
    case = _coerce(Case, dict(row))
    events = [
        _coerce(CaseEvent, r)
        for r in tables.query("case_event", {"case_id": case_id}, order_by=("seq",))
    ]
    signoffs = [_coerce(Signoff, r) for r in tables.query("signoff", {"case_id": case_id})]
    lo = case.opened_at - timedelta(days=1)
    hi = case.closed_at or (now or datetime.now(UTC))
    all_verdicts = (
        _coerce(Verdict, r) for r in tables.query("verdict", {"agent_id": case.agent_id})
    )
    verdicts = [v for v in all_verdicts if lo <= v.ts <= hi]
    refs = case_chain_refs(case_id, events, verdicts, signoffs)
    lane_rows = tables.query("chain_entry", {"lane": f"agent:{case.agent_id}"}, order_by=("seq",))
    chain = [e for e in (_coerce(ChainEntry, r) for r in lane_rows) if e.record_ref in refs]
    return {
        "case": case,
        "case_events": events,
        "verdicts": verdicts,
        "signoffs": signoffs,
        "chain_entries": chain,
    }


def record_case_file(sink: EvidenceSink, case_file: CaseFile, fmt: str, data: bytes) -> str:
    """Record the file sha256 in the evidence chain. Returns the entry hash."""
    payload = {
        "agent_id": case_file.agent_id,
        "case_id": case_file.case_id,
        "format": fmt,
        "sha256": sha256_bytes_hex(data),
        "size_bytes": len(data),
        "mask_version": case_file.mask_version,
        "generator_version": case_file.generator_version,
    }
    return sink.record("case_file", f"case_file:{case_file.case_id}:{fmt}", payload)


def write_case_file(
    cf: CaseFile,
    out_dir: Path,
    fmt: Literal["json", "html", "pdf"],
    sink: EvidenceSink | None = None,
    font_path: Path | None = None,
) -> tuple[Path, str | None]:
    """Render and write ``<case_id>.<ext>``; never overwrite. Returns (path, notice)."""
    from supervisor.evidence.casefile.render_html import render_html
    from supervisor.evidence.casefile.render_json import render_json
    from supervisor.evidence.casefile.render_pdf import render_pdf

    notice: str | None = None
    out_fmt: str = fmt
    if fmt == "json":
        data = render_json(cf)
    elif fmt == "html":
        data = render_html(cf)
    else:
        res = render_pdf(cf, font_path=font_path)
        data, out_fmt, notice = res.data, res.fmt, res.notice
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{cf.case_id}.{out_fmt}"
    try:
        with path.open("xb") as fh:
            fh.write(data)
    except FileExistsError:
        raise CaseFileError(f"refusing to overwrite existing file: {path}") from None
    if sink is not None:
        try:
            record_case_file(sink, cf, out_fmt, data)
        except BaseException:
            path.unlink(missing_ok=True)  # not in the chain -> do not keep it; retry is possible
            raise
    return path, notice
