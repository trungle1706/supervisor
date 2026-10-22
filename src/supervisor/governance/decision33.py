"""Decision 33 question flow (WP-G2, docs/decision33.md): the pure, deterministic part.

``config/decision33.yaml`` lists ordered questions and outcomes. This module loads it with a
strict schema and evaluates it:

    load_flow(path)                    -> Flow
    derive(flow, facts)                -> {question id: answer entry}   (answers from system fields)
    decide(flow, answers)              -> Decision                       (outcome and why)

Nothing here reads a store or calls a model. A question with no ``derive`` is answered by a
person (or pre-filled by the AI, tagged ``ai_prefill``, in ``classification.py``). The outcome is
``high_risk``, ``not_high_risk`` or ``unclassified``. A person applies it; this module never does.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from supervisor.governance import conditions as cond
from supervisor.governance import model as gm
from supervisor.governance.conditions import FieldSpec, RulesError
from supervisor.governance.rules import field_spec

ANSWERS: tuple[str, ...] = ("yes", "no")
SOURCES: tuple[str, ...] = ("rules", "ai_prefill", "person")
OUTCOMES: tuple[str, ...] = ("high_risk", "not_high_risk")
_QID = re.compile(r"^Q-[A-Z0-9-]{1,40}$")
_OID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
MAX_TEXT = 500
MAX_JUSTIFICATION = 500


@dataclass(frozen=True)
class Question:
    id: str
    text_en: str
    text_vi: str
    ref: str
    derive: cond.Node | None


@dataclass(frozen=True)
class OutcomeRule:
    id: str
    outcome: str
    reason: str
    when: cond.Node


@dataclass(frozen=True)
class Flow:
    questions: tuple[Question, ...]
    outcomes: tuple[OutcomeRule, ...]
    complete: str
    incomplete: str
    sha256: str
    illustrative: bool = True

    def question(self, qid: str) -> Question:
        for q in self.questions:
            if q.id == qid:
                return q
        raise RulesError(f"unknown question {qid}")

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(q.id for q in self.questions)


@dataclass(frozen=True)
class Decision:
    outcome: str
    rule_id: str | None
    reason: str
    complete: bool
    traces: Mapping[str, cond.Trace]


def _text(value: Any, where: str, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > MAX_TEXT:
        raise RulesError(f"{where}: must be text of 1 to {MAX_TEXT} characters")
    return value.strip()


def _strict(item: Any, allowed: tuple[str, ...], where: str) -> Mapping[str, Any]:
    if not isinstance(item, Mapping):
        raise RulesError(f"{where}: must be an object")
    unknown = sorted(str(k) for k in set(item) - set(allowed))
    if unknown:
        raise RulesError(f"{where}: unknown key: {', '.join(unknown)}")
    return item


def _question_lookup(ids: tuple[str, ...]) -> Any:
    def lookup(name: str) -> FieldSpec | None:
        return FieldSpec("enum", ANSWERS) if name in ids else None

    return lookup


def _fix_leaves(node: Any) -> Any:
    """In an outcome ``when``, an unquoted yes or no is a YAML boolean: read it as text."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "eq" and isinstance(v, bool):
                out[k] = "yes" if v else "no"
            else:
                out[k] = _fix_leaves(v)
        return out
    if isinstance(node, list):
        return [_fix_leaves(v) for v in node]
    return node


def parse_flow(doc: Any, raw_sha: str, name: str = "decision33.yaml") -> Flow:
    top = _strict(doc, ("version", "illustrative", "questions", "outcomes", "default"), name)
    if top.get("version") != 1:
        raise RulesError(f"{name}: version must be 1")
    qs = top.get("questions")
    if not isinstance(qs, list) or not qs:
        raise RulesError(f"{name}: questions must be a non-empty list")
    questions: list[Question] = []
    for i, item in enumerate(qs):
        where = f"{name} question {i + 1}"
        q = _strict(item, ("id", "text_en", "text_vi", "ref", "derive"), where)
        qid = q.get("id")
        if not isinstance(qid, str) or not _QID.match(qid):
            raise RulesError(f"{where}: id must look like Q-NAME (A-Z 0-9 -)")
        if qid in {x.id for x in questions}:
            raise RulesError(f"{where}: the id {qid} is used twice")
        derive = None
        if q.get("derive") is not None:
            derive = cond.parse(q["derive"], field_spec, f"{where} derive")
        questions.append(
            Question(
                qid,
                _text(q.get("text_en"), f"{where} text_en"),
                _text(q.get("text_vi"), f"{where} text_vi"),
                _text(q.get("ref"), f"{where} ref", required=False),
                derive,
            )
        )
    ids = tuple(q.id for q in questions)
    outs = top.get("outcomes")
    if not isinstance(outs, list) or not outs:
        raise RulesError(f"{name}: outcomes must be a non-empty list")
    rules: list[OutcomeRule] = []
    for i, item in enumerate(outs):
        where = f"{name} outcome {i + 1}"
        o = _strict(item, ("id", "outcome", "reason", "when"), where)
        oid = o.get("id")
        if not isinstance(oid, str) or not _OID.match(oid) or oid in {r.id for r in rules}:
            raise RulesError(
                f"{where}: id must be unique, 1 to 64 characters from A-Z a-z 0-9 _ . : -"
            )
        if o.get("outcome") not in OUTCOMES:
            raise RulesError(f"{where}: outcome must be one of {', '.join(OUTCOMES)}")
        if "when" not in o:
            raise RulesError(f"{where}: when is required")
        when = cond.parse(_fix_leaves(o["when"]), _question_lookup(ids), f"{where} when")
        rules.append(
            OutcomeRule(oid, str(o["outcome"]), _text(o.get("reason"), f"{where} reason"), when)
        )
    default = _strict(top.get("default"), ("complete", "incomplete"), f"{name} default")
    complete, incomplete = default.get("complete"), default.get("incomplete")
    if complete not in gm.DECISION33_CLASSES or incomplete not in gm.DECISION33_CLASSES:
        raise RulesError(f"{name}: default must name classes of {', '.join(gm.DECISION33_CLASSES)}")
    if incomplete != "unclassified":
        raise RulesError(f"{name}: default.incomplete must be unclassified")
    return Flow(
        tuple(questions),
        tuple(rules),
        str(complete),
        str(incomplete),
        raw_sha,
        bool(top.get("illustrative", True)),
    )


def load_flow(path: Path | str) -> Flow:
    p = Path(path)
    if not p.is_file():
        raise RulesError(f"{p.name}: the Decision 33 flow file is missing")
    try:
        raw = p.read_bytes()
        doc = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RulesError(f"{p.name}: cannot read the flow file ({type(exc).__name__})") from None
    return parse_flow(doc, hashlib.sha256(raw).hexdigest(), p.name)


def entry(answer: str | None, source: str, justification: str = "", **extra: Any) -> dict[str, Any]:
    """One answer entry as it is stored: answer (yes, no, or None = not answered), source and
    justification."""
    if answer is not None and answer not in ANSWERS:
        raise RulesError("an answer must be yes or no")
    if source not in SOURCES:
        raise RulesError(f"source must be one of {', '.join(SOURCES)}")
    return {"answer": answer, "source": source, "justification": justification, **extra}


def derive(flow: Flow, facts: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Answers that follow from the fields of the system. A question with no ``derive`` is left
    unanswered (``answer`` None, source ``person``)."""
    out: dict[str, dict[str, Any]] = {}
    for q in flow.questions:
        if q.derive is None:
            out[q.id] = entry(None, "person")
            continue
        tr = cond.evaluate(q.derive, facts, field_spec)
        fields = ", ".join(sorted(cond.support(tr)))
        out[q.id] = entry("yes" if tr.result else "no", "rules", f"from the system field {fields}")
    return out


def decide(flow: Flow, answers: Mapping[str, Mapping[str, Any]]) -> Decision:
    """The first outcome whose condition is true; else the default for a complete or an
    incomplete set of answers. Pure and deterministic."""
    facts = {q.id: (answers.get(q.id) or {}).get("answer") for q in flow.questions}
    traces: dict[str, cond.Trace] = {}
    for rule in flow.outcomes:
        tr = cond.evaluate(rule.when, facts, _question_lookup(flow.ids))
        traces[rule.id] = tr
        if tr.result:
            return Decision(rule.outcome, rule.id, rule.reason, all(facts.values()), traces)
    complete = all(v in ANSWERS for v in facts.values())
    if complete:
        return Decision(
            flow.complete, None, "every question is answered; no high-risk entry", True, traces
        )
    return Decision(flow.incomplete, None, "some questions are not answered yet", False, traces)


def check_justification(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MAX_JUSTIFICATION:
        raise RulesError(f"justification must be text of {MAX_JUSTIFICATION} characters at most")
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", value):
        raise RulesError("justification has a control character")
    return value.strip()
