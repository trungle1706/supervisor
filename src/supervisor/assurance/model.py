"""WP17 assurance eval packs: the contract every pack, runner and target follows.

An *eval pack* is one well-known test (TruthfulQA, BBQ, OWASP LLM probes, an SBOM check,
...) wired into Supervisor. A pack has a YAML manifest (``packs/<id>.yaml``, schema
:class:`EvalPack`) and a runner (``runners/<module>.py``) that implements
:class:`PackRunner`. The framework (``engine.py``) applies the manifest thresholds to the
runner's integer metrics; runners never decide pass or fail themselves.

Three targets (``TargetKind``):

* ``agent``  - a supervised agent driven through the launch sandbox (:class:`AgentTarget`);
* ``traces`` - recorded ``agent_event`` rows of one agent (:class:`TraceTarget`);
* ``judge``  - the judge itself, for its validation (:class:`JudgeTarget`).

Rules (CLAUDE.md): integers only in metrics (basis points 0..10000, counts, ms);
a pack with no data reports ``skip``, never a pass; mocks are labelled ``is_mock``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from supervisor.assurance.taxonomy import (
    ATLAS,
    FINVAULT,
    OWASP_AGENTIC,
    OWASP_LLM,
    REGKB_DUTIES,
)

DimensionT = Literal[
    "accuracy",
    "hallucination",
    "bias_fairness",
    "dependency",
    "security",
    "robustness",
]
TargetKind = Literal["agent", "traces", "judge"]
DataModeT = Literal["synthetic", "bank_supplied_path", "vendored_sample"]
LicenceT = Literal[
    "MIT",
    "Apache-2.0",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "CC-BY-SA-3.0",
    "BSD-3-Clause",
    "own",  # our own implementation / own synthetic data (Apache-2.0 like the repo)
]
DirectionT = Literal["higher_better", "lower_better"]
UnitT = Literal["bp", "count", "ms"]
LaunchGateT = Literal["required", "advisory", "off"]
StatusT = Literal["ok", "warn", "fail", "skip", "error"]
MetricStatusT = Literal["pass", "warn", "fail", "na"]

CAPABILITIES = frozenset({"chat", "tools", "planned", "decide", "deps", "models", "tool_manifest"})
SHARE_ALIKE = frozenset({"CC-BY-SA-4.0", "CC-BY-SA-3.0"})
VENDORABLE = frozenset({"MIT", "Apache-2.0", "CC-BY-4.0", "BSD-3-Clause", "own"})

_ID = r"^[a-z][a-z0-9_]{2,48}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(_Strict):
    """Where the test comes from (paper / dataset / standard)."""

    name: str = Field(min_length=1, max_length=200)
    url: str = Field(pattern=r"^https://")
    paper: str | None = None  # citation or arXiv URL
    licence_url: str | None = Field(default=None, pattern=r"^https://")
    licence_verified_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str | None = None


class MetricSpec(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    direction: DirectionT
    unit: UnitT
    description: str = Field(min_length=1, max_length=600)  # formula, as in the paper


class Threshold(_Strict):
    """``go`` / ``no_go`` per metric (integers).

    higher_better: value >= go -> pass; value < no_go -> fail; between -> warn.
    lower_better:  value <= go -> pass; value > no_go -> fail; between -> warn.
    Defaults are ILLUSTRATIVE until the bank sets its own (docs/assurance.md)."""

    metric: str
    go: int
    no_go: int

    @field_validator("go", "no_go", mode="before")
    @classmethod
    def _int_only(cls, v: Any) -> int:
        if type(v) is not int:
            raise ValueError("thresholds are integers only (bp, counts or ms)")
        return v


class MapsTo(_Strict):
    regkb_duties: list[str] = Field(default_factory=list)
    owasp_llm: list[str] = Field(default_factory=list)
    owasp_agentic: list[str] = Field(default_factory=list)
    atlas: list[str] = Field(default_factory=list)
    finvault: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _known_ids(self) -> MapsTo:
        bad: list[str] = []
        for name, values, vocab in (
            ("regkb_duties", self.regkb_duties, REGKB_DUTIES),
            ("owasp_llm", self.owasp_llm, OWASP_LLM),
            ("owasp_agentic", self.owasp_agentic, OWASP_AGENTIC),
            ("atlas", self.atlas, ATLAS),
            ("finvault", self.finvault, FINVAULT),
        ):
            bad += [f"{name}:{v}" for v in values if v not in vocab]
        if bad:
            raise ValueError(f"unknown taxonomy ids: {bad}")
        if not self.regkb_duties:
            raise ValueError("maps_to.regkb_duties needs at least one duty")
        return self


class EvalPack(_Strict):
    """One manifest in ``src/supervisor/assurance/packs/<id>.yaml``."""

    id: str = Field(pattern=_ID)
    version: int = Field(ge=1, default=1)
    dimension: DimensionT
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1500)
    source: Source
    licence: LicenceT
    data_modes: list[DataModeT] = Field(min_length=1)
    targets: list[TargetKind] = Field(min_length=1)
    runner: str = Field(pattern=r"^supervisor\.assurance\.runners\.[a-z_][a-z0-9_.]*:[A-Za-z_]\w*$")
    metrics: list[MetricSpec] = Field(min_length=1)
    thresholds: list[Threshold] = Field(default_factory=list)
    maps_to: MapsTo
    launch_gate: LaunchGateT = "advisory"
    judge_gate: bool = False  # True: judge enablement requires this pack to pass
    importer: str | None = None  # bank_supplied_path: expected files + format (docs)
    min_items: int = Field(ge=1, default=10)  # fewer usable items -> skip, never pass
    # An agent target that lacks any of these capabilities gets a structured "not applicable"
    # skip from the engine (never a NO-GO). Only for packs that do not apply to some agents
    # (credit decisions); behavioural packs leave it empty so a missing capability stays a NO-GO.
    requires_capabilities: list[str] = Field(default_factory=list)
    owner: str = "Supervisor Assurance"

    @model_validator(mode="after")
    def _consistent(self) -> EvalPack:
        names = [m.name for m in self.metrics]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.id}: duplicate metric names")
        for t in self.thresholds:
            if t.metric not in names:
                raise ValueError(f"{self.id}: threshold for unknown metric {t.metric!r}")
            spec = next(m for m in self.metrics if m.name == t.metric)
            if spec.direction == "higher_better" and t.go < t.no_go:
                raise ValueError(f"{self.id}.{t.metric}: higher_better needs go >= no_go")
            if spec.direction == "lower_better" and t.go > t.no_go:
                raise ValueError(f"{self.id}.{t.metric}: lower_better needs go <= no_go")
        if not self.thresholds:
            raise ValueError(f"{self.id}: a pack needs at least one threshold")
        bad_caps = [c for c in self.requires_capabilities if c not in CAPABILITIES]
        if bad_caps:
            raise ValueError(f"{self.id}: unknown capabilities {bad_caps}")
        if "synthetic" not in self.data_modes:
            raise ValueError(f"{self.id}: every pack needs a synthetic offline data path")
        if self.licence in SHARE_ALIKE and "vendored_sample" in self.data_modes:
            raise ValueError(f"{self.id}: CC-BY-SA data is never vendored (importer only)")
        if "bank_supplied_path" in self.data_modes and not self.importer:
            raise ValueError(f"{self.id}: bank_supplied_path needs an importer description")
        if self.licence not in ("own",) and not (
            self.source.licence_url and self.source.licence_verified_on
        ):
            raise ValueError(f"{self.id}: third-party licence needs licence_url + verified date")
        if self.judge_gate and "judge" not in self.targets:
            raise ValueError(f"{self.id}: judge_gate needs target 'judge'")
        return self

    def threshold(self, metric: str) -> Threshold | None:
        return next((t for t in self.thresholds if t.metric == metric), None)

    def metric(self, name: str) -> MetricSpec:
        return next(m for m in self.metrics if m.name == name)


# --------------------------------------------------------------------------- results


@dataclass
class RunnerOutput:
    """What a runner returns. ``metrics`` values are int (or None when not computable).

    ``status`` is ``ok`` (metrics computed) or ``skip`` (with ``skip_reason``): no data,
    fewer than ``min_items`` usable items, or the target lacks a needed capability.
    ``details`` holds small JSON-safe extras (str / int / bool / lists / dicts; no floats,
    no PII; e.g. per-slice counts, failing item ids)."""

    status: Literal["ok", "skip"]
    metrics: dict[str, int | None] = field(default_factory=dict)
    n_items: int = 0
    data_mode: DataModeT = "synthetic"
    dataset_id: str = ""
    dataset_sha256: str = ""
    is_mock: bool = False
    skip_reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    # Thresholded metrics that are None because they do not apply to this target (kind or
    # capability). A thresholded None metric NOT listed here is "unmeasured": pack -> skip.
    not_applicable_metrics: set[str] = field(default_factory=set)

    @classmethod
    def skip(cls, reason: str, **kw: Any) -> RunnerOutput:
        return cls(status="skip", skip_reason=reason, **kw)


@dataclass
class PackResult:
    """One pack x one target. Rows in ``eval_result``; ``assurance_result`` evidence."""

    run_id: str
    pack_id: str
    pack_version: int
    dimension: str
    target_kind: TargetKind
    target_id: str
    status: StatusT
    metrics: dict[str, int | None]
    metric_status: dict[str, MetricStatusT]
    reasons: list[str]
    n_items: int
    data_mode: str
    dataset_id: str
    dataset_sha256: str
    is_mock: bool
    launch_gate: LaunchGateT
    judge_gate: bool
    started_at: datetime
    finished_at: datetime
    details: dict[str, Any] = field(default_factory=dict)
    evidence_hash: str = ""


# --------------------------------------------------------------------------- targets


@dataclass
class TargetReply:
    """One answer from an agent target. ``refused`` = the agent declined the request."""

    text: str
    refused: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # {tool, args, status}
    gate_would_stop: list[str] = field(default_factory=list)  # rule ids (SHADOW gate)
    trace_id: str = ""
    is_mock: bool = False


@dataclass
class ModelDependency:
    """One model an agent (or the judge) depends on."""

    role: str  # agent | judge_t1 | judge_t2 | challenger
    vendor: str
    family: str
    model_id: str
    version_pinned: bool
    hosting_region: str | None
    is_mock: bool


@runtime_checkable
class AgentTarget(Protocol):
    """A supervised agent in the launch sandbox (gate in SHADOW, synthetic world).

    ``capabilities`` names the optional features: ``chat`` (respond), ``tools``
    (run_with_tool_result), ``planned`` (run_planned), ``decide`` (credit-style decision),
    ``deps`` (dependency
    files), ``models``, ``tool_manifest``. A runner that needs a missing capability
    returns ``RunnerOutput.skip``."""

    kind: Literal["agent"]
    target_id: str
    is_mock: bool
    capabilities: frozenset[str]

    def respond(self, prompt: str, *, context: Sequence[str] = (), sample: int = 0) -> TargetReply:
        """Answer ``prompt`` (Vietnamese or English) given optional context passages.
        ``sample`` > 0 asks for an independent stochastic sample (SelfCheckGPT)."""
        ...

    def run_with_tool_result(
        self, prompt: str, tool: str, injected_result: Mapping[str, Any]
    ) -> TargetReply:
        """Run a task where the first call to ``tool`` returns ``injected_result``
        (indirect injection, AgentDojo / InjecAgent style)."""
        ...

    def run_planned(self, prompt: str, planned_calls: Sequence[Mapping[str, Any]]) -> TargetReply:
        """Worst case: the agent is already compromised and makes ``planned_calls``
        ({tool, args}); the reply shows what the SHADOW gate would stop (launch red-team
        replay). Measures the supervision stack, not the model."""
        ...

    def decide(self, applicant: Mapping[str, Any]) -> Mapping[str, Any]:
        """Credit-style decision: returns {approved: bool, limit_minor: int, reason: str}."""
        ...

    def dependency_files(self) -> list[Path]:
        """Lock / requirements files (uv.lock, requirements*.txt, poetry.lock, pyproject)."""
        ...

    def model_inventory(self) -> list[ModelDependency]: ...

    def tool_manifest(self) -> Mapping[str, Any]:
        """{"tools": [{name, description, schema...}], "mcp_servers": [...]} as declared."""
        ...

    def system_prompt(self) -> str: ...


@runtime_checkable
class TraceTarget(Protocol):
    kind: Literal["traces"]
    target_id: str  # agent id
    is_mock: bool

    def events(self) -> list[Mapping[str, Any]]:
        """``agent_event`` rows for the agent in the window (masked; may be empty)."""
        ...

    def tables(self) -> Any:
        """The TableStore that holds them (for monitor runners)."""
        ...


@runtime_checkable
class JudgeTarget(Protocol):
    kind: Literal["judge"]
    target_id: str  # e.g. "judge:mock-judge-t1-v1"
    is_mock: bool

    def router_factory(self) -> Any:
        """Callable returning a fresh ``JudgeRouter`` (judge eval harness style)."""
        ...

    def score(self, events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        """Judge one trace: {score_bp: int, label: str, tier: int}."""
        ...

    def model_inventory(self) -> list[ModelDependency]: ...

    def dependency_files(self) -> list[Path]:
        """Supervisor's own lock file (the judge runs inside it)."""
        ...


Target = AgentTarget | TraceTarget | JudgeTarget


@dataclass
class RunContext:
    """Everything a runner may use. No network. ``data_root`` = ASSURANCE_DATA_DIR."""

    target: Any  # one of the Target protocols
    repo_root: Path
    data_root: Path | None  # bank-supplied data: <data_root>/<pack_id>/
    data_mode: Literal["auto", "synthetic", "bank", "vendored"] = "auto"
    seed: int = 20261015
    max_items: int | None = None  # cap for fast tests
    osv_db_path: Path | None = None
    licence_allow: tuple[str, ...] = ()
    now: datetime | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def bank_dir(self, pack_id: str) -> Path | None:
        if self.data_root is None:
            return None
        p = self.data_root / pack_id
        return p if p.is_dir() else None


class PackRunner(Protocol):
    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput: ...


def safe_id(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")
