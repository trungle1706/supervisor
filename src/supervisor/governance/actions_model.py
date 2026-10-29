"""Governance loop model (WP-G5, docs/governance-actions.md): events, rules, planning.

Pure Python. No SQL, no web, no Databricks imports, no clock. An event and the rules file give
the same planned actions every time (a test asserts it). Nothing here can pause or block an
agent: the action vocabulary has no such kind and the loader refuses one by name (rule R1; the
gate already did).

* ``GovernanceEvent``: the one normalised shape of everything the loop reads.
* ``Rule``: one line of ``config/governance_actions.yaml`` (strict schema, unknown keys fail).
* ``plan``: event + rules + facts of the system -> the actions to run, once each, in a fixed order.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.canonical import sha256_hex
from supervisor.core.errors import SupervisorError

EVENT_KINDS: tuple[str, ...] = (
    "alert",
    "gate_stop",
    "detector_failed",
    "monitor_failing",
    "pack_no_go",
    "chain_break",
    "model_version_change",
    "judge_escalation",
    "regkb_changed",  # WP-W2: a law change was applied (REGKB_CHANGE_LOOP)
)
SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(SEVERITIES)}
# Order is the run order: the incident first (the record), then the messages, then the changes.
ACTION_KINDS: tuple[str, ...] = (
    "create_incident",
    "notify_owner",
    "raise_risk_level",
    "move_to_re_evaluation",
    "create_review",
    "fire_webhook",
    "reopen_control",
    "reopen_obligations",  # WP-W2: duty rows back to open, gap tasks
)
# Words a rule author may reach for. The loader names them in its error (rule R1).
FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "pause",
    "block",
    "quarantine",
    "pause_agent",
    "block_agent",
    "quarantine_agent",
    "retire",
    "kill",
)
ACTION_STATUSES: tuple[str, ...] = ("done", "skipped", "refused", "failed", "dry_run")
SYSTEM_ACTIONS: tuple[str, ...] = (
    "raise_risk_level",
    "move_to_re_evaluation",
    "create_review",
    "fire_webhook",
    "reopen_obligations",
)  # these need a system
RULE_KEYS = {
    "id",
    "title",
    "kind",
    "alert_rule",
    "min_severity",
    "system_class",
    "actions",
    "controls",
    "enabled",
}
SYSTEM_CLASS_KEYS = {"decision33_class", "risk_level", "autonomy_level_gte"}
DECISION33_CLASSES = ("high_risk", "not_high_risk", "unclassified")
RISK_LEVELS = ("unspecified", "low", "medium", "high", "prohibited")
MAX_RULES = 200
MAX_CONTROLS = 20

_RULE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_ALERT_RULE = re.compile(r"^[A-Z][A-Z0-9-]{1,63}$")
_CONTROL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_AUTONOMY = re.compile(r"^l?([0-5])$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9_.:@-]")


class GovernanceActionsError(SupervisorError):
    """A bad rules file or a bad input to the governance loop (HTTP 400 / CLI [FAIL])."""


def safe_ref(*parts: Any) -> str:
    """A reference made only of id characters, at most 128 long (long parts are hashed)."""
    text = ":".join(_UNSAFE.sub("_", str(p)) for p in parts)
    if len(text) <= 128:
        return text
    return text[:90] + ":" + sha256_hex({"ref": text})[:24]


def autonomy_rank(value: Any) -> int | None:
    """``l3`` or ``3`` -> 3; anything else (including a missing column) -> None."""
    if isinstance(value, bool) or value is None:
        return None
    m = _AUTONOMY.match(str(value).strip().lower())
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class GovernanceEvent:
    """One normalised event. ``ref`` names the source row (ids only, never text).

    ``rule_id`` is the id of the alert rule, gate rule or assurance pack behind the event (it
    is what a rule's ``alert_rule`` matches and what ``reopen_control`` follows to a control).
    ``evidence`` is ``(kind, target)`` with kind ``rule``, ``pack`` or ``monitor``: the control
    map entry this event contradicts. ``case_id`` links an incident to a case that exists."""

    kind: str
    severity: str
    agent_id: str
    ref: str
    at: datetime
    system_id: str | None = None
    rule_id: str = ""
    case_id: str | None = None
    evidence: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise GovernanceActionsError(f"unknown event kind {self.kind!r}")
        if self.severity not in SEVERITIES:
            raise GovernanceActionsError(f"unknown severity {self.severity!r}")
        if not ID_PATTERN.match(self.ref):
            raise GovernanceActionsError("event ref must be an id (A-Z a-z 0-9 _ . : @ -)")

    @property
    def key(self) -> str:
        """The dedupe key: one per source row and system. Ids only, so it is safe to store."""
        return event_key(self.kind, self.ref, self.system_id)

    def for_system(self, system_id: str | None) -> GovernanceEvent:
        return GovernanceEvent(
            self.kind,
            self.severity,
            self.agent_id,
            self.ref,
            self.at,
            system_id,
            self.rule_id,
            self.case_id,
            self.evidence,
        )

    def sort_key(self) -> tuple[datetime, str, str, str]:
        return (self.at, self.kind, self.ref, self.system_id or "")


def event_key(kind: str, ref: str, system_id: str | None) -> str:
    return sha256_hex({"kind": kind, "ref": ref, "system": system_id or ""})[:32]


@dataclass(frozen=True)
class SystemClass:
    """The filter of a rule on the system the event belongs to."""

    decision33_class: tuple[str, ...] = ()
    risk_level: tuple[str, ...] = ()
    autonomy_level_gte: int | None = None

    def empty(self) -> bool:
        return not (self.decision33_class or self.risk_level or self.autonomy_level_gte is not None)


@dataclass(frozen=True)
class SystemFacts:
    """What the filter looks at, taken from the system row (autonomy_level is WP-G2: None when
    the column does not exist yet)."""

    decision33_class: str = "unclassified"
    risk_level: str = "unspecified"  # the effective level
    autonomy_level: int | None = None


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    kind: str
    min_severity: str
    actions: tuple[str, ...]
    alert_rule: str = ""
    system_class: SystemClass = field(default_factory=SystemClass)
    controls: tuple[str, ...] = ()
    enabled: bool = True


@dataclass(frozen=True)
class PlannedAction:
    action: str
    rules: tuple[str, ...]  # ids of the rules that asked for it
    controls: tuple[str, ...] = ()  # reopen_control: controls named by those rules


# --------------------------------------------------------------------------- loading


def _list_of(value: Any, allowed: Sequence[str], what: str, errors: list[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        errors.append(f"{what}: a non-empty list is required")
        return ()
    out = []
    for item in value:
        if item not in allowed:
            errors.append(f"{what}: {item!r} is not one of {', '.join(allowed)}")
        elif item not in out:
            out.append(item)
    return tuple(out)


def _system_class(raw: Any, where: str, errors: list[str]) -> SystemClass:
    if raw is None:
        return SystemClass()
    if not isinstance(raw, Mapping):
        errors.append(f"{where}.system_class: a mapping is required")
        return SystemClass()
    for key in sorted(set(raw) - SYSTEM_CLASS_KEYS, key=str):
        errors.append(f"{where}.system_class: unknown key {key!r}")
    d33: tuple[str, ...] = ()
    risk: tuple[str, ...] = ()
    auto: int | None = None
    if "decision33_class" in raw:
        d33 = _list_of(
            raw["decision33_class"], DECISION33_CLASSES, f"{where}.decision33_class", errors
        )
    if "risk_level" in raw:
        risk = _list_of(raw["risk_level"], RISK_LEVELS, f"{where}.risk_level", errors)
    if "autonomy_level_gte" in raw:
        auto = autonomy_rank(raw["autonomy_level_gte"])
        if auto is None:
            errors.append(f"{where}.autonomy_level_gte: use l0 to l5 (or 0 to 5)")
    return SystemClass(d33, risk, auto)


def parse_rules(doc: Any, name: str = "governance_actions.yaml") -> list[Rule]:
    """Rules from the parsed YAML. Every problem is collected, then one error lists them all."""
    errors: list[str] = []
    if not isinstance(doc, Mapping):
        raise GovernanceActionsError(f"{name}: the file must be a mapping with a rules list")
    for key in sorted(set(doc) - {"version", "rules"}, key=str):
        errors.append(f"unknown top-level key {key!r}")
    if doc.get("version", 1) != 1:
        errors.append("version must be 1")
    items = doc.get("rules")
    if not isinstance(items, list):
        raise GovernanceActionsError(f"{name}: rules must be a list")
    if len(items) > MAX_RULES:
        errors.append(f"at most {MAX_RULES} rules")
    out: list[Rule] = []
    seen: set[str] = set()
    for i, raw in enumerate(items[:MAX_RULES]):
        where = f"rules[{i}]"
        if not isinstance(raw, Mapping):
            errors.append(f"{where}: a mapping is required")
            continue
        rid = raw.get("id")
        if isinstance(rid, str) and _RULE_ID.match(rid):
            where = f"rule {rid}"
            if rid in seen:
                errors.append(f"{where}: duplicate id")
            seen.add(rid)
        else:
            errors.append(f"{where}: id must be 1 to 64 characters from A-Z a-z 0-9 _ . : -")
            rid = f"rules[{i}]"
        for key in sorted(set(raw) - RULE_KEYS, key=str):
            errors.append(f"{where}: unknown key {key!r}")
        kind = raw.get("kind")
        if kind not in EVENT_KINDS:
            errors.append(f"{where}: kind must be one of {', '.join(EVENT_KINDS)}")
        sev = raw.get("min_severity")
        if sev not in SEVERITIES:
            errors.append(f"{where}: min_severity must be one of {', '.join(SEVERITIES)}")
        title = raw.get("title", "")
        if not isinstance(title, str) or len(title) > 200:
            errors.append(f"{where}: title must be text of 200 characters at most")
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            errors.append(f"{where}: enabled must be true or false")
        actions = raw.get("actions")
        planned: tuple[str, ...] = ()
        if not isinstance(actions, list) or not actions:
            errors.append(f"{where}: actions must be a non-empty list")
        else:
            bad = [a for a in actions if a in FORBIDDEN_ACTIONS]
            if bad:
                errors.append(
                    f"{where}: {', '.join(map(str, bad))} is not an action: a rule never pauses "
                    "or blocks an agent (the gate already did)"
                )
            planned = _list_of(
                [a for a in actions if a not in FORBIDDEN_ACTIONS],
                ACTION_KINDS,
                f"{where}.actions",
                errors,
            )
        alert_rule = raw.get("alert_rule", "")
        if alert_rule:
            if kind != "alert":
                errors.append(f"{where}: alert_rule is only for kind alert")
            elif not isinstance(alert_rule, str) or not _ALERT_RULE.match(alert_rule):
                errors.append(f"{where}: alert_rule must be an alert rule id such as AL-QUARANTINE")
        controls = raw.get("controls", [])
        ctl: tuple[str, ...] = ()
        if controls:
            if "reopen_control" not in planned:
                errors.append(f"{where}: controls is only for the action reopen_control")
            if (
                not isinstance(controls, list)
                or len(controls) > MAX_CONTROLS
                or not all(isinstance(c, str) and _CONTROL_ID.match(c) for c in controls)
            ):
                errors.append(f"{where}: controls must be a list of at most {MAX_CONTROLS} ids")
            else:
                ctl = tuple(sorted(set(controls)))
        sclass = _system_class(raw.get("system_class"), where, errors)
        if kind in EVENT_KINDS and sev in SEVERITIES and isinstance(title, str):
            out.append(
                Rule(
                    id=str(rid),
                    title=title,
                    kind=str(kind),
                    min_severity=str(sev),
                    actions=planned,
                    alert_rule=str(alert_rule or ""),
                    system_class=sclass,
                    controls=ctl,
                    enabled=bool(enabled) if isinstance(enabled, bool) else True,
                )
            )
    if errors:
        raise GovernanceActionsError(f"{name}: " + "; ".join(errors))
    return out


def load_rules(path: Path | str) -> list[Rule]:
    p = Path(path)
    if not p.is_file():
        raise GovernanceActionsError(f"rules file not found: {p.name}")
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise GovernanceActionsError(f"{p.name}: cannot read the rules file") from None
    return parse_rules(doc, p.name)


def rules_digest(rules: Sequence[Rule]) -> str:
    """Hash of the rules in force, for the chain record (the same file gives the same hash)."""
    return sha256_hex(
        [
            {
                "id": r.id,
                "kind": r.kind,
                "alert_rule": r.alert_rule,
                "min": r.min_severity,
                "actions": list(r.actions),
                "controls": list(r.controls),
                "enabled": r.enabled,
                "class": [
                    list(r.system_class.decision33_class),
                    list(r.system_class.risk_level),
                    r.system_class.autonomy_level_gte,
                ],
            }
            for r in rules
        ]
    )


# --------------------------------------------------------------------------- matching


def class_matches(sc: SystemClass, facts: SystemFacts | None) -> bool:
    """An empty filter always matches. A filter needs a system: without facts it never matches,
    and a missing autonomy level (WP-G2 not merged, or not set) fails an autonomy filter."""
    if sc.empty():
        return True
    if facts is None:
        return False
    if sc.decision33_class and facts.decision33_class not in sc.decision33_class:
        return False
    if sc.risk_level and facts.risk_level not in sc.risk_level:
        return False
    if sc.autonomy_level_gte is not None and (
        facts.autonomy_level is None or facts.autonomy_level < sc.autonomy_level_gte
    ):
        return False
    return True


def matches(rule: Rule, event: GovernanceEvent, facts: SystemFacts | None) -> bool:
    if not rule.enabled or rule.kind != event.kind:
        return False
    if SEVERITY_RANK[event.severity] < SEVERITY_RANK[rule.min_severity]:
        return False
    if rule.alert_rule and rule.alert_rule != event.rule_id:
        return False
    return class_matches(rule.system_class, facts)


def plan(
    event: GovernanceEvent, rules: Sequence[Rule], facts: SystemFacts | None
) -> list[PlannedAction]:
    """The actions to run for one event: every action of every matching rule, once each, in the
    fixed ``ACTION_KINDS`` order. Pure and deterministic: the same event, rules and facts give
    the same list. An action that needs a system is left out when the event has none."""
    asked: dict[str, list[str]] = {}
    controls: dict[str, set[str]] = {}
    for rule in sorted(rules, key=lambda r: r.id):
        if not matches(rule, event, facts):
            continue
        for action in rule.actions:
            asked.setdefault(action, []).append(rule.id)
            if action == "reopen_control":
                controls.setdefault(action, set()).update(rule.controls)
    out = []
    for action in ACTION_KINDS:
        if action not in asked:
            continue
        if action in SYSTEM_ACTIONS and event.system_id is None:
            continue
        out.append(
            PlannedAction(action, tuple(asked[action]), tuple(sorted(controls.get(action, ()))))
        )
    return out


__all__ = [
    "ACTION_KINDS",
    "ACTION_STATUSES",
    "EVENT_KINDS",
    "GovernanceActionsError",
    "GovernanceEvent",
    "ID_PATTERN",
    "PlannedAction",
    "Rule",
    "SEVERITIES",
    "SystemClass",
    "SystemFacts",
    "autonomy_rank",
    "class_matches",
    "event_key",
    "load_rules",
    "matches",
    "parse_rules",
    "plan",
    "rules_digest",
    "safe_ref",
]
