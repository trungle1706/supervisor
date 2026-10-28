"""assessment_report_v1: the fixed output of every assessment agent (WP-F1).

No floats anywhere: counts and scores are integers, confidence is an enum. A finding with verdict
``pass`` or ``fail`` and no evidence is invalid. ``harness_trace`` holds integers and pointers
only (what each harness component did in the run); it never holds text from a document.
"""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from supervisor.factory import caps

DimensionId = Literal[
    "model",
    "data_governance",
    "cybersecurity",
    "legal_compliance",
    "ethics",
    "third_party",
    "supply_chain",
    "reputation",
]
Verdict = Literal["pass", "fail", "not_applicable", "question"]
Confidence = Literal["low", "medium", "high"]
EvidenceKind = Literal["fact", "document", "regkb", "pack", "system_record"]
StopReason = Literal["single_pass", "all_answered", "evaluator_done", "max_iterations", "budget"]
Count = StrictInt


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(_M):
    kind: EvidenceKind
    ref: str = Field(min_length=1, max_length=caps.REF_MAX)
    file: str | None = Field(default=None, max_length=caps.REF_MAX)
    line: StrictInt | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _line_needs_file(self) -> Evidence:
        if self.line is not None and not self.file:
            raise ValueError("line needs file")
        return self


class Finding(_M):
    finding_id: str = Field(pattern=caps.SLUG_RE.pattern)
    checklist_id: str = Field(pattern=caps.SLUG_RE.pattern)
    verdict: Verdict
    evidence: list[Evidence] = Field(default_factory=list, max_length=caps.EVIDENCE_MAX)
    rationale: str = Field(max_length=caps.RATIONALE_MAX)
    confidence: Confidence

    @model_validator(mode="after")
    def _evidence_rule(self) -> Finding:
        if self.verdict in ("pass", "fail") and not self.evidence:
            raise ValueError(
                f"evidence: a finding with verdict {self.verdict} needs at least one evidence "
                f"item (finding {self.finding_id})"
            )
        return self


class Summary(_M):
    total: Count = Field(ge=0)
    passed: Count = Field(ge=0)
    failed: Count = Field(ge=0)
    not_applicable: Count = Field(ge=0)
    questions: Count = Field(ge=0)


class TraceSystemPrompt(_M):
    preamble_version: Count = Field(ge=1)
    instructions_tokens: Count = Field(ge=0)


class TraceContext(_M):
    sources_loaded: Count = Field(ge=0)
    tokens_used: Count = Field(ge=0)
    budget_tokens: Count = Field(ge=0)
    source_refs: list[str] = Field(default_factory=list, max_length=200)


class TraceMemory(_M):
    reads: Count = Field(ge=0)
    writes: Count = Field(ge=0)
    rows_stored: Count = Field(ge=0)


class TraceHitl(_M):
    stop_points_fired: Count = Field(ge=0)
    approvals_requested: Count = Field(ge=0)
    tool_calls_blocked: Count = Field(ge=0)


class TraceVerification(_M):
    findings_checked: Count = Field(ge=0)
    findings_rejected: Count = Field(ge=0)
    judge_calls: Count = Field(ge=0)


class TraceIteration(_M):
    iteration: Count = Field(ge=1)
    evaluator_score: Count | None = Field(default=None, ge=0, le=caps.MIN_SCORE_MAX)
    reason_ref: str = Field(max_length=caps.REF_MAX)  # pointer to the logged evaluator reason
    tokens_used: Count = Field(ge=0)


class TraceLoop(_M):
    iterations: Count = Field(ge=1, le=caps.LOOP_MAX_ITERATIONS)
    stopped_by: StopReason
    tokens_used: Count = Field(ge=0)
    per_iteration: list[TraceIteration] = Field(default_factory=list, max_length=8)


class HarnessTrace(_M):
    system_prompt: TraceSystemPrompt
    context: TraceContext
    memory: TraceMemory
    hitl: TraceHitl
    verification: TraceVerification
    loop: TraceLoop


class AssessmentReportV1(_M):
    report_id: str = Field(pattern=caps.SLUG_RE.pattern)
    agent_id: str = Field(pattern=caps.ID_RE.pattern)
    agent_version: str = Field(min_length=1, max_length=32)
    system_id: str = Field(min_length=1, max_length=200)
    dimension_id: DimensionId
    findings: list[Finding] = Field(max_length=caps.FINDINGS_MAX)
    summary: Summary
    model_id: str = Field(min_length=1, max_length=120)
    harness_trace: HarnessTrace
    created_at: str

    @field_validator("created_at")
    @classmethod
    def _timestamp(cls, v: str) -> str:
        if not caps.TIMESTAMP_RE.match(v):
            raise ValueError("must be an RFC 3339 UTC timestamp such as 2026-10-28T09:00:00Z")
        return v

    @model_validator(mode="after")
    def _summary_matches(self) -> AssessmentReportV1:
        n = {v: sum(1 for f in self.findings if f.verdict == v) for v in caps.VERDICTS}
        want = Summary(
            total=len(self.findings),
            passed=n["pass"],
            failed=n["fail"],
            not_applicable=n["not_applicable"],
            questions=n["question"],
        )
        if self.summary != want:
            raise ValueError(
                f"summary: counts do not match the findings (expected {want.model_dump()})"
            )
        ids = [f.finding_id for f in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("findings: finding_id must be unique")
        return self
