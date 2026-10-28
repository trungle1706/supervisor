"""The Duties step of the register workflow v2 (WP-L2, flag ``CONSOLE_REGISTER_DUTIES``).

The step builds a product profile from the draft answers, runs the compliance matrix
(``supervisor.advisory.compliance``) on it and shows the rows: instrument, article, duty, applies
(yes, no, needs answer) and coverage (full, partial, none). The open questions of the matrix are
form fields of the step (field name = question id, for example ``Q-data_classes``). The answers
are kept in the draft under ``duties_answers`` and every run uses them.

On submit, ``write`` adds one ``obligation_status`` row for every duty that applies to the new AI
system and one task for every applying duty whose coverage is partial or none.

Advisory only. Not legal advice. Bank counsel must confirm. The matrix never decides compliance:
an unknown fact is a question, never a guess.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from supervisor.advisory.compliance import questionnaire as qn
from supervisor.advisory.compliance.facts import apply_answers, standard_controls
from supervisor.advisory.compliance.matrix import build_matrix
from supervisor.advisory.compliance.model import (
    Pointer,
    ProductProfile,
    RuleFact,
)
from supervisor.core.errors import DuplicateKeyError
from supervisor.governance.register_v2 import model as rm

log = logging.getLogger("supervisor.governance")

BANNER = "Not legal advice. Bank counsel must confirm."
TEMPLATE_PREFIX = "DUTY-"
PAGE_SIZE = 100
MAX_ANSWER_TEXT = 200
FILTERS: tuple[str, ...] = ("gaps", "yes", "needs_answer", "no", "all")
# status of the matrix -> coverage of the duty by Supervisor controls
COVERAGE_OF_STATUS: dict[str, str] = {
    "met": "full",
    "partial": "partial",
    "gap": "none",
    "bank_process": "none",  # only a bank process covers it: Supervisor covers nothing
    "not_applicable": "unknown",
}
_AUTONOMY_OF_LEVEL: dict[str, str] = {
    "l0_rule_based": "advisory",
    "l1_assistive": "advisory",
    "l2_workflow_step": "acts_with_approval",
    "l3_tool_using_supervised": "acts_with_approval",
}
_FIELD: dict[str, qn.QField] = {f.name: f for f in qn.FIELDS}
# facts of the questionnaire a person can answer in a form field (not the identity fields)
ANSWERABLE: tuple[str, ...] = tuple(
    f.name
    for f in qn.FIELDS
    if f.type in ("bool", "enum", "enum_list", "int", "date")
    and f.name not in ("product_id", "name", "version")
)


def enabled(settings: Any) -> bool:
    """The Duties step is part of the workflow (the flag and what it needs are on)."""
    return bool(
        getattr(settings, "console_register_duties", False)
        and getattr(settings, "console_register_v2", False)
        and getattr(settings, "governance_enabled", False)
    )


# ------------------------------------------------------------------------------ the profile


def _ptr(draft: Mapping[str, Any], field: str) -> tuple[Pointer, ...]:
    return (Pointer("console", f"register draft {draft['draft_id']}: {field}"),)


def _controls(ctx: Any, agent_id: str) -> Any:
    """Controls the new system will have: registered with Supervisor (basis ``planned``) and the
    gate rules of the deployed policy that name the agent. Nothing else is assumed."""
    from supervisor.governance.register_v2 import service as rs

    rules: list[RuleFact] = []
    doc = rs.policy_doc(ctx)
    if agent_id and doc is not None and agent_id in rs.policy_agents(ctx):
        for r in doc.rules:
            if r.in_scope(agent_id):
                rules.append(
                    RuleFact(
                        str(r.id),
                        str(getattr(r, "description", "") or ""),
                        Pointer("rule", str(r.id), "gate rule of the deployed policy"),
                    )
                )
    return standard_controls(basis="planned", supervised=True, rules=tuple(rules))


def facts_rows(ctx: Any, draft: Mapping[str, Any]) -> int:
    """Number of facts rows (WP-O2, table ``onboard_facts``) for the scanned node of the draft.
    The table is read by name only; when it does not exist, or the draft has no scanned node, the
    answer is 0 and the step runs on the draft answers alone."""
    ref = draft.get("source_ref") if draft.get("source_kind") == "scan" else None
    if not ref:
        return 0
    try:
        return len(ctx.state.query("onboard_facts", {"node_id": str(ref)}))
    except Exception:  # noqa: BLE001 - no such table (WP-O2 not merged) or no such column
        return 0


def profile_of(
    ctx: Any, draft: Mapping[str, Any], answers: Mapping[str, Any] | None = None
) -> ProductProfile:
    """Product facts from the draft answers, then the answers of this step on top."""
    v = dict(draft["data"]["v"])
    money, credit = bool(v.get("money_movement")), bool(v.get("credit_decision"))
    seg = str(v.get("user_segment") or "")
    classes: list[str] = []
    if money:
        classes.append("payment")
    if credit:
        classes.append("credit_decision")
    if seg == "customer":
        classes.append("customer_facing")
    if seg == "internal":
        classes.append("internal_tool")
    pd = str(v.get("personal_data") or "")
    data_classes: tuple[str, ...] | None = None
    if pd in ("identifiable", "pseudonymised"):
        data_classes = ("personal",)
    elif pd == "special":
        data_classes = ("personal", "sensitive_personal")
    elif pd == "none":
        data_classes = ()
    role = str(v.get("org_role") or "")
    roles = {"provider": ("provider",), "deployer": ("deployer",), "both": ("deployer", "provider")}
    hc = str(v.get("human_control") or "")
    prov = {
        f: _ptr(draft, f)
        for f in ("purpose", "user_segment", "personal_data", "org_role", "money_movement")
    }
    base = ProductProfile(
        product_id=str(draft["draft_id"]).replace("_", "-"),
        name=str(v.get("name") or "draft"),
        source="questionnaire",
        owner_team=v.get("owner_team") or None,
        purpose=v.get("purpose") or None,
        # step 2 asks for the segment and the two money boxes: the class set is complete once the
        # segment is known; the data classes are a lower bound (financial data is not asked)
        agent_classes=tuple(classes) if seg else None,
        agent_classes_complete=bool(seg),
        data_classes=data_classes,
        data_classes_complete=False,
        autonomy=_AUTONOMY_OF_LEVEL.get(str(v.get("autonomy_level") or ""))
        or (
            "acts_autonomously"
            if str(v.get("autonomy_level") or "").startswith(("l4", "l5"))
            else None
        ),
        roles=roles.get(role),
        roles_complete=role in roles,
        customer_facing={"customer": True, "internal": False}.get(seg),
        executes_payments=money,
        human_approval_before_execution=(hc == "pre_approval") if money and hc else None,
        credit_decisions=credit,
        controls=_controls(ctx, str(v.get("agent_id") or "")),
        provenance=prov,
    )
    return apply_answers(base, {k[2:]: val for k, val in (answers or {}).items()})


_CACHE: OrderedDict[tuple[str, str], Any] = OrderedDict()
_CACHE_MAX = 8


def matrix_of(ctx: Any, draft: Mapping[str, Any]) -> Any:
    """The obligations matrix of the draft. The KB is loaded once per process; a matrix takes a
    few seconds, so the last few results are kept by the profile they were built from (the
    page, the review and the submit of one draft then run the matrix once)."""
    from supervisor.console.compliance_view import kb_for

    answers = draft["data"].get("duties_answers") or {}
    product = profile_of(ctx, draft, answers)
    key = (str(getattr(ctx.settings, "regkb_internal_dir", "") or ""), repr(product))
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit
    matrix = build_matrix(kb_for(ctx.settings), product, chat=None)
    _CACHE[key] = matrix
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return matrix


# ------------------------------------------------------------------------------ the answers


def _typed(fact: str, key: str, raw: str) -> Any:
    """One form value as the typed answer of the questionnaire (``None`` = blank = unknown)."""
    f = _FIELD[fact]
    text = raw.strip()
    if not text:
        return None
    if any(ord(c) < 32 for c in text) or len(text) > MAX_ANSWER_TEXT:
        raise rm.RegisterError(key, "has control characters or is too long")
    if f.type == "bool":
        low = text.lower()
        if low in ("yes", "true", "1"):
            return True
        if low in ("no", "false", "0"):
            return False
        raise rm.RegisterError(key, "must be yes or no")
    if f.type == "int":
        if not (text.isascii() and text.isdigit()):
            raise rm.RegisterError(key, "must be a whole number of VND (digits only)")
        return int(text)
    if f.type == "enum_list":
        if text.lower() in ("none", "[]"):
            return []
        return [p for p in text.replace(";", ",").replace(" ", ",").split(",") if p]
    return text


def answers_from(form: Mapping[str, str], current: Mapping[str, Any]) -> dict[str, Any]:
    """The stored answers after one form post. A field in the form replaces the answer (blank =
    unknown again); a question not in the form keeps its answer. A bad value is a RegisterError
    that names the field (HTTP 400)."""
    out = dict(current)
    for key, raw in form.items():
        if not key.startswith("Q-"):
            continue
        fact = key[2:]
        if fact not in ANSWERABLE:
            raise rm.RegisterError(key, "is not a question of this step")
        val = _typed(fact, key, str(raw))
        if val is None:
            out.pop(key, None)
            continue
        try:
            qn.validate_answers({fact: val})
        except qn.QuestionnaireError as exc:
            raise rm.RegisterError(key, exc.problems[0].split(": ", 1)[-1]) from None
        out[key] = val
    return out


def _text_of(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if isinstance(value, list):
        return ", ".join(value) if value else "none"
    return "" if value is None else str(value)


# ------------------------------------------------------------------------------ the view


def _date(item: Any) -> dt.date | None:
    raw = getattr(item, "date", None)
    try:
        return dt.date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def coverage_of(row: Any) -> str:
    return COVERAGE_OF_STATUS.get(row.status, "unknown")


def effective_date(row: Any) -> dt.date | None:
    """The effective date of the instrument of the duty, when RegKB knows it."""
    return _date(row.deadline.effective)


def _question(q: Any, stored: Mapping[str, Any], *, open_: bool = True) -> dict[str, Any]:
    f = _FIELD.get(q.fact)
    editable = f is not None and q.fact in ANSWERABLE
    kind = f.type if editable and f is not None else "text"
    return {
        "id": q.id,
        "fact": q.fact,
        "text_en": q.text_en,
        "text_vi": q.text_vi,
        "why": q.why,
        "n": len(q.obligation_ids),
        "editable": editable,
        "kind": kind,
        "options": list(f.enum) if f is not None and f.type in ("enum", "enum_list") else [],
        "value": _text_of(stored.get(q.id)),
        "answered": q.id in stored,
        "open": open_,  # False: answered, so the matrix does not ask it now; kept to be changed
    }


def view(
    ctx: Any,
    draft: Mapping[str, Any],
    *,
    flt: str = "gaps",
    page: int = 1,
    posted: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Step view model: summary counts, a page of rows, the open questions, the banner."""
    if flt not in FILTERS:
        raise rm.RegisterError("filter", f"must be one of {', '.join(FILTERS)}")
    if not isinstance(page, int) or page < 1:
        raise rm.RegisterError("page", "must be 1 or more")
    ready = bool(draft["data"]["v"].get("user_segment"))
    stored = dict(draft["data"].get("duties_answers") or {})
    base: dict[str, Any] = {
        "banner": BANNER,
        "ready": ready,
        "filter": flt,
        "filters": FILTERS,
        "facts_n": facts_rows(ctx, draft),
    }
    if not ready:
        return {**base, "rows": [], "questions": [], "summary": {}, "pages": 1, "page": 1}
    m = matrix_of(ctx, draft)
    rows = [(r, coverage_of(r)) for r in m.rows]

    def keep(r: Any, cov: str) -> bool:
        if flt == "all":
            return True
        if flt == "gaps":
            return r.applies == "yes" and cov in ("partial", "none")
        return r.applies == flt

    shown = [(r, c) for r, c in rows if keep(r, c)]
    pages = max(1, -(-len(shown) // PAGE_SIZE))
    page = min(page, pages)
    chunk = shown[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    yes = [(r, c) for r, c in rows if r.applies == "yes"]
    summary = {
        "total": len(rows),
        "yes": len(yes),
        "no": sum(1 for r, _ in rows if r.applies == "no"),
        "needs_answer": sum(1 for r, _ in rows if r.applies == "needs_answer"),
        "full": sum(1 for _, c in yes if c == "full"),
        "partial": sum(1 for _, c in yes if c == "partial"),
        "none": sum(1 for _, c in yes if c == "none"),
        "tasks": sum(1 for _, c in yes if c in ("partial", "none")),
        "d33": m.decision33.classification,
    }
    view_rows = []
    for r, cov in chunk:
        eff = effective_date(r)
        view_rows.append(
            {
                "obligation_id": r.obligation_id,
                "instrument_id": r.instrument_id,
                "instrument": r.instrument_number or r.instrument_id,
                "article": r.article_ref,
                "duty": r.summary_en,
                "duty_ids": list(r.duties),
                "applies": r.applies,
                "coverage": cov,
                "due": eff.isoformat() if eff else "",
            }
        )
    questions = [_question(q, stored) for q in m.questions]
    asked = {q["id"] for q in questions}
    for qid in sorted(stored):  # an answered question stays on the page so it can be changed
        if qid not in asked and qid[2:] in ANSWERABLE:
            questions.append(_question(qn.make_question(qid[2:]), stored, open_=False))
    if posted:  # a rejected post: show what the person typed
        for q in questions:
            if q["id"] in posted:
                q["value"] = str(posted[q["id"]])
    return {
        **base,
        "rows": view_rows,
        "questions": questions,
        "summary": summary,
        "pages": pages,
        "page": page,
        "n_shown": len(shown),
    }


def review(ctx: Any, draft: Mapping[str, Any]) -> dict[str, Any]:
    """Counts for the review page (what the submit will write)."""
    v = view(ctx, draft, flt="yes")
    s = v["summary"]
    return {
        "ready": v["ready"],
        "rows": s.get("yes", 0),
        "tasks": s.get("tasks", 0),
        "open_questions": sum(1 for q in v["questions"] if q["open"]),
        "answers_n": len(draft["data"].get("duties_answers") or {}),
        "banner": BANNER,
    }


# ------------------------------------------------------------------------------ the writes


def status_id(system_id: str, obligation_id: str) -> str:
    return "os_" + hashlib.sha256(f"{system_id}|{obligation_id}".encode()).hexdigest()[:20]


def _task(ctx: Any, system_id: str, row: Any, actor: str) -> bool:
    tasks = ctx.tasks
    eff = effective_date(row)
    note = f"{BANNER} {row.instrument_number or row.instrument_id} {row.article_ref}"
    trow = tasks._row_for(  # noqa: SLF001 - the one place that writes a task for a system
        system_id,
        "initiation",
        template_id=TEMPLATE_PREFIX + row.obligation_id,
        kind="custom",
        title=f"Close duty {row.obligation_id}",
        owner_role="owner",
        required=False,
        due_days=14,
        evidence_kind="none",
        evidence_ref=note[:200],
        level="low",
        d33_class="unclassified",
        actor=actor,
    )
    now = ctx.clock.now()
    if eff is not None:
        due = dt.datetime(eff.year, eff.month, eff.day, tzinfo=dt.UTC)
        if due > now:  # a date in the past keeps the default: the duty is in force already
            trow["due_at"] = due
    return bool(tasks._insert(trow, actor))  # noqa: SLF001


def write(ctx: Any, draft: Mapping[str, Any], system_id: str, owner_user: str, actor: str) -> dict:
    """One ``obligation_status`` row per applying duty and one task per applying duty with
    coverage partial or none. A repeat is a no-op (stable ids). Returns the counts."""
    m = matrix_of(ctx, draft)
    now = ctx.clock.now()
    rows_n = tasks_n = 0
    for r in m.rows:
        if r.applies != "yes":
            continue
        cov = coverage_of(r)
        eff = effective_date(r)
        try:
            ctx.state.insert(
                "obligation_status",
                {
                    "status_id": status_id(system_id, r.obligation_id),
                    "system_id": system_id,
                    "obligation_id": r.obligation_id,
                    "instrument_id": r.instrument_id,
                    "applies": r.applies,
                    "coverage": cov,
                    "status": "open",
                    "owner_user": owner_user,
                    "due_date": eff.isoformat() if eff else None,
                    "closing_control": None,
                    "note": f"{BANNER} {r.status_reason}"[:1000],
                    "created_at": now,
                },
            )
            rows_n += 1
        except DuplicateKeyError:
            pass
        if cov in ("partial", "none"):
            try:
                if _task(ctx, system_id, r, actor):
                    tasks_n += 1
            except Exception:  # noqa: BLE001 - a duty without its task is still a duty row
                log.exception("register_v2: could not open task for %s", r.obligation_id)
    return {"rows": rows_n, "tasks": tasks_n}
