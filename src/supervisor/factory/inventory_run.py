"""Run one risk assessment agent over the whole AI inventory (flag ``FACTORY_INVENTORY_RUN``).

The owner asks: "in deploying a risk assessment agent, I want it fully run and simulated on the
entire use cases inventory". This module is that run. It takes ONE agent version (a draft or a live
one), picks every AI system of the inventory where the agent's risk type applies, and runs the
agent on each system with the gateway model (``factory.runtime.run_agent``). It stores one report
and one executive document per system under::

    DATA_DIR/factory/<agent>/inventory/<run_id>/
        run.json                      status, counts, tokens, seconds, model id, agent version
        rows.jsonl                    one summary line per system (the dashboard reads this)
        systems/<system>/<dim>.json           the assessment_report_v1 (text masked)
        systems/<system>/<dim>.evidence.json  masked snippets of the cited sources
        systems/<system>/<dim>.exec.json      the executive_v1 document (onboard.executive)

A simulation never promotes a version and never writes ``risk_dimension_status`` or any other
table. The only state it keeps outside its folder is one ``factory_agent_event`` row.

Which systems (the plan)
------------------------
* Skipped: status ``archived``, lifecycle stage ``retirement``.
* The outcome of the classification tree decides the rest. A system with an applied classification
  record uses its outcome. A system without one gets an outcome derived from its record
  (``derived_outcome``): risk level ``prohibited`` -> ``prohibited``; ``high`` or Decision 33 class
  ``high_risk`` -> ``high_self``; ``medium`` -> ``medium``; ``low`` -> ``low``; nothing set (level
  ``unspecified``) -> ``medium``. An unknown is never a reason to skip an assessment, so it is
  assessed as ``medium``.
* ``orchestrator.plan`` then says whether the agent's risk type applies (the same rules as a real
  risk assessment: ``high`` = all eight types, core types always, ethics by decision/personal data,
  ``third_party``, ``supply_chain`` and ``reputation`` by signals). Prohibited and not-a-system
  outcomes assess nothing.

Inputs of one system are what the orchestrator builds: the system row,
``orchestrator.facts_for``, the rule proposal of ``risk_dimensions.propose`` for the type and
``prior`` = ``{}``.

Errors per system are recorded in the row and never stop the run. Not legal advice. Bank counsel
confirms.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import threading
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import SupervisorError
from supervisor.core.ports import ChatModel
from supervisor.factory import caps, gate
from supervisor.factory import runtime as rt
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from supervisor.factory.schemas.assessment_report_v1 import AssessmentReportV1
from supervisor.factory.store import definition_sha256
from supervisor.onboard.agent_log import clean

log = logging.getLogger("supervisor.factory.inventory_run")

FORMAT = "inventory_run_v1"
FLAG_TEXT = (
    "Inventory runs are switched off. Ask an administrator to set FACTORY_INVENTORY_RUN=1 "
    "(it also needs AGENT_FACTORY and GOVERNANCE_ENABLED)."
)
BANNER = "Simulation on the inventory. It does not change any assessment."
RUN_ID_RE = re.compile(r"^inv_[0-9a-f]{20}$")
ACTIVE = ("queued", "running")
VERDICTS = ("fail", "question", "pass", "not_applicable")
SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}
PARALLEL_MIN, PARALLEL_MAX = 1, 16
SYSTEM_SECONDS = 120
SNIPPET = 300
LEVELS = ("high", "medium", "low", "prohibited", "unspecified")
HIGH_OUTCOMES = ("high_certify", "high_self")

_LOCK = threading.Lock()
_RUNNING: dict[str, str] = {}  # agent id -> run id
_THREADS: dict[str, threading.Thread] = {}
_CANCEL: dict[str, threading.Event] = {}


class InventoryError(SupervisorError):
    """A refused request (HTTP 400). ``code`` is the stable machine word."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


# ------------------------------------------------------------------------------ settings


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "factory_inventory_run", False)
        and getattr(settings, "agent_factory", False)
        and getattr(settings, "governance_enabled", False)
    )


def require_on(settings: Any) -> None:
    if not enabled(settings):
        raise InventoryError("factory_inventory_off", FLAG_TEXT)


def parallel_of(settings: Any) -> int:
    try:
        n = int(getattr(settings, "factory_inventory_parallel", 4))
    except (TypeError, ValueError):
        n = 4
    return min(max(n, PARALLEL_MIN), PARALLEL_MAX)


def max_of(settings: Any) -> int:
    try:
        return max(0, int(getattr(settings, "factory_inventory_max", 0)))
    except (TypeError, ValueError):
        return 0


# ------------------------------------------------------------------------------ environment


class Meter:
    """Counts the calls and the estimated tokens of a model; safe across threads."""

    def __init__(self, inner: ChatModel) -> None:
        self.inner = inner
        self.family = getattr(inner, "family", "")
        self.model_id = getattr(inner, "model_id", "")
        self.is_mock = getattr(inner, "is_mock", False)
        self.calls = 0
        self.tokens = 0
        self._lock = threading.Lock()

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float,
    ) -> Mapping[str, Any]:
        with self._lock:
            self.calls += 1
            self.tokens += caps.estimate_tokens(json.dumps(list(messages), default=str))
        out = self.inner.complete_json(messages, json_schema, timeout_s)
        with self._lock:
            self.tokens += caps.estimate_tokens(json.dumps(out, default=str))
        return out


@dataclass
class InvEnv:
    """What an inventory run needs: the console context (inventory, classification, facts, risk
    rules) and the gate environment (settings, clock, factory store, tools, model)."""

    ctx: Any
    gate: gate.GateEnv

    @property
    def settings(self) -> Any:
        return self.gate.settings

    @property
    def data_dir(self) -> Path:
        return self.gate.data_dir

    @classmethod
    def from_console(
        cls, ctx: Any, chat: ChatModel | None = None, tools: Any = None, groups: Any = None
    ) -> InvEnv:
        return cls(ctx, gate.GateEnv.from_console(ctx, chat, tools, groups))


def _executive() -> Any:
    """The executive module (``supervisor.onboard.executive``) or ``None`` while it is not there.
    Tests replace this function with a stub."""
    try:
        from supervisor.onboard import executive

        return executive
    except ImportError:
        return None


# ------------------------------------------------------------------------------ files


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:80] or "system"


def check_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id or ""):
        raise InventoryError("bad_id", "this is not an inventory run id")
    return run_id


def run_dir(data_dir: Path, agent_id: str, run_id: str) -> Path:
    if not caps.ID_RE.match(agent_id or ""):
        raise InventoryError("bad_id", "this is not an agent id")
    return Path(data_dir) / "factory" / agent_id / "inventory" / check_run_id(run_id)


def read_rows(d: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        text = (d / "rows.jsonl").read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def read_run(data_dir: Path, agent_id: str, run_id: str) -> dict[str, Any]:
    """``run.json``. A run left ``queued`` or ``running`` by a restart reads as ``failed``."""
    doc = gate.read_json(run_dir(data_dir, agent_id, run_id) / "run.json")
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise InventoryError("not_found", "this inventory run does not exist")
    if doc["status"] in ACTIVE and _RUNNING.get(agent_id) != run_id:
        doc["status"] = "failed"
        doc["error"] = doc.get("error") or "stopped_by_restart"
    ev = _CANCEL.get(run_id)
    if doc["status"] in ACTIVE and ev is not None and ev.is_set():
        doc["cancel_requested"] = True
    return doc


def list_runs(data_dir: Path, agent_id: str, limit: int = 30) -> list[dict[str, Any]]:
    if not caps.ID_RE.match(agent_id or ""):
        raise InventoryError("bad_id", "this is not an agent id")
    root = Path(data_dir) / "factory" / agent_id / "inventory"
    out: list[dict[str, Any]] = []
    try:
        names = [p.name for p in root.iterdir() if RUN_ID_RE.match(p.name)]
    except OSError:
        return out
    for name in names:
        try:
            out.append(read_run(data_dir, agent_id, name))
        except InventoryError:
            continue
    out.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return out[:limit]


# ------------------------------------------------------------------------------ the plan


def derived_outcome(system: Mapping[str, Any]) -> str:
    """The classification outcome for a system without an applied classification record. See the
    module doc: an unknown is assessed as ``medium``, never skipped."""
    level = str(system.get("risk_level") or "unspecified")
    d33 = str(system.get("decision33_class") or "unclassified")
    if level == "prohibited":
        return "prohibited"
    if level == "high" or d33 == "high_risk":
        return "high_self"
    if level in ("medium", "low"):
        return level
    return "medium"


def level_of(outcome: str) -> str:
    if outcome in HIGH_OUTCOMES:
        return "high"
    if outcome in ("medium", "low", "prohibited"):
        return outcome
    return "unspecified"


@dataclass
class ScopeItem:
    system_id: str
    name: str
    owner_team: str
    outcome: str
    outcome_source: str  # classification | derived
    level: str
    customer_facing: bool
    reason: str
    facts: Any = None
    facts_loaded: bool = False


@dataclass
class Scope:
    items: list[ScopeItem] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    inventory_n: int = 0
    cut_n: int = 0  # systems left out by FACTORY_INVENTORY_MAX


def _outcome(ctx: Any, system: Mapping[str, Any]) -> tuple[str, str]:
    from supervisor.onboard import orchestrator as orch

    try:
        got = orch.classification_outcome(ctx, str(system["system_id"]))
    except Exception:  # noqa: BLE001 - classification off or unreadable: use the record
        got = None
    if got:
        return got, "classification"
    return derived_outcome(system), "derived"


def _facts(ctx: Any, sid: str) -> Any:
    from supervisor.onboard import orchestrator as orch

    try:
        return orch.facts_for(ctx, sid)
    except Exception:  # noqa: BLE001 - a system whose facts cannot be read is assessed without
        log.warning("inventory run: the facts of one system could not be read")
        return None


def build_scope(env: InvEnv, dimension_id: str, limit: int = 0) -> Scope:
    """The systems the agent runs on. Reads the inventory; writes nothing."""
    from supervisor.governance import risk_dimensions as rd
    from supervisor.onboard import orchestrator as orch

    ctx = env.ctx
    try:
        cfg = rd.Env.from_console(ctx).cfg
    except Exception:  # noqa: BLE001 - risk dimensions off: the shipped config still plans
        cfg = rd.load_config()
    institution = orch.institution_of(ctx.settings)
    systems = sorted(ctx.state.query("ai_system"), key=lambda r: str(r["system_id"]))
    scope = Scope(inventory_n=len(systems))
    skipped: Counter[str] = Counter()
    for raw in systems:
        system = dict(raw)
        sid = str(system["system_id"])
        if str(system.get("status") or "") == "archived":
            skipped["archived"] += 1
            continue
        if str(system.get("lifecycle_stage") or "") == "retirement":
            skipped["retired"] += 1
            continue
        outcome, source = _outcome(ctx, system)
        flags = orch.derive_flags(system)
        p = orch.plan(system, outcome, flags, None, institution=institution, cfg=cfg)
        item = next((i for i in p.items if i.dimension_id == dimension_id), None)
        facts: Any = None
        loaded = False
        if item is not None and item.reason == "unknown_assume_applies":
            facts = _facts(ctx, sid)  # a signal in the code facts can rule the type out
            loaded = True
            p = orch.plan(system, outcome, flags, facts, institution=institution, cfg=cfg)
            item = next((i for i in p.items if i.dimension_id == dimension_id), None)
        if p.blocked in ("prohibited", "not_system"):
            skipped[p.blocked] += 1
            continue
        if item is None or not item.applies:
            skipped["not_applicable"] += 1
            continue
        scope.items.append(
            ScopeItem(
                sid,
                str(system.get("name") or sid),
                str(system.get("owner_team") or ""),
                outcome,
                source,
                level_of(outcome),
                str(system.get("user_segment") or "") == "customer",
                item.reason,
                facts,
                loaded,
            )
        )
    if limit and len(scope.items) > limit:
        scope.cut_n = len(scope.items) - limit
        scope.items = scope.items[:limit]
    scope.skipped = dict(skipped)
    return scope


def build_inputs(env: InvEnv, item: ScopeItem, dimension_id: str) -> dict[str, Any]:
    """The inputs the orchestrator would build for this system and type."""
    from supervisor.governance import risk_dimensions as rd
    from supervisor.onboard import orchestrator as orch

    ctx = env.ctx
    system = gate._json_safe(orch.system_row(ctx, item.system_id))
    facts = item.facts if item.facts_loaded else _facts(ctx, item.system_id)
    try:
        proposal = rd.propose(rd.Env.from_console(ctx), item.system_id, dimension_id)[dimension_id]
    except Exception:  # noqa: BLE001 - risk dimensions off: no pack results, still a run
        proposal = {}
    return {
        "system_id": item.system_id,
        "system": system,
        "facts": facts,
        "proposal": proposal,
        "prior": {},
        "now": format_ts(env.gate.clock.now()),
    }


# ------------------------------------------------------------------------------ one system


def _worst(verdicts: Mapping[str, str]) -> str:
    present = set(verdicts.values())
    return next((v for v in VERDICTS if v in present), "not_applicable")


def _mask_report(report: Mapping[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(report))
    for f in out.get("findings") or []:
        f["rationale"] = clean(f.get("rationale"), caps.RATIONALE_MAX)
    return out


def _exec_items(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for it in doc.get("items") or []:
        if not isinstance(it, Mapping):
            continue
        head = it.get("headline") or {}
        out.append(
            {
                "key": str(it.get("key") or "")[:64],
                "severity": str(it.get("severity") or "low"),
                "status": str(it.get("status") or "open"),
                "headline": {k: clean(head.get(k, ""), 200) for k in ("en", "vi")},
                "owner": str(it.get("owner") or ""),
            }
        )
    return out


def assess_one(
    env: InvEnv,
    defn: AgentDefinitionV1,
    definition: Mapping[str, Any],
    model: ChatModel,
    item: ScopeItem,
    out_dir: Path,
    db_lock: threading.Lock,
    tokens_cap: int,
) -> dict[str, Any]:
    """Assess one system. Returns its row; an error is a row with ``status`` ``error``."""
    dim = defn.dimension_id
    row: dict[str, Any] = {
        "system_id": item.system_id,
        "name": clean(item.name, 120),
        "owner_team": clean(item.owner_team, 80),
        "outcome": item.outcome,
        "outcome_source": item.outcome_source,
        "level": item.level,
        "customer_facing": item.customer_facing,
        "reason": item.reason,
        "status": "error",
        "error": "",
        "verdicts": {},
        "worst": "",
        "n_fail": 0,
        "n_question": 0,
        "rating": "",
        "exec_items": [],
        "exec_fail": 0,
        "tokens": 0,
        "ms": 0,
    }
    t0 = time.monotonic()

    def done() -> dict[str, Any]:
        row["ms"] = int((time.monotonic() - t0) * 1000)
        return row

    try:
        with db_lock:  # the inventory reads are serial; the model calls run in parallel
            inputs = build_inputs(env, item, dim)
        inputs["report_id"] = f"inv-{safe(item.system_id)}"[:60]
        inputs["budget"] = {"seconds": SYSTEM_SECONDS, "tokens": tokens_cap}
        report = rt.run_agent(definition, inputs, model, env.gate.clock, tools=env.gate.tools)
    except rt.AgentRuntimeError as exc:
        row["error"] = exc.code
        return done()
    except Exception as exc:  # noqa: BLE001 - one system never stops the run
        row["error"] = f"run_broke_{type(exc).__name__}"[:60]
        return done()
    try:
        valid = AssessmentReportV1.model_validate(report).model_dump(mode="json")
        if valid["dimension_id"] != dim:
            raise ValueError("another type")
    except Exception:  # noqa: BLE001 - an invalid report is an error row
        row["error"] = "invalid_report"
        return done()
    masked = _mask_report(valid)
    sub = out_dir / "systems" / safe(item.system_id)
    try:
        texts = rt.loaded_texts(definition, inputs, masked)
    except Exception:  # noqa: BLE001 - evidence snippets are a convenience
        texts = {}
    refs = {e["ref"] for f in masked["findings"] for e in f["evidence"]}
    gate.write_json(sub / f"{dim}.json", masked)
    gate.write_json(
        sub / f"{dim}.evidence.json",
        {r: clean(texts.get(r, ""), SNIPPET) for r in sorted(refs) if texts.get(r)},
    )
    verdicts: dict[str, str] = {}
    for f in masked["findings"]:
        prev = verdicts.get(f["checklist_id"])
        if prev is None or VERDICTS.index(f["verdict"]) < VERDICTS.index(prev):
            verdicts[f["checklist_id"]] = f["verdict"]
    row["verdicts"] = verdicts
    row["worst"] = _worst(verdicts)
    row["n_fail"] = sum(1 for v in verdicts.values() if v == "fail")
    row["n_question"] = sum(1 for v in verdicts.values() if v == "question")
    trace = masked["harness_trace"]
    row["tokens"] = int(max(trace["context"]["tokens_used"], trace["loop"]["tokens_used"]))
    row["status"] = "assessed"
    ex = _executive()
    if ex is not None:
        try:
            doc = ex.build(dim, masked, inputs.get("facts"), inputs["system"], definition)
            ex.write(sub, doc)
            row["rating"] = str(doc.get("rating") or "")
            row["exec_items"] = _exec_items(doc)
            row["exec_fail"] = sum(1 for i in row["exec_items"] if i["status"] == "fail")
        except Exception as exc:  # noqa: BLE001 - the report stays; the summary falls back
            row["exec_error"] = type(exc).__name__
    return done()


# ------------------------------------------------------------------------------ the run


def _check_doc(c: Any) -> dict[str, Any]:
    """A checklist item as ``run.json`` keeps it: the question, the evidence kinds and, when the
    definition has an ``executive`` block, its key and the two headlines."""
    out: dict[str, Any] = {
        "id": c.id,
        "question": c.question,
        "severity": c.severity,
        "evidence": list(c.evidence),
    }
    if c.executive is not None:
        out["key"] = c.executive.key
        out["headline_fail"] = c.executive.headline_fail.model_dump()
        out["headline_open"] = c.executive.headline_open.model_dump()
    return out


def start(
    env: InvEnv, agent_id: str, version: str, by: str, *, background: bool = True
) -> dict[str, Any]:
    """Plan the run, write ``run.json`` (``queued``) and run in a background thread
    (``background=False``: in this thread, for tests). One run at a time per agent."""
    require_on(env.settings)
    row = env.gate.store.get(agent_id, version or None)
    if row is None:
        raise InventoryError("not_found", f"agent {agent_id} does not exist")
    if row["state"] == "retired":
        raise InventoryError("bad_state", "a retired version cannot run; choose another version")
    try:
        defn = AgentDefinitionV1.model_validate(row["definition"])
    except Exception:  # noqa: BLE001
        raise InventoryError("invalid_definition", "the agent definition is not valid") from None
    model = env.gate.model()  # model_not_configured while LLM_BASE_URL is empty
    if getattr(model, "is_mock", False):
        raise gate.GateError("model_not_configured", rt.MODEL_OFF_TEXT)
    scope = build_scope(env, defn.dimension_id, max_of(env.settings))
    if not scope.items:
        raise InventoryError(
            "nothing_to_run",
            f"no AI system in the inventory needs the {defn.dimension_id} risk type",
        )
    with _LOCK:
        if agent_id in _RUNNING:
            raise InventoryError(
                "run_in_progress", f"an inventory run of {agent_id} is in progress; wait or cancel"
            )
        run_id = "inv_" + sha256_hex([agent_id, row["version"], time.time_ns()])[:20]
        d = run_dir(env.data_dir, agent_id, run_id)
        doc: dict[str, Any] = {
            "format": FORMAT,
            "version": 1,
            "banner": BANNER,
            "run_id": run_id,
            "agent_id": agent_id,
            "agent_version": row["version"],
            "agent_state": row["state"],
            "draft": row["state"] == "draft",
            "dimension_id": defn.dimension_id,
            "definition_sha256": definition_sha256(row["definition"]),
            "model_id": str(getattr(model, "model_id", "") or ""),
            "status": "queued",
            "started_by": by[:120],
            "started_at": format_ts(env.gate.clock.now()),
            "finished_at": None,
            "parallel": parallel_of(env.settings),
            "max": max_of(env.settings),
            "inventory_n": scope.inventory_n,
            "total": len(scope.items),
            "cut_n": scope.cut_n,
            "skipped": scope.skipped,
            "done": 0,
            "errors": 0,
            "needs_action": 0,
            "open": 0,
            "clear": 0,
            "model_calls": 0,
            "tokens": 0,
            "seconds": 0,
            "cancel_requested": False,
            "error": "",
            "checklist": [_check_doc(c) for c in defn.checklist],
        }
        gate.write_json(d / "run.json", doc)
        _RUNNING[agent_id] = run_id
        _CANCEL[run_id] = threading.Event()
    env.gate.store.record_event(
        agent_id, row["version"], "gate_run", by, f"inventory run {run_id} queued"
    )
    args = (env, doc, row["definition"], defn, model, scope.items)
    if background:
        th = threading.Thread(target=_thread, args=args, daemon=True)
        _THREADS[agent_id] = th
        th.start()
    else:
        _thread(*args)
    return read_run(env.data_dir, agent_id, run_id)


def join(agent_id: str, timeout: float = 120.0) -> None:
    th = _THREADS.get(agent_id)
    if th is not None:
        th.join(timeout)


def cancel(env: InvEnv, agent_id: str, run_id: str) -> dict[str, Any]:
    require_on(env.settings)
    run = read_run(env.data_dir, agent_id, run_id)
    ev = _CANCEL.get(run_id)
    if run["status"] not in ACTIVE or ev is None:
        raise InventoryError("not_running", "this run has already finished")
    ev.set()
    return run


def _thread(
    env: InvEnv,
    doc: dict[str, Any],
    definition: Mapping[str, Any],
    defn: AgentDefinitionV1,
    model: ChatModel,
    items: list[ScopeItem],
) -> None:
    agent_id, run_id = doc["agent_id"], doc["run_id"]
    try:
        execute(env, doc, definition, defn, model, items)
    except Exception as exc:  # noqa: BLE001 - the thread must leave a state, never die silently
        log.warning("inventory run failed (%s)", type(exc).__name__)
        try:
            doc.update(
                {
                    "status": "failed",
                    "error": f"run_broke_{type(exc).__name__}"[:60],
                    "finished_at": format_ts(env.gate.clock.now()),
                }
            )
            gate.write_json(run_dir(env.data_dir, agent_id, run_id) / "run.json", doc)
        except Exception:  # noqa: BLE001
            log.exception("inventory run: could not close the run")
    finally:
        with _LOCK:
            if _RUNNING.get(agent_id) == run_id:
                del _RUNNING[agent_id]
            _CANCEL.pop(run_id, None)


def execute(
    env: InvEnv,
    doc: dict[str, Any],
    definition: Mapping[str, Any],
    defn: AgentDefinitionV1,
    model: ChatModel,
    items: list[ScopeItem],
) -> None:
    """The run itself (also the unit under test)."""
    d = run_dir(env.data_dir, doc["agent_id"], doc["run_id"])
    cancel_ev = _CANCEL.setdefault(doc["run_id"], threading.Event())
    meter = Meter(model)
    t0 = time.monotonic()
    state_lock = threading.Lock()
    db_lock = threading.Lock()
    loop = (definition.get("harness") or {}).get("loop") or {}
    asked = loop.get("budget_tokens")
    tokens_cap = min(
        int(asked) if isinstance(asked, int) and asked > 0 else caps.LOOP_BUDGET_DEFAULT,
        caps.LOOP_BUDGET_MAX,
    )
    doc["status"] = "running"
    d.mkdir(parents=True, exist_ok=True)
    gate.write_json(d / "run.json", doc)

    def flush(status: str | None = None) -> None:
        doc["model_calls"] = meter.calls
        doc["tokens"] = meter.tokens
        doc["seconds"] = int(time.monotonic() - t0)
        if status:
            doc["status"] = status
            doc["finished_at"] = format_ts(env.gate.clock.now())
        doc["cancel_requested"] = cancel_ev.is_set()
        gate.write_json(d / "run.json", doc)

    def one(item: ScopeItem) -> None:
        if cancel_ev.is_set():
            return
        row = assess_one(env, defn, definition, meter, item, d, db_lock, tokens_cap)
        with state_lock:
            with (d / "rows.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
            doc["done"] += 1
            b = bucket_of(row)
            doc[b] += 1
            flush()

    with ThreadPoolExecutor(max_workers=parallel_of(env.settings)) as pool:
        for fut in [pool.submit(one, it) for it in items]:
            try:
                fut.result()
            except Exception:  # noqa: BLE001 - a bug in one system is logged, the run goes on
                log.exception("inventory run: one system broke")
    with state_lock:
        flush("cancelled" if cancel_ev.is_set() and doc["done"] < doc["total"] else "done")


# ------------------------------------------------------------------------------ aggregation


def sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Fails first, then the highest severity, then open questions, then the name."""
    sev = max(
        (
            SEVERITY_RANK.get(i.get("severity", ""), 0)
            for i in row.get("exec_items") or []
            if i.get("status") == "fail"
        ),
        default=0,
    )
    return (
        row.get("status") != "assessed",
        -(int(row.get("n_fail", 0)) + exec_fail_of(row)),
        -sev,
        -int(row.get("n_question", 0)),
        str(row.get("name") or "").casefold(),
    )


def item_list(
    row: Mapping[str, Any], checklist: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The risk items of a row: the executive items; when there are none (the executive module is
    missing or failed) the failed and open checklist items stand in, key ``item:<id>``."""
    if row.get("exec_items"):
        return [dict(i) for i in row["exec_items"]]
    sev = {c["id"]: c.get("severity", "medium") for c in checklist}
    out = []
    for cid, v in (row.get("verdicts") or {}).items():
        if v in ("fail", "question"):
            out.append(
                {
                    "key": f"item:{cid}",
                    "severity": sev.get(cid, "medium"),
                    "status": "fail" if v == "fail" else "open",
                    "headline": {"en": "", "vi": ""},
                    "owner": "",
                }
            )
    return out


def exec_fail_of(row: Mapping[str, Any]) -> int:
    if "exec_fail" in row:
        return int(row["exec_fail"])
    return sum(1 for i in row.get("exec_items") or [] if i.get("status") == "fail")


def bucket_of(row: Mapping[str, Any]) -> str:
    """``needs_action``: the agent failed a check, or the code facts show a failed finding (a
    deterministic executive item with status ``fail``). ``open``: only open questions. ``clear``:
    nothing failed or open. ``errors``: the system could not be assessed."""
    if row.get("status") != "assessed":
        return "errors"
    if row.get("worst") == "fail" or exec_fail_of(row) > 0:
        return "needs_action"
    return "open" if row.get("worst") == "question" else "clear"


GAP_PACK = "gap:pack"


class Resolver:
    """Maps the keys of executive items to the checklist item they stand for. ``item:MR-01`` and
    ``check_mr_01`` name an item by its id; a key equal to the ``executive.key`` of an item names
    that item. Several keys of one issue then fold into one (``canon``)."""

    def __init__(self, checklist: Sequence[Mapping[str, Any]]) -> None:
        self.items = {c["id"]: c for c in checklist}
        self.by_slug = {c["id"].lower().replace("-", "_"): c["id"] for c in checklist}
        self.by_key = {c["key"]: c["id"] for c in checklist if c.get("key")}

    def item_id(self, key: str) -> str:
        if key.startswith("item:"):
            return key[5:] if key[5:] in self.items else ""
        if key.startswith("check_"):
            return self.by_slug.get(key[6:], "")
        return self.by_key.get(key, "")

    def canon(self, key: str) -> str:
        cid = self.item_id(key)
        return self.items[cid].get("key") or key if cid else key

    def is_pack(self, key: str) -> bool:
        cid = self.item_id(key)
        return bool(cid) and list(self.items[cid].get("evidence") or []) == ["pack"]


def row_keys(row: Mapping[str, Any], res: Resolver) -> dict[str, dict[str, Any]]:
    """The findings of one assessed row by canonical key: ``{key: {status, severity, headline}}``.
    A fail wins over an open question for the same key."""
    out: dict[str, dict[str, Any]] = {}
    for it in item_list(row, list(res.items.values())):
        if it["status"] not in ("fail", "open"):
            continue
        k = res.canon(it["key"])
        cur = out.get(k)
        if cur is None or (it["status"] == "fail" and cur["status"] != "fail"):
            out[k] = {
                "status": it["status"],
                "severity": it["severity"],
                "headline": it.get("headline") or {"en": "", "vi": ""},
                "pack": res.is_pack(it["key"]),
            }
        elif SEVERITY_RANK.get(it["severity"], 0) > SEVERITY_RANK.get(cur["severity"], 0):
            cur["severity"] = it["severity"]
    return out


def aggregate(run: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Everything the dashboard shows, from the rows of a run. Pure.

    ``risks``: findings with status fail (agent fails and failed executive items), by severity then
    by number of systems. ``gaps``: open questions, one line per key, with every required test
    folded into one line (``gap:pack``)."""
    checklist = list(run.get("checklist") or [])
    res = Resolver(checklist)
    tiles = {"needs_action": 0, "open": 0, "clear": 0, "errors": 0}
    mix: dict[str, dict[str, int]] = {
        c["id"]: {"fail": 0, "question": 0, "pass": 0, "not_applicable": 0} for c in checklist
    }
    risks: dict[str, dict[str, Any]] = {}
    gaps: dict[str, dict[str, Any]] = {}
    pack_systems: set[str] = set()
    pack_items: set[str] = set()
    teams: dict[str, Counter[str]] = {}
    levels: dict[str, Counter[str]] = {}
    for row in rows:
        b = bucket_of(row)
        tiles[b] += 1
        teams.setdefault(row.get("owner_team") or "", Counter())[b] += 1
        levels.setdefault(row.get("level") or "unspecified", Counter())[b] += 1
        if row.get("status") != "assessed":
            continue
        for cid, v in (row.get("verdicts") or {}).items():
            if cid in mix and v in mix[cid]:
                mix[cid][v] += 1
        for k, f in row_keys(row, res).items():
            if f["status"] == "fail":
                r = risks.setdefault(k, {"key": k, "severity": f["severity"], "systems": []})
                r["systems"].append(row["system_id"])
                if SEVERITY_RANK.get(f["severity"], 0) > SEVERITY_RANK.get(r["severity"], 0):
                    r["severity"] = f["severity"]
                r.setdefault("headline", f["headline"])
            elif f["pack"]:
                pack_systems.add(row["system_id"])
                pack_items.add(res.canon(k))
            else:
                g = gaps.setdefault(k, {"key": k, "severity": f["severity"], "systems": []})
                g["systems"].append(row["system_id"])
                g.setdefault("headline", f["headline"])
    found = []
    for r in risks.values():
        cid = res.item_id(r["key"])
        found.append(
            {
                **r,
                "n": len(r["systems"]),
                "item": cid,
                "text": (res.items.get(cid) or {}).get("headline_fail") or {},
            }
        )
    found.sort(key=lambda r: (-SEVERITY_RANK.get(r["severity"], 0), -r["n"], r["key"]))
    lines = []
    for g in gaps.values():
        cid = res.item_id(g["key"])
        lines.append(
            {
                **g,
                "n": len(g["systems"]),
                "item": cid,
                "kind": "item" if cid else "key",
                "text": (res.items.get(cid) or {}).get("headline_open") or {},
            }
        )
    lines.sort(key=lambda g: (-g["n"], -SEVERITY_RANK.get(g["severity"], 0), g["key"]))
    if pack_systems:
        lines.insert(
            0,
            {
                "key": GAP_PACK,
                "kind": "pack",
                "n": len(pack_systems),
                "items": len(pack_items),
                "severity": "high",
                "systems": sorted(pack_systems),
            },
        )

    def table(src: Mapping[str, Counter[str]]) -> list[dict[str, Any]]:
        out = [
            {
                "name": k,
                "systems": sum(c.values()),
                "needs_action": c["needs_action"],
                "open": c["open"],
                "clear": c["clear"],
                "errors": c["errors"],
            }
            for k, c in src.items()
        ]
        return sorted(out, key=lambda r: (-r["needs_action"], -r["systems"], str(r["name"])))

    by_level = table(levels)
    by_level.sort(key=lambda r: LEVELS.index(r["name"]) if r["name"] in LEVELS else len(LEVELS))
    return {
        "tiles": tiles,
        "assessed": tiles["needs_action"] + tiles["open"] + tiles["clear"],
        "mix": [
            {
                "id": c["id"],
                "text": c["question"],
                "label": c.get("headline_fail") or {},
                **mix[c["id"]],
            }
            for c in checklist
        ],
        "risks": found,
        "gaps": lines,
        "by_team": table(teams),
        "by_level": by_level,
        "teams": sorted(t for t in teams if t),
        "executive": any(r.get("exec_items") for r in rows),
    }


def filter_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    team: str = "",
    level: str = "",
    customer: str = "",
    q: str = "",
    key: str = "",
    kstatus: str = "",
    bucket: str = "",
    checklist: Sequence[Mapping[str, Any]] = (),
) -> list[Mapping[str, Any]]:
    needle = (q or "").strip().casefold()
    res = Resolver(checklist)
    out = []
    for r in rows:
        if team and r.get("owner_team") != team:
            continue
        if level and r.get("level") != level:
            continue
        if customer == "yes" and not r.get("customer_facing"):
            continue
        if customer == "no" and r.get("customer_facing"):
            continue
        if bucket and bucket_of(r) != bucket:
            continue
        if needle and needle not in f"{r.get('name', '')} {r.get('system_id', '')}".casefold():
            continue
        if key:
            found = row_keys(r, res) if r.get("status") == "assessed" else {}
            if key == GAP_PACK:
                hit = any(f["pack"] and f["status"] == "open" for f in found.values())
            else:
                f = found.get(res.canon(key))
                hit = f is not None and (not kstatus or f["status"] == kstatus)
            if not hit:
                continue
        out.append(r)
    return sorted(out, key=sort_key)


# ------------------------------------------------------------------------------ detail and CSV


def system_detail(data_dir: Path, run: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """The stored report, evidence snippets and executive document of one system."""
    d = run_dir(data_dir, run["agent_id"], run["run_id"])
    sub = d / "systems" / safe(row["system_id"])
    dim = run["dimension_id"]
    exec_doc = gate.read_json(sub / f"{dim}.exec.json")
    return {
        "report": gate.read_json(sub / f"{dim}.json") or {},
        "texts": gate.read_json(sub / f"{dim}.evidence.json") or {},
        "exec": exec_doc if isinstance(exec_doc, dict) else None,
    }


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(run: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    """The per-system results as CSV (ids, enums and masked names only)."""
    checklist = run.get("checklist") or []
    ids = [c["id"] for c in checklist]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(
        [
            "system_id",
            "name",
            "owner_team",
            "risk_level",
            "customer_facing",
            "outcome",
            "outcome_source",
            "result",
            "rating",
            *ids,
            "risk_keys",
            "tokens",
            "error",
        ]
    )
    names = {"needs_action": "needs_action", "open": "open_questions", "clear": "clear"}
    for r in sorted(rows, key=sort_key):
        keys = [i["key"] for i in item_list(r, checklist) if i["status"] in ("fail", "open")]
        w.writerow(
            [
                _cell(r.get("system_id")),
                _cell(r.get("name")),
                _cell(r.get("owner_team")),
                r.get("level", ""),
                "yes" if r.get("customer_facing") else "no",
                r.get("outcome", ""),
                r.get("outcome_source", ""),
                names.get(bucket_of(r), "error"),
                r.get("rating", ""),
                *[(r.get("verdicts") or {}).get(i, "") for i in ids],
                " ".join(keys),
                r.get("tokens", 0),
                _cell(r.get("error")),
            ]
        )
    return out.getvalue()
