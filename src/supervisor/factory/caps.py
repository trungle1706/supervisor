"""Platform caps of the agent factory: the single source of every limit (WP-F1).

The agent definition schema, the harness block and the docs table (docs/factory.md) read these
values; a team can only choose a value inside the cap. A change here is a platform change.
"""

from __future__ import annotations

import re

SCHEMA_VERSION = "1.0"

# ------------------------------------------------------------------ identity and text
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")  # agent id: lowercase-hyphen, <= 64
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")  # checklist id, doc id, ids in lists
NAME_MAX = 64
DESCRIPTION_MAX = 1024
QUESTION_MAX = 500
PASS_RULE_MAX = 500
RATIONALE_MAX = 600
REF_MAX = 300
INSTRUCTIONS_MAX_TOKENS = 5000
CHECKLIST_MAX = 60
POLICY_REFS_MAX = 20
SECTIONS_MAX = 30
TOOLS_MAX = 12
GUARDIANS_MAX = 20
FINDINGS_MAX = 200
EVIDENCE_MAX = 20
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# ------------------------------------------------------------------ vocabularies
DIMENSIONS = (
    "model",
    "data_governance",
    "cybersecurity",
    "legal_compliance",
    "ethics",
    "third_party",
    "supply_chain",
    "reputation",
)
GROUPS = ("model_risk", "data", "cyber", "legal", "third_party", "ethics", "platform")
EVIDENCE_KINDS = ("fact", "document", "regkb", "pack", "system_record")
VERDICTS = ("pass", "fail", "not_applicable", "question")
SEVERITIES = ("low", "medium", "high")
CONFIDENCES = ("low", "medium", "high")
LIFECYCLE_STATES = ("draft", "tested", "approved", "live", "retired")
TOOL_KINDS = (
    "read_facts",
    "read_regkb",
    "read_pack_results",
    "read_system_record",
    "search_documents",
)
TOOL_MODES = ("read", "propose")  # `act` does not exist in 12B
SCOPE_KINDS = ("system", "regkb", "pack", "documents")
DATA_CLASSES = ("public", "internal", "confidential", "personal_masked")
ROLES = ("viewer", "operator", "reviewer", "approver", "owner", "auditor", "admin")

# The mandatory guardians: locked by the platform, always present, never removable.
MANDATORY_GUARDIANS = ("pii_mask_v2", "tool_scope_guard", "citation_required")
OUTPUT_SCHEMA = "assessment_report_v1"

# ------------------------------------------------------------------ harness: system_prompt
PREAMBLE = "platform_v1"

# ------------------------------------------------------------------ harness: context
CONTEXT_SOURCES = ("facts_v1", "pack_results", "system_record", "regkb_rows", "document_sections")
CONTEXT_BUDGET_MIN = 1000
CONTEXT_BUDGET_MAX = 24000  # tokens per call
CONTEXT_BUDGET_DEFAULT = 12000
MAX_DOCUMENT_CHARS_MAX = 20000
MAX_DOCUMENT_CHARS_DEFAULT = 8000

# ------------------------------------------------------------------ harness: memory
MEMORY_RETENTION_MAX_DAYS = 365
MEMORY_FIELDS = ("prior_verdicts", "open_questions", "waivers")

# ------------------------------------------------------------------ harness: hitl
APPROVAL_POINTS_MAX = 20
APPROVAL_KINDS = ("checklist", "verdict")

# ------------------------------------------------------------------ harness: verification
VERIFIERS = ("rules", "rules+judge")
LOCKED_VALIDATORS = ("evidence_exists", "quote_matches", "pass_rule_follows")
EXTRA_VALIDATORS = ("evidence_kind_allowed", "evidence_age", "rationale_length", "no_personal_data")

# ------------------------------------------------------------------ harness: loop
LOOP_MODES = ("single_pass", "loop")
LOOP_MAX_ITERATIONS = 8
LOOP_BUDGET_MAX = 200000  # tokens per run
LOOP_BUDGET_DEFAULT = 60000
STOP_WHEN = ("all_answered", "evaluator_done")
LOOP_EVALUATORS = ("rules", "judge")
MIN_SCORE_MAX = 100  # integer scale 0..100
STOP_REASONS = ("single_pass", "all_answered", "evaluator_done", "max_iterations", "budget")

# ------------------------------------------------------------------ evidence rules
MAX_AGE_DAYS_MAX = 3650

# Phrases that try to override the locked preamble (instruction linter).
OVERRIDE_PATTERNS = (
    r"ignore\s+(all\s+|the\s+|any\s+)?(previous|prior|above|earlier)",
    r"disregard\s+(all\s+|the\s+|any\s+)?(previous|prior|above|earlier|system)",
    r"forget\s+(all\s+|the\s+)?(previous|prior|above|your)\s+(instructions|rules)",
    r"do\s+not\s+(cite|quote)\s+(evidence|sources)",
    r"reveal\s+(the\s+)?system\s+prompt",
)


def estimate_tokens(text: str) -> int:
    """Deterministic token estimate: UTF-8 bytes divided by 4, rounded up (conservative for
    Vietnamese, which has more bytes per token than English)."""
    return (len(text.encode("utf-8")) + 3) // 4
