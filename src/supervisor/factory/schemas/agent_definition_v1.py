"""agent_definition_v1: the locked definition of an assessment agent (WP-F1).

The platform locks the schema keys, the output schema, the tool registry reference, the
mandatory guardians and the harness caps (``supervisor.factory.caps``). A team edits the
description, policy references, checklist, evidence rules, instructions, tool selection inside
the allow-list of its group, the editable part of each harness component, and the eval pack.

Every message names the field (the ``loc`` of the error, or a ``field:`` prefix in the text).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from supervisor.factory import caps

Dimension = Literal[
    "model",
    "data_governance",
    "cybersecurity",
    "legal_compliance",
    "ethics",
    "third_party",
    "supply_chain",
    "reputation",
]
Group = Literal["model_risk", "data", "cyber", "legal", "third_party", "ethics", "platform"]
EvidenceKind = Literal["fact", "document", "regkb", "pack", "system_record"]
ToolMode = Literal["read", "propose"]
_INLINE_KEYS = {"name", "description", "schema", "parameters", "function", "code", "script", "url"}
_OVERRIDE = re.compile("|".join(caps.OVERRIDE_PATTERNS), re.IGNORECASE)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------- body


class PolicyRef(_M):
    doc_id: str = Field(pattern=caps.SLUG_RE.pattern)
    source: Literal["regkb", "internal"] = "regkb"
    version: StrictInt = Field(ge=1)
    sections: list[str] = Field(default_factory=list, max_length=caps.SECTIONS_MAX)


class ChecklistItem(_M):
    id: str = Field(pattern=caps.SLUG_RE.pattern)
    question: str = Field(min_length=1, max_length=caps.QUESTION_MAX)
    evidence: list[EvidenceKind] = Field(min_length=1)
    severity: Literal["low", "medium", "high"]
    pass_rule: str = Field(min_length=1, max_length=caps.PASS_RULE_MAX)


class EvidenceRules(_M):
    allowed_sources: list[EvidenceKind] = Field(min_length=1)
    must_cite: bool = True
    max_age_days: StrictInt = Field(default=365, ge=1, le=caps.MAX_AGE_DAYS_MAX)

    @field_validator("must_cite")
    @classmethod
    def _locked(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("must_cite is locked to true by the platform")
        return v


class ToolRef(_M):
    tool_id: str = Field(pattern=caps.SLUG_RE.pattern)
    scope: str | None = Field(default=None, max_length=caps.REF_MAX)
    mode: ToolMode = "read"

    @model_validator(mode="before")
    @classmethod
    def _no_inline_tool(cls, data: Any) -> Any:
        if isinstance(data, dict):
            inline = sorted(str(k) for k in set(data) & _INLINE_KEYS)
            if inline or "tool_id" not in data:
                raise ValueError(
                    "inline tool definitions are refused"
                    + (f" (keys: {', '.join(inline)})" if inline else "")
                    + "; reference a tool_id from config/factory_tools.yaml"
                )
        return data


class OutputSchema(_M):
    type: str

    @field_validator("type")
    @classmethod
    def _locked(cls, v: str) -> str:
        if v != caps.OUTPUT_SCHEMA:
            raise ValueError(f"output_schema.type must be {caps.OUTPUT_SCHEMA}, got {v!r}")
        return v


class Approval(_M):
    by: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=60)
    at: str
    note: str = Field(default="", max_length=300)

    @field_validator("at")
    @classmethod
    def _ts(cls, v: str) -> str:
        if not caps.TIMESTAMP_RE.match(v):
            raise ValueError("must be an RFC 3339 UTC timestamp such as 2026-10-28T09:00:00Z")
        return v


class Lifecycle(_M):
    state: Literal["draft", "tested", "approved", "live", "retired"]
    version: str = Field(pattern=r"^\d{1,4}\.\d{1,4}(\.\d{1,4})?$")
    approvals: list[Approval] = Field(default_factory=list, max_length=20)


# ---------------------------------------------------------------------------- harness


class SystemPromptH(_M):
    preamble: str = caps.PREAMBLE

    @field_validator("preamble")
    @classmethod
    def _locked(cls, v: str) -> str:
        if v != caps.PREAMBLE:
            raise ValueError(f"preamble is locked to {caps.PREAMBLE}")
        return v


class ContextH(_M):
    sources: list[
        Literal["facts_v1", "pack_results", "system_record", "regkb_rows", "document_sections"]
    ] = Field(default_factory=lambda: list(caps.CONTEXT_SOURCES), min_length=1)
    budget_tokens: StrictInt = Field(
        default=caps.CONTEXT_BUDGET_DEFAULT,
        ge=caps.CONTEXT_BUDGET_MIN,
        le=caps.CONTEXT_BUDGET_MAX,
    )
    max_document_chars: StrictInt = Field(
        default=caps.MAX_DOCUMENT_CHARS_DEFAULT, ge=0, le=caps.MAX_DOCUMENT_CHARS_MAX
    )
    progressive: StrictBool = True

    @field_validator("sources")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("sources must not repeat a source")
        return v

    @field_validator("progressive")
    @classmethod
    def _locked(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("progressive loading is locked to true by the platform")
        return v


class MemoryH(_M):
    run: Literal["scratchpad"] = "scratchpad"
    system_memory: StrictBool = False
    retention_days: StrictInt | None = Field(default=None, ge=1, le=caps.MEMORY_RETENTION_MAX_DAYS)
    fields: list[Literal["prior_verdicts", "open_questions", "waivers"]] = Field(
        default_factory=list
    )
    cross_run: str = "off"

    @field_validator("cross_run")
    @classmethod
    def _off(cls, v: str) -> str:
        if v != "off":
            raise ValueError("cross_run memory must be off (it stays off in phase 12B)")
        return v

    @model_validator(mode="after")
    def _system_memory(self) -> MemoryH:
        if self.system_memory:
            if self.retention_days is None:
                raise ValueError(
                    f"retention_days: required when system_memory is on (1 to "
                    f"{caps.MEMORY_RETENTION_MAX_DAYS})"
                )
            if not self.fields:
                raise ValueError("fields: at least one field is required when system_memory is on")
        elif self.retention_days is not None or self.fields:
            raise ValueError("retention_days and fields: only allowed when system_memory is on")
        if len(self.fields) != len(set(self.fields)):
            raise ValueError("fields: must not repeat a field")
        return self


class ApprovalPoint(_M):
    kind: Literal["checklist", "verdict"]
    ref: str = Field(min_length=1, max_length=64)


class Permission(_M):
    tool_id: str = Field(pattern=caps.SLUG_RE.pattern)
    mode: ToolMode


class HitlH(_M):
    approval_points: list[ApprovalPoint] = Field(
        default_factory=list, max_length=caps.APPROVAL_POINTS_MAX
    )
    permissions: list[Permission] = Field(default_factory=list, max_length=caps.TOOLS_MAX)


class VerificationH(_M):
    verifier: Literal["rules", "rules+judge"] = "rules"
    validators: list[
        Literal["evidence_kind_allowed", "evidence_age", "rationale_length", "no_personal_data"]
    ] = Field(default_factory=list)


class LoopH(_M):
    mode: Literal["single_pass", "loop"] = "single_pass"
    max_iterations: StrictInt = Field(default=1, ge=1, le=caps.LOOP_MAX_ITERATIONS)
    stop_when: list[Literal["all_answered", "evaluator_done"]] = Field(
        default_factory=lambda: ["all_answered"], min_length=1
    )
    loop_evaluator: Literal["rules", "judge"] = "rules"
    min_score: StrictInt | None = Field(default=None, ge=0, le=caps.MIN_SCORE_MAX)
    budget_tokens: StrictInt = Field(
        default=caps.LOOP_BUDGET_DEFAULT, ge=caps.CONTEXT_BUDGET_MIN, le=caps.LOOP_BUDGET_MAX
    )

    @model_validator(mode="after")
    def _modes(self) -> LoopH:
        if self.mode == "single_pass":
            if self.max_iterations != 1:
                raise ValueError("max_iterations: must be 1 when mode is single_pass")
            if self.loop_evaluator != "rules" or self.min_score is not None:
                raise ValueError(
                    "loop_evaluator and min_score: only used when mode is loop "
                    "(single_pass keeps rules and no min_score)"
                )
        elif self.loop_evaluator == "judge" and self.min_score is None:
            raise ValueError("min_score: required when loop_evaluator is judge (integer 0 to 100)")
        elif self.loop_evaluator == "rules" and self.min_score is not None:
            raise ValueError("min_score: only used when loop_evaluator is judge")
        if "evaluator_done" in self.stop_when and self.mode == "single_pass":
            raise ValueError("stop_when: evaluator_done needs mode loop")
        return self


class Harness(_M):
    system_prompt: SystemPromptH = Field(default_factory=SystemPromptH)
    context: ContextH = Field(default_factory=ContextH)
    memory: MemoryH = Field(default_factory=MemoryH)
    hitl: HitlH = Field(default_factory=HitlH)
    verification: VerificationH = Field(default_factory=VerificationH)
    loop: LoopH = Field(default_factory=LoopH)


# ---------------------------------------------------------------------------- the definition


class AgentDefinitionV1(_M):
    schema_version: str
    id: str = Field(pattern=caps.ID_RE.pattern)
    name: str = Field(min_length=1, max_length=caps.NAME_MAX)
    description: str = Field(min_length=1, max_length=caps.DESCRIPTION_MAX)
    owner_group: Group
    dimension_id: Dimension
    policy_refs: list[PolicyRef] = Field(default_factory=list, max_length=caps.POLICY_REFS_MAX)
    checklist: list[ChecklistItem] = Field(min_length=1, max_length=caps.CHECKLIST_MAX)
    evidence_rules: EvidenceRules
    tools: list[ToolRef] = Field(default_factory=list, max_length=caps.TOOLS_MAX)
    instructions: str = ""
    harness: Harness = Field(default_factory=Harness)
    output_schema: OutputSchema
    guardians: list[str] = Field(max_length=caps.GUARDIANS_MAX)
    eval_pack: str = Field(pattern=caps.SLUG_RE.pattern)
    lifecycle: Lifecycle

    @field_validator("schema_version")
    @classmethod
    def _version(cls, v: str) -> str:
        if v != caps.SCHEMA_VERSION:
            raise ValueError(f"must be {caps.SCHEMA_VERSION!r}, got {v!r}")
        return v

    @field_validator("instructions")
    @classmethod
    def _lint(cls, v: str) -> str:
        tokens = caps.estimate_tokens(v)
        if tokens > caps.INSTRUCTIONS_MAX_TOKENS:
            raise ValueError(
                f"too long: about {tokens} tokens, the cap is {caps.INSTRUCTIONS_MAX_TOKENS}"
            )
        if any(ord(c) < 32 and c not in "\n\t\r" for c in v):
            raise ValueError("lint: control characters are not allowed")
        m = _OVERRIDE.search(v)
        if m:
            raise ValueError(f"lint: text that overrides the platform preamble ({m.group(0)!r})")
        return v

    @field_validator("guardians")
    @classmethod
    def _mandatory(cls, v: list[str]) -> list[str]:
        missing = [g for g in caps.MANDATORY_GUARDIANS if g not in v]
        if missing:
            raise ValueError(f"missing mandatory guardian(s): {', '.join(missing)}")
        if len(v) != len(set(v)):
            raise ValueError("must not repeat a guardian")
        bad = [g for g in v if not caps.SLUG_RE.match(g)]
        if bad:
            raise ValueError(f"not a guardian id: {', '.join(bad)}")
        return v

    @model_validator(mode="after")
    def _cross(self) -> AgentDefinitionV1:
        ids = [c.id for c in self.checklist]
        if len(ids) != len(set(ids)):
            raise ValueError("checklist: ids must be unique")
        tool_ids = [t.tool_id for t in self.tools]
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("tools: a tool_id may appear once")
        by_id = {t.tool_id: t for t in self.tools}
        for p in self.harness.hitl.permissions:
            tool = by_id.get(p.tool_id)
            if tool is None:
                raise ValueError(f"harness.hitl.permissions: {p.tool_id} is not in tools")
            if p.mode == "propose" and tool.mode == "read":
                raise ValueError(
                    f"harness.hitl.permissions: {p.tool_id} is read in tools; "
                    "a permission cannot widen it to propose"
                )
        for ap in self.harness.hitl.approval_points:
            if ap.kind == "checklist" and ap.ref not in ids:
                raise ValueError(
                    f"harness.hitl.approval_points: checklist item {ap.ref} does not exist"
                )
            if ap.kind == "verdict" and ap.ref not in caps.VERDICTS:
                raise ValueError(
                    f"harness.hitl.approval_points: {ap.ref} is not a verdict "
                    f"({', '.join(caps.VERDICTS)})"
                )
        allowed = set(self.evidence_rules.allowed_sources)
        for c in self.checklist:
            extra = sorted(set(c.evidence) - allowed)
            if extra:
                raise ValueError(
                    f"checklist: item {c.id} needs evidence kind(s) {', '.join(extra)} "
                    "that evidence_rules.allowed_sources does not allow"
                )
        src = set(self.harness.context.sources)
        if "document" in allowed and "document_sections" not in src:
            raise ValueError("harness.context.sources: document evidence needs document_sections")
        return self
