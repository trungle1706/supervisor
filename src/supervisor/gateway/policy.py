"""Policy YAML: typed schema, loader, validator, policy hash, deploy to the ``rule`` table.

Policy files are untrusted data (ADR D11): ``yaml.safe_load`` only, a size limit,
a strict schema (unknown keys fail), and no code. Predicates use a small fixed
operator set that :mod:`supervisor.gateway.engine` interprets by hand.

File layout (``policies/*.yaml``)::

    policy_version: 1
    tools:   {tool_name: money|credit|pii_export|read_only}
    agents:  {agent_id: {name, owner_user, owner_team, initial_state, ...}}
    reviewers: [user ids allowed to approve a resume as reviewer]
    admins:    [user ids allowed to release a quarantine]
    rules:   [ {id, version, agent_scope, when, aggregate?, prior?, action, ...} ]

``policies/schema.json`` is generated from the models here (a test keeps it current).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from supervisor.core.canonical import sha256_hex
from supervisor.core.errors import ConcurrencyError, SupervisorError
from supervisor.core.monitor_bindings import MonitorBindings
from supervisor.core.ports import Clock, StateStore

log = logging.getLogger("supervisor.gateway")
MAX_POLICY_BYTES = 256 * 1024
MAX_PATTERN_LEN = 200
MANIFEST_RULE_ID = "_manifest"

RiskClass = Literal["money", "credit", "pii_export", "read_only"]
RuleActionT = Literal["log", "alert", "block", "pause"]
FailModeT = Literal["open", "closed"]
SeverityT = Literal["low", "medium", "high", "critical"]
Op = Literal["eq", "ne", "gt", "ge", "lt", "le", "in", "not_in", "matches", "absent", "present"]

DEFAULT_FAIL_MODE: dict[str, FailModeT] = {
    "money": "closed",
    "credit": "closed",
    "pii_export": "closed",
    "read_only": "open",
}
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
ACTION_RANK = {"log": 0, "alert": 1, "block": 2, "pause": 3}

# A group that contains a quantifier and is itself quantified, e.g. (a+)+ or (x*)*: ReDoS risk.
_REDOS = re.compile(r"\([^)]*[+*}][^)]*\)\s*[+*{]")
_PATH_RE = re.compile(r"^(ctx\.)?[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,4}$")
# ``fact.<source>.<field>`` reads a record from the gateway's FactSource (system of record),
# keyed by the tool argument ``<source>_id``. See supervisor.gateway.facts.
FACT_PREFIX = "fact."
_ID_RE = r"^[A-Z0-9][A-Z0-9_-]{1,40}$"
_NAME_RE = r"^[A-Za-z0-9_.:-]{1,80}$"


class PolicyError(SupervisorError):
    """A policy file is invalid or the deployed policy cannot be read."""


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


Scalar = str | int | bool | None


def _check_scalar(value: Any, where: str) -> None:
    if isinstance(value, float):
        raise ValueError(f"{where}: floats are not allowed (use integer minor units)")
    if not isinstance(value, str | int | bool) and value is not None:
        raise ValueError(f"{where}: value must be a string, integer, boolean or null")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Predicate(_Strict):
    """``arg`` is a dotted path into the tool args; ``ctx.`` reads the call context;
    ``fact.<source>.<field>`` reads the system of record (missing record -> rule error)."""

    arg: str
    op: Op
    value: Any = None

    @field_validator("arg")
    @classmethod
    def _path(cls, v: str) -> str:
        if not _PATH_RE.match(v):
            raise ValueError(
                f"bad arg path {v!r} (dotted identifiers, optional ctx. or fact. prefix)"
            )
        if v.startswith(FACT_PREFIX) and len(v.split(".")) != 3:
            raise ValueError(f"bad fact path {v!r} (fact.<source>.<field>)")
        return v

    @model_validator(mode="after")
    def _value_matches_op(self) -> Predicate:
        _validate_op_value(self.op, self.value, f"predicate on {self.arg}")
        return self


def _validate_op_value(op: str, value: Any, where: str) -> None:
    if op in ("absent", "present"):
        if value is not None:
            raise ValueError(f"{where}: op {op} takes no value")
    elif op in ("gt", "ge", "lt", "le"):
        if type(value) is not int:
            raise ValueError(f"{where}: op {op} needs an integer value")
    elif op in ("in", "not_in"):
        if not isinstance(value, list) or not value:
            raise ValueError(f"{where}: op {op} needs a non-empty list")
        for item in value:
            _check_scalar(item, where)
    elif op == "matches":
        if not isinstance(value, str) or not value or len(value) > MAX_PATTERN_LEN:
            raise ValueError(f"{where}: op matches needs a pattern of 1..{MAX_PATTERN_LEN} chars")
        if _REDOS.search(value) or re.search(r"\\[1-9]", value):
            raise ValueError(f"{where}: nested quantifiers and backreferences are not allowed")
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"{where}: bad pattern: {exc}") from exc
    else:  # eq, ne
        _check_scalar(value, where)


class ToolMatch(_Strict):
    """Which tool names a rule applies to. YAML shorthand: ``tool: name`` means ``eq``."""

    op: Literal["eq", "in", "not_in", "matches"] = "eq"
    value: Any

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"op": "eq", "value": data}
        if isinstance(data, Mapping) and len(data) == 1 and "op" not in data:
            ((op, value),) = data.items()
            return {"op": op, "value": value}
        return data

    @model_validator(mode="after")
    def _check(self) -> ToolMatch:
        if self.op == "eq" and not isinstance(self.value, str):
            raise ValueError("tool eq needs a tool name")
        _validate_op_value(self.op, self.value, "tool")
        return self

    def names(self) -> list[str]:
        """Tool names listed literally (for catalog checks and aggregate defaults)."""
        if self.op == "eq":
            return [self.value]
        if self.op in ("in", "not_in"):
            return [str(v) for v in self.value]
        return []


class When(_Strict):
    tool: ToolMatch | None = None
    all: list[Predicate] = Field(default_factory=list)
    any: list[Predicate] = Field(default_factory=list)


class Aggregate(_Strict):
    """Stateful window: sum ``field`` (or count calls) of allowed calls, plus this call."""

    fn: Literal["sum", "count"]
    field: str | None = None
    window_s: int = Field(ge=1, le=31 * 86400)
    group_by: Literal["agent", "customer"]
    customer_arg: str = "customer_id"
    # Extra grouping arguments, e.g. [payee_id]: the window then sums calls with the same
    # customer (or agent) AND the same values of these arguments (split payment, ADR D10).
    also_by: list[str] = Field(default_factory=list, max_length=3)
    tools: list[str] | None = None
    op: Literal["gt", "ge"] = "gt"
    limit: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> Aggregate:
        if self.fn == "sum":
            if not self.field or not self.field.endswith("_minor"):
                raise ValueError("sum aggregates need field: <name>_minor (integer minor units)")
        elif self.field is not None:
            raise ValueError("count aggregates take no field")
        for name in [self.customer_arg, *self.also_by]:
            if not _PATH_RE.match(name) or name.startswith(("ctx.", FACT_PREFIX)):
                raise ValueError(f"bad grouping argument {name!r}")
        if len(set(self.also_by)) != len(self.also_by):
            raise ValueError("also_by has duplicates")
        return self


class Prior(_Strict):
    """Earlier allowed call of ``tool`` with the same ``match_args`` values.

    mode ``present``: the rule matches when such a call happened within the window
    (for example a new payee added minutes ago). mode ``absent``: the rule matches
    when no such call happened (for example no documents fetched before a decision)."""

    tool: str
    within_s: int = Field(ge=1, le=400 * 86400)
    match_args: list[str] = Field(min_length=1, max_length=4)
    mode: Literal["present", "absent"]
    same_agent: bool = False

    @field_validator("match_args")
    @classmethod
    def _paths(cls, v: list[str]) -> list[str]:
        for p in v:
            if not _PATH_RE.match(p) or p.startswith(("ctx.", FACT_PREFIX)):
                raise ValueError(f"bad match arg {p!r}")
        return v


class RuleSpec(_Strict):
    id: str = Field(pattern=_ID_RE)
    version: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=500)
    agent_scope: list[str] | Literal["*"]
    when: When = Field(default_factory=When)
    aggregate: Aggregate | None = None
    prior: Prior | None = None
    action: RuleActionT
    fail_mode: FailModeT | None = None
    severity: SeverityT
    risk_class: RiskClass
    regulation_ref: str | None = None
    owner: str = Field(min_length=1)
    approvals: list[str] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def _check(self) -> RuleSpec:
        if self.agent_scope != "*":
            if not self.agent_scope:
                raise ValueError(f"{self.id}: agent_scope is empty")
            for a in self.agent_scope:
                if not re.match(_NAME_RE, a):
                    raise ValueError(f"{self.id}: bad agent id {a!r}")
        if self.action in ("block", "pause"):
            if len(self.approvals) != 2 or len(set(self.approvals)) != 2:
                raise ValueError(
                    f"{self.id}: block/pause rules need two distinct approver ids in approvals"
                )
        if self.aggregate and self.prior:
            raise ValueError(f"{self.id}: use aggregate or prior, not both")
        return self

    @property
    def effective_fail_mode(self) -> FailModeT:
        return self.fail_mode or DEFAULT_FAIL_MODE[self.risk_class]

    def in_scope(self, agent_id: str) -> bool:
        return self.agent_scope == "*" or agent_id in self.agent_scope

    def counted_tools(self) -> list[str]:
        if self.aggregate and self.aggregate.tools:
            return list(self.aggregate.tools)
        if self.when.tool and self.when.tool.op in ("eq", "in"):
            return self.when.tool.names()
        return []


class AgentDetectors(_Strict):
    """WP37 (ADR D23): per-agent override of ``config/detectors.yaml`` (``agents.<id>.detectors``).

    ``preset`` is the agent's default sensitivity preset; ``enable`` / ``disable`` switch single
    detectors; ``settings`` overrides detector settings by slug; ``skip_tools`` lists tools for
    which the gate runs no detector (verdict status ``skip``, a deterministic policy value).
    Read only when DETECTORS_ENABLED=1; the key is left out of the policy hash when unset, so a
    policy file without it keeps the hash it had before WP37."""

    preset: Literal["strict", "balanced", "lenient"] | None = None
    enable: list[str] = Field(default_factory=list, max_length=16)
    disable: list[str] = Field(default_factory=list, max_length=16)
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)
    skip_tools: list[str] = Field(
        default_factory=list,
        max_length=64,
        description=(
            "Tools for which no detector runs (status skip). The loader refuses a tool whose "
            "risk class is money, credit or pii_export: a skip must not switch off "
            "GATE-DETECTOR-FAILED protection."
        ),
    )

    @field_validator("settings")
    @classmethod
    def _no_floats(cls, v: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        for slug, values in v.items():
            for key, value in values.items():
                if isinstance(value, float):
                    raise ValueError(f"{slug}.{key}: floats are not allowed (use basis points)")
        return v


CONSUMER_ID_RE = r"^[A-Za-z0-9_.:@-]{1,128}$"
MAX_CONSUMERS = 200
ModeT = Literal["enforce", "observe"]


def valid_consumer_id(value: Any) -> bool:
    """A consumer id from the request context: text, 1..128 characters from ``A-Za-z0-9_.:@-``.
    Anything else is ignored by the gate (the agent's own settings then apply)."""
    return isinstance(value, str) and re.fullmatch(CONSUMER_ID_RE, value) is not None


class RuleSwitches(_Strict):
    """WP38 (ADR D28): switch single rules off or on for an agent or one consumer.

    A disabled rule is not evaluated for that agent or consumer (no hit, no record). ``enable``
    on a consumer undoes a ``disable`` of the agent. Rule ids must exist in the policy."""

    enable: list[str] = Field(default_factory=list, max_length=64)
    disable: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def _check(self) -> RuleSwitches:
        for rid in [*self.enable, *self.disable]:
            if not re.match(_ID_RE, rid):
                raise ValueError(f"bad rule id {rid!r}")
        both = set(self.enable) & set(self.disable)
        if both:
            raise ValueError(f"rule(s) both enabled and disabled: {sorted(both)}")
        return self


class ConsumerOverride(_Strict):
    """WP38 (ADR D28): ``agents.<id>.consumers.<consumer_id>``. A field that is set replaces the
    agent's value for calls whose ``context.consumer_id`` is this consumer; a field left out
    keeps the agent's value. ``rules`` merges with the agent's switches."""

    mode: ModeT | None = None
    detectors: AgentDetectors | None = None
    rules: RuleSwitches | None = None


class AgentManifest(_Strict):
    name: str = Field(min_length=1)
    owner_user: str = Field(min_length=1)
    owner_team: str = Field(min_length=1)
    risk_tier: Literal["low", "medium", "high", "critical"] = "high"
    model_family: str = "unknown"
    host_type: str = "python"
    plug_point: str = "sdk"
    initial_state: Literal["RUNNING", "SHADOW"] = "SHADOW"
    # WP1b-B (D06): which tools the quality / fairness / drift / multi-agent monitors read.
    monitors: MonitorBindings | None = None
    # WP37 (D23): per-agent detector override; absent from the dump (and the hash) when None.
    detectors: AgentDetectors | None = None
    # WP38 (D28): observe mode, rule switches and per-consumer overrides. All three are left out
    # of the dump (and the hash) when unset, so a file without them keeps its old hash.
    mode: ModeT | None = None
    rules: RuleSwitches | None = None
    consumers: dict[str, ConsumerOverride] = Field(default_factory=dict)
    # WP38 review: two distinct approver ids that allow observe mode to lift a decision on a
    # money, credit or pii_export tool (see _cross_check_modes). Left out of the hash when empty.
    observe_approvals: list[str] = Field(default_factory=list, max_length=2)

    # WP38 follow-up F14: two distinct approver ids that allow ``rules.disable`` to name a block
    # or pause rule of risk class money, credit or pii_export. Left out of the hash when empty.
    rule_approvals: list[str] = Field(default_factory=list, max_length=2)

    # WP41 review: two distinct approver ids that allow ``detectors.settings.dlp_vn.keep_args``
    # to name a money, credit or pii_export tool (the named argument reaches the tool unmasked).
    # Left out of the hash when empty.
    keep_args_approvals: list[str] = Field(default_factory=list, max_length=2)

    @field_validator("observe_approvals", "rule_approvals", "keep_args_approvals")
    @classmethod
    def _two_approvers(cls, v: list[str]) -> list[str]:
        if v and (len(v) != 2 or len(set(v)) != 2):
            raise ValueError("approvals need two distinct approver ids")
        for a in v:
            if not re.match(_NAME_RE, a):
                raise ValueError(f"bad approver id {a!r}")
        return v

    @field_validator("consumers")
    @classmethod
    def _consumer_ids(cls, v: dict[str, ConsumerOverride]) -> dict[str, ConsumerOverride]:
        if len(v) > MAX_CONSUMERS:
            raise ValueError(f"at most {MAX_CONSUMERS} consumers per agent")
        for cid in v:
            if not valid_consumer_id(cid):
                raise ValueError(f"bad consumer id {cid!r} (1..128 of A-Za-z0-9_.:@-)")
        return v


class PolicyDoc(_Strict):
    policy_version: int = Field(ge=1)
    tools: dict[str, RiskClass] = Field(default_factory=dict)
    agents: dict[str, AgentManifest] = Field(default_factory=dict)
    reviewers: list[str] = Field(default_factory=list)
    admins: list[str] = Field(default_factory=list)
    rules: list[RuleSpec] = Field(default_factory=list)


def _merge(docs: Sequence[PolicyDoc]) -> PolicyDoc:
    tools: dict[str, str] = {}
    agents: dict[str, AgentManifest] = {}
    reviewers: list[str] = []
    admins: list[str] = []
    rules: list[RuleSpec] = []
    for d in docs:
        for k, v in d.tools.items():
            if tools.get(k, v) != v:
                raise PolicyError(f"tool {k} has two risk classes ({tools[k]} and {v})")
            tools[k] = v
        for k, a in d.agents.items():
            if k in agents and agents[k] != a:
                raise PolicyError(f"agent {k} is defined twice with different values")
            agents[k] = a
        reviewers += [r for r in d.reviewers if r not in reviewers]
        admins += [r for r in d.admins if r not in admins]
        rules += d.rules
    return PolicyDoc(
        policy_version=max((d.policy_version for d in docs), default=1),
        tools=dict(sorted(tools.items())),
        agents=dict(sorted(agents.items())),
        reviewers=sorted(reviewers),
        admins=sorted(admins),
        rules=sorted(rules, key=lambda r: (r.id, r.version)),
    )


# Rules a consumer override may not switch off: a block or pause rule on a money, credit or
# pii_export tool. The consumer id is asserted by the caller; it must not be a way around the
# money controls.
_PROTECTED_RISK = ("money", "credit", "pii_export")


def money_agent(doc: PolicyDoc, agent_id: str) -> bool:
    """The agent has a rule in scope whose risk class is money, credit or pii_export."""
    return any(r.in_scope(agent_id) and r.risk_class in _PROTECTED_RISK for r in doc.rules)


def _cross_check_modes(doc: PolicyDoc) -> None:
    by_id = {r.id: r for r in doc.rules}
    for agent_id, agent in doc.agents.items():
        groups: list[tuple[str, RuleSwitches | None]] = [(f"agent {agent_id}", agent.rules)]
        groups += [(f"agent {agent_id} consumer {c}", o.rules) for c, o in agent.consumers.items()]
        for where, sw in groups:
            if sw is None:
                continue
            for rid in [*sw.enable, *sw.disable]:
                if rid not in by_id:
                    raise PolicyError(f"{where}: rule {rid} is not in the rules section")
        money = money_agent(doc, agent_id)
        for rid in agent.rules.disable if agent.rules else []:
            r = by_id[rid]
            if (
                r.action in ("block", "pause")
                and r.risk_class in _PROTECTED_RISK
                and len(set(agent.rule_approvals)) != 2
            ):
                raise PolicyError(
                    _ascii(
                        f"agent {agent_id}: rules.disable names {r.action} rule {rid} "
                        f"({r.risk_class}); that needs two distinct ids in rule_approvals"
                    )
                )
        if agent.mode == "observe" and money:
            if agent.initial_state != "SHADOW" and not agent.observe_approvals:
                raise PolicyError(
                    _ascii(
                        f"agent {agent_id}: mode observe on an agent with money, credit or "
                        "pii_export rules needs initial_state SHADOW or two approver ids in "
                        "observe_approvals"
                    )
                )
        for cid, over in agent.consumers.items():
            if over.mode == "observe":  # F15: no consumer of any agent may observe
                raise PolicyError(
                    _ascii(
                        f"agent {agent_id} consumer {cid}: mode observe is not allowed for a "
                        "consumer (the consumer id is asserted by the caller); set mode on "
                        "the agent"
                    )
                )
            for rid in over.rules.disable if over.rules else []:
                r = by_id[rid]
                if r.action in ("block", "pause") and r.risk_class in _PROTECTED_RISK:
                    raise PolicyError(
                        f"agent {agent_id} consumer {cid}: rule {rid} ({r.action}, "
                        f"{r.risk_class}) cannot be switched off for a consumer"
                    )


SKIP_FORBIDDEN_RISK = ("money", "credit", "pii_export")


def keep_args_of(det: AgentDetectors | None) -> dict[str, Any]:
    """WP41: the ``dlp_vn.keep_args`` mapping of a detector block ({} when absent or not a
    mapping; the shape itself is checked by the detector gate)."""
    keep = ((det.settings.get("dlp_vn") or {}).get("keep_args") if det else None) or {}
    return keep if isinstance(keep, Mapping) else {}


def _cross_check_keep_args(doc: PolicyDoc) -> None:
    """WP41 review: ``keep_args`` is an agent setting (never a consumer one: the consumer id is
    asserted by the caller), and naming a money, credit or pii_export tool needs two distinct
    ids in ``keep_args_approvals``, like ``rule_approvals`` for a rule switch."""
    for agent_id, agent in doc.agents.items():
        for cid, over in agent.consumers.items():
            if keep_args_of(over.detectors):
                raise PolicyError(
                    _ascii(
                        f"agent {agent_id} consumer {cid}: dlp_vn keep_args is an agent "
                        "setting, not a consumer setting"
                    )
                )
        risky = sorted(
            str(t) for t in keep_args_of(agent.detectors) if doc.tools.get(t) in _PROTECTED_RISK
        )
        if risky and len(set(agent.keep_args_approvals)) != 2:
            raise PolicyError(
                _ascii(
                    f"agent {agent_id}: dlp_vn keep_args names {', '.join(risky)} (money, credit "
                    "or pii_export); that needs two distinct ids in keep_args_approvals"
                )
            )


def _cross_check(doc: PolicyDoc) -> None:
    _cross_check_modes(doc)
    _cross_check_keep_args(doc)
    for agent_id, agent in doc.agents.items():
        blocks = [(agent_id, agent.detectors)]
        blocks += [(f"{agent_id}/{c}", o.detectors) for c, o in agent.consumers.items()]
        for where, det in blocks:
            for tool in det.skip_tools if det else []:
                if doc.tools.get(tool) in SKIP_FORBIDDEN_RISK:
                    raise PolicyError(
                        _ascii(
                            f"agent {where}: skip_tools names the {doc.tools[tool]} tool "
                            f"{tool}; detectors cannot be skipped for money, credit or "
                            "pii_export tools"
                        )
                    )
    seen: set[str] = set()
    for r in doc.rules:
        if r.id in seen:
            raise PolicyError(f"rule id {r.id} appears twice")
        seen.add(r.id)
        if r.agent_scope != "*":
            for a in r.agent_scope:
                if a not in doc.agents:
                    raise PolicyError(f"{r.id}: agent {a} is not in the agents section")
        names = r.when.tool.names() if r.when.tool else []
        names += list(r.aggregate.tools or []) if r.aggregate else []
        names += [r.prior.tool] if r.prior else []
        for t in names:
            if t not in doc.tools:
                raise PolicyError(f"{r.id}: tool {t} is not in the tools section")
        if r.aggregate and not r.counted_tools():
            raise PolicyError(f"{r.id}: aggregate needs tools: [...] or when.tool eq/in")


def _dump(doc: PolicyDoc, exclude: set[str] | None = None) -> dict[str, Any]:
    """JSON dump of a policy document. An agent's ``detectors`` key is dropped when unset, so
    adding the WP37 field did not change the hash of any existing policy file. Same for
    ``monitors.session`` (WP27)."""
    out = doc.model_dump(mode="json", by_alias=True, exclude=exclude)
    for agent in out.get("agents", {}).values():
        if agent.get("detectors") is None:
            agent.pop("detectors", None)
        for key in ("mode", "rules"):  # WP38: unset keys are not part of the hash
            if agent.get(key) is None:
                agent.pop(key, None)
        for key in ("observe_approvals", "rule_approvals", "keep_args_approvals"):
            if not agent.get(key):
                agent.pop(key, None)
        if not agent.get("consumers"):
            agent.pop("consumers", None)
        else:
            for over in agent["consumers"].values():
                for key in [k for k, v in over.items() if v is None]:
                    del over[key]
        mons = agent.get("monitors")
        if isinstance(mons, dict) and mons.get("session") is None:
            mons.pop("session", None)  # WP27: same rule, the hash of an old file is unchanged
    return out


@dataclass(frozen=True)
class Effective:
    """What applies to one call after ``consumers[context.consumer_id] ?? agent`` (WP38).

    ``active`` is true when the agent uses mode, rule switches or consumers at all; only then
    does the gate add ``mode`` (and the other WP38 fields) to its answer."""

    mode: str = "enforce"
    consumer_id: str | None = None  # the consumer whose override was applied
    consumer_ignored: bool = False  # a consumer id was sent but is invalid or has no entry
    detectors: AgentDetectors | None = None
    disabled: frozenset[str] = frozenset()
    active: bool = False
    # Observe may lift a decision on a money, credit or pii_export tool only when the agent has
    # two observe_approvals (WP38 review). Without them those tools stay enforced.
    observe_approved: bool = False


class Policy:
    """A validated, merged policy with its hash and per-agent rule lists."""

    def __init__(self, doc: PolicyDoc) -> None:
        _cross_check(doc)
        self.doc = doc
        self.policy_hash = sha256_hex(_dump(doc))
        self._patterns: dict[str, re.Pattern[str]] = {}
        self._by_agent: dict[str, list[RuleSpec]] = {}
        for r in doc.rules:
            for p in [*r.when.all, *r.when.any]:
                if p.op == "matches":
                    self._patterns[p.value] = re.compile(p.value)
            if r.when.tool and r.when.tool.op == "matches":
                self._patterns[r.when.tool.value] = re.compile(r.when.tool.value)
        # Deterministic order: strongest action first, then severity, then id.
        self.ordered = sorted(
            doc.rules,
            key=lambda r: (-ACTION_RANK[r.action], -SEVERITY_RANK[r.severity], r.id),
        )
        self.max_window_s = max(
            [r.aggregate.window_s for r in doc.rules if r.aggregate]
            + [r.prior.within_s for r in doc.rules if r.prior]
            + [1]
        )

    @property
    def rules(self) -> list[RuleSpec]:
        return self.doc.rules

    def pattern(self, text: str) -> re.Pattern[str]:
        return self._patterns[text]

    def rules_for(self, agent_id: str) -> list[RuleSpec]:
        cached = self._by_agent.get(agent_id)
        if cached is None:
            cached = [r for r in self.ordered if r.in_scope(agent_id)]
            self._by_agent[agent_id] = cached
        return cached

    def risk_class(self, tool_name: str) -> str | None:
        return self.doc.tools.get(tool_name)

    def agent_detectors(self, agent_id: str) -> AgentDetectors | None:
        """WP37: the agent's detector override, or None."""
        agent = self.doc.agents.get(agent_id)
        return agent.detectors if agent is not None else None

    def effective(self, agent_id: str, consumer_id: Any = None) -> Effective:
        """Mode, detector override and disabled rules for this agent and consumer.

        Resolved as ``consumers[consumer_id] ?? agent`` field by field: a consumer field that is
        set wins, a field left out keeps the agent's value, and rule switches merge (the
        consumer's ``enable`` undoes the agent's ``disable``). An invalid consumer id, or one
        without an entry, gives the agent's own settings."""
        agent = self.doc.agents.get(agent_id)
        if agent is None:
            return Effective()
        active = bool(agent.mode or agent.rules or agent.consumers)
        mode = agent.mode or "enforce"
        detectors = agent.detectors
        disabled = set(agent.rules.disable) if agent.rules else set()
        over = None
        ignored = False
        if consumer_id is not None and agent.consumers:
            over = agent.consumers.get(consumer_id) if valid_consumer_id(consumer_id) else None
            ignored = over is None
        if over is not None:
            mode = over.mode or mode
            detectors = over.detectors or detectors
            if over.rules:
                disabled = (disabled - set(over.rules.enable)) | set(over.rules.disable)
        return Effective(
            mode=mode,
            consumer_id=consumer_id if over is not None else None,
            consumer_ignored=ignored,
            detectors=detectors,
            disabled=frozenset(disabled),
            active=active,
            observe_approved=len(set(agent.observe_approvals)) == 2,
        )

    def tracked_keys(self) -> dict[str, set[str]]:
        """Per tool: the arg paths that aggregates and prior rules group by."""
        out: dict[str, set[str]] = {}
        for r in self.doc.rules:
            if r.aggregate:
                for t in r.counted_tools():
                    keys = out.setdefault(t, set())
                    if r.aggregate.group_by == "customer":
                        keys.add(r.aggregate.customer_arg)
                    keys.update(r.aggregate.also_by)
            if r.prior:
                out.setdefault(r.prior.tool, set()).update(r.prior.match_args)
                for t in r.when.tool.names() if r.when.tool else []:
                    out.setdefault(t, set()).update(r.prior.match_args)
        return out


# ---------------------------------------------------------------- loading


def parse_policy_text(text: str, source: str = "<text>") -> PolicyDoc:
    if len(text.encode("utf-8")) > MAX_POLICY_BYTES:
        raise PolicyError(f"{source}: policy file is larger than {MAX_POLICY_BYTES} bytes")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PolicyError(f"{source}: not valid YAML: {exc}") from exc
    if not isinstance(data, Mapping):
        raise PolicyError(f"{source}: top level must be a mapping")
    try:
        return PolicyDoc.model_validate(data)
    except ValidationError as exc:
        msgs = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10]
        )
        raise PolicyError(f"{source}: {msgs}") from exc


def load_policy_texts(texts: Iterable[tuple[str, str]]) -> Policy:
    docs = [parse_policy_text(text, source) for source, text in texts]
    if not docs:
        raise PolicyError("no policy files found")
    return Policy(_merge(docs))


def load_policy_dir(directory: str | Path) -> Policy:
    """Load and merge every ``*.yaml`` file in ``directory`` (sorted by name)."""
    root = Path(directory).resolve()
    files = sorted(root.glob("*.yaml"))
    texts = []
    for f in files:
        if f.stat().st_size > MAX_POLICY_BYTES:
            raise PolicyError(f"{f.name}: policy file is larger than {MAX_POLICY_BYTES} bytes")
        texts.append((f.name, f.read_text(encoding="utf-8")))
    return load_policy_texts(texts)


def policy_json_schema() -> dict[str, Any]:
    schema = PolicyDoc.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Supervisor gateway policy"
    return schema


# ---------------------------------------------------------------- deploy to the rule table


def _manifest_expression(doc: PolicyDoc) -> dict[str, Any]:
    return _dump(doc, exclude={"rules"})


def deploy_policy(
    policy: Policy, state: StateStore, clock: Clock, git_sha: str | None = None
) -> dict[str, int]:
    """Write the policy into the ``rule`` table. Idempotent.

    * New (rule_id, version) -> insert. Same version with other content -> error
      (bump the version). Rules no longer in the policy get ``effective_to``.
    * Tools, agents, reviewers and admins go into one ``_manifest`` row whose
      version grows when its content changes.
    """
    now = clock.now()
    counts = {"inserted": 0, "updated": 0, "retired": 0}
    active = state.query("rule", {"effective_to": None})
    wanted: dict[tuple[str, int], dict[str, Any]] = {}
    for r in policy.rules:
        expr = r.model_dump(mode="json", by_alias=True)
        wanted[(r.id, r.version)] = {
            "rule_id": r.id,
            "version": r.version,
            "agent_scope": "*" if r.agent_scope == "*" else ",".join(r.agent_scope),
            "expression": expr,
            "action": r.action,
            "fail_mode": r.effective_fail_mode,
            "severity": r.severity,
            "regulation_ref": r.regulation_ref,
            "owner": r.owner,
            "approved_by_1": r.approvals[0] if r.approvals else None,
            "approved_by_2": r.approvals[1] if len(r.approvals) > 1 else None,
        }
    manifest_expr = _manifest_expression(policy.doc)
    current_manifest = [row for row in active if row["rule_id"] == MANIFEST_RULE_ID]
    if current_manifest and current_manifest[0]["expression"] == manifest_expr:
        m_version = int(current_manifest[0]["version"])
    else:
        existing = state.query("rule", {"rule_id": MANIFEST_RULE_ID})
        m_version = max([int(x["version"]) for x in existing] + [0]) + 1
    wanted[(MANIFEST_RULE_ID, m_version)] = {
        "rule_id": MANIFEST_RULE_ID,
        "version": m_version,
        "agent_scope": "*",
        "expression": manifest_expr,
        "action": "log",
        "fail_mode": "closed",
        "severity": "low",
        "regulation_ref": None,
        "owner": "gateway",
        "approved_by_1": None,
        "approved_by_2": None,
    }
    for (rid, ver), base in wanted.items():
        row = {**base, "git_sha": git_sha, "policy_hash": policy.policy_hash}
        existing_row = state.get("rule", {"rule_id": rid, "version": ver})
        if existing_row is None:
            state.insert("rule", {**row, "effective_from": now, "effective_to": None})
            counts["inserted"] += 1
            continue
        if existing_row["expression"] != row["expression"]:
            raise PolicyError(
                f"rule {rid} version {ver} is already deployed with other content; bump the version"
            )
        changes = {}
        if existing_row["policy_hash"] != policy.policy_hash:
            changes["policy_hash"] = policy.policy_hash
        if existing_row["effective_to"] is not None:
            changes["effective_to"] = None
        if git_sha and existing_row.get("git_sha") != git_sha:
            changes["git_sha"] = git_sha
        if changes:
            state.update(
                "rule", {"rule_id": rid, "version": ver}, changes, int(existing_row["row_version"])
            )
            counts["updated"] += 1
    for row in active:
        if (row["rule_id"], int(row["version"])) not in wanted:
            state.update(
                "rule",
                {"rule_id": row["rule_id"], "version": row["version"]},
                {"effective_to": now},
                int(row["row_version"]),
            )
            counts["retired"] += 1
    return counts


def load_deployed(state: StateStore) -> Policy:
    """Rebuild the policy from active ``rule`` rows and check its hash."""
    rows = state.query("rule", {"effective_to": None})
    manifest = [r for r in rows if r["rule_id"] == MANIFEST_RULE_ID]
    if len(manifest) != 1:
        raise PolicyError("no deployed policy (rule table has no active _manifest row)")
    data = dict(manifest[0]["expression"])
    data["rules"] = [r["expression"] for r in rows if r["rule_id"] != MANIFEST_RULE_ID]
    try:
        doc = PolicyDoc.model_validate(data)
    except ValidationError as exc:
        raise PolicyError(f"deployed policy is invalid: {exc.errors()[:3]}") from exc
    policy = Policy(_merge([doc]))
    hashes = {r["policy_hash"] for r in rows}
    if hashes != {policy.policy_hash}:
        raise PolicyError(
            f"deployed policy hash mismatch: rows say {sorted(hashes)}, "
            f"content hashes to {policy.policy_hash}"
        )
    return policy


# ---------------------------------------------------------------- providers


class PolicyProvider(Protocol):
    def current(self) -> Policy:
        """The policy to enforce now. Raises when the policy source is unavailable."""
        ...

    def last_known(self) -> Policy | None:
        """Last policy read successfully (used only to pick a fail mode)."""
        ...


class StaticPolicyProvider:
    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    def current(self) -> Policy:
        return self.policy

    def last_known(self) -> Policy | None:
        return self.policy


class StorePolicyProvider:
    """Reads the deployed policy from the ``rule`` table; re-reads every ``refresh_s``.

    A failed re-read raises (the gateway then applies the fail mode). It does not
    silently keep enforcing a stale copy."""

    def __init__(self, state: StateStore, refresh_s: float = 5.0) -> None:
        self.state = state
        self.refresh_s = refresh_s
        self._policy: Policy | None = None
        self._loaded_at = 0.0
        # WP37 (F11): set by the composition root when detectors are on. Returns the problems of
        # a new policy (bad per-agent detector overrides). A policy with problems is rejected on
        # a reload and the old one stays; the first load raises, like any invalid policy.
        self.validator: Callable[[Policy], list[str]] | None = None
        self.rejected_hash: str | None = None
        self.rejected_reason: str | None = None
        # WP41: called with each policy that is accepted (first load and every changed reload),
        # for audit lines. An error in it is logged, never raised.
        self.on_accept: Callable[[Policy], None] | None = None

    def current(self) -> Policy:
        now = time.monotonic()
        if self._policy is None or now - self._loaded_at >= self.refresh_s:
            policy = load_deployed(self.state)
            if self._policy is None or policy.policy_hash != self._policy.policy_hash:
                problems = self.validator(policy) if self.validator else []
                if problems and self._policy is None:
                    raise PolicyError(_ascii("deployed policy rejected: " + "; ".join(problems)))
                if problems:
                    if self.rejected_hash != policy.policy_hash:  # log once per bad policy
                        log.error(
                            "%s",
                            _ascii(
                                "policy reload rejected, old policy kept: " + "; ".join(problems)
                            ),
                        )
                    self.rejected_hash = policy.policy_hash
                    self.rejected_reason = _ascii("; ".join(problems))
                else:
                    self._policy = policy
                    self.rejected_hash = self.rejected_reason = None
                    if self.on_accept is not None:
                        try:
                            self.on_accept(policy)
                        except Exception as exc:  # noqa: BLE001 - audit must not stop the gate
                            log.error("policy on_accept hook failed: %s", type(exc).__name__)
            self._loaded_at = now
        return self._policy

    def last_known(self) -> Policy | None:
        return self._policy


def deploy_with_retry(
    policy: Policy, state: StateStore, clock: Clock, git_sha: str | None = None, attempts: int = 3
) -> dict[str, int]:
    for i in range(attempts):
        try:
            return deploy_policy(policy, state, clock, git_sha)
        except ConcurrencyError:
            if i == attempts - 1:
                raise
    raise AssertionError("unreachable")


__all__ = [
    "DEFAULT_FAIL_MODE",
    "FACT_PREFIX",
    "Aggregate",
    "AgentManifest",
    "ConsumerOverride",
    "Effective",
    "Policy",
    "PolicyDoc",
    "PolicyError",
    "PolicyProvider",
    "Predicate",
    "Prior",
    "RuleSpec",
    "RuleSwitches",
    "StaticPolicyProvider",
    "StorePolicyProvider",
    "deploy_policy",
    "deploy_with_retry",
    "load_deployed",
    "load_policy_dir",
    "load_policy_texts",
    "money_agent",
    "parse_policy_text",
    "policy_json_schema",
    "valid_consumer_id",
]
