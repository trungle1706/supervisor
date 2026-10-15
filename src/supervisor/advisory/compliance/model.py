"""Data model of the compliance advisor (WP14). Frozen dataclasses, plain JSON via ``to_plain``.

Rules that every builder keeps:
- A fact the advisor does not know is ``None`` (scalar) or an incomplete set; it becomes an
  open question, never a guess.
- Every status traces to control ids (``ControlCheck``) and product facts (``Pointer``).
- Money is integer VND (no floats).

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

# ----------------------------------------------------------------------------- vocabularies

AGENT_CLASSES = ("customer_facing", "credit_decision", "payment", "internal_tool")
DATA_CLASSES = (
    "personal",
    "sensitive_personal",
    "financial",
    "biometric",
    "core_data",
    "important_data",
)
AUTONOMY = ("advisory", "acts_with_approval", "acts_autonomously")
MODEL_HOSTING = ("on_prem", "domestic_cloud", "foreign_cloud")
ROLES = ("deployer", "provider")
CUSTOMER_TYPES = ("individual", "organisation")

APPLIES = ("yes", "no", "needs_answer")
STATUSES = ("met", "partial", "gap", "bank_process", "not_applicable")
D33_CLASSES = ("high_risk", "not_high_risk", "needs_answer")
THRESHOLD_VERDICTS = ("exceeds", "at_cap", "within", "needs_answer")


# ----------------------------------------------------------------------------- product facts


@dataclass(frozen=True)
class Pointer:
    """Where a fact comes from.

    kind: file | rule | manifest | catalogue | table | setting | questionnaire | plan |
    profile | console | default. ref: ``server.py:32``, ``PAY-03``, ``single_limit``,
    ``agent_event``, ``FAIRNESS_ENABLED``, ``product.yaml#autonomy`` ...
    """

    kind: str
    ref: str
    note: str = ""


@dataclass(frozen=True)
class LimitFact:
    """A money limit the product's policy or manifest sets (integer VND)."""

    id: str  # rule id (PAY-03) or manifest key (daily_transfer_max_minor) or questionnaire key
    source: str  # rule | manifest | questionnaire
    period: str  # per_transaction | daily
    scope: str  # per_customer | per_account | per_agent | unknown
    value_vnd: int
    tools: tuple[str, ...] = ()
    pointer: Pointer | None = None
    risk_class: str = ""  # money | credit | "" (unknown); credit limits never meet payment caps


@dataclass(frozen=True)
class RuleFact:
    """A gate rule present in the product's policy YAML."""

    id: str
    description: str
    pointer: Pointer  # kind rule, ref "policies/baseline.yaml:153"


@dataclass(frozen=True)
class ProductControls:
    """Supervisor controls the product actually has.

    known False = nobody told the advisor (no plan, no policy, questionnaire blank): every
    Supervisor control then counts as absent and an open question is raised.
    """

    known: bool = False
    basis: str = "unknown"  # deployed | planned (onboarding plan, after the PR merges) | declared
    supervised: bool | None = None  # registered with Supervisor (gateway / recorder / chain)
    catalogue_on: tuple[str, ...] = ()
    rules: tuple[RuleFact, ...] = ()
    monitors: tuple[str, ...] = ()  # controls.yaml monitor names (drift, fairness, ...)
    evidence: tuple[str, ...] = ()  # controls.yaml evidence ids
    console: tuple[str, ...] = ()  # controls.yaml console screen names
    pointers: dict[str, Pointer] = field(default_factory=dict)  # "<kind>:<id>" -> Pointer
    policy_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductProfile:
    """Facts about one product. None = not known. ``*_complete`` False = the set is a lower
    bound found in code (more values may exist), so a predicate it does not meet is a
    question, not 'not applicable'."""

    product_id: str
    name: str
    source: str  # onboard | questionnaire
    version: str = ""
    owner_team: str | None = None
    purpose: str | None = None
    agent_classes: tuple[str, ...] | None = None
    agent_classes_complete: bool = False
    data_classes: tuple[str, ...] | None = None
    data_classes_complete: bool = False
    autonomy: str | None = None
    cross_border: bool | None = None
    model_hosting: str | None = None
    roles: tuple[str, ...] | None = None
    roles_complete: bool = False
    customer_facing: bool | None = None
    decisions_affecting_customers: bool | None = None
    customer_types: tuple[str, ...] | None = None
    customer_types_complete: bool = False
    executes_payments: bool | None = None
    human_approval_before_execution: bool | None = None
    credit_decisions: bool | None = None
    independent_credit_approval: bool | None = None
    max_transaction_vnd: int | None = None  # largest single payment the product may execute
    max_daily_vnd: int | None = None  # largest total per customer per day
    max_credit_vnd: int | None = None  # largest credit amount it may process
    in_operation_since: str | None = None  # ISO date; Circular 53 Art. 24 / AI Law Art. 35
    limits: tuple[LimitFact, ...] = ()
    controls: ProductControls = field(default_factory=ProductControls)
    provenance: dict[str, tuple[Pointer, ...]] = field(default_factory=dict)  # field -> where
    onboard_decision33: dict[str, Any] | None = None  # AgentProfile.decision33 dump (reused)


# ----------------------------------------------------------------------------- matrix


@dataclass(frozen=True)
class Question:
    id: str  # Q-<fact>, stable
    fact: str  # ProductProfile field name (or controls / limits key)
    text_en: str
    text_vi: str
    obligation_ids: tuple[str, ...] = ()
    why: str = ""


@dataclass(frozen=True)
class ControlCheck:
    """One control_mapping entry joined with the product facts."""

    kind: str  # catalogue | rule | monitor | console | evidence | process
    id: str
    coverage: str  # full | partial | none (from RegKB)
    present: bool | None  # None for process controls (owned by the bank)
    pointer: Pointer | None = None  # where the product shows it has the control
    note: str = ""


@dataclass(frozen=True)
class DateItem:
    label: str
    date: str | None
    source: str
    verification: str
    note: str = ""


@dataclass(frozen=True)
class Deadline:
    effective: DateItem | None = None
    compliance_deadline: DateItem | None = None
    transitions: tuple[DateItem, ...] = ()  # milestones, Circular 53 Art. 24, AI Law Art. 35
    article_effective: DateItem | None = None  # milestone that names this article


@dataclass(frozen=True)
class ThresholdFinding:
    id: str  # TH-<obligation short>-<limit id>
    obligation_id: str
    limit_id: str  # rule id or manifest key; "none" when no limit was found
    period: str
    customer_type: str  # individual | organisation | unknown
    limit_vnd: int | None
    cap_vnd: int
    verdict: str  # exceeds | at_cap | within | needs_answer
    reason: str
    pointer: Pointer | None = None


@dataclass(frozen=True)
class D33Entry:
    entry: str  # transactions | credit
    triggered: bool | None  # None = needs answer
    lines: tuple[str, ...]  # reasoning lines, each cites an obligation id or a fact
    obligation_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision33Suggestion:
    classification: str  # high_risk | not_high_risk | needs_answer
    entries: tuple[D33Entry, ...]
    lines: tuple[str, ...]
    caveat: str
    question_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatrixRow:
    obligation_id: str
    instrument_id: str
    instrument_number: str
    jurisdiction: str
    binding: bool
    instrument_status: str
    article_ref: str
    summary_en: str
    duties: tuple[str, ...]
    applies: str  # yes | no | needs_answer
    applies_reasons: tuple[str, ...]
    missing_facts: tuple[str, ...]
    status: str  # met | partial | gap | bank_process | not_applicable
    status_reason: str
    controls: tuple[ControlCheck, ...]
    evidence_needed: tuple[str, ...]
    evidence_pointers: tuple[Pointer, ...]
    deadline: Deadline
    question_ids: tuple[str, ...] = ()
    threshold_ids: tuple[str, ...] = ()
    # WP17 assurance packs whose maps_to.regkb_duties meet this row's duties: where an auditor
    # finds test evidence (eval_result table). The advisor does not read results; no status effect.
    assurance_packs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Narrative:
    text: str
    model_id: str
    is_mock: bool
    label: str = "advisory"


@dataclass(frozen=True)
class MatrixHeader:
    product_id: str
    product_name: str
    product_source: str
    regkb_version: str
    instruments: int
    obligations: int
    internal_rules: bool
    internal_instruments: tuple[str, ...]
    as_of: str
    generated_at: str
    disclaimer: str
    advisory_note: str
    tool: str = "supervisor.advisory.compliance"


@dataclass(frozen=True)
class ObligationMatrix:
    header: MatrixHeader
    product: ProductProfile
    rows: tuple[MatrixRow, ...]  # sorted by obligation_id
    questions: tuple[Question, ...]  # sorted by id
    thresholds: tuple[ThresholdFinding, ...]
    decision33: Decision33Suggestion
    summary: dict[str, Any]
    narrative: Narrative | None = None


def to_plain(obj: Any) -> Any:
    """Dataclass tree -> JSON-ready dict/list/str/int/bool/None (keeps None)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in sorted(obj.items())}
    if isinstance(obj, tuple | list):
        return [to_plain(v) for v in obj]
    if isinstance(obj, frozenset | set):
        return sorted(to_plain(v) for v in obj)
    return obj
