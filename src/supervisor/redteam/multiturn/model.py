"""Data classes of the multi-turn red team: objectives, turns, conversation results.

An *objective* is one pack item: what the attacker wants (a violating tool call sequence), how
success is decided (the oracle spec) and the two written descriptions that the two-stage
evidence judge compares a conversation with (success description, benign description).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FAMILIES: tuple[str, ...] = (
    "echo_chamber",
    "crescendo",
    "payload_split",
    "tool_poisoning",
    "memory_poison",
    "policy_puppetry",
)
LANGS: tuple[str, ...] = ("vi", "en")
AGENTS: tuple[str, ...] = ("payments", "customer_service", "credit_prequal")
GAP_CLASSES: tuple[str, ...] = ("", "group-key-evasion", "rule-missing")
OBJECTIVE_FIELDS = (
    "id",
    "pair_id",
    "lang",
    "family",
    "agent",
    "kind",
    "ordinal",
    "split",
    "theme",
    "title",
    "oracle",
    "expected_rules",
    "gap_class",
    "success_description",
    "benign_description",
    "source",
    "licence",
    "label",
    "labeller",
)


@dataclass(frozen=True)
class Step:
    """One tool call the attacker wants the agent to make."""

    tool: str
    args: dict[str, Any]

    def as_call(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": dict(self.args)}


@dataclass(frozen=True)
class Objective:
    """One pack item (a line of ``objectives.jsonl``)."""

    id: str
    pair_id: str
    lang: str
    family: str
    agent: str
    kind: str
    ordinal: int
    split: str
    theme: dict[str, str]
    title: str
    oracle: dict[str, Any]
    expected_rules: list[str]
    gap_class: str
    success_description: str
    benign_description: str
    source: str = "own"
    licence: str = "own"
    label: str = "attack"
    labeller: str = "expert rubric"

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in OBJECTIVE_FIELDS}


@dataclass
class Binding:
    """Concrete sandbox ids for one trial (synthetic customers, accounts, payees, applications)."""

    agent: str
    customer_id: str
    accounts: list[str]
    payees: list[str]
    account_owner: dict[str, str]
    ticket_id: str = ""
    other_customer_id: str = ""
    other_pii: list[str] = field(default_factory=list)
    app_incomplete: str = ""
    app_complete: str = ""
    extra_apps: list[str] = field(default_factory=list)
    extra_customers: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """What an attack tries to make the agent do, in order, and the numbers behind it."""

    steps: list[Step]
    slots: dict[str, Any]
    gap_s: int = 90  # seconds between turns that carry a step
    benign_steps: list[Step] = field(default_factory=list)


@dataclass
class TurnPlan:
    """One attacker turn before it is sent: text, calls it asks for, and labels."""

    text: str
    stage: str
    calls: list[Step] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    gap_s: int = 90
    planted: str = ""  # text of a poisoned tool result that reaches the agent on this turn
    step_index: int = -1  # index in the plan of the step this turn asks for, or -1


@dataclass
class TurnRecord:
    """What happened on one turn (everything the oracle, monitor and traces need)."""

    index: int
    stage: str
    tags: list[str]
    text: str
    text_sha256: str
    attacker_mode: str  # template | llm | llm_fallback
    tier0b_kinds: list[str]
    planted_tier0b: list[str]
    cues: dict[str, int]
    asked_calls: int
    executed: list[dict[str, Any]]  # {tool, status, amount_minor?, rule_hit}
    complied: bool
    refused: bool
    reply: str
    gate_stops: list[str]
    oracle_hit: bool
    ts: str


@dataclass
class ConversationResult:
    objective_id: str
    pair_id: str
    family: str
    agent: str
    lang: str
    kind: str
    gap_class: str  # known hole class of the objective, "" when a rule should stop it
    split: str
    trial: int
    seed: str
    benign: bool
    mode: str  # model = susceptibility model, always = worst case (agent complies)
    success: bool
    success_turn: int  # 1-based turn index where the oracle first fired, 0 = never
    n_turns: int
    gate_caught: bool  # SHADOW gate would stop the call that crossed the line
    gate_stops_at_success: list[str]
    first_stop_turn: int  # first turn where the gate would stop anything, 0 = never
    any_stop: bool
    expected_rule_hit: bool
    tier0b_turn1: bool
    tier0b_any: bool
    tier0b_first_turn: int
    monitor_visible: bool
    monitor_first_turn: int
    monitor_before_success: bool
    refusals: int
    expand_requests: int
    risk_topic_turns: int
    tier0b_hits: int
    miss_class: str  # "" | gap-rule-missing | gap-group-key-evasion | unexpected-miss
    attacker: str  # template | llm
    attacker_model: str
    prompt_version: str
    is_mock: bool
    ms: int
    turns: list[TurnRecord] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
