"""Assignment rules (WP-G2, docs/assignment-rules.md): the pure, deterministic part.

``config/assignment_rules.yaml`` holds IF-THEN rules over the fields of an AI system. This module
loads the file with a strict schema (an unknown key fails at load) and evaluates it:

    load_rules(path)  ->  RuleSet                        (rules + sha256 of the file)
    evaluate(ruleset, facts, catalogue)  ->  Evaluation  (assignments, the rules that fired, traces)

``evaluate`` is pure: the same facts and the same file give the same assignments, in the same
order, with the same explanation. No model, no clock, no store. Reading the facts of a system and
saving the result is the work of ``rules_service.RulesService``.

The CLI lives here too::

    python -m supervisor.governance.rules run [--system ID] [--by USER]
    python -m supervisor.governance.rules explain --system ID
    python -m supervisor.governance.rules check            (the file against the catalogues)
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.governance import conditions as cond
from supervisor.governance import model as gm
from supervisor.governance.conditions import FieldSpec, RulesError

KINDS: tuple[str, ...] = ("obligation", "control", "risk", "task", "guardian")
# key in `assign` -> assignment kind
ASSIGN_KEYS: dict[str, str] = {
    "obligations": "obligation",
    "controls": "control",
    "risks": "risk",
    "tasks": "task",
    "guardian_floor": "guardian",
}
RULE_KEYS = ("id", "title", "when", "assign")
MAX_RULES = 200
MAX_IDS = 200
_RULE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\*?$")
_COMPONENT = re.compile(r"^component\.([a-z_]+)\.(count|risk_class)$")
COMPONENT_KINDS: tuple[str, ...] = (
    "agent",
    "model",
    "model_endpoint",
    "tool",
    "mcp_server",
    "dataset",
    "prompt",
    "supplier",
    "entrypoint",
    "system",
)
IMPACT_ORDER: tuple[str, ...] = ("unspecified", "low", "medium", "high")

# Fields of the AI system a rule may use, with their value scales.
_SYSTEM_FIELDS: dict[str, FieldSpec] = {
    "system_type": FieldSpec("enum", gm.SYSTEM_TYPES),
    "org_role": FieldSpec("enum", gm.ORG_ROLES),
    "user_segment": FieldSpec("enum", gm.USER_SEGMENTS),
    "personal_data": FieldSpec("enum", gm.PERSONAL_DATA),
    "money_movement": FieldSpec("bool"),
    "credit_decision": FieldSpec("bool"),
    "human_control": FieldSpec("enum", gm.HUMAN_CONTROLS),
    "lifecycle_stage": FieldSpec("ordered", gm.LIFECYCLE_STAGES),
    "risk_level": FieldSpec("ordered", gm.RISK_LEVELS),
    "decision33_class": FieldSpec("enum", gm.DECISION33_CLASSES),
    "business_impact": FieldSpec("ordered", IMPACT_ORDER),
    "status": FieldSpec("enum", gm.STATUSES),
    "effective_risk_level": FieldSpec("ordered", gm.RISK_LEVELS),
}


def field_spec(name: str) -> FieldSpec | None:
    """The spec of a field a rule may use, or ``None``. Besides the ``ai_system`` columns:
    ``component.<kind>.count`` (a whole number), ``component.tool.risk_class`` (the risk classes
    of the tools the system reaches) and ``effective_risk_level``."""
    spec = _SYSTEM_FIELDS.get(name)
    if spec is not None:
        return spec
    m = _COMPONENT.match(name)
    if m is None:
        return None
    kind, what = m.groups()
    if kind not in COMPONENT_KINDS:
        return None
    if what == "count":
        return FieldSpec("int")
    return FieldSpec("set") if kind == "tool" else None


FIELD_NAMES: tuple[str, ...] = (
    *_SYSTEM_FIELDS,
    *(f"component.{k}.count" for k in COMPONENT_KINDS),
    "component.tool.risk_class",
)


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    when: cond.Node
    assign: Mapping[str, tuple[str, ...]]  # kind -> patterns (an id, or a prefix ending in *)


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    sha256: str
    name: str = "assignment_rules.yaml"


@dataclass(frozen=True)
class Catalogue:
    """The ids a rule may name, by kind. A pattern ending in ``*`` matches a prefix."""

    obligation: frozenset[str] = frozenset()
    control: frozenset[str] = frozenset()
    risk: frozenset[str] = frozenset()
    task: frozenset[str] = frozenset()
    guardian: frozenset[str] = frozenset()

    def ids(self, kind: str) -> frozenset[str]:
        return getattr(self, kind)  # type: ignore[no-any-return]

    def expand(self, kind: str, pattern: str) -> tuple[str, ...]:
        """An exact id stands for itself (even if the catalogue does not list it: a bank control
        may live only in the store); ``PREFIX*`` stands for every listed id with the prefix."""
        if pattern.endswith("*"):
            head = pattern[:-1]
            return tuple(sorted(i for i in self.ids(kind) if i.startswith(head)))
        return (pattern,)


@dataclass(frozen=True)
class Assigned:
    kind: str
    ref_id: str
    rules: tuple[tuple[str, tuple[str, ...]], ...]  # (rule id, fields that fired), by rule id

    @property
    def rule_id(self) -> str:
        return self.rules[0][0]


@dataclass(frozen=True)
class Evaluation:
    assignments: tuple[Assigned, ...]
    fired: tuple[str, ...]  # rule ids that fired, sorted
    traces: Mapping[str, cond.Trace] = field(default_factory=dict)
    facts: Mapping[str, Any] = field(default_factory=dict)

    def of(self, kind: str) -> tuple[Assigned, ...]:
        return tuple(a for a in self.assignments if a.kind == kind)


# ---------------------------------------------------------------------------- loading


def _refs(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise RulesError(f"{where}: must be a non-empty list of ids")
    if len(value) > MAX_IDS:
        raise RulesError(f"{where}: more than {MAX_IDS} ids")
    out: list[str] = []
    for v in value:
        if not isinstance(v, str) or not _REF.match(v):
            raise RulesError(f"{where}: {v!r} is not an id (A-Z a-z 0-9 _ . : -, may end in *)")
        if v == "*":
            raise RulesError(f"{where}: * alone is not allowed; give a prefix")
        if v not in out:
            out.append(v)
    return tuple(out)


def parse_rules(doc: Any, name: str = "assignment_rules.yaml") -> tuple[Rule, ...]:
    """Check the parsed YAML. The file is a list of rules; an unknown key fails."""
    if not isinstance(doc, list):
        raise RulesError(f"{name}: the file must be a list of rules")
    if len(doc) > MAX_RULES:
        raise RulesError(f"{name}: more than {MAX_RULES} rules")
    rules: list[Rule] = []
    seen: set[str] = set()
    for i, item in enumerate(doc):
        where = f"{name} rule {i + 1}"
        if not isinstance(item, Mapping):
            raise RulesError(f"{where}: a rule must be an object")
        unknown = sorted(str(k) for k in set(item) - set(RULE_KEYS))
        if unknown:
            raise RulesError(f"{where}: unknown key: {', '.join(unknown)}")
        rid = item.get("id")
        if not isinstance(rid, str) or not _RULE_ID.match(rid):
            raise RulesError(f"{where}: id must be 1 to 64 characters from A-Z a-z 0-9 _ . : -")
        where = f"{name} rule {rid}"
        if rid in seen:
            raise RulesError(f"{where}: the id is used twice")
        seen.add(rid)
        title = item.get("title", "")
        if not isinstance(title, str) or len(title) > 200:
            raise RulesError(f"{where}: title must be text of 200 characters at most")
        if "when" not in item:
            raise RulesError(f"{where}: when is required")
        when = cond.parse(item["when"], field_spec, f"{where} when")
        assign = item.get("assign")
        if not isinstance(assign, Mapping) or not assign:
            raise RulesError(f"{where}: assign is required (obligations, controls, ...)")
        bad = sorted(str(k) for k in set(assign) - set(ASSIGN_KEYS))
        if bad:
            raise RulesError(
                f"{where}: unknown assign key: {', '.join(bad)} (allowed: {', '.join(ASSIGN_KEYS)})"
            )
        by_kind = {
            ASSIGN_KEYS[k]: _refs(v, f"{where} assign.{k}") for k, v in sorted(assign.items())
        }
        rules.append(Rule(rid, title.strip(), when, by_kind))
    return tuple(rules)


def load_rules(path: Path | str) -> RuleSet:
    """Read ``config/assignment_rules.yaml``. A missing file is a RulesError."""
    p = Path(path)
    if not p.is_file():
        raise RulesError(f"{p.name}: the assignment rules file is missing")
    try:
        raw = p.read_bytes()
        doc = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RulesError(f"{p.name}: cannot read the rules file ({type(exc).__name__})") from None
    return RuleSet(parse_rules(doc, p.name), hashlib.sha256(raw).hexdigest(), p.name)


# ---------------------------------------------------------------------------- evaluation


def evaluate(ruleset: RuleSet, facts: Mapping[str, Any], catalogue: Catalogue) -> Evaluation:
    """Pure and deterministic. Rules run in id order; each assignment keeps every rule that gives
    it and the fields that fired; the list is sorted by (kind, id)."""
    given: dict[tuple[str, str], list[tuple[str, tuple[str, ...]]]] = {}
    fired: list[str] = []
    traces: dict[str, cond.Trace] = {}
    for rule in sorted(ruleset.rules, key=lambda r: r.id):
        trace = cond.evaluate(rule.when, facts, field_spec)
        traces[rule.id] = trace
        if not trace.result:
            continue
        fired.append(rule.id)
        fields = tuple(sorted(cond.support(trace)))
        for kind in KINDS:
            for pattern in rule.assign.get(kind, ()):
                for ref in catalogue.expand(kind, pattern):
                    given.setdefault((kind, ref), []).append((rule.id, fields))
    items = tuple(
        Assigned(kind, ref, tuple(sorted(by)))
        for (kind, ref), by in sorted(
            given.items(), key=lambda kv: (KINDS.index(kv[0][0]), kv[0][1])
        )
    )
    return Evaluation(items, tuple(fired), traces, dict(facts))


def problems(ruleset: RuleSet, catalogue: Catalogue) -> list[str]:
    """Names in the rules that the catalogues do not know: an exact id that is not listed, a
    prefix that matches nothing. A bank-owned control that lives only in the store shows here
    as a note, not as a load error."""
    out: list[str] = []
    for rule in ruleset.rules:
        for kind in KINDS:
            for pattern in rule.assign.get(kind, ()):
                if pattern.endswith("*"):
                    if not catalogue.expand(kind, pattern):
                        out.append(f"{rule.id}: {kind} prefix {pattern} matches nothing")
                elif pattern not in catalogue.ids(kind):
                    out.append(f"{rule.id}: {kind} {pattern} is not in the catalogue")
    return out


def explain_lines(ruleset: RuleSet, ev: Evaluation) -> list[str]:
    """ASCII text of one evaluation: the facts, every rule with the trace of its condition, and
    the assignments with the rules that gave them."""
    lines = [f"rules file {ruleset.name} sha256 {ruleset.sha256[:16]}  rules {len(ruleset.rules)}"]
    lines.append("facts:")
    for name in sorted(ev.facts):
        v = ev.facts[name]
        shown = ",".join(map(str, v)) if isinstance(v, (tuple, list, set, frozenset)) else v
        lines.append(f"  {name} = {shown}")
    for rule in sorted(ruleset.rules, key=lambda r: r.id):
        tr = ev.traces.get(rule.id)
        verdict = "FIRED" if tr is not None and tr.result else "no"
        lines.append(f"rule {rule.id}: {verdict}" + (f"  ({rule.title})" if rule.title else ""))
        if tr is not None:
            lines += ["  " + ln for ln in cond.render(tr)]
    lines.append(f"assignments ({len(ev.assignments)}):")
    for a in ev.assignments:
        why = "; ".join(f"{rid} [{', '.join(f)}]" for rid, f in a.rules)
        lines.append(f"  {a.kind:10} {a.ref_id}  <- {why}")
    return [ln.encode("ascii", "replace").decode("ascii") for ln in lines]


def facts_of(
    system: Mapping[str, Any],
    effective_risk_level: str,
    counts: Mapping[str, int],
    tool_classes: Sequence[str],
) -> dict[str, Any]:
    """The facts a rule can see, from the ``ai_system`` row and what the parts add. Pure."""

    def on(v: Any) -> bool:
        return v.strip().lower() in ("1", "true") if isinstance(v, str) else bool(v)

    facts: dict[str, Any] = {k: system.get(k) for k in _SYSTEM_FIELDS if k in system}
    facts["money_movement"] = on(system.get("money_movement"))
    facts["credit_decision"] = on(system.get("credit_decision"))
    facts["effective_risk_level"] = effective_risk_level
    for kind in COMPONENT_KINDS:
        facts[f"component.{kind}.count"] = int(counts.get(kind, 0))
    facts["component.tool.risk_class"] = tuple(sorted(set(tool_classes)))
    return facts


# ---------------------------------------------------------------------------- CLI


def _say(text: str) -> None:
    print(text.encode("ascii", "replace").decode("ascii"))  # noqa: T201


def main(argv: list[str] | None = None) -> int:
    import argparse

    from supervisor.bootstrap import bootstrap

    bootstrap()
    from supervisor.core.errors import SupervisorError

    ap = argparse.ArgumentParser(prog="python -m supervisor.governance.rules", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="evaluate the rules and save the assignments")
    p.add_argument("--system", default="", help="one system id (default: every open system)")
    p.add_argument("--by", default="cli", help="who runs it (written to the chain as a keyed hash)")
    p = sub.add_parser("explain", help="print the trace of the rules for one system")
    p.add_argument("--system", required=True)
    sub.add_parser("check", help="check the rules file against the catalogues")
    args = ap.parse_args(argv)

    from supervisor.config import load_settings

    try:
        settings = load_settings()
        if args.cmd == "check":
            from supervisor.governance.rules_service import build_catalogue

            rs = load_rules(settings.assignment_rules_config)
            notes = problems(rs, build_catalogue(settings))
            for n in notes:
                _say(f"[WARN] {n}")
            _say(f"[OK] {len(rs.rules)} rule(s), sha256 {rs.sha256[:16]}, {len(notes)} note(s)")
            return 0
        if not settings.governance_enabled:
            _say("[SKIP] governance is off (GOVERNANCE_ENABLED=1 turns it on)")
            return 0
        from supervisor.governance.rules_service import RulesService

        if args.cmd == "run":
            from supervisor.monitors.jobctx import standalone

            with standalone(settings) as (_, adapters, ctx):
                svc = RulesService.from_adapters(adapters, evidence=ctx.evidence)
                results = (
                    [svc.run(args.system, args.by, "manual")]
                    if args.system
                    else svc.run_all(args.by, "manual")
                )
            for r in results:
                _say(
                    f"[OK] {r['system_id']}: {r['assigned_n']} assignment(s) from "
                    f"{len(r['rules_fired'])} rule(s); added {r['added_n']}, "
                    f"deactivated {r['deactivated_n']}"
                )
            _say(f"[OK] {len(results)} system(s) evaluated")
            return 0
        from supervisor.adapters.factory import build_adapters
        from supervisor.jobs import bootstrap_schema

        adapters = build_adapters(settings)
        try:
            if adapters.executor.dialect == "sqlite":
                bootstrap_schema.run(settings, adapters)
            for line in RulesService.from_adapters(adapters).explain(args.system):
                _say(line)
        finally:
            adapters.close()
        return 0
    except (SupervisorError, OSError) as exc:
        _say(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
