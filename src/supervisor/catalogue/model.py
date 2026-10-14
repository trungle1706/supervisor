"""Capability manifest schema (product spec component 10).

A capability is one monitoring check that Supervisor can switch on for an agent: a gate
rule family, a judge, a monitor, an ingest path or an evidence feature. Each capability
ships a YAML manifest in ``supervisor/catalogue/manifests/``. The Onboarding Agent's Plan
stage picks capabilities from the catalogue by the agent's tool risk classes and by the
features that Discover found (``requires``).

Manifests are untrusted data (a bank team can add its own): ``yaml.safe_load``, a size
limit, a strict schema (unknown keys fail), integers only for thresholds and costs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RiskClassT = Literal["money", "credit", "pii_export", "read_only"]
KindT = Literal["gate_rule", "judge", "monitor", "ingest", "evidence", "masking"]
LaneT = Literal["fast", "slow", "evidence"]
PlugPointT = Literal["gate_hook", "otel", "proxy_log", "mcp_proxy"]

# Features that Discover/Understand can report for an agent. A capability that
# ``requires`` a feature is off (with a reason) when the agent does not have it.
FEATURES: frozenset[str] = frozenset(
    {
        "amount_arg",  # a money/credit tool takes an integer ``*_minor`` amount
        "declared_limit",  # the agent manifest declares a per-call limit
        "declared_daily_limit",  # the agent manifest declares a daily limit
        "destination_arg",  # a money tool sends value to a payee / account / bank
        "customer_key",  # a money/credit tool has a customer or account key
        "record_fact",  # a read tool returns a completeness flag from a system of record
        "prior_read",  # a decision tool shares an id with a read tool
        "pii_tool",  # a tool exports personal data
        "free_text_output",  # the agent writes free text to a customer
        "llm",  # the agent calls a language model
        "otel_spans",  # the agent emits OpenTelemetry spans
        "decision_tool",  # the agent records credit decisions
    }
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CostEstimate(_Strict):
    """Integer cost per 1,000 agent events. Design estimates, not measurements."""

    llm_tokens_per_1k_events: int = Field(ge=0)
    compute_ms_per_1k_events: int = Field(ge=0)
    storage_bytes_per_1k_events: int = Field(ge=0)


class CapabilityManifest(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,40}$")
    version: int = Field(ge=1, default=1)
    name: str = Field(min_length=1, max_length=120)
    kind: KindT
    lane: LaneT
    description: str = Field(min_length=1, max_length=1000)
    signals_needed: list[str] = Field(min_length=1)
    checks: list[str] = Field(min_length=1)
    default_thresholds: dict[str, int] = Field(default_factory=dict)
    cost_estimate: CostEstimate
    applies_to: list[RiskClassT] = Field(min_length=1)
    requires: list[str] = Field(default_factory=list)
    plug_points: list[PlugPointT] = Field(min_length=1)
    regulation_refs: list[str] = Field(default_factory=list)
    owner: str = Field(min_length=1)
    module: str = Field(pattern=r"^[a-z_][a-z0-9_.]*$")
    always_on: bool = False
    can_block: bool = False  # only deterministic gate rules may block or pause

    @field_validator("default_thresholds")
    @classmethod
    def _ints_only(cls, v: dict[str, int]) -> dict[str, int]:
        for key, value in v.items():
            if type(value) is not int:
                raise ValueError(f"threshold {key}: integers only (bp or minor units)")
            if not key.replace("_", "").isalnum():
                raise ValueError(f"threshold name {key!r} must be an identifier")
        return v

    @field_validator("requires")
    @classmethod
    def _known_features(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - FEATURES)
        if unknown:
            raise ValueError(f"unknown required features: {unknown}")
        return v

    @model_validator(mode="after")
    def _only_rules_block(self) -> CapabilityManifest:
        """Judges and monitors advise only: they can never block (CLAUDE.md product rules)."""
        if self.can_block and self.kind != "gate_rule":
            raise ValueError(f"{self.id}: only gate_rule capabilities may block")
        return self
