"""Classification tree (WP-C1 of phase 12, docs/classification.md): the pure, deterministic part.

``config/classification.yaml`` lists the nodes of the tree, the outcomes and the re-classification
triggers. This module loads it with a strict schema and walks it:

    load_tree(path)                 -> Tree
    walk(tree, answers, facts, d33) -> Walk        (the path, the outcome, the node still open)
    article_in_kb(kb, instrument, ref) -> bool     (does RegKB hold the article?)

Nothing here reads a store or calls a model. A node is answered by a person, by a deterministic
``prefill`` rule over the fields of the AI system, or (the node with ``subflow: decision33``) by
the Decision 33 flow. A bad file raises ``RulesError`` that names the field.
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
from supervisor.governance.conditions import RulesError
from supervisor.governance.rules import field_spec

ANSWERS: tuple[str, ...] = ("yes", "no", "excluded")
SUBFLOW_ANSWERS: tuple[str, ...] = ("high_risk", "not_high_risk")
SOURCES: tuple[str, ...] = ("rules", "person", "decision33")
OUTCOME_IDS: tuple[str, ...] = (
    "not_system",
    "prohibited",
    "high_certify",
    "high_self",
    "medium",
    "low",
)
THRESHOLD_KEYS: tuple[str, ...] = (
    "personal_per_transaction_vnd",
    "personal_per_day_vnd",
    "organisation_per_transaction_vnd",
    "organisation_per_day_vnd",
    "credit_vnd",
)
SUBFLOWS: tuple[str, ...] = ("decision33",)
_NODE_ID = re.compile(r"^N-[A-Z0-9-]{1,40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_INSTRUMENT = re.compile(r"^(VN|INTL|INT)-[A-Z0-9]+(-[A-Z0-9]+){0,3}$")
MAX_TEXT = 1200
MAX_POINTER = 200
MAX_NOTE = 300


@dataclass(frozen=True)
class Article:
    instrument: str
    ref: str

    @property
    def text(self) -> str:
        return f"{self.instrument} {self.ref}"


@dataclass(frozen=True)
class Prefill:
    when: cond.Node
    answer: str


@dataclass(frozen=True)
class TreeNode:
    id: str
    question_en: str
    question_vi: str
    article: Article
    see: tuple[Article, ...]
    answers: Mapping[str, str]
    prefill: Prefill | None
    subflow: str | None
    evidence_hint: str


@dataclass(frozen=True)
class Duty:
    id: str
    article: Article
    text_en: str


@dataclass(frozen=True)
class Outcome:
    id: str
    label_en: str
    label_vi: str
    level: str | None
    duties: tuple[Duty, ...]


@dataclass(frozen=True)
class Trigger:
    id: str
    article: Article
    text_en: str
    text_vi: str


@dataclass(frozen=True)
class Tree:
    start: str
    thresholds: Mapping[str, int]
    nodes: Mapping[str, TreeNode]
    outcomes: Mapping[str, Outcome]
    retriggers: tuple[Trigger, ...]
    not_triggers: tuple[Trigger, ...]
    sha256: str
    illustrative: bool = True

    def node(self, node_id: str) -> TreeNode:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise RulesError(f"unknown node {node_id}") from None

    def articles(self) -> list[tuple[str, Article]]:
        """Every article the file cites, with where it is cited (for the RegKB check)."""
        out: list[tuple[str, Article]] = []
        for n in self.nodes.values():
            out.append((f"node {n.id}", n.article))
            out.extend((f"node {n.id} see", a) for a in n.see)
        for o in self.outcomes.values():
            out.extend((f"outcome {o.id} duty {d.id}", d.article) for d in o.duties)
        out.extend((f"trigger {t.id}", t.article) for t in (*self.retriggers, *self.not_triggers))
        return out


@dataclass(frozen=True)
class Step:
    """One step of a path. ``source`` is rules (a prefill rule), person or decision33."""

    node: str
    answer: str
    source: str
    evidence: str = ""
    note: str = ""
    next: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Walk:
    steps: tuple[Step, ...]
    outcome: str | None
    pending: str | None  # id of the first node that has no answer yet
    pending_reason: str = ""

    @property
    def complete(self) -> bool:
        return self.outcome is not None


class TreeAnswerError(RulesError):
    """A bad answer for a node (the service turns it into HTTP 400 ``bad_answer``)."""


# ----------------------------------------------------------------------------- loading


def _text(value: Any, where: str, *, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise RulesError(f"{where}: must be text of 1 to {limit} characters")
    return value.strip()


def _strict(item: Any, allowed: tuple[str, ...], where: str) -> Mapping[Any, Any]:
    if not isinstance(item, Mapping):
        raise RulesError(f"{where}: must be an object")
    unknown = sorted(str(k) for k in set(item) - set(allowed))
    if unknown:
        raise RulesError(f"{where}: unknown key: {', '.join(unknown)}")
    return item


def _yn(value: Any) -> Any:
    """An unquoted yes or no is a YAML boolean: read it as text."""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return value


def _article(item: Any, where: str) -> Article:
    a = _strict(item, ("instrument", "ref"), where)
    inst = a.get("instrument")
    if not isinstance(inst, str) or not _INSTRUMENT.match(inst):
        raise RulesError(f"{where}: instrument must be a RegKB instrument id")
    return Article(inst, _text(a.get("ref"), f"{where} ref", limit=80))


def _nodes(raw: Any, name: str) -> dict[str, TreeNode]:
    if not isinstance(raw, list) or not raw:
        raise RulesError(f"{name}: nodes must be a non-empty list")
    out: dict[str, TreeNode] = {}
    for i, item in enumerate(raw):
        where = f"{name} node {i + 1}"
        n = _strict(
            item,
            (
                "id",
                "question_en",
                "question_vi",
                "article",
                "see",
                "answers",
                "prefill",
                "subflow",
                "evidence_hint",
            ),
            where,
        )
        nid = n.get("id")
        if not isinstance(nid, str) or not _NODE_ID.match(nid):
            raise RulesError(f"{where}: id must look like N-NAME (A-Z 0-9 -)")
        if nid in out:
            raise RulesError(f"{where}: the id {nid} is used twice")
        where = f"{name} node {nid}"
        subflow = n.get("subflow")
        if subflow is not None and subflow not in SUBFLOWS:
            raise RulesError(f"{where}: subflow must be one of {', '.join(SUBFLOWS)}")
        raw_answers = n.get("answers")
        if not isinstance(raw_answers, Mapping) or not raw_answers:
            raise RulesError(f"{where}: answers must be a non-empty object")
        answers: dict[str, str] = {}
        for k, v in raw_answers.items():
            key = _yn(k)
            allowed = SUBFLOW_ANSWERS if subflow else ANSWERS
            if key not in allowed:
                raise RulesError(f"{where}: answer {k} is not one of {', '.join(allowed)}")
            if not isinstance(v, str) or not v:
                raise RulesError(f"{where}: answer {key} must name a node or an outcome")
            answers[str(key)] = v
        if subflow and set(answers) != set(SUBFLOW_ANSWERS):
            raise RulesError(f"{where}: a sub-flow node needs {', '.join(SUBFLOW_ANSWERS)}")
        prefill = None
        if n.get("prefill") is not None:
            p = _strict(n["prefill"], ("when", "answer"), f"{where} prefill")
            ans = _yn(p.get("answer"))
            if subflow:
                raise RulesError(f"{where}: a sub-flow node has no prefill")
            if ans not in answers:
                raise RulesError(f"{where} prefill: answer must be one of {', '.join(answers)}")
            prefill = Prefill(
                cond.parse(_fix_bool_leaves(p.get("when")), field_spec, f"{where} prefill when"),
                str(ans),
            )
        see_raw = n.get("see") or []
        if not isinstance(see_raw, list):
            raise RulesError(f"{where}: see must be a list")
        out[nid] = TreeNode(
            nid,
            _text(n.get("question_en"), f"{where} question_en"),
            _text(n.get("question_vi"), f"{where} question_vi"),
            _article(n.get("article"), f"{where} article"),
            tuple(_article(a, f"{where} see") for a in see_raw),
            answers,
            prefill,
            subflow,
            _text(n.get("evidence_hint"), f"{where} evidence_hint"),
        )
    return out


def _fix_bool_leaves(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: (_yn(v) if k == "eq" else _fix_bool_leaves(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [_fix_bool_leaves(v) for v in node]
    return node


def _outcomes(raw: Any, name: str) -> dict[str, Outcome]:
    if not isinstance(raw, list) or not raw:
        raise RulesError(f"{name}: outcomes must be a non-empty list")
    out: dict[str, Outcome] = {}
    for i, item in enumerate(raw):
        where = f"{name} outcome {i + 1}"
        o = _strict(item, ("id", "label_en", "label_vi", "level", "duties"), where)
        oid = o.get("id")
        if oid not in OUTCOME_IDS or oid in out:
            raise RulesError(f"{where}: id must be one of {', '.join(OUTCOME_IDS)}, once")
        level = o.get("level")
        if level is not None and level not in gm.RISK_LEVELS:
            raise RulesError(f"{where}: level must be null or one of {', '.join(gm.RISK_LEVELS)}")
        duties: list[Duty] = []
        for j, d in enumerate(o.get("duties") or []):
            dw = f"{where} duty {j + 1}"
            dd = _strict(d, ("id", "article", "text_en"), dw)
            did = dd.get("id")
            if not isinstance(did, str) or not _ID.match(did):
                raise RulesError(f"{dw}: id must be 1 to 64 characters from A-Z a-z 0-9 _ . : -")
            duties.append(
                Duty(
                    did, _article(dd.get("article"), f"{dw} article"), _text(dd.get("text_en"), dw)
                )
            )
        out[str(oid)] = Outcome(
            str(oid),
            _text(o.get("label_en"), f"{where} label_en"),
            _text(o.get("label_vi"), f"{where} label_vi"),
            level,
            tuple(duties),
        )
    missing = [x for x in OUTCOME_IDS if x not in out]
    if missing:
        raise RulesError(f"{name}: outcomes missing: {', '.join(missing)}")
    return out


def _triggers(raw: Any, name: str, what: str) -> tuple[Trigger, ...]:
    if not isinstance(raw, list) or not raw:
        raise RulesError(f"{name}: {what} must be a non-empty list")
    out: list[Trigger] = []
    for i, item in enumerate(raw):
        where = f"{name} {what} {i + 1}"
        t = _strict(item, ("id", "article", "text_en", "text_vi"), where)
        tid = t.get("id")
        if not isinstance(tid, str) or not _ID.match(tid) or tid in {x.id for x in out}:
            raise RulesError(f"{where}: id must be unique, 1 to 64 characters")
        out.append(
            Trigger(
                tid,
                _article(t.get("article"), f"{where} article"),
                _text(t.get("text_en"), f"{where} text_en"),
                _text(t.get("text_vi"), f"{where} text_vi"),
            )
        )
    return tuple(out)


def _check_graph(
    start: str, nodes: Mapping[str, TreeNode], outcomes: Mapping[str, Outcome]
) -> None:
    """Every target exists, there is no loop, and every path from the start ends in an outcome."""
    if start not in nodes:
        raise RulesError(f"start {start} is not a node")
    for n in nodes.values():
        for ans, target in n.answers.items():
            if target not in nodes and target not in outcomes:
                raise RulesError(f"node {n.id}: answer {ans} leads to unknown {target}")
    state: dict[str, int] = {}

    def visit(nid: str) -> None:
        if state.get(nid) == 1:
            raise RulesError(f"node {nid}: the tree has a loop")
        if state.get(nid) == 2:
            return
        state[nid] = 1
        for target in nodes[nid].answers.values():
            if target in nodes:
                visit(target)
        state[nid] = 2

    visit(start)
    unreachable = sorted(set(nodes) - set(state))
    if unreachable:
        raise RulesError(f"nodes not reachable from {start}: {', '.join(unreachable)}")


def parse_tree(doc: Any, raw_sha: str, name: str = "classification.yaml") -> Tree:
    top = _strict(
        doc,
        (
            "version",
            "illustrative",
            "start",
            "thresholds",
            "nodes",
            "outcomes",
            "retriggers",
            "not_triggers",
        ),
        name,
    )
    if top.get("version") != 1:
        raise RulesError(f"{name}: version must be 1")
    th = _strict(top.get("thresholds"), THRESHOLD_KEYS, f"{name} thresholds")
    thresholds: dict[str, int] = {}
    for key in THRESHOLD_KEYS:
        val = th.get(key)
        if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
            raise RulesError(f"{name} thresholds: {key} must be a whole number of VND above 0")
        thresholds[key] = val
    nodes = _nodes(top.get("nodes"), name)
    outcomes = _outcomes(top.get("outcomes"), name)
    start = top.get("start")
    if not isinstance(start, str):
        raise RulesError(f"{name}: start must name a node")
    _check_graph(start, nodes, outcomes)
    return Tree(
        start,
        thresholds,
        nodes,
        outcomes,
        _triggers(top.get("retriggers"), name, "retriggers"),
        _triggers(top.get("not_triggers"), name, "not_triggers"),
        raw_sha,
        bool(top.get("illustrative", True)),
    )


def load_tree(path: Path | str) -> Tree:
    p = Path(path)
    if not p.is_file():
        raise RulesError(f"{p.name}: the classification tree file is missing")
    try:
        raw = p.read_bytes()
        doc = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RulesError(f"{p.name}: cannot read the tree file ({type(exc).__name__})") from None
    return parse_tree(doc, hashlib.sha256(raw).hexdigest(), p.name)


# ----------------------------------------------------------------------------- walking


def check_pointer(value: Any, what: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise TreeAnswerError(f"{what} must be text of {limit} characters at most")
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", value):
        raise TreeAnswerError(f"{what} has a control character")
    return value.strip()


def walk(
    tree: Tree,
    answers: Mapping[str, Mapping[str, Any]],
    facts: Mapping[str, Any],
    d33_outcome: str | None,
    d33_extra: Mapping[str, Any] | None = None,
) -> Walk:
    """Follow the tree from the start. A person's answer wins over a prefill rule. The sub-flow
    node takes ``d33_outcome`` (``high_risk``, ``not_high_risk``; anything else keeps it open).
    The walk stops at an outcome or at the first node with no answer."""
    steps: list[Step] = []
    current = tree.start
    for _ in range(len(tree.nodes) + 1):
        node = tree.node(current)
        given = answers.get(current) or {}
        answer: str | None
        source = "person"
        extra: dict[str, Any] = {}
        if node.subflow:
            answer = d33_outcome if d33_outcome in SUBFLOW_ANSWERS else None
            source = "decision33"
            extra = dict(d33_extra or {})
            if answer is None:
                return Walk(tuple(steps), None, node.id, "decision33_open")
        else:
            answer = given.get("answer") or None
            if answer is None and node.prefill is not None:
                tr = cond.evaluate(node.prefill.when, facts, field_spec)
                if tr.result:
                    answer, source = node.prefill.answer, "rules"
            if answer is None:
                return Walk(tuple(steps), None, node.id, "unanswered")
            if answer not in node.answers:
                raise TreeAnswerError(f"{node.id}: answer must be one of {', '.join(node.answers)}")
        nxt = node.answers[str(answer)]
        steps.append(
            Step(
                node.id,
                str(answer),
                source,
                check_pointer(given.get("evidence"), f"{node.id} evidence", MAX_POINTER),
                check_pointer(given.get("note"), f"{node.id} note", MAX_NOTE),
                nxt,
                extra,
            )
        )
        if nxt in tree.outcomes:
            return Walk(tuple(steps), nxt, None)
        current = nxt
    raise RulesError("the tree did not end")  # unreachable: the loader forbids loops


def step_dicts(steps: Sequence[Step]) -> list[dict[str, Any]]:
    out = []
    for s in steps:
        d: dict[str, Any] = {
            "node": s.node,
            "answer": s.answer,
            "source": s.source,
            "evidence": s.evidence,
            "note": s.note,
            "next": s.next,
        }
        if s.extra:
            d["d33"] = dict(s.extra)
        out.append(d)
    return out


# ----------------------------------------------------------------------------- RegKB


def article_in_kb(kb: Any, instrument: str, ref: str) -> bool:
    """True when RegKB holds a row of the instrument for the article: the same reference, a row
    of a part of it (``Art. 4(2)`` and the row ``Art. 4(2)(a)``) or the row of the paragraph it
    is a part of (``Art. 11(1)(a)`` and the row ``Art. 11(1)``)."""
    for o in kb.obligations.values():
        if o.instrument_id != instrument:
            continue
        row = str(o.article_ref)
        if row == ref or row.startswith(ref + "(") or ref.startswith(row + "("):
            return True
    return False
