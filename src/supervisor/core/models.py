"""Domain models. Field names match the columns in schema/model.yaml (a test checks it).

* Money: ``*_minor`` fields are strict ints of minor units (VND has no minor unit,
  so 1 VND = 1). Never floats.
* Timestamps: timezone-aware, normalised to UTC. Naive datetimes are rejected.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, model_validator


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware (UTC)")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]
MinorUnits = StrictInt
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

RiskTier = Literal["low", "medium", "high", "critical"]
AgentStatus = Literal["onboarding", "shadow", "enforced", "paused", "retired"]
GateState = Literal["RUNNING", "SHADOW", "PAUSED", "QUARANTINED", "RETIRED"]  # ADR D03
EventType = Literal["llm_call", "tool_call", "message", "handoff", "gate_decision"]
EventSource = Literal["otel", "otlp", "mlflow", "proxy"]
CaptureLevel = Literal["digest", "masked", "raw"]
RuleAction = Literal["log", "alert", "block", "pause"]
FailMode = Literal["open", "closed"]
Severity = Literal["low", "medium", "high", "critical"]
VerdictAction = Literal["allow", "log", "alert", "block", "pause", "open_case", "raise_severity"]
# WP8 console workflow: open -> triaged -> contained -> closed (older values kept).
CaseStatus = Literal["open", "triage", "triaged", "contained", "escalated", "resolved", "closed"]
ActorKind = Literal["user", "service_principal", "system"]


class Record(BaseModel):
    """Base for table rows. ``__table__`` names the table in schema/model.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    __table__: ClassVar[str] = ""

    def row(self) -> dict[str, Any]:
        return self.model_dump(mode="python")


class StateRecord(Record):
    """Mutable row: optimistic concurrency via ``row_version``."""

    row_version: int = 0
    updated_at: UtcDatetime | None = None


class Agent(StateRecord):
    __table__: ClassVar[str] = "agent"
    agent_id: str
    name: str
    owner_team: str
    owner_user: str
    business_owner: str | None = None
    risk_tier: RiskTier
    decision33_class: str | None = None
    host_type: str
    plug_point: str
    model_family: str
    status: AgentStatus = "onboarding"
    gate_state: GateState = "SHADOW"
    created_at: UtcDatetime


class AgentVersion(Record):
    __table__: ClassVar[str] = "agent_version"
    agent_id: str
    version: str
    code_ref: str | None = None
    prompt_hash: str | None = None
    tool_manifest_hash: str | None = None
    model_endpoint: str | None = None
    model_family: str
    deployed_at: UtcDatetime
    baseline_id: str | None = None


class AgentEvent(Record):
    __table__: ClassVar[str] = "agent_event"
    event_id: str
    ts: UtcDatetime
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    agent_id: str
    agent_version: str | None = None
    caller_agent_id: str | None = None
    event_type: EventType
    tool_name: str | None = None
    args_hash: str | None = None
    args_masked: str | None = None
    result_masked: str | None = None
    amount_minor: MinorUnits | None = None
    currency: Currency | None = None
    status: str | None = None
    latency_ms: int | None = None
    env: str
    classification: str | None = None
    source: EventSource
    capture_level: CaptureLevel = "masked"
    mask_version: str | None = None  # masker + HMAC key id (WP4); None at digest level
    latency_us: int | None = None  # WP22: gate decision latency, microseconds (null on old rows)
    # WP37 verdict contract v2 (null unless DETECTORS_ENABLED; a span event carries only the id)
    verdict_status: str | None = None
    correlation_id: str | None = None
    coverage_json: dict[str, Any] | None = None
    # WP27 session monitor (null unless a session id was sent or the monitor is on)
    session_id: str | None = None
    session_source: str | None = None
    session_json: dict[str, Any] | None = None


class Rule(StateRecord):
    __table__: ClassVar[str] = "rule"
    rule_id: str
    version: int
    agent_scope: str
    expression: dict[str, Any]
    action: RuleAction
    fail_mode: FailMode
    severity: Severity
    regulation_ref: str | None = None
    owner: str
    approved_by_1: str | None = None
    approved_by_2: str | None = None
    git_sha: str | None = None
    policy_hash: str
    effective_from: UtcDatetime
    effective_to: UtcDatetime | None = None


class Verdict(Record):
    """Tier 0 = deterministic rule; Tier 1/2 = judge (always advisory)."""

    __table__: ClassVar[str] = "verdict"
    verdict_id: str
    ts: UtcDatetime
    trace_id: str | None = None
    event_id: str | None = None
    agent_id: str
    tier: Literal[0, 1, 2]
    checker_id: str
    model_id: str | None = None
    model_family: str | None = None
    is_mock: bool = False
    advisory: bool
    score: float | None = None
    label: str
    action: VerdictAction
    latency_ms: int | None = None
    rule_id: str | None = None
    policy_hash: str | None = None
    rationale_masked: str | None = None
    # WP7 (additive): judge fields; integer basis points for the score.
    score_bp: int | None = Field(default=None, ge=0, le=10000)
    role: str | None = None
    region: str | None = None
    model_version: str | None = None
    mask_version: str | None = None
    # WP19 (additive): change control fields for judge verdicts.
    prompt_hash: str | None = None
    rubric_version: str | None = None
    # D05 (additive): where model_family came from: derived | declared-test-only | mock.
    family_source: str | None = None

    @model_validator(mode="after")
    def _judges_only_advise(self) -> Verdict:
        if self.tier > 0:
            if not self.advisory:
                raise ValueError("judge verdicts (tier 1/2) must be advisory")
            if self.action in ("block", "pause"):
                raise ValueError("judge verdicts cannot block or pause; only rules can")
        if self.is_mock and self.model_id is not None and "mock" not in self.model_id:
            raise ValueError("mock verdicts must carry 'mock' in model_id")
        return self


class Case(StateRecord):
    __table__: ClassVar[str] = "cases"
    case_id: str
    agent_id: str
    severity: Severity
    status: CaseStatus = "open"
    opened_at: UtcDatetime
    assignee: str | None = None
    itsm_ref: str | None = None
    regulation_refs: list[str] = Field(default_factory=list)
    summary: str
    report_due_at: UtcDatetime | None = None
    closed_at: UtcDatetime | None = None
    case_type: str | None = None  # WP7: rule | judge | drift | fairness | multiagent | manual
    # WP19 (additive): incident clock (Decree 142/2026 Art. 19), computed by cases/service.
    incident_detected_at: UtcDatetime | None = None
    urgency_class: Literal["urgent", "standard"] | None = None
    prelim_report_due_at: UtcDatetime | None = None
    formal_report_due_at: UtcDatetime | None = None
    prelim_report_sent_at: UtcDatetime | None = None
    formal_report_sent_at: UtcDatetime | None = None


class CaseEvent(Record):
    __table__: ClassVar[str] = "case_event"
    case_id: str
    seq: int
    ts: UtcDatetime
    actor: str
    actor_kind: ActorKind
    action: str
    comment_masked: str | None = None
    auth_method: str | None = None  # WP8: how the actor was identified


class Signoff(Record):
    __table__: ClassVar[str] = "signoff"
    signoff_id: str
    case_id: str
    reviewer_id: str
    decision: str
    reason: str
    ts: UtcDatetime
    auth_method: str


class ChainEntry(Record):
    __table__: ClassVar[str] = "chain_entry"
    lane: str
    seq: int = Field(ge=0)
    ts: UtcDatetime
    record_type: str
    record_ref: str
    payload_hash: Sha256Hex
    prev_hash: Sha256Hex
    entry_hash: Sha256Hex
    writer: str
    env: str


class Anchor(Record):
    __table__: ClassVar[str] = "anchor"
    anchor_id: str
    lane: str
    seq_from: int
    seq_to: int
    root_hash: Sha256Hex
    head_signature: str
    key_id: str
    anchored_at: UtcDatetime
    anchor_target: str
    receipt: str | None = None


class OversightMetric(StateRecord):
    __table__: ClassVar[str] = "oversight_metric"
    metric_date: date
    agent_id: str
    coverage: float | None = None
    ttd_ms: int | None = None
    tth_s: int | None = None
    catch_rate: float | None = None
    false_alarm_rate: float | None = None
    chain_ok: bool | None = None
    groundedness: float | None = None
    fairness_gap: float | None = None
    computed_at: UtcDatetime
    # WP7 (additive): integer columns, documented in docs/metrics.md.
    events_seen: int | None = None
    events_gated: int | None = None
    coverage_bp: int | None = None
    catch_rate_bp: int | None = None
    false_alarm_bp: int | None = None
    judge_verdicts: int | None = None
    judge_disagree_bp: int | None = None
    groundedness_bp: int | None = None
    fairness_gap_bp: int | None = None
    cases_opened: int | None = None
    blocks: int | None = None
    llm_calls: int | None = None
    judge_latency_ms: int | None = None
    # WP19 (additive): judge-vs-human agreement from sign-offs.
    judge_human_pairs: int | None = None
    judge_human_agree_bp: int | None = None
    # WP1b-B: {monitor: {status, code, reason, n}} for quality / fairness / drift / multiagent
    monitor_status: dict[str, Any] | None = None


ALL_RECORDS: tuple[type[Record], ...] = (
    Agent,
    AgentVersion,
    AgentEvent,
    Rule,
    Verdict,
    Case,
    CaseEvent,
    Signoff,
    ChainEntry,
    Anchor,
    OversightMetric,
)
