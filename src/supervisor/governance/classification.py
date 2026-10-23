"""Decision 33 classification service (WP-G2, docs/decision33.md).

A classification is made in three steps, and only the last one changes the AI system:

1. ``draft``: answers come from the fields of the system (source ``rules``). With
   ``CLASSIFIER_AI_PREFILL=1`` the questions that no field can answer may be pre-filled by the
   LLM adapter; every such answer is tagged ``ai_prefill`` (and ``mock`` when the model is the
   mock). A draft never changes the system.
2. ``edit``: a person changes an answer (source ``person``) and gives a justification.
3. ``apply``: a person applies the draft. The service sets ``decision33_class`` and the floor of
   the risk level (high_risk -> at least ``high``). It refuses when the caller is the reviewer or
   oversight manager of the system, when the draft is not complete, or when an ``ai_prefill``
   answer is still unconfirmed. The service never applies a draft by itself.

Every change writes a ``classification_change`` chain record: ids, enums, integers and hashes. No
justification text and no user id.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core import rbac
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import NotFoundError
from supervisor.governance import decision33 as d33
from supervisor.governance.conditions import RulesError
from supervisor.governance.model import (
    SOD_ROLES,
    SegregationOfDuties,
    SystemsError,
    check_system_id,
    check_user,
    ensure_on,
    rank,
)

log = logging.getLogger("supervisor.governance")

PREFILL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["answers"],
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "answer", "justification"],
                "properties": {
                    "id": {"type": "string"},
                    "answer": {"type": "string", "enum": ["yes", "no", "unknown"]},
                    "justification": {"type": "string"},
                },
            },
        }
    },
}
PREFILL_SYSTEM = (
    "You pre-fill a questionnaire about one AI system at a bank. Answer yes or no only when the "
    "description states it; otherwise answer unknown. Never invent facts. A person reviews every "
    "answer and decides. Give one short reason for each answer."
)
MAX_PREFILL_REASON = 300


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def classification_id(system_id: str, n: int) -> str:
    return "cl_" + sha256_hex({"system": system_id, "n": n})[:20]


def _answers_of(row: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = row.get("answers")
    try:
        val = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return {str(k): dict(v) for k, v in val.items()} if isinstance(val, dict) else {}


def _stamp(value: Any) -> Any:
    return format_ts(value) if hasattr(value, "isoformat") else value


class ClassificationService:
    def __init__(
        self,
        state: Any,
        tables: Any,
        clock: Any,
        settings: Any,
        *,
        evidence: Any = None,
        chat: Any = None,
        masker: Any = None,
    ) -> None:
        self.state = state
        self.tables = tables
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence
        self._chat = chat
        self._masker = masker

    @classmethod
    def from_adapters(
        cls, adapters: Any, evidence: Any = None, chat: Any = None, masker: Any = None
    ) -> ClassificationService:
        return cls(
            adapters.state,
            adapters.tables,
            adapters.clock,
            adapters.settings,
            evidence=evidence,
            chat=chat,
            masker=masker,
        )

    # ------------------------------------------------------------------ plumbing
    def _chain(self, record_type: str, ref: str, payload: Mapping[str, Any]) -> None:
        if self.evidence_sink is None:
            return
        try:
            self.evidence_sink.record(record_type, ref, payload)
        except Exception:  # noqa: BLE001 - the row is stored; log and go on
            log.exception("classification chain record failed")

    def flow(self) -> d33.Flow:
        return d33.load_flow(self.settings.decision33_config)

    def _system(self, system_id: str) -> dict[str, Any]:
        check_system_id(system_id)
        row = self.state.get("ai_system", {"system_id": system_id})
        if row is None:
            raise NotFoundError(f"AI system {system_id} does not exist")
        return dict(row)

    def _rows(self, system_id: str) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.state.query("classification", {"system_id": system_id})]
        rows.sort(key=lambda r: str(r["created_at"]))
        return rows

    def _draft_row(self, system_id: str) -> dict[str, Any] | None:
        for r in reversed(self._rows(system_id)):
            if r["status"] == "draft":
                return r
        return None

    def _systems(self) -> Any:
        from supervisor.governance.systems import SystemService

        return SystemService(
            self.state, self.tables, self.clock, self.settings, evidence=self.evidence_sink
        )

    def _changed(
        self,
        action: str,
        row: Mapping[str, Any],
        actor: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        answers = _answers_of(row)
        by_source = {s: 0 for s in d33.SOURCES}
        for a in answers.values():
            if a.get("source") in by_source and a.get("answer") is not None:
                by_source[str(a["source"])] += 1
        payload: dict[str, Any] = {
            "system_id": row["system_id"],
            "classification_id": row["classification_id"],
            "action": action,
            "outcome": row["outcome"],
            "status": row["status"],
            "questions_n": len(answers),
            "answered_n": sum(by_source.values()),
            "answers_by_source": by_source,
            "flow_sha256": row["flow_sha256"],
            "answers_hash": sha256_hex(
                {q: [a.get("answer"), a.get("source")] for q, a in sorted(answers.items())}
            ),
            "justifications_hash": sha256_hex(
                {q: a.get("justification", "") for q, a in sorted(answers.items())}
            ),
            "actor_ref": actor_ref(self.settings, actor, "system"),
            "ts": format_ts(self.clock.now()),
        }
        if extra:
            payload.update(extra)
        self._chain("classification_change", f"system:{row['system_id']}", payload)

    # ------------------------------------------------------------------ views
    def view(self, row: Mapping[str, Any], flow: d33.Flow | None = None) -> dict[str, Any]:
        flow = flow or self.flow()
        answers = _answers_of(row)
        dec = d33.decide(flow, answers)
        return {
            "classification_id": row["classification_id"],
            "system_id": row["system_id"],
            "outcome": row["outcome"],
            "reason": dec.reason,
            "decided_by_rule": dec.rule_id,
            "status": row["status"],
            "created_by": row["created_by"],
            "created_at": _stamp(row["created_at"]),
            "applied_by": row.get("applied_by"),
            "applied_at": _stamp(row.get("applied_at")),
            "flow_sha256": row["flow_sha256"],
            "answers": [
                {
                    "id": q.id,
                    "text_en": q.text_en,
                    "text_vi": q.text_vi,
                    "ref": q.ref,
                    **{
                        "answer": None,
                        "source": "person",
                        "justification": "",
                        **answers.get(q.id, {}),
                    },
                }
                for q in flow.questions
            ],
        }

    def get(self, system_id: str) -> dict[str, Any]:
        """The open draft (or None), the newest applied classification (or None) and the
        history of applied ones."""
        self._system(system_id)
        flow = self.flow()
        rows = self._rows(system_id)
        draft = next((r for r in reversed(rows) if r["status"] == "draft"), None)
        applied = [r for r in rows if r["status"] == "applied"]
        return {
            "system_id": system_id,
            "ai_prefill_enabled": bool(getattr(self.settings, "classifier_ai_prefill", False)),
            "draft": self.view(draft, flow) if draft else None,
            "applied": self.view(applied[-1], flow) if applied else None,
            "history_n": len(applied),
        }

    # ------------------------------------------------------------------ steps
    def draft(self, system_id: str, actor: str) -> dict[str, Any]:
        """Make (or remake) the draft from the rules. A draft already open is replaced: the
        answers go back to what the fields say. Never changes the system."""
        ensure_on(self.settings)
        check_user(actor, "actor")
        system = self._system(system_id)
        if system["status"] == "archived":
            raise SystemsError(f"AI system {system_id} is archived; it cannot be classified")
        flow = self.flow()
        from supervisor.governance.rules_service import RulesService

        facts = RulesService(self.state, self.tables, self.clock, self.settings).system_facts(
            system_id
        )
        answers = d33.derive(flow, facts)
        self._cross_check(system_id, facts, answers)  # WP-P2
        prefill = self._prefill(flow, system, answers)
        dec = d33.decide(flow, answers)
        now = self.clock.now()
        cur = self._draft_row(system_id)
        fields = {
            "outcome": dec.outcome,
            "answers": json.dumps(answers, sort_keys=True),
            "flow_sha256": flow.sha256,
        }
        if cur is None:
            n = len(self._rows(system_id)) + 1
            stored = self.state.insert(
                "classification",
                {
                    "classification_id": classification_id(system_id, n),
                    "system_id": system_id,
                    "status": "draft",
                    "created_by": actor,
                    "created_at": now,
                    **fields,
                },
            )
        else:
            stored = self.state.update(
                "classification",
                {"classification_id": cur["classification_id"]},
                {**fields, "created_by": actor, "created_at": now},
                cur["row_version"],
            )
        extra = {"ai_prefill": bool(prefill["used"]), "mock": bool(prefill["mock"])}
        self._changed("draft", dict(stored), actor, extra)
        out = self.view(dict(stored), flow)
        out["ai_prefill"] = prefill
        return out

    def _cross_check(
        self, system_id: str, facts: Mapping[str, Any], answers: dict[str, dict[str, Any]]
    ) -> None:
        """WP-P2: Q-PRE-APPROVAL "yes" that comes only from the declared human_control is checked
        against the define profile of the linked agents (``profile_check``). Not found in code:
        the question goes back to a person (unanswered, text says why). Found: stays yes, with
        the evidence reference."""
        cur = answers.get("Q-PRE-APPROVAL")
        if (
            cur is None
            or cur.get("answer") != "yes"
            or facts.get("human_control") != "pre_approval"
        ):
            return
        from supervisor.governance.profile_check import check_pre_approval

        agents = [
            str(c["ref_id"])
            for c in self.state.query("system_component", {"system_id": system_id})
            if _on(c["active"]) and c["ref_kind"] == "agent"
        ]
        verdict, text = check_pre_approval(self.settings.data_dir, agents)
        if verdict == "not_found":
            answers["Q-PRE-APPROVAL"] = d33.entry(None, "person", text)
        elif verdict == "confirmed":
            answers["Q-PRE-APPROVAL"] = d33.entry(
                "yes", "rules", f"{cur.get('justification', '')}; {text}"[:500]
            )

    def _prefill(
        self, flow: d33.Flow, system: Mapping[str, Any], answers: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Ask the LLM adapter about the questions no field answers. Advisory: it fills only
        empty answers, tags them ``ai_prefill`` and never decides the outcome by itself."""
        info: dict[str, Any] = {"used": False, "mock": False, "model": None, "answers_n": 0}
        if not getattr(self.settings, "classifier_ai_prefill", False):
            return info
        todo = [q for q in flow.questions if answers[q.id]["answer"] is None]
        chat = self._chat
        if not todo or chat is None:
            return info
        from supervisor.onboard.scrub import scrub_text

        # Only enum fields and the purpose, which is masked for personal data (names, phone,
        # CCCD, accounts: the repo masker) after the secret scrub. The system name is not sent.
        # With no masker (MASKER_KIND=none) the purpose is not sent at all.
        masker = self._masker
        purpose = ""
        if masker is not None:
            purpose = str(masker.mask(scrub_text(str(system["purpose"])).text))
        brief = {
            "purpose": purpose,
            "system_type": system["system_type"],
            "user_segment": system["user_segment"],
            "personal_data": system["personal_data"],
            "human_control": system["human_control"],
        }
        messages = [
            {"role": "system", "content": PREFILL_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {"system": brief, "questions": [{"id": q.id, "text": q.text_en} for q in todo]},
                    sort_keys=True,
                ),
            },
        ]
        mock = bool(getattr(chat, "is_mock", False))
        info.update(used=True, mock=mock, model=str(getattr(chat, "model_id", "")))
        try:
            raw = chat.complete_json(messages, PREFILL_SCHEMA, 60.0)
            items = raw.get("answers") if isinstance(raw, Mapping) else None
        except Exception:  # noqa: BLE001 - the draft stands without a pre-fill
            log.warning("classification pre-fill failed", exc_info=True)
            info["used"] = False
            return info
        ids = {q.id for q in todo}
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, Mapping) or it.get("id") not in ids:
                continue
            if it.get("answer") not in d33.ANSWERS:
                continue
            why = str(it.get("justification") or "")[:MAX_PREFILL_REASON]
            why = ("[mock] " if mock else "") + why
            answers[str(it["id"])] = d33.entry(
                str(it["answer"]),
                "ai_prefill",
                why,
                model=info["model"],
                mock=mock,
            )
            ids.discard(str(it["id"]))
            info["answers_n"] += 1
        return info

    def edit(self, system_id: str, actor: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        """A person changes answers of the open draft. ``changes``: question id -> ``{answer,
        justification}`` (answer ``yes`` or ``no``, or null to clear it). The source becomes
        ``person``."""
        ensure_on(self.settings)
        check_user(actor, "actor")
        self._system(system_id)
        cur = self._draft_row(system_id)
        if cur is None:
            raise SystemsError("there is no draft to edit; make one first")
        if not isinstance(changes, Mapping) or not changes:
            raise SystemsError(
                "answers must be an object of question id -> {answer, justification}"
            )
        flow = self.flow()
        answers = _answers_of(cur)
        for qid, ch in changes.items():
            if qid not in flow.ids:
                raise SystemsError(f"unknown question {str(qid)[:40]}")
            if not isinstance(ch, Mapping) or set(ch) - {"answer", "justification"}:
                raise SystemsError(f"{qid}: give answer and justification")
            if "answer" not in ch:
                raise SystemsError(f"{qid}: answer is required (yes, no, or null to clear)")
            if ch["answer"] is not None and ch["answer"] not in d33.ANSWERS:
                raise SystemsError(f"{qid}: answer must be yes or no")
            try:
                why = d33.check_justification(ch.get("justification"))
            except RulesError as exc:
                raise SystemsError(f"{qid}: {exc}") from None
            answers[qid] = d33.entry(ch["answer"], "person", why)
        dec = d33.decide(flow, answers)
        stored = self.state.update(
            "classification",
            {"classification_id": cur["classification_id"]},
            {"answers": json.dumps(answers, sort_keys=True), "outcome": dec.outcome},
            cur["row_version"],
        )
        self._changed("edit", dict(stored), actor, {"changed_n": len(changes)})
        return self.view(dict(stored), flow)

    def _check_apply(self, system_id: str, user: Any, draft: Mapping[str, Any]) -> None:
        roles = frozenset(getattr(user, "roles", ()) or ())
        if not rbac.allowed(roles, "systems.edit"):
            from supervisor.cases.service import PermissionDenied

            raise PermissionDenied("applying a classification needs systems.edit")
        uid = str(user.user_id)
        for m in self.state.query("system_team", {"system_id": system_id, "user_id": uid}):
            if _on(m["active"]) and m["team_role"] in SOD_ROLES:
                raise SegregationOfDuties(
                    f"segregation of duties: {uid} is {m['team_role']} of this system and "
                    "cannot apply its classification"
                )
        if draft["outcome"] not in d33.OUTCOMES:
            raise SystemsError(
                "the draft is not complete: answer every question before it can be applied"
            )

    def _refresh(
        self, system_id: str, draft: Mapping[str, Any], flow: d33.Flow
    ) -> dict[str, dict[str, Any]]:
        """Answers of the draft checked against the system NOW: the rules-sourced answers are
        derived again from the current fields and the outcome is decided again. A draft that no
        longer matches (a field changed, or the flow file changed) is refused."""
        from supervisor.governance.rules_service import RulesService

        stored = _answers_of(draft)
        facts = RulesService(self.state, self.tables, self.clock, self.settings).system_facts(
            system_id
        )
        fresh = d33.derive(flow, facts)
        answers = dict(stored)
        for qid, entry in fresh.items():
            cur = stored.get(qid)
            if cur is not None and cur.get("source") == "rules":
                answers[qid] = entry
        stale = draft["flow_sha256"] != flow.sha256 or any(
            stored.get(q, {}).get("answer") != answers[q].get("answer")
            for q in answers
            if stored.get(q, {}).get("source") == "rules"
        )
        if stale or d33.decide(flow, answers).outcome != draft["outcome"]:
            raise SystemsError("the system changed since the draft; remake it")
        return answers

    def apply(
        self, system_id: str, user: Any, *, confirm_ai_prefill: bool = False
    ) -> dict[str, Any]:
        """A person applies the draft. Sets ``decision33_class`` and the classifier floor of the
        risk level (high_risk -> at least high; l5 -> prohibited). It never lowers the stored
        level. The draft is checked against the system as it is now."""
        ensure_on(self.settings)
        actor = check_user(str(getattr(user, "user_id", "")), "actor")
        if getattr(user, "kind", "user") != "user":
            raise SystemsError("applying a classification needs a signed-in person")
        system = self._system(system_id)
        draft = self._draft_row(system_id)
        if draft is None:
            raise SystemsError("there is no draft to apply; make one first")
        self._check_apply(system_id, user, draft)
        level = system.get("autonomy_level") or "unspecified"
        if level == "unspecified":
            raise SystemsError(
                "autonomy_level is not set: set the autonomy level of the system "
                "(docs/autonomy-levels.md) before the classification can be applied"
            )
        flow = self.flow()
        answers = self._refresh(system_id, draft, flow)
        pending = sorted(q for q, a in answers.items() if a.get("source") == "ai_prefill")
        if pending and not confirm_ai_prefill:
            raise SystemsError(
                "the draft has AI pre-filled answers (" + ", ".join(pending) + "): "
                "check them and send confirm_ai_prefill=true, or answer them yourself"
            )
        outcome = str(draft["outcome"])
        changes: dict[str, Any] = {"decision33_class": outcome}
        floor = (
            "prohibited"
            if level == "l5_self_directed"
            else ("high" if outcome == "high_risk" else "unspecified")
        )
        # Apply never lowers the stored level. A downgrade is a separate, justified call
        # (SystemService.lower_risk_level).
        if rank(system["risk_level"]) < rank(floor):
            changes.update(risk_level=floor, risk_level_source="classifier")
        now = self.clock.now()
        key = {"classification_id": draft["classification_id"]}
        # mark applied first; if the system cannot be changed, put the draft back
        stored = self.state.update(
            "classification",
            key,
            {"status": "applied", "applied_by": actor, "applied_at": now},
            draft["row_version"],
        )
        try:
            self._systems().update_fields(system_id, changes, actor, allow_class=True)
        except Exception:
            self.state.update(
                "classification",
                key,
                {"status": "draft", "applied_by": None, "applied_at": None},
                stored["row_version"],
            )
            raise
        self._changed(
            "apply",
            dict(stored),
            actor,
            {"risk_floor_set": "risk_level" in changes},
        )
        return self.get(system_id)
