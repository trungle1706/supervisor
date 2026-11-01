"""Typed, versioned report of the source analysis agent (pydantic).

One ``Finding`` = one claim about the source. Every finding carries file:line evidence and the
deterministic verifier decides ``verified`` after the run. The agent never sets ``verified``.

Kinds (what downstream features read):

    framework, model, tool, entrypoint, data_flow, egress, secret_handling, guardrail, hitl,
    logging, pii

``attrs`` holds the typed details of a kind (see ``ATTR_SPEC``). Unknown keys and values outside
the closed lists are dropped by ``clean_attrs`` and counted, so a model cannot smuggle free text
into a field that a rule reads.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from supervisor.onboard.models import Evidence

SCHEMA_VERSION = 1

Kind = Literal[
    "framework",
    "model",
    "tool",
    "entrypoint",
    "data_flow",
    "egress",
    "secret_handling",
    "guardrail",
    "hitl",
    "logging",
    "pii",
]
KINDS: tuple[str, ...] = (
    "framework",
    "model",
    "tool",
    "entrypoint",
    "data_flow",
    "egress",
    "secret_handling",
    "guardrail",
    "hitl",
    "logging",
    "pii",
)
Source = Literal["deterministic", "agent"]
Basis = Literal["manifest", "ast", "name", "agent"]  # where an attribute value came from

# attribute -> closed list of values (a tuple), or ``bool`` / ``str`` (free short text, scrubbed)
ATTR_SPEC: dict[str, dict[str, Any]] = {
    "framework": {},
    "model": {
        "provider": str,
        "family": str,
        "pinned": bool,
        "resolved": bool,
    },
    "tool": {
        "effect": ("read", "write", "money", "credit", "message", "delete", "other"),
        "irreversible": bool,
        "approval": bool,
        "amount_arg": str,
        "destination_arg": str,
    },
    "entrypoint": {"entry": ("http", "cli", "mcp", "notebook", "mlflow", "queue", "schedule")},
    "data_flow": {
        "tool": str,
        "direction": ("read", "write"),
        "sink": ("db", "http", "bank_api", "file"),
        "target": str,
    },
    "egress": {
        "internal": bool,
        "direction": ("read", "write"),
    },
    "secret_handling": {"source": ("hardcoded", "env", "secret_store")},
    "guardrail": {
        "guard": (
            "amount_limit",
            "allowlist",
            "input_validation",
            "output_filter",
            "rate_limit",
            "content_filter",
        ),
        "scope": str,
    },
    "hitl": {
        "mode": ("pre_approval", "interrupt", "review_queue"),
        "guards": str,  # comma list of tool names
    },
    "logging": {
        "sink": ("log", "trace_otel", "trace_mlflow", "audit_table"),
        "logs_pii": bool,
    },
    "pii": {"tool": str},
}
MAX_ATTR_TEXT = 80


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Finding(_M):
    finding_id: str = Field(min_length=1, max_length=40)
    kind: Kind
    name: str = Field(min_length=1, max_length=200)
    attrs: dict[str, str | bool] = Field(default_factory=dict)
    # where each attribute value came from (merge result); empty for a raw finding
    attr_basis: dict[str, Basis] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(min_length=1)
    source: Source
    verified: bool = False
    # deterministic corroboration: a deterministic finding with the same key exists
    corroborated: bool = False
    confidence_bp: int = Field(ge=0, le=10000)
    note: str = Field(default="", max_length=240)

    def key(self) -> tuple[str, str]:
        return (self.kind, self.name.strip().lower())


class Disagreement(_M):
    kind: Kind
    name: str
    attr: str
    deterministic: str
    agent: str
    applied: Literal["deterministic", "agent"]  # which value the report keeps
    reason: str = Field(max_length=240)
    evidence: list[Evidence] = Field(default_factory=list)


class Rejected(_M):
    """A claim of the agent that failed the check. No claim text is kept (it is untrusted)."""

    kind: str
    name: str = Field(max_length=120)
    file: str = Field(max_length=300)
    line: int
    reason: Literal[
        "bad_kind",
        "no_file",
        "line_out_of_range",
        "quote_not_on_line",
        "quote_too_short",
        "evidence_is_prose",
        "injection_text",
        "bad_attrs",
        "duplicate",
        "over_limit",
        "not_a_tool",
        "claim_not_visible",
        "not_an_approval_step",
    ]


class Coverage(_M):
    files_total: int = Field(ge=0)
    files_read: int = Field(ge=0)  # files the agent opened with read_file or ast_outline
    files_seen: int = Field(ge=0)  # also touched by grep / find_references hits
    lines_total: int = Field(ge=0)
    lines_read: int = Field(ge=0)
    skipped: dict[str, str] = Field(default_factory=dict)  # file -> reason (binary, too large)


class RunStats(_M):
    steps: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    tokens_estimated: int = Field(ge=0)  # chars / 3.5 of every prompt and reply; not a bill
    seconds: float = Field(ge=0)
    stop_reason: Literal[
        "finished", "max_steps", "max_tokens", "max_seconds", "max_read_lines", "model_error", "off"
    ]
    tool_calls: dict[str, int] = Field(default_factory=dict)
    tool_errors: int = 0
    injection_lines_withheld: int = 0
    proposed: int = 0
    kept: int = 0
    rejected: int = 0


class ModelInfo(_M):
    model_id: str
    family: str
    is_mock: bool
    api_shape: str = ""


class CodeAnalysisReport(_M):
    version: Literal[1] = 1
    node_id: str
    attempt_n: int
    tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: Literal["deterministic", "agent"]
    model: ModelInfo | None = None
    summary: str = Field(default="", max_length=600)
    findings: list[Finding] = Field(default_factory=list)
    disagreements: list[Disagreement] = Field(default_factory=list)
    rejected: list[Rejected] = Field(default_factory=list)
    coverage: Coverage
    stats: RunStats
    confidence: Literal["low", "medium", "high"]
    confidence_bp: int = Field(ge=0, le=10000)
    notes: list[str] = Field(default_factory=list)

    def of(self, kind: str) -> list[Finding]:
        return [f for f in self.findings if f.kind == kind]


def clean_attrs(kind: str, raw: Any) -> tuple[dict[str, str | bool], int]:
    """Keep only known attributes with allowed values. Returns (attrs, dropped count)."""
    spec = ATTR_SPEC.get(kind, {})
    out: dict[str, str | bool] = {}
    dropped = 0
    if not isinstance(raw, dict):
        return out, 0 if raw in (None, "") else 1
    for k, v in raw.items():
        want = spec.get(str(k))
        if want is None or v is None or v == "":
            dropped += 0 if want is not None else 1
            continue
        if want is bool:
            if isinstance(v, bool):
                out[str(k)] = v
            elif isinstance(v, str) and v.strip().lower() in ("true", "false", "yes", "no"):
                out[str(k)] = v.strip().lower() in ("true", "yes")
            else:
                dropped += 1
        elif want is str:
            out[str(k)] = " ".join(str(v).split())[:MAX_ATTR_TEXT]
        else:
            val = str(v).strip().lower()
            if val in want:
                out[str(k)] = val
            else:
                dropped += 1
    return out, dropped
