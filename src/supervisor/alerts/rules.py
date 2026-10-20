"""Alert rules: declarative YAML, validated, never evaluated as code (WP21, ADR D15).

``config/alerts.yaml``::

    version: 1
    rules:
      - id: AL-BLOCK-BURST            # stable id, shows in every alert and SIEM event
        title: Block burst            # fixed text (no free text from events)
        source: gate_decision         # which signal stream (SOURCES)
        where: {action: block}        # equality or "any of" list on signal fields
        group_by: agent_id            # one counter per value; "none" = one counter overall
        window_s: 600                 # count the last window_s seconds
        threshold: 5                  # fire when the count reaches this
        severity: high                # low | medium | high | critical
        dedupe_s: 1800                # after a fire, repeats inside this time only count
        routes: [inbox, siem]         # inbox | siem | webhook | pager
    suppressions:                     # planned maintenance; deterministic, time-boxed
      - {rule_id: AL-BLOCK-BURST, agent_id: pay-test, until: "2026-11-01T00:00:00Z",
         reason_code: planned_test}

The loader checks every field and reports all problems at once. The ``rule_hash`` of each
rule (SHA-256 of its canonical JSON) goes into every alert it raises, so a reviewer can see
which version of the rule fired.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.canonical import sha256_hex
from supervisor.core.errors import SupervisorError

SEVERITIES = ("low", "medium", "high", "critical")
ROUTES = ("inbox", "siem", "webhook", "pager")
# signal kind -> fields a rule may filter on (see signals.py)
SOURCES: dict[str, tuple[str, ...]] = {
    "gate_decision": ("agent_id", "action", "rule_id", "allow"),
    "gate_state_change": ("agent_id", "event", "to_state"),
    "verdict": ("agent_id", "tier", "label", "action", "rule_id", "is_mock"),
    "job_run": ("job", "status"),
    "chain_verify": ("ok",),
    "ingress_reject": ("agent_id", "reason_code"),
    "failmode_drill": ("ok",),
    "case": ("agent_id", "severity"),
}
GROUP_BY = ("none", "agent_id", "job", "rule_id")
MAX_WINDOW_S = 7 * 86400
_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,40}$")
_REASON = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class AlertConfigError(SupervisorError):
    """``alerts.yaml`` is wrong. The message lists every problem (CLI exit 1, never a 500)."""


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    source: str
    where: tuple[tuple[str, tuple[Any, ...]], ...]
    group_by: str
    window_s: int
    threshold: int
    severity: str
    dedupe_s: int
    routes: tuple[str, ...]
    rule_hash: str

    def matches(self, fields: Mapping[str, Any]) -> bool:
        for name, allowed in self.where:
            if fields.get(name) not in allowed:
                return False
        return True

    def group_of(self, fields: Mapping[str, Any]) -> str:
        if self.group_by == "none":
            return "*"
        value = fields.get(self.group_by)
        return str(value) if value not in (None, "") else "-"


@dataclass(frozen=True)
class Suppression:
    rule_id: str  # a rule id or "*"
    agent_id: str  # an agent id or "*"
    until: datetime
    reason_code: str


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    suppressions: tuple[Suppression, ...]
    config_hash: str

    def get(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)

    @property
    def max_window_s(self) -> int:
        return max((r.window_s for r in self.rules), default=0)

    def suppressed(self, rule_id: str, agent_id: str | None, now: datetime) -> Suppression | None:
        for s in self.suppressions:
            if s.until <= now:
                continue
            if s.rule_id in ("*", rule_id) and s.agent_id in ("*", agent_id):
                return s
        return None


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return None  # a time without a zone is ambiguous: refuse
    from datetime import UTC

    return dt.astimezone(UTC)


def _rule(raw: Any, i: int, errors: list[str]) -> Rule | None:
    where_s = f"rules[{i}]"
    if not isinstance(raw, dict):
        errors.append(f"{where_s}: must be a mapping")
        return None
    rid = str(raw.get("id", ""))
    where_s = f"rule {rid or i}"
    known = {
        "id", "title", "source", "where", "group_by", "window_s", "threshold",
        "severity", "dedupe_s", "routes", "enabled",
    }  # fmt: skip
    for k in sorted(set(raw) - known):
        errors.append(f"{where_s}: unknown key {k!r}")
    n0 = len(errors)
    if not _ID.match(rid):
        errors.append(f"{where_s}: id must match {_ID.pattern}")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        errors.append(f"{where_s}: title must be a short text")
    source = raw.get("source")
    if source not in SOURCES:
        errors.append(f"{where_s}: source must be one of {', '.join(SOURCES)}")
    conds: list[tuple[str, tuple[Any, ...]]] = []
    where = raw.get("where", {})
    if not isinstance(where, dict):
        errors.append(f"{where_s}: where must be a mapping")
        where = {}
    for name, val in sorted(where.items()):
        if source in SOURCES and name not in SOURCES[source]:
            errors.append(f"{where_s}: where field {name!r} is not a field of {source}")
            continue
        vals = tuple(val) if isinstance(val, list) else (val,)
        if not vals or not all(isinstance(v, (str, int, bool)) for v in vals):
            errors.append(f"{where_s}: where {name} must be text, number, bool or a list of them")
            continue
        conds.append((str(name), vals))
    group_by = raw.get("group_by", "none")
    if group_by not in GROUP_BY:
        errors.append(f"{where_s}: group_by must be one of {', '.join(GROUP_BY)}")
    elif group_by != "none" and source in SOURCES and group_by not in SOURCES[source]:
        errors.append(f"{where_s}: group_by {group_by} is not a field of {source}")
    window_s = raw.get("window_s", 0)
    threshold = raw.get("threshold", 1)
    dedupe_s = raw.get("dedupe_s", 0)
    for name, val, lo, hi in (
        ("window_s", window_s, 0, MAX_WINDOW_S),
        ("threshold", threshold, 1, 100000),
        ("dedupe_s", dedupe_s, 0, MAX_WINDOW_S),
    ):
        if isinstance(val, bool) or not isinstance(val, int) or not lo <= val <= hi:
            errors.append(f"{where_s}: {name} must be an integer {lo}..{hi}")
    if isinstance(threshold, int) and threshold > 1 and window_s == 0:
        errors.append(f"{where_s}: threshold > 1 needs window_s > 0")
    severity = raw.get("severity")
    if severity not in SEVERITIES:
        errors.append(f"{where_s}: severity must be one of {', '.join(SEVERITIES)}")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        errors.append(f"{where_s}: enabled must be true or false")
    routes = raw.get("routes", ["inbox"])
    if not isinstance(routes, list) or not routes or any(r not in ROUTES for r in routes):
        errors.append(f"{where_s}: routes must be a list from {', '.join(ROUTES)}")
        routes = []
    if len(errors) > n0 or enabled is False:
        return None  # a disabled rule is validated, then left out of the rule set
    body = {
        "id": rid, "title": title, "source": source, "where": {k: list(v) for k, v in conds},
        "group_by": group_by, "window_s": window_s, "threshold": threshold,
        "severity": severity, "dedupe_s": dedupe_s, "routes": sorted(set(routes)),
    }  # fmt: skip
    return Rule(
        id=rid,
        title=str(title),
        source=str(source),
        where=tuple(conds),
        group_by=str(group_by),
        window_s=int(window_s),
        threshold=int(threshold),
        severity=str(severity),
        dedupe_s=int(dedupe_s),
        routes=tuple(body["routes"]),
        rule_hash=sha256_hex(body),
    )


def parse_rules(doc: Any) -> RuleSet:
    errors: list[str] = []
    if not isinstance(doc, dict):
        raise AlertConfigError("alerts.yaml must be a mapping with a 'rules' list")
    if doc.get("version") != 1:
        errors.append("version must be 1")
    for k in sorted(set(doc) - {"version", "rules", "suppressions"}):
        errors.append(f"unknown top-level key {k!r}")
    raw_rules = doc.get("rules")
    if not isinstance(raw_rules, list):
        raise AlertConfigError("alerts.yaml: 'rules' must be a list")
    rules: list[Rule] = []
    for i, raw in enumerate(raw_rules):
        r = _rule(raw, i, errors)
        if r is not None:
            if any(x.id == r.id for x in rules):
                errors.append(f"rule {r.id}: duplicate id")
            else:
                rules.append(r)
    ids = {r.id for r in rules} | {
        str(raw.get("id"))
        for raw in raw_rules
        if isinstance(raw, dict) and raw.get("enabled") is False
    }  # a suppression may name a disabled rule
    sups: list[Suppression] = []
    for j, raw in enumerate(doc.get("suppressions") or []):
        if not isinstance(raw, dict):
            errors.append(f"suppressions[{j}]: must be a mapping")
            continue
        for k in sorted(set(raw) - {"rule_id", "agent_id", "until", "reason_code"}):
            errors.append(f"suppressions[{j}]: unknown key {k!r}")
        until = _as_utc(raw.get("until"))
        rid, aid = str(raw.get("rule_id", "")), str(raw.get("agent_id", ""))
        reason = str(raw.get("reason_code", ""))
        if until is None:
            errors.append(f"suppressions[{j}]: until must be an RFC 3339 time with a zone")
        if rid != "*" and rid not in ids:
            errors.append(f"suppressions[{j}]: rule_id {rid!r} is not a rule (or use '*')")
        if not aid:
            errors.append(f"suppressions[{j}]: agent_id is required (or '*')")
        if not _REASON.match(reason):
            errors.append(f"suppressions[{j}]: reason_code must be a short code like planned_test")
        if until is not None and rid and aid and _REASON.match(reason):
            sups.append(Suppression(rid, aid, until, reason))
    if errors:
        raise AlertConfigError("alerts.yaml: " + "; ".join(errors))
    return RuleSet(
        rules=tuple(rules),
        suppressions=tuple(sups),
        config_hash=sha256_hex({"rules": [r.rule_hash for r in rules]}),
    )


def load_rules(path: Path) -> RuleSet:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise AlertConfigError(f"cannot read {path}: {type(exc).__name__}") from exc
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AlertConfigError(f"{path}: not valid YAML ({type(exc).__name__})") from exc
    return parse_rules(doc)


__all__ = [
    "GROUP_BY",
    "ROUTES",
    "SEVERITIES",
    "SOURCES",
    "AlertConfigError",
    "Rule",
    "RuleSet",
    "Suppression",
    "load_rules",
    "parse_rules",
]
