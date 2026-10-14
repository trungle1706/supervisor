"""Strict JSON output schema shared by Tier 1 and Tier 2 judges.

The adapter asks the server to enforce it (``response_format: json_schema``) and checks
it again on our side; :func:`validate_output` adds the checks a JSON schema cannot do.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.adapters.llm import jsonschema_lite

RATIONALE_MAX_CHARS = 400
QUOTE_MAX_CHARS = 160
MAX_SPANS = 5
MAX_POLICY_REFS = 5
POLICY_REF_PATTERN = r"^[A-Z]{2,5}-[0-9]{2}$"

# FinVault-aligned risk labels plus two judge-specific ones.
LABELS: tuple[str, ...] = (
    "benign",
    "unauthorized_transaction",
    "limit_circumvention",
    "data_leakage",
    "fraud_facilitation",
    "unfair_lending",
    "policy_violation",
    "hallucinated_commitment",
    "compliance_bypass",
    "prompt_injection",
    "judge_manipulation",
)

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["suspicion_bp", "label", "evidence_spans", "rationale", "policy_refs"],
    "properties": {
        "suspicion_bp": {"type": "integer", "minimum": 0, "maximum": 10000},
        "label": {"type": "string", "enum": list(LABELS)},
        "evidence_spans": {
            "type": "array",
            "maxItems": MAX_SPANS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["event_index", "quote"],
                "properties": {
                    "event_index": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "quote": {"type": "string", "minLength": 1, "maxLength": QUOTE_MAX_CHARS},
                },
            },
        },
        "rationale": {"type": "string", "maxLength": RATIONALE_MAX_CHARS},
        "policy_refs": {
            "type": "array",
            "maxItems": MAX_POLICY_REFS,
            "items": {"type": "string", "pattern": POLICY_REF_PATTERN},
        },
    },
}


class JudgeOutputError(ValueError):
    """The judge reply does not match the output schema."""


def validate_output(value: Any) -> dict[str, Any]:
    """Return a copy of ``value`` if it matches :data:`OUTPUT_SCHEMA`, else raise."""
    if not isinstance(value, Mapping):
        raise JudgeOutputError("judge output is not a JSON object")
    errs = jsonschema_lite.errors(dict(value), OUTPUT_SCHEMA)
    if errs:
        raise JudgeOutputError("; ".join(errs[:5]))
    return {
        "suspicion_bp": int(value["suspicion_bp"]),
        "label": str(value["label"]),
        "evidence_spans": [
            {"event_index": int(s["event_index"]), "quote": str(s["quote"])}
            for s in value["evidence_spans"]
        ],
        "rationale": str(value["rationale"]),
        "policy_refs": [str(p) for p in value["policy_refs"]],
    }
