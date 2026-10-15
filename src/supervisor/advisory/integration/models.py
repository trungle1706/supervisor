"""Integration report: pydantic models.

The report is deterministic. Every field except ``narrative`` is computed from the
onboarding stages (Inventory, profile, plan) and from the target source by static
analysis. The report has no timestamps and no absolute paths: file references are
repo-relative ``file:line`` strings. Numbers are integers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

RiskClass = Literal["money", "credit", "pii_export", "read_only"]
GateMode = Literal["decorator", "builder_hook", "already_gated", "manual"]
Dimension = Literal[
    "accuracy",
    "hallucination",
    "bias_fairness",
    "dependency_risk",
    "adversarial_security",
    "robustness",
]
DIMENSIONS: tuple[str, ...] = (
    "accuracy",
    "hallucination",
    "bias_fairness",
    "dependency_risk",
    "adversarial_security",
    "robustness",
)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ found


class FrameworkFound(_M):
    name: str
    evidence: str | None = None  # file:line


class LlmCallFound(_M):
    provider: str
    family: str
    model: str | None = None
    via: str
    at: str  # file:line


class ToolFound(_M):
    name: str
    risk_class: RiskClass
    risk_source: Literal["manifest", "heuristic"]
    side_effects: list[str] = Field(default_factory=list)
    amount_arg: str | None = None
    destination_arg: str | None = None
    defined_at: str | None = None  # file:line of the def (or class)
    shape: Literal["function", "nested_function", "method", "class", "unresolved"] = "unresolved"
    gated: bool = False  # the function already carries a Supervisor gate


class DataAccessFound(_M):
    kind: str
    direction: str
    target: str | None = None
    at: str


class PiiFound(_M):
    name: str
    at: str


class Found(_M):
    framework: FrameworkFound
    llm_calls: list[LlmCallFound] = Field(default_factory=list)
    tools: list[ToolFound] = Field(default_factory=list)
    data_access: list[DataAccessFound] = Field(default_factory=list)
    pii_fields: list[PiiFound] = Field(default_factory=list)
    tracing: list[str] = Field(default_factory=list)
    mcp_server: bool = False
    secrets_count: int = Field(ge=0, default=0)
    injection_refs: list[str] = Field(default_factory=list)  # file:line only, never the text


# ------------------------------------------------------------------ needed


class SemconvOp(_M):
    operation: str
    attributes: list[str]
    note: str = ""


class GateSite(_M):
    tool: str
    risk_class: RiskClass
    at: str | None = None  # file:line of the def, None when the function was not resolved
    decorator: str
    mode: GateMode
    note: str = ""


class McpProxyNeeded(_M):
    config_path: str
    command: list[str]
    note: str = ""


class CatalogueItem(_M):
    id: str
    name: str
    kind: str
    lane: str


class SettingNeeded(_M):
    key: str
    purpose: str
    example: str


class AssuranceItem(_M):
    dimension: Dimension
    reason: str


class ManualItem(_M):
    what: str
    at: str | None = None
    note: str


class Needed(_M):
    semconv: list[SemconvOp] = Field(default_factory=list)
    gate_sites: list[GateSite] = Field(default_factory=list)
    mcp_proxy: McpProxyNeeded | None = None
    policy_yaml: str = ""
    catalogue: list[CatalogueItem] = Field(default_factory=list)
    settings: list[SettingNeeded] = Field(default_factory=list)
    test_plan: list[AssuranceItem] = Field(default_factory=list)
    manual: list[ManualItem] = Field(default_factory=list)


# ------------------------------------------------------------------ readiness


class AreaScore(_M):
    id: str
    weight: int
    points: int
    inputs: dict[str, int]
    reason: str


class Readiness(_M):
    total: int = Field(ge=0, le=100)
    areas: list[AreaScore]


# ------------------------------------------------------------------ patches, narrative


class PatchRef(_M):
    path: str
    kind: str
    description: str
    file: str  # patches/NN-slug.patch


class Narrative(_M):
    text: str = ""
    source: Literal["mock", "llm", "none"] = "none"


class IntegrationReport(_M):
    schema_version: int = SCHEMA_VERSION
    agent_id: str
    name: str
    version: str
    framework: str
    found: Found
    needed: Needed
    readiness: Readiness
    patches: list[PatchRef] = Field(default_factory=list)
    narrative: Narrative = Field(default_factory=Narrative)
