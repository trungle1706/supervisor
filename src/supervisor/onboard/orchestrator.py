"""The onboarding orchestrator (WP-F4, flag ``ONBOARD_ORCHESTRATOR``).

Deterministic. It has no model call of its own and it decides by rules only. For one AI system it

1. ``plan``: decides which of the eight risk types (Circular 53 Art. 14(3)) apply, which agent
   assesses each (a live factory agent from the ``AgentCatalog``, else the rule proposal of
   ``risk_dimensions.propose``), the order (``legal_compliance`` last, it reads the others) and the
   budget (time and tokens per agent and for the run, from ``factory.caps``);
2. ``run``: queued -> running -> done or failed (table ``orchestrator_run``). Each type is run
   through a ``Runner`` under its budget. A report that is not a valid ``assessment_report_v1``
   fails its item. A ``high`` severity ``fail`` (or a stop point of the agent definition) stops that
   type with status ``needs_person``. The worst verdict wins across the findings; a ``fail`` needs a
   person. The report is stored under ``DATA_DIR/assessments/<system>/<attempt>/<type>.json`` with
   its SHA-256. The run writes a *proposal* into ``risk_dimension_status`` and ``assessed_by``; it
   never writes ``pass`` (a person confirms with the existing action of WP-C2);
3. writes ``duties_prefill.json`` next to the reports (``read_duties_prefill`` reads it), the
   ``onboard_log`` rows and the ``orchestrator_run`` chain record (ids, hashes and integers).

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from supervisor.core.canonical import canonical_json, format_ts
from supervisor.core.errors import SupervisorError
from supervisor.evidence.chain import check_no_floats
from supervisor.factory import caps
from supervisor.factory.schemas.assessment_report_v1 import AssessmentReportV1
from supervisor.governance import risk_dimensions as rd
from supervisor.onboard import agent_log

log = logging.getLogger(__name__)

TABLE = "orchestrator_run"
RECORD_TYPE = "orchestrator_run"
BANNER = "Not legal advice. Bank counsel must confirm."
STATUSES = ("queued", "running", "done", "failed")
ITEM_STATUSES = (
    "queued",
    "running",
    "done",
    "needs_person",
    "budget_exceeded",
    "failed",
    "not_applicable",
    "skipped",
)
OUTCOMES = ("not_system", "prohibited", "high_certify", "high_self", "medium", "low")
# Order of the worst verdict: the first one present wins.
VERDICT_RANK = ("fail", "question", "pass", "not_applicable")
CORE = ("model", "data_governance", "cybersecurity", "legal_compliance")
# Run order: legal_compliance last because it reads the others.
ORDER = (
    "model",
    "data_governance",
    "cybersecurity",
    "ethics",
    "third_party",
    "supply_chain",
    "reputation",
    "legal_compliance",
)
THIRD_PARTY_KINDS = ("model", "endpoint", "external_url", "mcp_server")
SUPPLY_KINDS = ("tool", "mcp_server", "model", "external_url", "dataset")
# Budgets (platform defaults; a live agent may ask for less through its loop budget).
AGENT_SECONDS = 120
RULE_SECONDS = 30
TOTAL_SECONDS = 900
AGENT_TOKENS = caps.LOOP_BUDGET_DEFAULT
TOTAL_TOKENS = 8 * caps.LOOP_BUDGET_DEFAULT
STALE_S = 1800  # a queued or running row older than this, with no thread, was cut by a restart
MAX_SUMMARY = 300
MAX_NOTE = 300
MAX_ITEMS = 8

_LOCK = threading.RLock()
_RUNNING: dict[str, str] = {}
_THREADS: dict[str, threading.Thread] = {}


class OrchestratorError(SupervisorError):
    """A refusal (HTTP 400). The message starts with ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# ------------------------------------------------------------------------------ flag


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "onboard_orchestrator", False)
        and getattr(settings, "governance_enabled", False)
        and getattr(settings, "risk_dimensions", False)
        and getattr(settings, "classification_v2", False)
    )


def ensure_on(settings: Any) -> None:
    if not enabled(settings):
        raise OrchestratorError(
            "orchestrator_off",
            "the onboarding orchestrator is off (ONBOARD_ORCHESTRATOR=1 turns it on; "
            "needs GOVERNANCE_ENABLED, RISK_DIMENSIONS and CLASSIFICATION_V2)",
        )


# ------------------------------------------------------------------------------ interfaces


@dataclass(frozen=True)
class LiveAgent:
    """A factory agent in state ``live`` for one risk type (WP-F2 supplies it)."""

    agent_id: str
    version: str
    definition: Mapping[str, Any] = field(default_factory=dict)


class AgentCatalog(Protocol):
    """Which live factory agent assesses a risk type. WP-F2's store plugs in here."""

    def live_agent(self, dimension_id: str) -> LiveAgent | None: ...


class NullCatalog:
    """No factory store: every type is assessed by the rule proposal."""

    def live_agent(self, dimension_id: str) -> LiveAgent | None:
        return None


@dataclass(frozen=True)
class AgentRequest:
    """What a runner gets for one risk type."""

    run_id: str
    system_id: str
    attempt_n: int
    dimension_id: str
    report_id: str
    agent_id: str  # "rule-proposal" for the rule runner
    agent_version: str
    definition: Mapping[str, Any] | None
    inputs: Mapping[str, Any]  # system, facts, proposal, prior (reports already made), now
    budget_seconds: int
    budget_tokens: int


class Runner(Protocol):
    """Runs one risk type and returns a dict that validates as ``assessment_report_v1``.
    WP-F3 will provide ``factory.runtime.run_agent(definition, inputs)``; ``RoutingRunner`` calls it
    for a live agent as soon as it exists."""

    def run(self, request: AgentRequest) -> dict[str, Any]: ...


_CATALOG: AgentCatalog = NullCatalog()


def set_catalog(catalog: AgentCatalog) -> None:
    """Plug in the factory store (WP-F2). The default is the null catalogue."""
    global _CATALOG
    _CATALOG = catalog


def get_catalog() -> AgentCatalog:
    return _CATALOG


# ------------------------------------------------------------------------------ the plan


@dataclass(frozen=True)
class Budget:
    agent_seconds: int = AGENT_SECONDS
    rule_seconds: int = RULE_SECONDS
    agent_tokens: int = AGENT_TOKENS
    total_seconds: int = TOTAL_SECONDS
    total_tokens: int = TOTAL_TOKENS

    def to_dict(self) -> dict[str, int]:
        return {
            "agent_seconds": self.agent_seconds,
            "rule_seconds": self.rule_seconds,
            "agent_tokens": self.agent_tokens,
            "total_seconds": self.total_seconds,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class PlanItem:
    dimension_id: str
    order: int
    applies: bool
    reason: str
    agent: str  # "rule" or "<id>@<version>"
    agent_id: str
    agent_version: str
    budget_seconds: int
    budget_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension_id": self.dimension_id,
            "order": self.order,
            "applies": self.applies,
            "reason": self.reason,
            "agent": self.agent,
            "budget_seconds": self.budget_seconds,
            "budget_tokens": self.budget_tokens,
        }


@dataclass(frozen=True)
class Plan:
    system_id: str
    outcome: str  # an outcome of the classification tree, or "unclassified"
    blocked: str  # "" or a code: classification_required, prohibited, not_system
    items: tuple[PlanItem, ...]
    budget: Budget

    def applicable(self) -> list[PlanItem]:
        return [i for i in self.items if i.applies]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "system_id": self.system_id,
            "outcome": self.outcome,
            "blocked": self.blocked,
            "budget": self.budget.to_dict(),
            "items": [i.to_dict() for i in self.items],
        }

    @property
    def plan_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def _fact_kinds(facts_v1: Mapping[str, Any] | None) -> set[str] | None:
    """The kinds of the facts in the export, or ``None`` when there are no facts (unknown)."""
    if not facts_v1:
        return None
    rows = facts_v1.get("facts") or []
    if not rows:
        return None
    return {str(r.get("kind")) for r in rows if isinstance(r, Mapping)}


def _signal(
    flags: Mapping[str, Any], key: str, kinds: set[str] | None, wanted: Sequence[str]
) -> bool | None:
    """True/False when a flag or the facts answer; ``None`` when nothing does (unknown)."""
    if key in flags and flags[key] is not None:
        return _truthy(flags[key])
    if kinds is None:
        return None
    return bool(kinds & set(wanted))


def _applies(
    dim_id: str,
    outcome: str,
    system: Mapping[str, Any],
    flags: Mapping[str, Any],
    kinds: set[str] | None,
    institution: str,
    cfg: rd.Config,
) -> tuple[bool, str]:
    """The rule for one risk type. Returns ``(applies, reason code)``."""
    dim = cfg.get(dim_id)
    if dim.applies_to == "bank" and institution != "bank":
        return False, "bank_only"
    if outcome in ("high_certify", "high_self"):
        return True, "high_all_eight"
    if dim_id in CORE:
        return True, "core"
    if dim_id == "ethics":
        if "customer_decision" in flags and flags["customer_decision"] is not None:
            decision = _truthy(flags["customer_decision"])
        else:
            decision = (
                bool(system.get("credit_decision")) or system.get("system_type") == "decision"
            )
        if "personal_data" in flags and flags["personal_data"] is not None:
            personal = _truthy(flags["personal_data"])
        else:
            personal = str(system.get("personal_data") or "none") != "none"
        if decision or personal:
            return True, "customer_decision_or_personal_data"
        return False, "no_customer_decision_no_personal_data"
    if outcome == "low":
        return False, "low_core_only"
    if dim_id == "third_party":
        sig = _signal(flags, "third_party_model", kinds, THIRD_PARTY_KINDS)
        if sig is None:
            return True, "unknown_assume_applies"
        return (True, "third_party_signal") if sig else (False, "no_third_party_signal")
    if dim_id == "supply_chain":
        sig = _signal(flags, "dependencies", kinds, SUPPLY_KINDS)
        if sig is None:
            return True, "unknown_assume_applies"
        return (True, "dependency_signal") if sig else (False, "no_dependency_signal")
    if dim_id == "reputation":
        if system.get("user_segment") == "customer":
            return True, "customer_facing"
        return False, "medium_customer_facing_only"
    return True, "applies"  # pragma: no cover - the eight ids are all handled above


def plan(
    system: Mapping[str, Any],
    classification_outcome: str | None,
    ai_type_flags: Mapping[str, Any] | None,
    facts_v1: Mapping[str, Any] | None,
    *,
    institution: str = "bank",
    catalog: AgentCatalog | None = None,
    budget: Budget | None = None,
    cfg: rd.Config | None = None,
) -> Plan:
    """Which dimensions apply, who assesses each, in which order, under which budget.

    ``classification_outcome``: an outcome of ``config/classification.yaml`` or ``None`` (no
    approved record). ``ai_type_flags`` may hold ``customer_decision``, ``personal_data``,
    ``third_party_model``
    and ``dependencies`` (booleans); a missing flag is read from the system record or the facts, and
    when neither answers the type applies (an unknown is never a reason to skip an assessment)."""
    cfg = cfg or rd.load_config()
    catalog = catalog or NullCatalog()
    budget = budget or Budget()
    flags = dict(ai_type_flags or {})
    sid = str(system.get("system_id") or "")
    outcome = classification_outcome or "unclassified"
    blocked = ""
    if classification_outcome is None:
        blocked = "classification_required"
    elif classification_outcome == "prohibited":
        blocked = "prohibited"
    elif classification_outcome == "not_system":
        blocked = "not_system"
    elif classification_outcome not in OUTCOMES:
        blocked = "classification_required"
    kinds = _fact_kinds(facts_v1)
    items: list[PlanItem] = []
    for n, dim_id in enumerate(ORDER, start=1):
        if blocked:
            applies, reason = False, blocked
        else:
            applies, reason = _applies(dim_id, outcome, system, flags, kinds, institution, cfg)
        live = catalog.live_agent(dim_id) if applies else None
        if live is not None:
            loop = (
                ((live.definition.get("harness") or {}).get("loop") or {})
                if live.definition
                else {}
            )
            asked = loop.get("budget_tokens")
            tokens = min(
                int(asked) if isinstance(asked, int) and asked > 0 else budget.agent_tokens,
                caps.LOOP_BUDGET_MAX,
            )
            items.append(
                PlanItem(
                    dim_id,
                    n,
                    True,
                    reason,
                    f"{live.agent_id}@{live.version}",
                    live.agent_id,
                    live.version,
                    budget.agent_seconds,
                    tokens,
                )
            )
        else:
            items.append(
                PlanItem(
                    dim_id,
                    n,
                    applies,
                    reason,
                    "rule",
                    "rule-proposal",
                    "1",
                    budget.rule_seconds if applies else 0,
                    0,
                )
            )
    return Plan(sid, outcome, blocked, tuple(items), budget)


# ------------------------------------------------------------------------------ the rule runner


def _now_ts(inputs: Mapping[str, Any]) -> str:
    return str(inputs.get("now") or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))


def _trace(budget_tokens: int, refs: list[str], n: int) -> dict[str, Any]:
    return {
        "system_prompt": {"preamble_version": 1, "instructions_tokens": 0},
        "context": {
            "sources_loaded": n,
            "tokens_used": 0,
            "budget_tokens": budget_tokens,
            "source_refs": refs[:200],
        },
        "memory": {"reads": 0, "writes": 0, "rows_stored": 0},
        "hitl": {"stop_points_fired": 0, "approvals_requested": 0, "tool_calls_blocked": 0},
        "verification": {"findings_checked": n, "findings_rejected": 0, "judge_calls": 0},
        "loop": {
            "iterations": 1,
            "stopped_by": "single_pass",
            "tokens_used": 0,
            "per_iteration": [],
        },
    }


def _summary(findings: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    n = {v: sum(1 for f in findings if f["verdict"] == v) for v in caps.VERDICTS}
    return {
        "total": len(findings),
        "passed": n["pass"],
        "failed": n["fail"],
        "not_applicable": n["not_applicable"],
        "questions": n["question"],
    }


def rule_findings(
    dim_id: str, proposal: Mapping[str, Any], prior: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One finding per mapped pack or monitor with its result as evidence; the verdict follows the
    rule proposal: ok -> pass, fail -> fail, anything else -> question for a required item and
    not_applicable for an optional one. A type with no mapped item gets one question for a person.
    ``legal_compliance`` also gets one finding per type it read (``prior``)."""
    out: list[dict[str, Any]] = []
    for i, check in enumerate(proposal.get("checks") or [], start=1):
        pointers = [str(p) for p in check.get("pointers") or []]
        state = str(check["state"])
        required = bool(check["required"])
        if state == "ok" and pointers:
            verdict = "pass"
        elif state == "fail" and pointers:
            verdict = "fail"
        elif required or state == "fail":
            verdict = "question"
        else:
            verdict = "not_applicable"
        kind = "pack" if check["kind"] == "pack" else "system_record"
        evidence = [{"kind": kind, "ref": p[:300]} for p in pointers[:5]]
        out.append(
            {
                "finding_id": f"f{i}-{check['id']}"[:64],
                "checklist_id": f"{check['kind']}:{check['id']}"[:64],
                "verdict": verdict,
                "evidence": evidence,
                "rationale": (
                    f"{check['kind']} {check['id']} is {state} "
                    f"({'required' if required else 'optional'}); the stored result is the "
                    "evidence."
                ),
                "confidence": "high" if evidence else "low",
            }
        )
    if dim_id == "legal_compliance":
        for other, rep in prior.items():
            verdict = str(rep["verdict"])
            out.append(
                {
                    "finding_id": f"reads-{other}"[:64],
                    "checklist_id": f"reads:{other}"[:64],
                    "verdict": "pass"
                    if verdict == "pass"
                    else "fail"
                    if verdict == "fail"
                    else "question",
                    "evidence": [{"kind": "system_record", "ref": f"report:{rep['report_id']}"}],
                    "rationale": f"Read the report of {other}: worst verdict {verdict}.",
                    "confidence": "high",
                }
            )
    if dim_id in ("legal_compliance", "third_party", "reputation") or not out:
        out.append(
            {
                "finding_id": "person-decides",
                "checklist_id": "person:decides",
                "verdict": "question",
                "evidence": [],
                "rationale": (
                    "No pack or monitor decides this risk type; a person decides it "
                    "(see the Duties step)."
                ),
                "confidence": "high",
            }
        )
    return out


class RuleRunner:
    """The default runner: an ``assessment_report_v1`` built from the rule proposal. No model."""

    def run(self, request: AgentRequest) -> dict[str, Any]:
        inputs = request.inputs
        proposal = inputs.get("proposal") or {}
        findings = rule_findings(request.dimension_id, proposal, inputs.get("prior") or {})
        refs = [e["ref"] for f in findings for e in f["evidence"]]
        return {
            "report_id": request.report_id,
            "agent_id": request.agent_id,
            "agent_version": request.agent_version,
            "system_id": request.system_id,
            "dimension_id": request.dimension_id,
            "findings": findings,
            "summary": _summary(findings),
            "model_id": "none",
            "harness_trace": _trace(request.budget_tokens, refs, len(findings)),
            "created_at": _now_ts(inputs),
        }


class RoutingRunner:
    """A live agent goes to ``factory.runtime.run_agent(definition, inputs)`` once WP-F3 provides
    it; everything else (and every live agent while the runtime does not exist) goes to the rule
    runner."""

    def __init__(self, rule: Runner | None = None) -> None:
        self.rule = rule or RuleRunner()

    @staticmethod
    def _agent_runtime() -> Callable[..., dict[str, Any]] | None:
        import importlib

        try:
            mod = importlib.import_module("supervisor.factory.runtime")
        except ImportError:
            return None
        fn = getattr(mod, "run_agent", None)
        return fn if callable(fn) else None

    def run(self, request: AgentRequest) -> dict[str, Any]:
        if request.definition is not None:
            fn = self._agent_runtime()
            if fn is not None:
                inputs = {**request.inputs, "report_id": request.report_id}
                inputs["budget"] = {
                    "seconds": request.budget_seconds,
                    "tokens": request.budget_tokens,
                }
                return dict(fn(request.definition, inputs))
        return self.rule.run(request)


# ------------------------------------------------------------------------------ verdict rules


def worst_verdict(findings: Sequence[Mapping[str, Any]]) -> str:
    """The conflict rule: the worst verdict wins (fail, question, pass, not_applicable)."""
    present = {str(f["verdict"]) for f in findings}
    for v in VERDICT_RANK:
        if v in present:
            return v
    return "question"  # no finding at all is not an answer


def _severity(request: AgentRequest, proposal: Mapping[str, Any], checklist_id: str) -> str:
    if request.definition is not None:
        for c in request.definition.get("checklist") or []:
            if isinstance(c, Mapping) and c.get("id") == checklist_id:
                return str(c.get("severity") or "medium")
        return "medium"
    if checklist_id.startswith("reads:"):
        return "high"
    for check in proposal.get("checks") or []:
        if f"{check['kind']}:{check['id']}" == checklist_id:
            return "high" if check["required"] else "low"
    return "medium"


def stop_point(
    report: Mapping[str, Any], request: AgentRequest, proposal: Mapping[str, Any]
) -> str:
    """The hitl rule: a ``fail`` on a ``high`` severity item stops the type for a person; so does
    a verdict or checklist approval point of the agent definition. Returns a code or ``""``."""
    points: list[tuple[str, str]] = []
    if request.definition is not None:
        hitl = (request.definition.get("harness") or {}).get("hitl") or {}
        for ap in hitl.get("approval_points") or []:
            if isinstance(ap, Mapping):
                points.append((str(ap.get("kind")), str(ap.get("ref"))))
    for f in report["findings"]:
        if f["verdict"] == "fail" and _severity(request, proposal, f["checklist_id"]) == "high":
            return f"high_fail:{f['checklist_id']}"[:100]
        for kind, ref in points:
            if (kind == "verdict" and f["verdict"] == ref) or (
                kind == "checklist" and f["checklist_id"] == ref
            ):
                return f"approval_point:{ref}"[:100]
    return ""


def _tokens_used(report: Mapping[str, Any]) -> int:
    trace = report["harness_trace"]
    return int(max(trace["context"]["tokens_used"], trace["loop"]["tokens_used"]))


# ------------------------------------------------------------------------------ time limit


def call_limited(fn: Callable[[], Any], seconds: float) -> tuple[str, Any]:
    """Run ``fn`` in a daemon thread. Returns ``("ok", value)``, ``("error", exception)`` or
    ``("timeout", None)``. A thread that overruns is left to finish by itself; its result is
    dropped."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - reported as an item, never raised
            box["error"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(max(0.0, seconds))
    if th.is_alive():
        return "timeout", None
    if "error" in box:
        return "error", box["error"]
    return "ok", box.get("value")


# ------------------------------------------------------------------------------ storage helpers


def _clean(text: Any, limit: int) -> str:
    return agent_log.clean(text, limit)


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default if value is None else value


def _stamp(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else format_ts(value)


@dataclass
class OrchestratorRun:
    run_id: str
    system_id: str
    attempt_n: int
    status: str
    plan: dict[str, Any]
    plan_hash: str
    budget: dict[str, Any]
    items: list[dict[str, Any]]
    summary: str
    started_at: str | None
    finished_at: str | None
    created_by: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> OrchestratorRun:
        return cls(
            run_id=str(row["run_id"]),
            system_id=str(row["system_id"]),
            attempt_n=int(row["attempt_n"]),
            status=str(row["status"]),
            plan=dict(_json(row.get("plan_json"), {})),
            plan_hash=str(row["plan_hash"]),
            budget=dict(_json(row.get("budget_json"), {})),
            items=[dict(i) for i in _json(row.get("items_json"), [])],
            summary=str(row.get("summary") or ""),
            started_at=_stamp(row.get("started_at")),
            finished_at=_stamp(row.get("finished_at")),
            created_by=str(row.get("created_by") or ""),
        )

    @property
    def running(self) -> bool:
        return self.status in ("queued", "running")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "system_id": self.system_id,
            "attempt_n": self.attempt_n,
            "status": self.status,
            "running": self.running,
            "plan": self.plan,
            "plan_hash": self.plan_hash,
            "budget": self.budget,
            "items": self.items,
            "summary": self.summary,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "created_by": self.created_by,
            "banner": BANNER,
        }


def runs_of(ctx: Any, system_id: str) -> list[dict[str, Any]]:
    rows = [dict(r) for r in ctx.state.query(TABLE, {"system_id": system_id})]
    rows.sort(key=lambda r: (int(r["attempt_n"]), str(_stamp(r["started_at"]))))
    return rows


def latest(ctx: Any, system_id: str) -> OrchestratorRun | None:
    rows = runs_of(ctx, system_id)
    return OrchestratorRun.from_row(rows[-1]) if rows else None


def get(ctx: Any, run_id: str) -> OrchestratorRun | None:
    row = ctx.state.get(TABLE, {"run_id": run_id})
    return OrchestratorRun.from_row(dict(row)) if row is not None else None


def _save(ctx: Any, run_id: str, changes: Mapping[str, Any]) -> None:
    row = ctx.state.get(TABLE, {"run_id": run_id})
    if row is None:
        return
    ctx.state.update(TABLE, {"run_id": run_id}, dict(changes), row["row_version"])


def report_dir(settings: Any, system_id: str, attempt_n: int) -> Path:
    return Path(settings.data_dir) / "assessments" / system_id / str(int(attempt_n))


def write_json(path: Path, doc: Mapping[str, Any]) -> str:
    """Write ``doc`` as canonical-ish JSON (sorted keys, UTF-8) and return its SHA-256."""
    check_no_floats(doc)
    raw = json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)
    return hashlib.sha256(raw).hexdigest()


# ------------------------------------------------------------------------------ inputs


def system_row(ctx: Any, system_id: str) -> dict[str, Any]:
    from supervisor.governance.model import check_system_id

    check_system_id(system_id)
    row = ctx.state.get("ai_system", {"system_id": system_id})
    if row is None:
        from supervisor.core.errors import NotFoundError

        raise NotFoundError(f"AI system {system_id} does not exist")
    return dict(row)


def classification_outcome(ctx: Any, system_id: str) -> str | None:
    """The outcome of the newest approved classification record, or ``None``."""
    cur = ctx.classification_v2.get(system_id).get("current")
    return str(cur["outcome"]) if cur else None


def facts_for(ctx: Any, system_id: str) -> dict[str, Any] | None:
    """The ``facts_v1`` exports of the nodes and agents of the system, merged into one dict.
    ``None`` when ONBOARD_FACTS is off or there is no fact."""
    if not getattr(ctx.settings, "onboard_facts", False):
        return None
    from supervisor.factory.schemas.facts_v1 import export_card
    from supervisor.onboard.facts import FactsService

    svc = FactsService(ctx.settings, ctx.state, ctx.clock, tables=ctx.tables)
    merged: list[dict[str, Any]] = []
    nodes: list[str] = []
    for comp in ctx.state.query("system_component", {"system_id": system_id}):
        ref = str(comp["ref_id"])
        if str(comp.get("active", True)).lower() in ("false", "0"):
            continue
        try:
            doc = export_card(svc.card(ref))
        except Exception:  # noqa: BLE001, S112 - a node without a card adds nothing
            continue
        if doc["facts"]:
            nodes.append(ref)
            merged.extend(doc["facts"])
    if not merged:
        return None
    return {"version": 1, "nodes": nodes, "facts": merged}


def derive_flags(system: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "customer_decision": bool(system.get("credit_decision"))
        or system.get("system_type") == "decision",
        "personal_data": str(system.get("personal_data") or "none") != "none",
    }


def institution_of(settings: Any) -> str:
    return str(getattr(settings, "institution_type", "") or "bank")


# ------------------------------------------------------------------------------ start and run


def _attempt_next(ctx: Any, system_id: str) -> int:
    rows = runs_of(ctx, system_id)
    return (max(int(r["attempt_n"]) for r in rows) + 1) if rows else 1


def _close_stale(ctx: Any, system_id: str) -> None:
    """A row left ``queued`` or ``running`` with no thread of ours was cut by a restart: it becomes
    failed, so the system is not blocked for ever. Called with ``_LOCK`` held and no run of ours."""
    for r in runs_of(ctx, system_id):
        if r["status"] in ("queued", "running"):
            _save(
                ctx,
                r["run_id"],
                {
                    "status": "failed",
                    "finished_at": ctx.clock.now(),
                    "summary": "the run was cut short (the server restarted)",
                },
            )


def start(
    ctx: Any,
    system_id: str,
    by: str,
    *,
    attempt_n: int | None = None,
    background: bool = True,
    catalog: AgentCatalog | None = None,
    runner: Runner | None = None,
    budget: Budget | None = None,
) -> OrchestratorRun:
    """Plan, write a ``queued`` row and run in a background thread. One run at a time per system:
    a second start while one runs answers ``run_in_progress``. ``background=False`` finishes the run
    before the call returns (tests, the CLI)."""
    ensure_on(ctx.settings)
    system = system_row(ctx, system_id)
    if system.get("status") == "archived":
        raise OrchestratorError("archived", "the AI system is archived; it cannot be assessed")
    catalog = catalog or get_catalog()
    outcome = classification_outcome(ctx, system_id)
    facts = facts_for(ctx, system_id)
    the_plan = plan(
        system,
        outcome,
        derive_flags(system),
        facts,
        institution=institution_of(ctx.settings),
        catalog=catalog,
        budget=budget,
    )
    if the_plan.blocked:
        raise OrchestratorError(
            "plan_blocked",
            {
                "classification_required": "the AI system has no approved classification; "
                "classify and approve it first (step 4)",
                "prohibited": "the classification outcome is prohibited; nothing is assessed",
                "not_system": "the classification outcome is not_system; nothing is assessed",
            }[the_plan.blocked],
        )
    with _LOCK:
        if system_id in _RUNNING:
            raise OrchestratorError(
                "run_in_progress", f"a run for {system_id} is in progress; wait for it"
            )
        _close_stale(ctx, system_id)
        n = int(attempt_n) if attempt_n is not None else _attempt_next(ctx, system_id)
        if n < 1:
            raise OrchestratorError("bad_attempt", "attempt_n must be 1 or more")
        if any(int(r["attempt_n"]) == n for r in runs_of(ctx, system_id)):
            raise OrchestratorError("attempt_exists", f"attempt {n} of {system_id} already ran")
        now = ctx.clock.now()
        run_id = (
            "orc_" + hashlib.sha256(f"{system_id}|{n}|{time.time_ns()}".encode()).hexdigest()[:20]
        )
        items = [
            {
                "dimension_id": i.dimension_id,
                "order": i.order,
                "applies": i.applies,
                "reason": i.reason,
                "agent": i.agent,
                "status": "queued" if i.applies else "not_applicable",
                "verdict": "",
                "proposed_status": "",
                "status_written": "",
                "report_ref": "",
                "report_sha256": "",
                "stop_point": "",
                "needs_person": False,
                "ms_used": 0,
                "tokens_used": 0,
                "note": "",
            }
            for i in the_plan.items
        ]
        ctx.state.insert(
            TABLE,
            {
                "run_id": run_id,
                "system_id": system_id,
                "attempt_n": n,
                "plan_json": the_plan.to_dict(),
                "plan_hash": the_plan.plan_hash,
                "status": "queued",
                "started_at": now,
                "finished_at": None,
                "budget_json": {**the_plan.budget.to_dict(), "used_ms": 0, "used_tokens": 0},
                "items_json": items,
                "summary": "queued",
                "created_by": _clean(by, 120) or "unknown",
            },
        )
        _RUNNING[system_id] = run_id
    args = (ctx, run_id, the_plan, system, facts, runner or RoutingRunner(), catalog)
    if background:
        th = threading.Thread(target=_thread, args=args, daemon=True)
        _THREADS[system_id] = th
        th.start()
    else:
        _thread(*args)
    out = get(ctx, run_id)
    assert out is not None  # noqa: S101 - the row was just inserted
    return out


def run(
    ctx: Any,
    system_id: str,
    attempt_n: int,
    *,
    by: str = "rule:orchestrator",
    catalog: AgentCatalog | None = None,
    runner: Runner | None = None,
    budget: Budget | None = None,
) -> OrchestratorRun:
    """Run attempt ``attempt_n`` to the end in this thread (queued -> running -> done or failed)."""
    return start(
        ctx,
        system_id,
        by,
        attempt_n=attempt_n,
        background=False,
        catalog=catalog,
        runner=runner,
        budget=budget,
    )


def join(system_id: str, timeout: float = 60.0) -> None:
    th = _THREADS.get(system_id)
    if th is not None:
        th.join(timeout)


def _thread(
    ctx: Any,
    run_id: str,
    the_plan: Plan,
    system: Mapping[str, Any],
    facts: Mapping[str, Any] | None,
    runner: Runner,
    catalog: AgentCatalog,
) -> None:
    sid = the_plan.system_id
    try:
        _execute(ctx, run_id, the_plan, system, facts, runner, catalog)
    except Exception as exc:  # noqa: BLE001 - the thread must leave a row, never die silently
        log.warning("orchestrator: run failed (%s)", type(exc).__name__)
        try:
            _finish(ctx, run_id, "failed", f"the run broke: {type(exc).__name__}")
        except Exception:  # noqa: BLE001
            log.exception("orchestrator: could not close the run row")
    finally:
        with _LOCK:
            if _RUNNING.get(sid) == run_id:
                del _RUNNING[sid]


def _log(ctx: Any, run_id: str, sid: str, n: int, what: str) -> None:
    agent_log.log(ctx, sid, "orchestrate", what, f"run {run_id}", "rule", "rule", attempt_n=n)


def _finish(ctx: Any, run_id: str, status: str, summary: str) -> None:
    _save(
        ctx,
        run_id,
        {"status": status, "finished_at": ctx.clock.now(), "summary": _clean(summary, MAX_SUMMARY)},
    )
    row = get(ctx, run_id)
    if row is not None:
        _chain(ctx, row)
        _log(ctx, run_id, row.system_id, row.attempt_n, f"run {status}: {row.summary}"[:300])


def _counts(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    c = dict.fromkeys(ITEM_STATUSES, 0)
    for i in items:
        c[str(i["status"])] = c.get(str(i["status"]), 0) + 1
    return c


def _chain(ctx: Any, row: OrchestratorRun) -> None:
    sink = getattr(getattr(ctx, "runtime", None), "chain", None)
    if sink is None:
        return
    c = _counts(row.items)
    payload = {
        "run_id": row.run_id,
        "system_id": row.system_id,
        "attempt_n": row.attempt_n,
        "plan_hash": row.plan_hash,
        "status": row.status,
        "n_dimensions": len(row.items),
        "n_applicable": sum(1 for i in row.items if i["applies"]),
        "n_done": c["done"],
        "n_needs_person": c["needs_person"],
        "n_budget_exceeded": c["budget_exceeded"],
        "n_failed": c["failed"],
        "ts": format_ts(ctx.clock.now()),
    }
    try:
        check_no_floats(payload)
        sink.record(RECORD_TYPE, f"orchestrator:{row.run_id}", payload)
    except Exception:  # noqa: BLE001 - the row is stored; log and go on
        log.exception("orchestrator chain record failed")


def _proposed_status(verdict: str, stop: bool) -> str:
    """Never ``pass``: a pass verdict is only a proposal that a person confirms."""
    if verdict == "fail" or stop:
        return "fail"
    return "in_progress"


def _write_status(
    env: rd.Env,
    system: Mapping[str, Any],
    dim_id: str,
    status: str,
    agent: str,
    report_id: str,
    pointers: list[str],
    note: str,
) -> str:
    """Write the proposal into ``risk_dimension_status``. Returns the status written or ``""`` when
    the row is left alone (waived by a person). Never writes ``pass``."""
    if status == "pass":  # defence in depth: the caller never passes it
        raise OrchestratorError("pass_needs_person", "the orchestrator never writes pass")
    row = rd._need_row(env, system, dim_id)
    if row["status"] == "waived":
        return ""
    evidence = rd.clean_pointers([f"report:{report_id}", *pointers])
    changes: dict[str, Any] = {
        "status": status,
        "assessed_by": agent[:128],
        "report_ref": report_id,
        "evidence_json": evidence,
        "updated_by": "rule:orchestrator",
        "note": rd.clean_text(note, "the note") or None,
    }
    changes["valid_until"] = None
    rd._store(env, row, changes)
    rd._record(
        env,
        str(system["system_id"]),
        dim_id,
        str(row["status"]),
        status,
        "rule:orchestrator",
        evidence,
    )
    return status


def _write_na(env: rd.Env, system: Mapping[str, Any], dim_id: str, reason: str) -> str:
    row = rd._need_row(env, system, dim_id)
    if row["status"] in ("waived", "pass", "fail", "not_applicable"):
        return ""
    note = rd.clean_text(f"not applicable by rule: {reason} (orchestrator plan)", "the note", 20)
    rd._store(
        env,
        row,
        {
            "status": "not_applicable",
            "assessed_by": "rule:orchestrator",
            "updated_by": "rule:orchestrator",
            "note": note,
        },
    )
    rd._record(
        env,
        str(system["system_id"]),
        dim_id,
        str(row["status"]),
        "not_applicable",
        "rule:orchestrator",
        [],
    )
    return "not_applicable"


def _execute(
    ctx: Any,
    run_id: str,
    the_plan: Plan,
    system: Mapping[str, Any],
    facts: Mapping[str, Any] | None,
    runner: Runner,
    catalog: AgentCatalog,
) -> None:
    row = get(ctx, run_id)
    assert row is not None  # noqa: S101
    sid, n = row.system_id, row.attempt_n
    _save(ctx, run_id, {"status": "running", "summary": "running"})
    env = rd.Env.from_console(ctx)
    rd.ensure_rows(env, system)
    proposals = rd.propose(env, sid)
    _log(
        ctx,
        run_id,
        sid,
        n,
        f"plan {the_plan.plan_hash[:12]}: outcome {the_plan.outcome}, "
        f"{len(the_plan.applicable())} of {len(the_plan.items)} types apply",
    )
    items = row.items
    budget = the_plan.budget
    out_dir = report_dir(ctx.settings, sid, n)
    used_ms = 0
    used_tokens = 0
    prior: dict[str, dict[str, Any]] = {}
    t_start = time.monotonic()
    now_ts = ctx.clock.now().astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")  # report format

    def push() -> None:
        _save(
            ctx,
            run_id,
            {
                "items_json": items,
                "budget_json": {**budget.to_dict(), "used_ms": used_ms, "used_tokens": used_tokens},
            },
        )

    for pi, item in zip(the_plan.items, items, strict=True):
        dim = pi.dimension_id
        if not pi.applies:
            item["status_written"] = _write_na(env, system, dim, pi.reason)
            item["note"] = _clean(f"not applicable: {pi.reason}", MAX_NOTE)
            _log(ctx, run_id, sid, n, f"{dim}: not applicable ({pi.reason})")
            continue
        item["status"] = "running"
        push()
        _log(ctx, run_id, sid, n, f"{dim}: start, agent {pi.agent}")
        remaining_s = budget.total_seconds - (time.monotonic() - t_start)
        remaining_t = budget.total_tokens - used_tokens
        limit_s = min(float(pi.budget_seconds), remaining_s)
        limit_t = min(pi.budget_tokens, remaining_t) if pi.agent != "rule" else 0
        if limit_s <= 0 or (pi.agent != "rule" and limit_t <= 0):
            item["status"] = "budget_exceeded"
            item["note"] = "the budget of the run was used up before this type started"
            _log(ctx, run_id, sid, n, f"{dim}: budget exceeded before start")
            push()
            continue
        live = pi.agent != "rule"
        definition: Mapping[str, Any] | None = None
        if live:
            la = catalog.live_agent(dim)
            if la is not None and la.agent_id != pi.agent_id:
                la = None
            definition = la.definition if la else None
        report_id = f"{run_id}-{dim}"
        req = AgentRequest(
            run_id=run_id,
            system_id=sid,
            attempt_n=n,
            dimension_id=dim,
            report_id=report_id,
            agent_id=pi.agent_id,
            agent_version=pi.agent_version,
            definition=definition,
            inputs={
                "system": dict(system),
                "facts": facts,
                "proposal": proposals[dim],
                "prior": prior,
                "now": now_ts,
            },
            budget_seconds=int(limit_s),
            budget_tokens=int(limit_t),
        )
        t0 = time.monotonic()
        outcome, value = call_limited(lambda r=req: runner.run(r), limit_s)
        ms = int((time.monotonic() - t0) * 1000)
        used_ms += ms
        item["ms_used"] = ms
        if outcome == "timeout":
            item["status"] = "budget_exceeded"
            item["note"] = f"cut after {int(limit_s)} s (time budget)"
            _log(ctx, run_id, sid, n, f"{dim}: cut by the time budget")
            push()
            continue
        if outcome == "error":
            item["status"] = "failed"
            item["note"] = _clean(f"the runner raised {type(value).__name__}", MAX_NOTE)
            _log(ctx, run_id, sid, n, f"{dim}: runner failed ({type(value).__name__})")
            push()
            continue
        try:
            report = AssessmentReportV1.model_validate(value).model_dump(mode="json")
            if report["dimension_id"] != dim or report["system_id"] != sid:
                raise ValueError("report is for another type or system")
        except Exception as exc:  # noqa: BLE001 - an invalid report fails the item
            item["status"] = "failed"
            item["note"] = _clean(f"invalid assessment_report_v1: {type(exc).__name__}", MAX_NOTE)
            _log(ctx, run_id, sid, n, f"{dim}: report not valid")
            push()
            continue
        tokens = _tokens_used(report)
        item["tokens_used"] = tokens
        used_tokens += tokens
        if live and tokens > limit_t:
            item["status"] = "budget_exceeded"
            item["note"] = f"used {tokens} tokens; the budget was {limit_t}"
            _log(ctx, run_id, sid, n, f"{dim}: cut by the token budget")
            push()
            continue
        path = out_dir / f"{dim}.json"
        sha = write_json(path, report)
        verdict = worst_verdict(report["findings"])
        stop = stop_point(report, req, proposals[dim])
        item.update(
            {
                "verdict": verdict,
                "report_ref": report["report_id"],
                "report_sha256": sha,
                "stop_point": stop,
                "needs_person": verdict == "fail" or bool(stop),
                "status": "needs_person" if stop else "done",
                "proposed_status": "pass" if verdict == "pass" and not stop else verdict,
            }
        )
        pointers = [
            e["ref"]
            for f in report["findings"]
            for e in f["evidence"]
            if e["kind"] == "pack" and rd._POINTER.match(e["ref"])
        ][:5]
        item["status_written"] = _write_status(
            env,
            system,
            dim,
            _proposed_status(verdict, bool(stop)),
            f"{pi.agent}"[:128],
            report["report_id"],
            pointers,
            f"orchestrator run {run_id}: verdict {verdict}"
            + (f", stop point {stop}" if stop else "")
            + "; a person confirms",
        )
        prior[dim] = {"report_id": report["report_id"], "verdict": verdict}
        _log(
            ctx,
            run_id,
            sid,
            n,
            f"{dim}: {item['status']}, verdict {verdict}" + (f", stop {stop}" if stop else ""),
        )
        push()
    # duties pre-fill and the run row
    prefill = build_duties_prefill(ctx, env, row, the_plan, items)
    write_json(out_dir / "duties_prefill.json", prefill)
    c = _counts(items)
    summary = (
        f"{len(the_plan.applicable())} types planned: {c['done']} done, {c['needs_person']} need a "
        f"person, {c['budget_exceeded']} over budget, {c['failed']} failed; "
        f"{c['not_applicable']} not applicable"
    )
    push()
    _finish(ctx, run_id, "done", summary)


# ------------------------------------------------------------------------------ the duties pre-fill


def build_duties_prefill(
    ctx: Any,
    env: rd.Env,
    row: OrchestratorRun,
    the_plan: Plan,
    items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Which duties the reports can answer: the articles and controls of every type whose report
    has the verdict ``pass``. ``confirmed`` becomes true only when a person set the status to
    ``pass`` (``read_duties_prefill`` re-reads it)."""
    covered: list[dict[str, Any]] = []
    open_: list[dict[str, str]] = []
    for it in items:
        dim = env.cfg.get(str(it["dimension_id"]))
        if it["applies"] and it["verdict"] == "pass" and not it["stop_point"]:
            covered.append(
                {
                    "dimension_id": dim.id,
                    "articles": list(dim.articles),
                    "controls": list(dim.controls),
                    "report_ref": it["report_ref"],
                    "report_sha256": it["report_sha256"],
                    "confirmed": False,
                }
            )
        else:
            open_.append(
                {"dimension_id": dim.id, "why": str(it["verdict"] or it["status"] or "open")}
            )
    return {
        "version": 1,
        "banner": BANNER,
        "system_id": row.system_id,
        "attempt_n": row.attempt_n,
        "run_id": row.run_id,
        "plan_hash": the_plan.plan_hash,
        "outcome": the_plan.outcome,
        "generated_at": format_ts(ctx.clock.now()),
        "covered": covered,
        "open": open_,
    }


def read_duties_prefill(settings: Any, system_id: str, state: Any = None) -> dict[str, Any] | None:
    """The newest ``duties_prefill.json`` of the system, or ``None``. With ``state`` each covered
    entry gets ``confirmed`` = the status row of the type is ``pass`` now. For the Duties step of
    the register workflow (WP-C3 wires it). Reads a file only; never raises."""
    try:
        from supervisor.governance.model import check_system_id

        base = Path(settings.data_dir) / "assessments" / check_system_id(system_id)
        attempts = sorted((int(p.name) for p in base.iterdir() if p.name.isdigit()), reverse=True)
        for a in attempts:
            path = base / str(a) / "duties_prefill.json"
            if not path.is_file():
                continue
            doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            if state is not None:
                for c in doc.get("covered", []):
                    r = state.get(
                        "risk_dimension_status",
                        {"status_id": rd.status_id(system_id, c["dimension_id"])},
                    )
                    c["confirmed"] = bool(r is not None and r["status"] == "pass")
            return doc
    except Exception:  # noqa: BLE001 - a missing or broken file is "no pre-fill"
        return None
    return None


def report_path(settings: Any, system_id: str, attempt_n: int, dim_id: str) -> Path | None:
    if dim_id not in rd.DIMENSION_IDS:
        return None
    p = report_dir(settings, system_id, attempt_n) / f"{dim_id}.json"
    return p if p.is_file() else None


__all__ = [
    "AgentCatalog",
    "AgentRequest",
    "Budget",
    "LiveAgent",
    "NullCatalog",
    "OrchestratorError",
    "OrchestratorRun",
    "Plan",
    "PlanItem",
    "RoutingRunner",
    "RuleRunner",
    "Runner",
    "enabled",
    "plan",
    "read_duties_prefill",
    "run",
    "start",
    "worst_verdict",
]
