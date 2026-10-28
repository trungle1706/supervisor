"""Platform caps of the guardian factory: the single source of every limit (WP-G1).

The definition schema, the author, the adapter and the docs table (docs/guardian-factory.md)
read these values. A change here is a platform change.
"""

from __future__ import annotations

import re

SCHEMA_VERSION = "1.0"

# ------------------------------------------------------------------ identity and text
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")  # lowercase-hyphen, at most 64
NAME_MAX = 64
RESERVED_IDS = ("new", "schema")  # used by the console route and the schema route
DESCRIPTION_MAX = 1024
SCOPE_ITEM_RE = re.compile(r"^[A-Za-z0-9*][A-Za-z0-9_.:-]{0,63}$")
SCOPE_MAX = 50
USER_MAX = 120
PROSE_MAX = 1000  # the person's sentence in the plain-words box

# ------------------------------------------------------------------ vocabularies
TYPES = ("regex", "keyword_list", "classifier", "judge_prompt", "policy")
STAGES = ("preflight", "input", "tool_call", "output")
ACTIONS = ("block", "redact", "require_approval", "log")
DATA_CLASSES = ("public", "internal", "confidential", "pii", "pii_export", "credit", "money")

# Only deterministic types may block or redact. A model advises (CLAUDE.md product rules).
DETERMINISTIC_TYPES = ("regex", "keyword_list", "policy")
MODEL_TYPES = ("classifier", "judge_prompt")
ACTIONS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "regex": ACTIONS,
    "keyword_list": ACTIONS,
    "policy": ACTIONS,
    "classifier": ("log", "require_approval"),
    "judge_prompt": ("log", "require_approval"),
}

SENSITIVITY_MIN, SENSITIVITY_MAX = 1, 4

# ------------------------------------------------------------------ per-type config
KEYWORDS_MAX = 500
KEYWORD_CHARS = 80
MODEL_REFS = ("injection_classifier", "guard_model")  # slugs of detectors that exist
THRESHOLD_BP_MAX = 10_000
JUDGE_PROMPT_MAX_TOKENS = 2_000
VERDICT_LABELS_MIN, VERDICT_LABELS_MAX = 2, 6
LABEL_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
POLICY_RULES_MAX = 20
POLICY_CONDITIONS_MAX = 5
POLICY_VALUES_MAX = 20
POLICY_VALUE_CHARS = 64
POLICY_KINDS = ("tool", "argument", "amount", "data_class")
POLICY_OPS = ("eq", "in", "gt", "gte", "lt", "lte", "present")
POLICY_EFFECTS = ("permit", "forbid")
RULE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
ARG_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
AMOUNT_MAX = 10**15  # integer minor units (VND has no decimals)

# ------------------------------------------------------------------ thresholds
PCT_MAX = 100
P95_MS_MAX = 60_000
DEFAULT_THRESHOLDS = {"min_tpr_pct": 90, "max_fpr_pct": 5, "max_p95_ms": 50}

# ------------------------------------------------------------------ lifecycle
# ONE place for the states and the transitions. G2 (benchmarked) and G3 (shadow, approved, live)
# switch more on by adding pairs to ALLOWED_NOW; the table itself does not change.
STATES = ("draft", "benchmarked", "shadow", "approved", "live", "retired")
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("benchmarked", "retired"),  # benchmarked: WP-G2
    "benchmarked": ("shadow", "draft", "retired"),  # shadow: WP-G3
    "shadow": ("approved", "draft", "retired"),  # approved: WP-G3
    "approved": ("live", "retired"),  # live: WP-G3
    "live": ("retired",),
    "retired": ("draft", "live"),  # live: rollback only (WP-G3, an admin with a reason)
}
# WP-G2 adds draft -> benchmarked (needs a passing run of this version and definition) and
# benchmarked -> draft (any change of the definition).
ALLOWED_NOW: frozenset[tuple[str, str]] = frozenset(
    {
        ("draft", "retired"),
        ("retired", "draft"),
        ("draft", "benchmarked"),
        ("benchmarked", "draft"),
        ("benchmarked", "retired"),
        # WP-G3: shadow and promotion (the conditions are in guardian_factory/promotion.py)
        ("benchmarked", "shadow"),
        ("shadow", "approved"),
        ("shadow", "draft"),
        ("shadow", "retired"),
        ("approved", "live"),
        ("approved", "retired"),
        ("live", "retired"),
        ("retired", "live"),
    }
)
SHADOW_DAYS_MAX = 90
SHADOW_DAYS_DEFAULT = 7  # lifecycle.shadow_days 0 = not set = this many days
APPROVALS_MAX = 10
ALLOW_LIST_MAX = 50
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
BENCH_PACK_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# ------------------------------------------------------------------ benchmark (WP-G2)
BENCH_MAX_BYTES = 5_000_000
BENCH_MAX_CASES = 5_000
BENCH_TEXT_MAX = 4_000  # characters of one case (text, or the JSON of its arguments)
BENCH_TRACE_SAMPLE_MAX = 2_000
BENCH_GENERATED_ATTACK = 100
BENCH_STALE_S = 1_800  # a queued or running row older than this, with no thread, was cut short
BENCH_META_KEYS = ("agent_id", "tool_name", "data_class")
# compare_with: "" = the closest catalogue detector of the stage; "none" = no live row
COMPARE_WITH = ("", "dlp_vn", "injection_regex", "none")

# ------------------------------------------------------------------ author
OVER_BROAD_PCT = 5  # a regex that matches more than this share of the benign sample is flagged
AUTHOR_TIMEOUT_S = 30.0

# ------------------------------------------------------------------ shadow and promotion (WP-G3)
GF_PREFIX = "gf:"  # detector slug of a live guardian: gf:<def_id>@<version>
GF_SLUG_RE = re.compile(r"^gf:([a-z0-9][a-z0-9-]{0,63})@([0-9]{1,5})$")
APPROVAL_KINDS = ("owner_lead", "platform_security")
SECURITY_GROUP = "platform"  # the group of config/factory_groups.yaml that is platform security
REASON_MIN = 20  # characters: a rollback, an allow-list entry
REASON_MAX = 200
ALLOW_MAX_DAYS = 90  # an allow-list entry ends within this many days
REVIEW_LIST_MAX = 200
REVIEWS = ("correct", "false")
SHADOW_CACHE_S = 5.0  # how long the gate keeps the list of shadow and live guardians
SHADOW_FLUSH_CALLS = 25  # day counters are written every this many calls ...
SHADOW_FLUSH_S = 5.0  # ... or this many seconds
SHADOW_MODEL_QUEUE = 50  # model-type shadow checks waiting for the one worker thread
