"""Helper agents of the agent factory (WP-F2, owner decision 3): they draft, a person accepts.

* ``checklist_drafter``  input: the text of a policy section (pasted, or from a stored internal
  document) and its pointer; output: proposed checklist rows, each with the section pointer.
* ``golden_generator``   input: the checklist; output: proposed synthetic Vietnamese cases with
  expected verdicts. Every case goes through the masker (``golden.check_cases``); a case that
  trips it is refused and never stored.
* ``result_explainer``   input: an ``assessment_report_v1`` document; output: plain sentences,
  each with pointers to findings of that report.

Like the RegKB drafts (``regkb/drafts.py``): a row is written to ``factory_helper_draft`` with
status ``draft``; a person with the edit right of the group accepts or drops each row; every
accept and every drop writes a ``factory_agent_event`` row. The model is the gateway model
(``make_chat_model``). With ``LLM_BASE_URL`` empty, or a mock model, a helper answers
``model_not_configured``; there is no mock path. A model drafts and advises; nothing here decides.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from supervisor.config import timeout_setting
from supervisor.core.errors import ConcurrencyError, SupervisorError
from supervisor.core.ports import ChatModel, Clock, StateStore
from supervisor.factory import caps, golden
from supervisor.factory.schemas.assessment_report_v1 import AssessmentReportV1
from supervisor.factory.store import FactoryStore
from supervisor.onboard.scrub import scrub_text

log = logging.getLogger("supervisor.factory.helpers")

TABLE = "factory_helper_draft"
HELPERS = ("checklist_drafter", "golden_generator", "result_explainer")
STATUSES = ("draft", "accepted", "dropped")
PROMPT_VERSION = "factory-helpers-1"
TIMEOUT_S = 60.0
MAX_POLICY_CHARS = 12000
MAX_REPORT_BYTES = 100_000
MAX_ROWS = 20
MAX_PER_ITEM = 5
MAX_SENTENCE = 400
DRAFT_ID_RE = re.compile(r"^fhd_[0-9a-f]{20}$")
MODEL_OFF_TEXT = (
    "model not configured: the helper agents need the gateway model (set LLM_BASE_URL); "
    "nothing was drafted"
)


class HelperError(SupervisorError):
    """A refused helper request. ``code`` is the stable machine word."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def default_chat(settings: Any) -> ChatModel:
    from supervisor.adapters.factory import make_chat_model  # late: keeps imports light

    return make_chat_model(settings)


def require_model(settings: Any) -> ChatModel:
    """The gateway model, or ``model_not_configured``. A mock model is not accepted."""
    if not getattr(settings, "llm_base_url", ""):
        raise HelperError("model_not_configured", MODEL_OFF_TEXT)
    chat = default_chat(settings)
    if getattr(chat, "is_mock", False):
        raise HelperError("model_not_configured", MODEL_OFF_TEXT)
    return chat


def model_ready(settings: Any) -> bool:
    return bool(getattr(settings, "llm_base_url", "")) and not getattr(settings, "llm_mock", False)


# ------------------------------------------------------------------------------ the table


class HelperStore:
    def __init__(self, state: StateStore, clock: Clock) -> None:
        self.state = state
        self.clock = clock

    def add(
        self,
        agent_id: str,
        version: str,
        helper: str,
        rows: Sequence[Mapping[str, Any]],
        model_id: str,
        run_id: str,
    ) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            data = {
                "draft_id": "fhd_" + uuid.uuid4().hex[:20],
                "agent_id": agent_id,
                "version": version,
                "helper": helper,
                "row_json": dict(row),
                "status": "draft",
                "model_id": model_id,
                "prompt_version": PROMPT_VERSION,
                "run_id": run_id,
                "created_at": self.clock.now(),
            }
            out.append(self._row(self.state.insert(TABLE, data)))
        return out

    @staticmethod
    def _row(raw: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        val = row.get("row_json")
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except ValueError:
                val = {}
        row["row"] = dict(val or {})
        return row

    def get(self, draft_id: str) -> dict[str, Any] | None:
        raw = self.state.get(TABLE, {"draft_id": draft_id})
        return self._row(raw) if raw is not None else None

    def list(
        self, agent_id: str, helper: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {"agent_id": agent_id}
        if helper:
            where["helper"] = helper
        if status:
            where["status"] = status
        rows = self.state.query(TABLE, where, order_by=("created_at", "draft_id"))
        return [self._row(r) for r in rows]

    def decide(self, draft_id: str, status: str, by: str, expected_version: int) -> dict[str, Any]:
        if status not in ("accepted", "dropped"):
            raise HelperError("bad_status", "a draft can only be accepted or dropped")
        row = self.get(draft_id)
        if row is None:
            raise HelperError("not_found", "this draft does not exist")
        if row["status"] != "draft":
            raise HelperError("decided", f"this draft was already {row['status']}; reload the page")
        try:
            updated = self.state.update(
                TABLE,
                {"draft_id": draft_id},
                {"status": status, "decided_by": by, "decided_at": self.clock.now()},
                expected_version,
            )
        except ConcurrencyError:
            raise HelperError("stale", "the draft was changed in another window; reload") from None
        return self._row(updated)


# ------------------------------------------------------------------------------ prompts

_SYSTEM = (
    "You help a bank team write an assessment agent for AI systems. You only propose rows; a "
    "person decides. Use synthetic or generic wording. Never write a real person name, phone "
    "number, address, account number, national id or email. Answer with the JSON object only."
)

CHECKLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "severity": {"type": "string"},
                    "pass_rule": {"type": "string"},
                    "section": {"type": "string"},
                },
                "required": ["question", "evidence", "severity", "pass_rule", "section"],
            },
        }
    },
    "required": ["rows"],
}
GOLDEN_SCHEMA = {
    "type": "object",
    "properties": {
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "checklist_id": {"type": "string"},
                    "input": {"type": "string"},
                    "expected_verdict": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["checklist_id", "input", "expected_verdict"],
            },
        }
    },
    "required": ["cases"],
}
EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "pointers": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "pointers"],
            },
        }
    },
    "required": ["sentences"],
}


def _call(chat: ChatModel, user: str, schema: Mapping[str, Any]) -> Mapping[str, Any]:
    messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]
    try:
        reply = chat.complete_json(
            messages, schema, timeout_setting("factory_helper_timeout_s", TIMEOUT_S)
        )
    except Exception as exc:  # noqa: BLE001 - a model error is a message, never a 500
        log.warning("factory helper: model call failed: %s", type(exc).__name__)
        raise HelperError(
            "model_error", f"the model did not answer ({type(exc).__name__})"
        ) from None
    if not isinstance(reply, Mapping):
        raise HelperError("model_error", "the model answer was not a JSON object")
    return reply


def _summary(added: int, reasons: Counter[str], chat: ChatModel, run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "model_id": str(getattr(chat, "model_id", "unknown")),
        "added": added,
        "dropped": sum(reasons.values()),
        "reasons": dict(reasons),
    }


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# ------------------------------------------------------------------------------ the three helpers


def run_checklist_drafter(
    store: FactoryStore,
    drafts: HelperStore,
    chat: ChatModel,
    agent: Mapping[str, Any],
    policy_text: str,
    section: str,
    actor: str,
) -> dict[str, Any]:
    text = scrub_text(policy_text or "").text.strip()
    section = _text(section, 100)
    if not text:
        raise HelperError("no_input", "paste the text of the policy section first")
    if len(text) > MAX_POLICY_CHARS:
        raise HelperError(
            "too_long", f"the policy text is longer than {MAX_POLICY_CHARS} characters"
        )
    if not section:
        raise HelperError("no_pointer", "name the section (for example Art.16(3)) of this text")
    defn = agent["definition"]
    allowed = list(defn["evidence_rules"]["allowed_sources"])
    user = (
        f"Policy section {section}:\n{text}\n\nPropose at most {MAX_ROWS} checklist rows an "
        f"assessment agent for the risk dimension {agent['dimension_id']} can check. Each row: "
        "question, evidence (a list from: " + ", ".join(allowed) + "), severity (low, medium or "
        "high), pass_rule (when the answer is pass), section (the pointer "
        f'{section!r} or a sub-clause of it). Return {{"rows": [...]}}.'
    )
    reply = _call(chat, user, CHECKLIST_SCHEMA)
    reasons: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for raw in list(reply.get("rows") or [])[:MAX_ROWS]:
        raw = raw if isinstance(raw, Mapping) else {}
        q, rule = (
            _text(raw.get("question"), caps.QUESTION_MAX + 1),
            _text(raw.get("pass_rule"), caps.PASS_RULE_MAX + 1),
        )
        kinds = raw.get("evidence")
        sec = _text(raw.get("section"), 100)
        if not q or len(q) > caps.QUESTION_MAX or not rule or len(rule) > caps.PASS_RULE_MAX:
            reasons["text_missing_or_too_long"] += 1
        elif raw.get("severity") not in caps.SEVERITIES:
            reasons["bad_severity"] += 1
        elif not isinstance(kinds, list) or not kinds or not all(k in allowed for k in kinds):
            reasons["evidence_kind_not_allowed"] += 1
        elif not sec:
            reasons["no_section_pointer"] += 1
        elif golden.trips_masker(q) or golden.trips_masker(rule):
            reasons["personal_data"] += 1
        else:
            rows.append(
                {
                    "question": q,
                    "evidence": list(dict.fromkeys(kinds)),
                    "severity": raw["severity"],
                    "pass_rule": rule,
                    "section": sec,
                }
            )
    run_id = "fr_" + uuid.uuid4().hex[:12]
    drafts.add(
        agent["id"],
        agent["version"],
        "checklist_drafter",
        rows,
        str(getattr(chat, "model_id", "unknown")),
        run_id,
    )
    store.record_event(
        agent["id"],
        agent["version"],
        "saved",
        str(getattr(chat, "model_id", "model")),
        f"checklist_drafter proposed {len(rows)} row(s) for {section}",
    )
    return _summary(len(rows), reasons, chat, run_id)


def run_golden_generator(
    store: FactoryStore,
    drafts: HelperStore,
    chat: ChatModel,
    agent: Mapping[str, Any],
    per_item: int,
    actor: str,
) -> dict[str, Any]:
    per_item = max(1, min(int(per_item), MAX_PER_ITEM))
    checklist = agent["definition"]["checklist"]
    items = [
        {"id": c["id"], "question": c["question"], "pass_rule": c["pass_rule"]} for c in checklist
    ]
    user = (
        "Checklist (JSON):\n" + json.dumps(items, ensure_ascii=False) + f"\n\nFor each item write "
        f"{per_item} short test cases in Vietnamese (synthetic: invented company and product "
        "names, no real person, no phone, no account number, no id number). Each case: "
        "checklist_id, input (a short description of an AI system record or fact set the agent "
        "would see), expected_verdict (pass, fail, not_applicable or question), note. "
        'Return {"cases": [...]}.'
    )
    reply = _call(chat, user, GOLDEN_SCHEMA)
    raw_cases = [c for c in (reply.get("cases") or []) if isinstance(c, Mapping)]
    raw_cases = raw_cases[: per_item * len(items)]
    numbered = []
    counters: Counter[str] = Counter()
    for c in raw_cases:
        cid = str(c.get("checklist_id") or "")
        counters[cid] += 1
        numbered.append({**c, "case_id": f"{cid}-g{counters[cid]:02d}"[:64]})
    ok, bad = golden.check_cases(numbered, [c["id"] for c in checklist])
    reasons: Counter[str] = Counter()
    for b in bad:
        reasons["masker" if "personal data" in b["reason"] else "invalid_case"] += 1
    run_id = "fg_" + uuid.uuid4().hex[:12]
    drafts.add(
        agent["id"],
        agent["version"],
        "golden_generator",
        ok,
        str(getattr(chat, "model_id", "unknown")),
        run_id,
    )
    store.record_event(
        agent["id"],
        agent["version"],
        "saved",
        str(getattr(chat, "model_id", "model")),
        f"golden_generator proposed {len(ok)} case(s); refused {len(bad)}",
    )
    return {**_summary(len(ok), reasons, chat, run_id), "refused": bad}


def run_result_explainer(
    store: FactoryStore,
    drafts: HelperStore,
    chat: ChatModel,
    agent: Mapping[str, Any],
    report_json: str,
    actor: str,
) -> dict[str, Any]:
    if len((report_json or "").encode("utf-8")) > MAX_REPORT_BYTES:
        raise HelperError("too_long", "the report is larger than 100 KB")
    try:
        doc = json.loads(report_json)
    except ValueError:
        raise HelperError("bad_report", "the report is not valid JSON") from None
    try:
        report = AssessmentReportV1.model_validate(doc)
    except ValidationError as exc:
        first = exc.errors(include_url=False, include_input=False)[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise HelperError("bad_report", f"{loc}: {first['msg']}") from None
    finding_ids = {f.finding_id for f in report.findings}
    user = (
        "Assessment report (JSON):\n" + json.dumps(doc, ensure_ascii=False) + "\n\nExplain the "
        "result in plain sentences for a risk manager (at most 8 sentences). Each sentence must "
        'list the finding_id values it relies on in pointers. Return {"sentences": [...]}.'
    )
    reply = _call(chat, user, EXPLAIN_SCHEMA)
    reasons: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for raw in list(reply.get("sentences") or [])[:8]:
        raw = raw if isinstance(raw, Mapping) else {}
        text = _text(raw.get("text"), MAX_SENTENCE + 1)
        pointers = raw.get("pointers")
        if not text or len(text) > MAX_SENTENCE:
            reasons["text_missing_or_too_long"] += 1
        elif (
            not isinstance(pointers, list)
            or not pointers
            or not all(p in finding_ids for p in pointers)
        ):
            reasons["pointer_not_in_report"] += 1
        elif golden.trips_masker(text):
            reasons["personal_data"] += 1
        else:
            rows.append(
                {
                    "text": text,
                    "pointers": list(dict.fromkeys(pointers)),
                    "report_id": report.report_id,
                }
            )
    run_id = "fe_" + uuid.uuid4().hex[:12]
    drafts.add(
        agent["id"],
        agent["version"],
        "result_explainer",
        rows,
        str(getattr(chat, "model_id", "unknown")),
        run_id,
    )
    store.record_event(
        agent["id"],
        agent["version"],
        "saved",
        str(getattr(chat, "model_id", "model")),
        f"result_explainer proposed {len(rows)} sentence(s) for {report.report_id}",
    )
    return _summary(len(rows), reasons, chat, run_id)


# ------------------------------------------------------------------------------ accept and drop


def _next_item_id(checklist: Sequence[Mapping[str, Any]], dimension_id: str) -> str:
    prefix = "CK"
    if checklist:
        m = re.match(r"^(.*?)-?\d+$", str(checklist[0]["id"]))
        if m and m.group(1):
            prefix = m.group(1)
    taken = {c["id"] for c in checklist}
    n = len(taken) + 1
    while f"{prefix}-{n:02d}" in taken:
        n += 1
    return f"{prefix}-{n:02d}"


def accept(
    store: FactoryStore,
    drafts: HelperStore,
    draft_id: str,
    actor: str,
    expected_version: int,
    data_dir: Any,
) -> dict[str, Any]:
    """A person accepts one row. The effect is applied first, so a refusal (a field name from the
    schema) leaves the draft open; then the draft is marked and an event is written."""
    if not DRAFT_ID_RE.match(draft_id or ""):
        raise HelperError("bad_id", "invalid draft id")
    d = drafts.get(draft_id)
    if d is None:
        raise HelperError("not_found", "this draft does not exist")
    if d["status"] != "draft":
        raise HelperError("decided", f"this draft was already {d['status']}; reload the page")
    agent = store.get(d["agent_id"], d["version"])
    if agent is None:
        raise HelperError("not_found", "the agent version of this draft does not exist")
    row = d["row"]
    detail = ""
    if d["helper"] == "checklist_drafter":
        defn = agent["definition"]
        item_id = _next_item_id(defn["checklist"], agent["dimension_id"])
        rule = row["pass_rule"]
        suffix = f" ({row['section']})"
        if len(rule) + len(suffix) <= caps.PASS_RULE_MAX:
            rule += suffix
        defn["checklist"].append(
            {
                "id": item_id,
                "question": row["question"],
                "evidence": row["evidence"],
                "severity": row["severity"],
                "pass_rule": rule,
            }
        )
        try:
            store.save_draft(agent["id"], agent["version"], defn, actor, int(agent["row_version"]))
        except SupervisorError as exc:
            raise HelperError("not_accepted", str(exc)) from None
        detail = f"checklist row {item_id} from {row['section']}"
    elif d["helper"] == "golden_generator":
        if agent["state"] == "retired":
            raise HelperError("not_accepted", "the agent version is retired")
        golden.store_cases(data_dir, agent["id"], [row])
        detail = f"golden case {row['case_id']}"
    else:
        detail = f"explanation of {row.get('report_id', '?')}"
    updated = drafts.decide(draft_id, "accepted", actor, expected_version)
    store.record_event(
        agent["id"], agent["version"], "helper_accepted", actor, f"{d['helper']}: {detail}"
    )
    return updated


def drop(
    store: FactoryStore, drafts: HelperStore, draft_id: str, actor: str, expected_version: int
) -> dict[str, Any]:
    if not DRAFT_ID_RE.match(draft_id or ""):
        raise HelperError("bad_id", "invalid draft id")
    d = drafts.get(draft_id)
    if d is None:
        raise HelperError("not_found", "this draft does not exist")
    updated = drafts.decide(draft_id, "dropped", actor, expected_version)
    store.record_event(
        d["agent_id"], d["version"], "helper_dropped", actor, f"{d['helper']}: dropped"
    )
    return updated
