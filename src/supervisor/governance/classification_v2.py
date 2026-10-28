"""Classification tree service (WP-C1 of phase 12, CLASSIFICATION_V2, docs/classification.md).

A record is made in two steps by two different people:

1. ``decide``: a person walks the tree (``config/classification.yaml``) and the service stores the
   path and the outcome in ``classification_v2``. Nothing changes on the AI system.
2. ``approve``: another person, who is not the system owner, approves the record (Circular 53
   Art. 4(3)). Only then does the risk level of the system change, by the floor rule of Decision 33
   (a level never goes down here), and the Decision 33 draft of the sub-flow is applied by the
   existing ``ClassificationService.apply``.

The tree node "in the Prime Minister's list" is answered by the Decision 33 flow
(``config/decision33.yaml``): its questions are not repeated in the tree file.

Every change writes a ``classification_v2`` chain record: ids, enums, integers and hashes. No note,
no evidence text and no user id.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Mapping
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core import rbac
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import NotFoundError
from supervisor.governance import classification_tree as ct
from supervisor.governance import decision33 as d33
from supervisor.governance.conditions import RulesError
from supervisor.governance.model import (
    SystemsError,
    check_system_id,
    check_user,
    ensure_on,
    rank,
)

log = logging.getLogger("supervisor.governance")

OFF_MESSAGE = "the classification tree is off (CLASSIFICATION_V2=1 turns it on)"
VALID_DAYS = 365  # Circular 53 Art. 4(5): the inventory is reviewed at least every year
MAX_ANSWERS = 50
PAYLOAD_KEYS = ("answers", "decision33", "inherited_from_provider")
MIN_WHY = 20


class V2Error(SystemsError):
    """A refused step. The message starts with the short code (HTTP 400 at the route)."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def enabled(settings: Any) -> bool:
    return bool(getattr(settings, "classification_v2", False))


def require_on(settings: Any) -> None:
    """HTTP 400 ``classification_v2_off`` unless the flag is on, then GOVERNANCE_ENABLED."""
    if not enabled(settings):
        raise V2Error("classification_v2_off", OFF_MESSAGE)
    ensure_on(settings)


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def _stamp(value: Any) -> Any:
    return format_ts(value) if hasattr(value, "isoformat") else value


def _to_dt(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return None


def record_id(system_id: str, n: int) -> str:
    return "c2_" + sha256_hex({"system": system_id, "n": n})[:20]


def _path_of(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("path_json")
    try:
        val = raw if isinstance(raw, list) else json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [dict(s) for s in val] if isinstance(val, list) else []


class ClassificationV2Service:
    def __init__(
        self,
        state: Any,
        tables: Any,
        clock: Any,
        settings: Any,
        *,
        evidence: Any = None,
        d33_service: Any = None,
    ) -> None:
        self.state = state
        self.tables = tables
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence
        self._d33 = d33_service

    @classmethod
    def from_adapters(
        cls, adapters: Any, evidence: Any = None, d33_service: Any = None
    ) -> ClassificationV2Service:
        return cls(
            adapters.state,
            adapters.tables,
            adapters.clock,
            adapters.settings,
            evidence=evidence,
            d33_service=d33_service,
        )

    # ------------------------------------------------------------------ plumbing
    @property
    def d33(self) -> Any:
        if self._d33 is None:
            from supervisor.governance.classification import ClassificationService

            self._d33 = ClassificationService(
                self.state, self.tables, self.clock, self.settings, evidence=self.evidence_sink
            )
        return self._d33

    def tree(self) -> ct.Tree:
        try:
            return ct.load_tree(self.settings.classification_config)
        except RulesError as exc:
            raise V2Error("tree_invalid", str(exc)) from None

    def _chain(self, ref: str, payload: Mapping[str, Any]) -> None:
        if self.evidence_sink is None:
            return
        try:
            self.evidence_sink.record("classification_v2", ref, payload)
        except Exception:  # noqa: BLE001 - the row is stored; log and go on
            log.exception("classification_v2 chain record failed")

    def _system(self, system_id: str) -> dict[str, Any]:
        check_system_id(system_id)
        row = self.state.get("ai_system", {"system_id": system_id})
        if row is None:
            raise NotFoundError(f"AI system {system_id} does not exist")
        return dict(row)

    def _rows(self, system_id: str) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.state.query("classification_v2", {"system_id": system_id})]
        rows.sort(key=lambda r: str(_stamp(r["created_at"])))
        return rows

    def _facts(self, system_id: str) -> dict[str, Any]:
        from supervisor.governance.rules_service import RulesService

        return RulesService(self.state, self.tables, self.clock, self.settings).system_facts(
            system_id
        )

    def _is_owner(self, system_id: str, uid: str) -> bool:
        row = self.state.get("ai_system", {"system_id": system_id})
        if row is not None and row.get("owner_user") == uid:
            return True
        return any(
            _on(m["active"]) and m["team_role"] == "system_owner"
            for m in self.state.query("system_team", {"system_id": system_id, "user_id": uid})
        )

    def _systems(self) -> Any:
        from supervisor.governance.systems import SystemService

        return SystemService(
            self.state, self.tables, self.clock, self.settings, evidence=self.evidence_sink
        )

    # ------------------------------------------------------------------ the sub-flow
    def _subflow(
        self, facts: Mapping[str, Any], given: Any
    ) -> tuple[str | None, dict[str, Any], d33.Flow]:
        """The Decision 33 sub-flow: answers from the fields of the system, then the answers a
        person gave. Returns the outcome (high_risk, not_high_risk, or None while open)."""
        flow = self.d33.flow()
        answers = d33.derive(flow, facts)
        if given is not None and not isinstance(given, Mapping):
            raise V2Error("bad_answer", "decision33 must be an object of question id -> answer")
        for qid, ch in (given or {}).items():
            if qid not in flow.ids:
                raise V2Error("unknown_node", f"unknown Decision 33 question {str(qid)[:40]}")
            if not isinstance(ch, Mapping) or set(ch) - {"answer", "justification"}:
                raise V2Error("bad_answer", f"{qid}: give answer and justification")
            if ch.get("answer") not in (None, *d33.ANSWERS):
                raise V2Error("bad_answer", f"{qid}: answer must be yes or no")
            try:
                why = d33.check_justification(ch.get("justification"))
            except RulesError as exc:
                raise V2Error("bad_answer", f"{qid}: {exc}") from None
            if "answer" in ch and ch["answer"] is not None:
                answers[qid] = d33.entry(ch["answer"], "person", why)
        dec = d33.decide(flow, answers)
        extra = {
            "outcome": dec.outcome,
            "rule": dec.rule_id or "",
            "flow_sha256": flow.sha256,
            "answers": {
                q: {
                    "answer": a.get("answer"),
                    "source": a.get("source"),
                    "why": str(a.get("justification") or "")[: ct.MAX_NOTE],
                }
                for q, a in sorted(answers.items())
            },
        }
        out = dec.outcome if dec.outcome in ct.SUBFLOW_ANSWERS else None
        return out, extra, flow

    # ------------------------------------------------------------------ walking
    def check_payload(self, tree: ct.Tree, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise V2Error("bad_input", "the request must be a JSON object")
        unknown = sorted(str(k) for k in set(payload) - set(PAYLOAD_KEYS))
        if unknown:
            raise V2Error("bad_input", f"unknown key: {', '.join(unknown)}")
        answers = payload.get("answers") or {}
        if not isinstance(answers, Mapping) or len(answers) > MAX_ANSWERS:
            raise V2Error("bad_input", "answers must be an object of node id -> answer")
        clean: dict[str, dict[str, Any]] = {}
        for nid, item in answers.items():
            if nid not in tree.nodes:
                raise V2Error("unknown_node", f"unknown node {str(nid)[:40]}")
            if not isinstance(item, Mapping) or set(item) - {"answer", "evidence", "note"}:
                raise V2Error("bad_answer", f"{nid}: give answer, evidence and note")
            ans = item.get("answer")
            if ans is not None and ans not in tree.nodes[nid].answers:
                raise V2Error(
                    "bad_answer",
                    f"{nid}: answer must be one of {', '.join(tree.nodes[nid].answers)}",
                )
            if tree.nodes[nid].subflow and ans is not None:
                raise V2Error("bad_answer", f"{nid}: the Decision 33 questions answer this node")
            try:
                clean[str(nid)] = {
                    "answer": ans,
                    "evidence": ct.check_pointer(
                        item.get("evidence"), f"{nid} evidence", ct.MAX_POINTER
                    ),
                    "note": ct.check_pointer(item.get("note"), f"{nid} note", ct.MAX_NOTE),
                }
            except RulesError as exc:
                raise V2Error("bad_answer", str(exc)) from None
        inherited = payload.get("inherited_from_provider", False)
        if not isinstance(inherited, bool):
            raise V2Error("bad_input", "inherited_from_provider must be true or false")
        return {
            "answers": clean,
            "decision33": payload.get("decision33"),
            "inherited_from_provider": inherited,
        }

    def _walk(
        self, tree: ct.Tree, facts: Mapping[str, Any], data: Mapping[str, Any]
    ) -> tuple[ct.Walk, d33.Flow]:
        outcome, extra, flow = self._subflow(facts, data.get("decision33"))
        try:
            walked = ct.walk(tree, data["answers"], facts, outcome, extra)
        except ct.TreeAnswerError as exc:
            raise V2Error("bad_answer", str(exc)) from None
        return walked, flow

    def preview(self, system_id: str, payload: Any) -> dict[str, Any]:
        """Walk the tree with the given answers and the rules; store nothing."""
        require_on(self.settings)
        self._system(system_id)
        tree = self.tree()
        data = self.check_payload(tree, payload)
        walked, flow = self._walk(tree, self._facts(system_id), data)
        return self._walk_view(tree, walked, flow, data)

    def preview_facts(self, facts: Mapping[str, Any], given: Any = None) -> dict[str, Any]:
        """The tree for a system that is not stored yet (Register step 4): the path the rules
        and the given Decision 33 answers (question id -> {answer, justification}) lead to.
        Nothing is stored."""
        tree = self.tree()
        outcome, extra, flow = self._subflow(facts, given)
        walked = ct.walk(tree, {}, facts, outcome, extra)
        return self._walk_view(tree, walked, flow, {"decision33": given})

    def _walk_view(
        self, tree: ct.Tree, walked: ct.Walk, flow: d33.Flow, data: Mapping[str, Any]
    ) -> dict[str, Any]:
        view = tree_view(tree, walked)
        d33_step = next((s for s in walked.steps if s.node in _subflow_nodes(tree)), None)
        view["decision33"] = _d33_form(flow, d33_step, data.get("decision33"))
        view["inherited_from_provider"] = bool(data.get("inherited_from_provider"))
        return view

    # ------------------------------------------------------------------ steps
    def decide(self, system_id: str, user: Any, payload: Any) -> dict[str, Any]:
        """A person stores the path. Refuses a path that does not end in an outcome."""
        require_on(self.settings)
        actor = check_user(str(getattr(user, "user_id", "")), "actor")
        if getattr(user, "kind", "user") != "user":
            raise V2Error("person_required", "deciding a classification needs a signed-in person")
        if not rbac.allowed(frozenset(getattr(user, "roles", ()) or ()), "systems.edit"):
            from supervisor.cases.service import PermissionDenied

            raise PermissionDenied("deciding a classification needs systems.edit")
        system = self._system(system_id)
        if system["status"] == "archived":
            raise V2Error("archived", f"AI system {system_id} is archived; it cannot be classified")
        tree = self.tree()
        data = self.check_payload(tree, payload)
        walked, _flow = self._walk(tree, self._facts(system_id), data)
        if walked.outcome is None:
            raise V2Error(
                "incomplete_path",
                f"the path does not end in an outcome: answer node {walked.pending} "
                f"({walked.pending_reason})",
            )
        now = self.clock.now()
        steps = ct.step_dicts(walked.steps)
        path_hash = sha256_hex([[s["node"], s["answer"], s["source"], s["next"]] for s in steps])
        n = len(self._rows(system_id)) + 1
        stored = self.state.insert(
            "classification_v2",
            {
                "classification_id": record_id(system_id, n),
                "system_id": system_id,
                "outcome": walked.outcome,
                "path_json": json.dumps(steps, sort_keys=True),
                "tree_sha256": tree.sha256,
                "path_hash": path_hash,
                "decided_by": actor,
                "approved_by": None,
                "approved_at": None,
                "inherited_from_provider": data["inherited_from_provider"],
                "valid_until": now + dt.timedelta(days=VALID_DAYS),
                "created_at": now,
            },
        )
        self._changed("decide", dict(stored), actor)
        return self.view(dict(stored), tree)

    def approve(self, system_id: str, user: Any) -> dict[str, Any]:
        """A second person approves the newest record. Sets the risk-level floor and applies the
        Decision 33 draft of the sub-flow."""
        require_on(self.settings)
        actor = check_user(str(getattr(user, "user_id", "")), "actor")
        if getattr(user, "kind", "user") != "user":
            raise V2Error("person_required", "approving a classification needs a signed-in person")
        if not rbac.allowed(frozenset(getattr(user, "roles", ()) or ()), "systems.approve"):
            from supervisor.cases.service import PermissionDenied

            raise PermissionDenied("approving a classification needs systems.approve")
        system = self._system(system_id)
        rows = self._rows(system_id)
        if not rows:
            raise V2Error("no_record", "there is no classification to approve; decide one first")
        row = rows[-1]
        if row["approved_by"]:
            raise V2Error("already_approved", "the newest classification is already approved")
        if row["decided_by"] == actor:
            raise V2Error(
                "same_person",
                f"{actor} decided this classification; another person approves it",
            )
        if self._is_owner(system_id, actor):
            raise V2Error(
                "owner_cannot_approve",
                f"{actor} owns this system and cannot approve its classification",
            )
        tree = self.tree()
        if row["tree_sha256"] != tree.sha256:
            raise V2Error("tree_changed", "the tree file changed since the decision; decide again")
        now = self.clock.now()
        key = {"classification_id": row["classification_id"]}
        stored = self.state.update(
            "classification_v2",
            key,
            {
                "approved_by": actor,
                "approved_at": now,
                "valid_until": now + dt.timedelta(days=VALID_DAYS),
            },
            row["row_version"],
        )
        try:
            level_set = self._effects(system, dict(stored), tree, user, actor)
        except Exception:
            self.state.update(
                "classification_v2",
                key,
                {"approved_by": None, "approved_at": None, "valid_until": row["valid_until"]},
                stored["row_version"],
            )
            raise
        self._changed("approve", dict(stored), actor, {"risk_level_set": level_set})
        return self.view(dict(stored), tree)

    def _effects(
        self,
        system: Mapping[str, Any],
        row: Mapping[str, Any],
        tree: ct.Tree,
        user: Any,
        actor: str,
    ) -> bool:
        """The Decision 33 apply (when the sub-flow matches the outcome) and the level floor."""
        sid = str(system["system_id"])
        outcome = str(row["outcome"])
        sub = next((s for s in _path_of(row) if s.get("source") == "decision33"), None)
        if sub is not None:
            self._apply_d33(sid, row, sub, outcome, user, actor)
        target = tree.outcomes[outcome].level
        if target is None:
            return False
        cur = self._system(sid)
        if rank(cur["risk_level"]) >= rank(target):
            return False
        self._systems().update_fields(
            sid,
            {"risk_level": target, "risk_level_source": "classifier"},
            actor,
            allow_class=True,
        )
        return True

    def _apply_d33(
        self,
        system_id: str,
        row: Mapping[str, Any],
        step: Mapping[str, Any],
        outcome: str,
        user: Any,
        actor: str,
    ) -> None:
        """Make the Decision 33 draft from the sub-flow answers and apply it with the existing
        service. Skipped when the tree overrules the list (high in the list, threshold not met)."""
        info = step.get("d33") or {}
        d33_out = info.get("outcome")
        if d33_out == "high_risk" and not outcome.startswith("high"):
            return
        if d33_out not in ct.SUBFLOW_ANSWERS:
            return
        svc = self.d33
        svc.draft(system_id, actor)
        changes: dict[str, Any] = {}
        for qid, a in sorted((info.get("answers") or {}).items()):
            if a.get("answer") in d33.ANSWERS:
                why = str(a.get("why") or "")
                if len(why) < MIN_WHY:
                    why = f"Answer taken from classification tree record {row['classification_id']}"
                changes[qid] = {"answer": a["answer"], "justification": why}
        if changes:
            svc.edit(system_id, actor, changes)
        draft = svc.get(system_id)["draft"]
        if draft is None or draft["outcome"] != d33_out:
            raise V2Error(
                "decision33_changed",
                "the Decision 33 answers no longer give the same outcome; decide again",
            )
        svc.apply(system_id, user)

    def _changed(
        self,
        action: str,
        row: Mapping[str, Any],
        actor: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "system_id": row["system_id"],
            "classification_id": row["classification_id"],
            "action": action,
            "outcome": row["outcome"],
            "path_hash": row["path_hash"],
            "tree_sha256": row["tree_sha256"],
            "steps_n": len(_path_of(row)),
            "inherited_from_provider": _on(row["inherited_from_provider"]),
            "actor_ref": actor_ref(self.settings, actor, "system"),
            "ts": format_ts(self.clock.now()),
        }
        if extra:
            payload.update(extra)
        self._chain(f"system:{row['system_id']}", payload)

    # ------------------------------------------------------------------ reading
    def view(self, row: Mapping[str, Any], tree: ct.Tree | None = None) -> dict[str, Any]:
        tree = tree or self.tree()
        out = tree.outcomes.get(str(row["outcome"]))
        now = self.clock.now()
        until = _to_dt(row.get("valid_until"))
        return {
            "classification_id": row["classification_id"],
            "system_id": row["system_id"],
            "outcome": row["outcome"],
            "outcome_label_en": out.label_en if out else "",
            "outcome_label_vi": out.label_vi if out else "",
            "level": out.level if out else None,
            "status": "approved" if row.get("approved_by") else "pending_approval",
            "decided_by": row["decided_by"],
            "approved_by": row.get("approved_by"),
            "approved_at": _stamp(row.get("approved_at")),
            "inherited_from_provider": _on(row["inherited_from_provider"]),
            "valid_until": _stamp(row.get("valid_until")),
            "review_due": bool(until is not None and until <= now),
            "created_at": _stamp(row["created_at"]),
            "tree_sha256": row["tree_sha256"],
            "tree_changed": row["tree_sha256"] != tree.sha256,
            "path_hash": row["path_hash"],
            "path": _path_of(row),
        }

    def get(self, system_id: str) -> dict[str, Any]:
        """The newest approved record, the record waiting for approval (newer than the approved
        one), the count of records, and the re-classification triggers."""
        require_on(self.settings)
        self._system(system_id)
        tree = self.tree()
        rows = self._rows(system_id)
        approved = [r for r in rows if r.get("approved_by")]
        cur = approved[-1] if approved else None
        pending = rows[-1] if rows and not rows[-1].get("approved_by") else None
        return {
            "system_id": system_id,
            "tree_sha256": tree.sha256,
            "illustrative": tree.illustrative,
            "current": self.view(cur, tree) if cur else None,
            "pending": self.view(pending, tree) if pending else None,
            "records_n": len(rows),
            "thresholds_vnd": dict(tree.thresholds),
            "retriggers": [_trigger_dict(t) for t in tree.retriggers],
            "not_triggers": [_trigger_dict(t) for t in tree.not_triggers],
        }

    def summary(self, system_ids: Any) -> dict[str, Any]:
        """Counts for the portfolio: per outcome (approved records), waiting for approval, no
        record, and review due. ``system_ids``: ids in the caller's scope."""
        require_on(self.settings)
        tree = self.tree()
        wanted = set(system_ids)
        by_system: dict[str, list[dict[str, Any]]] = {}
        for r in self.state.query("classification_v2", {}):
            if r["system_id"] in wanted:
                by_system.setdefault(str(r["system_id"]), []).append(dict(r))
        counts = {o: 0 for o in tree.outcomes}
        waiting = none = due = 0
        now = self.clock.now()
        for sid in sorted(wanted):
            rows = sorted(by_system.get(sid, []), key=lambda r: str(_stamp(r["created_at"])))
            approved = [r for r in rows if r.get("approved_by")]
            if not rows:
                none += 1
                continue
            if not rows[-1].get("approved_by"):
                waiting += 1
            if approved:
                counts[str(approved[-1]["outcome"])] += 1
                until = _to_dt(approved[-1].get("valid_until"))
                if until is not None and until <= now:
                    due += 1
        return {
            "systems_n": len(wanted),
            "counts": counts,
            "approved_n": sum(counts.values()),
            "waiting_for_approval_n": waiting,
            "no_record_n": none,
            "review_due_n": due,
        }


# ----------------------------------------------------------------------------- views


def _subflow_nodes(tree: ct.Tree) -> set[str]:
    return {n.id for n in tree.nodes.values() if n.subflow}


def _trigger_dict(t: ct.Trigger) -> dict[str, str]:
    return {
        "id": t.id,
        "article": t.article.text,
        "text_en": t.text_en,
        "text_vi": t.text_vi,
    }


def _d33_form(flow: d33.Flow, step: ct.Step | None, given: Any) -> list[dict[str, Any]]:
    """The Decision 33 questions with the answers now in force (for the form)."""
    info = (step.extra.get("answers") if step is not None else None) or {}
    out = []
    for q in flow.questions:
        have = info.get(q.id) or {}
        person = (given or {}).get(q.id) or {}
        out.append(
            {
                "id": q.id,
                "text_en": q.text_en,
                "text_vi": q.text_vi,
                "ref": q.ref,
                "answer": person.get("answer") or have.get("answer"),
                "source": "person" if person.get("answer") else have.get("source") or "person",
                "mine": bool(person.get("answer")) or have.get("source") == "person",
                "why": person.get("justification") or have.get("why") or "",
            }
        )
    return out


def tree_view(tree: ct.Tree, walked: ct.Walk) -> dict[str, Any]:
    """Everything the page needs to draw the tree: the nodes in walk order (the path first as it
    was taken, then the nodes not visited), the edges with the taken one marked, the outcome
    cards and the step each node got."""
    by_node = {s.node: s for s in walked.steps}
    taken_edges = {(s.node, s.answer) for s in walked.steps}
    order: list[str] = []

    def visit(nid: str) -> None:
        if nid in order or nid not in tree.nodes:
            return
        order.append(nid)
        for target in tree.nodes[nid].answers.values():
            visit(target)

    visit(tree.start)
    nodes = []
    for nid in order:
        n = tree.nodes[nid]
        step = by_node.get(nid)
        if step is not None:
            state = "on"
        elif walked.pending == nid:
            state = "open"
        else:
            state = "off"
        nodes.append(
            {
                "id": n.id,
                "question_en": n.question_en,
                "question_vi": n.question_vi,
                "article": n.article.text,
                "see": [a.text for a in n.see],
                "evidence_hint": n.evidence_hint,
                "subflow": n.subflow or "",
                "has_prefill": n.prefill is not None,
                "answers": list(n.answers),
                "state": state,
                "step": (
                    {
                        "answer": step.answer,
                        "source": step.source,
                        "evidence": step.evidence,
                        "note": step.note,
                    }
                    if step is not None
                    else None
                ),
                "edges": [
                    {
                        "answer": a,
                        "target": t,
                        "kind": "node" if t in tree.nodes else "outcome",
                        "taken": (nid, a) in taken_edges,
                    }
                    for a, t in n.answers.items()
                ],
            }
        )
    outcomes = [
        {
            "id": o.id,
            "label_en": o.label_en,
            "label_vi": o.label_vi,
            "level": o.level,
            "reached": walked.outcome == o.id,
            "duties": [
                {"id": d.id, "article": d.article.text, "text_en": d.text_en} for d in o.duties
            ],
        }
        for o in tree.outcomes.values()
    ]
    return {
        "nodes": nodes,
        "outcomes": outcomes,
        "outcome": walked.outcome,
        "pending": walked.pending,
        "pending_reason": walked.pending_reason,
        "complete": walked.complete,
        "thresholds": dict(tree.thresholds),
        "illustrative": tree.illustrative,
        "tree_sha256": tree.sha256,
    }


def payload_from_form(form: Mapping[str, str], tree: ct.Tree, question_ids: Any) -> dict[str, Any]:
    """The answers of the classify form: ``a_<node>``, ``e_<node>`` (evidence), ``n_<node>``
    (note), ``q_<question>`` and ``qj_<question>`` for the Decision 33 sub-flow, and
    ``inherited``."""
    answers: dict[str, Any] = {}
    for nid, node in tree.nodes.items():
        if node.subflow:
            continue
        raw = form.get(f"a_{nid}", "")
        ev, note = form.get(f"e_{nid}", ""), form.get(f"n_{nid}", "")
        if raw or ev or note:
            answers[nid] = {"answer": raw or None, "evidence": ev, "note": note}
    d33_answers: dict[str, Any] = {}
    for qid in question_ids:
        raw = form.get(f"q_{qid}", "")
        if raw:
            d33_answers[qid] = {"answer": raw, "justification": form.get(f"qj_{qid}", "")}
    return {
        "answers": answers,
        "decision33": d33_answers,
        "inherited_from_provider": form.get("inherited", "") in ("1", "true", "on"),
    }
