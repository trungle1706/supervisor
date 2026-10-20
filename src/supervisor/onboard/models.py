"""Pydantic outputs of the six Onboard stages.

Rules: every claim carries file:line evidence (``Evidence``); numbers are integers
(basis points 0..10000, integer minor units, integer counts); text that came from the
repo is scrubbed before it is stored here.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from supervisor.onboard.injection import neutralize

RiskClassT = Literal["money", "credit", "pii_export", "read_only"]
TierT = Literal["low", "medium", "high", "critical"]

DECISION33_CAVEAT = (
    "Decision 33 (banking entries) applies to high-value electronic transactions executed "
    '"without human inspection, approval or control before execution" and to credit '
    'scoring or loan decisions made "without independent approval by credit officers". '
    "A Supervisor pause is a safety control after the agent acts; it is NOT human "
    "inspection, approval or control before execution and does not move an agent out of "
    "the high-risk list. The agent's own workflow needs the pre-execution approval step; "
    "Supervisor produces evidence that the step exists and works. Bank counsel confirms "
    "the classification against the official Appendix text."
)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(_M):
    """A pointer into the scanned repo: file, 1-based line, scrubbed quote, line hash."""

    file: str
    line: int = Field(ge=1)
    quote: str = Field(max_length=240)
    line_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def at(cls, file: str, line: int, text: str) -> Evidence:
        """Repo text that looks like a prompt injection is withheld from the quote (the line
        hash still identifies the line)."""
        clean = text.strip()
        return cls(
            file=file,
            line=line,
            quote=neutralize(clean)[:240],
            line_sha256=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
        )

    def ref(self) -> str:
        return f"{self.file}:{self.line}"


class Claim(_M):
    claim: str = Field(min_length=1, max_length=400)
    category: Literal[
        "purpose",
        "capability",
        "reversibility",
        "personal_data",
        "weak_spot",
        "decision33",
        "risk_tier",
        "secret",
    ]
    evidence: list[Evidence] = Field(min_length=1)
    confidence_bp: int = Field(ge=0, le=10000)
    source: Literal["deterministic", "llm"] = "deterministic"


# ------------------------------------------------------------------ Discover


class ToolInfo(_M):
    name: str
    risk_class: RiskClassT
    risk_source: Literal["manifest", "heuristic"]
    description: str = ""
    args: dict[str, str] = Field(default_factory=dict)
    approved: bool = True
    approval_note: str | None = None
    definition: Evidence | None = None
    manifest_entry: Evidence | None = None
    approval_evidence: Evidence | None = None
    returns_fields: list[str] = Field(default_factory=list)
    mutates: list[str] = Field(default_factory=list)
    amount_arg: str | None = None
    destination_arg: str | None = None
    key_args: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)  # WP16: writes found in the body


class PromptInfo(_M):
    kind: Literal["system", "task", "template"]
    excerpt: str = Field(max_length=240)
    sha256: str
    evidence: Evidence


class Endpoint(_M):
    name: str
    family: str | None = None
    source: Literal["manifest", "code", "workspace"]
    evidence: Evidence | None = None


class NamedRef(_M):
    name: str
    detail: str = ""
    source: Literal["manifest", "code", "workspace"] = "code"
    evidence: Evidence | None = None


class TableRef(_M):
    name: str
    direction: Literal["read", "write"]
    source: Literal["code", "workspace"]
    evidence: Evidence | None = None


class LlmCallSite(_M):
    """WP16: a line where a model request is made or a chat model is bound."""

    provider: str
    family: str
    model: str | None = None
    via: str
    evidence: Evidence


class DataAccess(_M):
    """WP16: a read or write of data outside the process (db, http, bank API, file)."""

    kind: Literal["db", "http", "bank_api", "file"]
    direction: Literal["read", "write"]
    target: str | None = None
    evidence: Evidence


class LimitInfo(_M):
    key: str
    value: int
    tool: str | None
    period: Literal["per_call", "daily"]
    evidence: Evidence
    code_refs: list[Evidence] = Field(default_factory=list)

    @property
    def enforced_in_code(self) -> bool:
        return bool(self.code_refs)


class Note(_M):
    text: str = Field(max_length=240)
    kind: Literal["not_enforced", "not_approved", "todo", "human_step", "other"]
    evidence: Evidence


class Inventory(_M):
    agent_id: str
    name: str
    version: str
    owner_team: str
    owner_user: str
    description: str = ""
    declared_risk_tier: TierT | None = None
    model_family: str = "unknown"
    model_id: str | None = None
    model_family_source: Literal["manifest", "code", "unknown"] = "unknown"
    host_type: str = "python"
    plug_point: str = "gate_hook"
    manifest_file: str | None = None
    revision: str | None = None
    files: list[str] = Field(default_factory=list)
    entrypoints: list[NamedRef] = Field(default_factory=list)
    tools: list[ToolInfo] = Field(default_factory=list)
    prompts: list[PromptInfo] = Field(default_factory=list)
    model_endpoints: list[Endpoint] = Field(default_factory=list)
    mcp_servers: list[NamedRef] = Field(default_factory=list)
    tables: list[TableRef] = Field(default_factory=list)
    traces: list[NamedRef] = Field(default_factory=list)
    limits: list[LimitInfo] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)
    constants: dict[str, list[str]] = Field(default_factory=dict)
    pii_fields: dict[str, Evidence] = Field(default_factory=dict)
    human_approval_refs: list[Evidence] = Field(default_factory=list)
    secret_refs: list[Evidence] = Field(default_factory=list)
    skipped: dict[str, str] = Field(default_factory=dict)
    scrub: dict[str, Any] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)
    apps: list[str] = Field(default_factory=list)
    # WP16 code facts (static analysis, see onboard/codefacts.py)
    framework: str = "unknown"
    framework_evidence: Evidence | None = None
    llm_calls: list[LlmCallSite] = Field(default_factory=list)
    data_access: list[DataAccess] = Field(default_factory=list)
    tracing: list[str] = Field(default_factory=list)
    pii_identifiers: dict[str, Evidence] = Field(default_factory=dict)
    injection_refs: list[Evidence] = Field(default_factory=list)
    # WP1b-B: places where an MCP tool list is read at run time (tools not enumerable)
    dynamic_tool_sources: list[Evidence] = Field(default_factory=list)

    def tool(self, name: str) -> ToolInfo | None:
        return next((t for t in self.tools if t.name == name), None)

    @property
    def risk_classes(self) -> list[str]:
        return sorted({t.risk_class for t in self.tools})


# ------------------------------------------------------------------ Understand


class Decision33Entry(_M):
    entry: Literal["transactions", "credit"]
    triggered: bool
    reason: str
    evidence: list[Evidence] = Field(min_length=1)


class Decision33(_M):
    classification: Literal["high_risk", "not_high_risk"]
    by_default: bool = True  # proposal; counsel confirms
    entries: list[Decision33Entry] = Field(default_factory=list)
    human_gate_in_code: bool
    wording_caveat: str = DECISION33_CAVEAT


class LlmUse(_M):
    used: bool
    model_id: str
    is_mock: bool
    note: str
    claims_proposed: int = 0
    claims_kept: int = 0
    claims_dropped: int = 0


AutonomyT = Literal["L0", "L1", "L2", "L3"]


class AgentProfile(_M):
    agent_id: str
    version: str
    name: str
    owner_team: str
    purpose: Claim
    capabilities: list[Claim]
    reversibility: list[Claim]
    personal_data: list[Claim]
    weak_spots: list[Claim]
    decision33: Decision33
    declared_risk_tier: TierT | None
    proposed_risk_tier: TierT
    risk_tier_reason: Claim
    tool_risk_classes: dict[str, RiskClassT]
    features: list[str]
    llm: LlmUse
    needs_human_confirmation: bool = True
    # WP16: L0 no tools, L1 read-only, L2 every side effect behind a human approval step in
    # code, L3 a side effect without one.
    autonomy: AutonomyT | None = None
    autonomy_reason: str = ""

    def all_claims(self) -> list[Claim]:
        return [
            self.purpose,
            *self.capabilities,
            *self.reversibility,
            *self.personal_data,
            *self.weak_spots,
            self.risk_tier_reason,
        ]


# ------------------------------------------------------------------ Plan


class PlannedRule(_M):
    rule_id: str
    capability_id: str
    spec: dict[str, Any]
    evidence: list[Evidence] = Field(default_factory=list)


class CapabilityChoice(_M):
    id: str
    name: str
    kind: str
    lane: str
    status: Literal["on", "off"]
    reason: str | None = None


class JudgePlan(_M):
    id: str
    sample_bp: int = Field(ge=0, le=10000)
    threshold_bp: int = Field(ge=0, le=10000)
    family_must_differ_from: str


class CostPlan(_M):
    events_per_day_assumed: int = Field(ge=0)
    llm_tokens_per_day: int = Field(ge=0)
    compute_ms_per_day: int = Field(ge=0)
    storage_bytes_per_day: int = Field(ge=0)


class MonitoringPlan(_M):
    agent_id: str
    capabilities: list[CapabilityChoice]
    signals: list[str]
    thresholds: dict[str, int]
    judges: list[JudgePlan]
    slices: list[str]
    sampling: dict[str, int]
    cost: CostPlan
    rules: list[PlannedRule]
    coverage: list[dict[str, Any]]

    @field_validator("thresholds", "sampling")
    @classmethod
    def _ints(cls, v: dict[str, int]) -> dict[str, int]:
        for k, x in v.items():
            if type(x) is not int:
                raise ValueError(f"{k}: integers only")
        return v

    @property
    def on_ids(self) -> list[str]:
        return [c.id for c in self.capabilities if c.status == "on"]


class PlaybookEntry(_M):
    trigger: str
    kind: Literal["rule", "capability"]
    action: Literal["log", "alert", "block", "pause"]
    severity: Literal["low", "medium", "high", "critical"]
    first_responder: str
    sla_minutes: int = Field(ge=1)
    steps: list[str]


class RemediationPlaybook(_M):
    agent_id: str
    entries: list[PlaybookEntry]
    resume_rule: str = "Resume needs two people: the agent owner and a reviewer."


# ------------------------------------------------------------------ Instrument


class InstrumentResult(_M):
    mode: Literal["clone", "copy"]
    work_repo: str
    branch: str
    base_ref: str
    base_sha: str
    commit_sha: str
    files_changed: list[str]
    codemod_applied: bool
    codemod_note: str
    warnings: list[str] = Field(default_factory=list)
    policy_hash: str
    merged: bool = False  # never True: the agent never merges


# ------------------------------------------------------------------ Launch


class CaseResult(_M):
    case_id: str
    expected: str
    vector: str
    calls: int
    would_stop: bool
    rules: list[str]
    rule_errors: list[str] = Field(default_factory=list)
    outcome: Literal["caught", "missed", "false_alarm", "clean", "info"]


class RuleSwitch(_M):
    rule_id: str
    action: str
    true_positives: int
    false_positives: int
    recommendation: Literal["enforce", "stay_shadow"]
    reason: str


class IntegrationCheck(_M):
    name: str
    ok: bool
    detail: str


class LaunchReport(_M):
    agent_id: str
    policy_hash: str
    mode: Literal["shadow"] = "shadow"
    llm_is_mock: bool
    cases_total: int
    cases_applicable: int
    rule_expected: int
    rule_caught: int
    catch_rate_bp: int | None
    benign_cases: int
    benign_flagged: int
    false_alarm_bp: int | None
    judge_or_drift_cases: int
    text_only_cases: int
    min_catch_rate_bp: int
    max_false_alarm_bp: int
    cases: list[CaseResult]
    baseline: dict[str, Any]
    rule_switches: list[RuleSwitch]
    integration_checks: list[IntegrationCheck]
    go: bool
    reasons: list[str]
    # WP17 assurance packs (off by default: ASSURANCE_LAUNCH_ENABLED). Compact rows, integers only.
    assurance_enabled: bool = False
    assurance: list[dict[str, Any]] = Field(default_factory=list)
    assurance_reasons: list[str] = Field(default_factory=list)
    # "none" | "mixed" | "all": mock pack results in the run (gates.assurance_mock_state)
    assurance_mock: str = "none"


# ------------------------------------------------------------------ Operate


class HandoverRecord(_M):
    agent_id: str
    run_id: str
    onboarded_by: str
    owner_team: str
    owner_user: str
    gate_state_after_merge: Literal["SHADOW"] = "SHADOW"
    enforce_first: list[str]
    keep_in_shadow: list[str]
    capabilities_on: list[str]
    decision33_classification: str
    proposed_risk_tier: str
    branch: str
    commit_sha: str
    go: bool
    artefacts: dict[str, str]  # name -> sha256
    next_steps: list[str]
