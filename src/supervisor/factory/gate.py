"""The test gate of the agent factory (WP-F3, flag ``AGENT_FACTORY_GATE``): test, eval, improve.

Run kinds (table ``gate_run``):

``full``        layers 1, 2 and 3; the only kind that can move a version to ``tested``
``sample``      layers 1 and 2 on a small batch (default 10, at most 25 cases), never promotes
``simulation``  the draft on chosen systems of the inventory, assessed by a person
``shadow``      layer 3 only

Layers:

1. **Deterministic**, all must be 100 percent: on every case report the schema is valid, every
   pass or fail cites evidence that was loaded from an allowed source, no tool outside the
   registry scope or mode, no personal data, the token budget is kept; plus the six harness
   component tests of plan section 2.0 (``probe.py``).
2. **Guideline judges** on the gateway model: ``verdict_matches_expected`` and
   ``rationale_faithful_to_evidence`` (yes or no with a reason per case); **calibration**: the
   judge labels the human-labelled findings and Cohen's kappa (integer hundredths, 81 = 0.81) with
   the confusion matrix must reach the platform floor; **no regression** against the live version
   on the same cases (paired); the **tier floor** on the share of cases the judge accepts.
3. **Shadow**: the candidate on the last N stored onboardings (assessments under
   ``DATA_DIR/assessments``), stored and not shown, compared with the stored reports and with the
   person-confirmed ``risk_dimension_status`` rows. Informational: it never blocks.

A judge advises. The gate verdict is a deterministic function of the integers above. The report is
signed JSON (evidence signer), integers only. The run is a background job with a status row.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from supervisor.config import timeout_setting
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import SupervisorError
from supervisor.core.ports import ChatModel
from supervisor.evidence.chain import check_no_floats
from supervisor.factory import caps, golden, linter, probe, promotion, registry
from supervisor.factory import runtime as rt
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from supervisor.factory.schemas.assessment_report_v1 import AssessmentReportV1
from supervisor.factory.store import FactoryStore, definition_sha256
from supervisor.onboard.agent_log import clean

log = logging.getLogger("supervisor.factory.gate")
TABLE = "gate_run"
RECORD_TYPE = "factory_gate_run"
FLAG_TEXT = "the agent test gate is off (AGENT_FACTORY_GATE=1 turns it on; needs AGENT_FACTORY)"
BANNER = (
    "Advisory. Judges advise; the gate verdict follows the deterministic rules in this report. "
    "A person approves every promotion."
)
JUDGE_TIMEOUT_S = 60.0
_LOCK = threading.Lock()
_RUNNING: dict[str, str] = {}  # agent id -> run id
_THREADS: dict[str, threading.Thread] = {}
VERDICT_RANK = {"fail": 3, "question": 2, "pass": 1, "not_applicable": 0}


class GateError(SupervisorError):
    """A refused gate request (HTTP 400). ``code`` is the stable machine word."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "agent_factory_gate", False)
        and getattr(settings, "agent_factory", False)
        and getattr(settings, "governance_enabled", False)
    )


def require_on(settings: Any) -> None:
    if not enabled(settings):
        raise GateError("factory_gate_off", FLAG_TEXT)


# ------------------------------------------------------------------------------ the environment


class MeteredModel:
    """Counts the calls and the estimated tokens of a model (the cost of a run)."""

    def __init__(self, inner: ChatModel) -> None:
        self.inner = inner
        self.family = getattr(inner, "family", "")
        self.model_id = getattr(inner, "model_id", "")
        self.is_mock = getattr(inner, "is_mock", False)
        self.calls = 0
        self.tokens = 0

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float,
    ) -> Mapping[str, Any]:
        self.calls += 1
        self.tokens += caps.estimate_tokens(json.dumps(list(messages), default=str))
        out = self.inner.complete_json(messages, json_schema, timeout_s)
        self.tokens += caps.estimate_tokens(json.dumps(out, default=str))
        return out


InputsFor = Callable[[str, str], dict[str, Any]]


@dataclass
class GateEnv:
    """What a gate run needs. ``chat`` is the gateway model (tests pass a fake ChatModel; the
    product builds it from ``LLM_BASE_URL``). ``inputs_for(system_id, dimension_id)`` loads the
    run inputs of a stored onboarding (shadow and simulation)."""

    settings: Any
    state: Any
    tables: Any
    clock: Any
    sink: Any
    store: FactoryStore
    tools: registry.ToolRegistry
    chat: ChatModel | None = None
    inputs_for: InputsFor | None = None
    signer: Any = None

    @property
    def data_dir(self) -> Path:
        return Path(self.settings.data_dir)

    def model(self) -> ChatModel:
        if self.chat is not None:
            return self.chat
        try:
            return rt.gateway_model({"settings": self.settings})
        except rt.AgentRuntimeError as exc:
            raise GateError("model_not_configured", rt.MODEL_OFF_TEXT) from exc

    @classmethod
    def from_console(
        cls,
        ctx: Any,
        chat: ChatModel | None = None,
        tools: registry.ToolRegistry | None = None,
        groups: registry.GroupRegistry | None = None,
    ) -> GateEnv:
        tools, groups = tools or registry.load_tools(), groups or registry.load_groups()
        chain = getattr(ctx.runtime, "chain", None)
        return cls(
            ctx.settings,
            ctx.state,
            ctx.tables,
            ctx.clock,
            chain,
            FactoryStore(ctx.state, ctx.tables, ctx.clock, tools, groups),
            tools,
            chat,
            lambda sid, dim: system_inputs(ctx, sid, dim),
            getattr(chain, "signer", None),
        )

    @classmethod
    def from_runtime(cls, runtime: Any, chat: ChatModel | None = None) -> GateEnv:
        from supervisor.console.context import build_context

        return cls.from_console(build_context(runtime), chat)


def _json_safe(row: Mapping[str, Any]) -> dict[str, Any]:
    """A stored row as plain JSON values: a timestamp column comes back as a datetime, and the
    simulation and shadow runs write the inputs they read to disk (WP-D3 fix)."""
    return {
        k: (format_ts(v) if hasattr(v, "isoformat") and hasattr(v, "utcoffset") else v)
        for k, v in row.items()
    }


def system_inputs(ctx: Any, system_id: str, dimension_id: str) -> dict[str, Any]:
    """The run inputs of a stored onboarding: the system record, the facts v1 export and the pack
    results of the rule proposal. Raises for a system that does not exist."""
    from supervisor.governance import risk_dimensions as rd
    from supervisor.onboard import orchestrator as orch

    system = _json_safe(orch.system_row(ctx, system_id))
    out: dict[str, Any] = {
        "system_id": system_id,
        "system": system,
        "facts": orch.facts_for(ctx, system_id),
        "now": format_ts(ctx.clock.now()),
    }
    try:
        out["proposal"] = rd.propose(rd.Env.from_console(ctx), system_id, dimension_id).get(
            dimension_id, {}
        )
    except Exception:  # noqa: BLE001 - risk dimensions off: no pack results, still a run
        out["proposal"] = {}
    return out


# ------------------------------------------------------------------------------ files


def gate_dir(data_dir: Path, agent_id: str, run_id: str) -> Path:
    if not caps.ID_RE.match(agent_id) or not re.match(r"^gate_[0-9a-f]{20}$", run_id):
        raise GateError("bad_id", "not an agent id or a run id")
    return Path(data_dir) / "factory" / agent_id / "gate" / run_id


def write_json(path: Path, doc: Any) -> str:
    check_no_floats(doc)
    raw = json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=1).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)
    return sha256_hex(json.loads(raw))


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------------ calibration math


def cohen_kappa_hundredths(matrix: Sequence[Sequence[int]]) -> int:
    """Cohen's kappa of a square confusion matrix (rows: human, columns: judge) as an integer in
    hundredths, rounded half up (81 = 0.81). Integer arithmetic only: with ``n`` ratings,
    ``agree`` on the diagonal and ``S`` the sum over categories of row total times column total,
    ``kappa = (n * agree - S) / (n * n - S)``. When every rating falls in one category the
    expected agreement is 1 and kappa is undefined: 100 for a perfect match, else 0."""
    n = sum(sum(r) for r in matrix)
    if n == 0:
        return 0
    agree = sum(matrix[i][i] for i in range(len(matrix)))
    rows = [sum(r) for r in matrix]
    cols = [sum(matrix[i][j] for i in range(len(matrix))) for j in range(len(matrix))]
    s = sum(r * c for r, c in zip(rows, cols, strict=True))
    den = n * n - s
    if den == 0:
        return 100 if agree == n else 0
    num = 100 * (n * agree - s)
    return (2 * num + den) // (2 * den) if den > 0 else 0


def confusion(
    pairs: Sequence[tuple[str, str]], labels: Sequence[str] = caps.VERDICTS
) -> dict[str, Any]:
    """``{"labels": [...], "matrix": [[...]]}``: rows are human verdicts, columns judge verdicts."""
    idx = {v: i for i, v in enumerate(labels)}
    m = [[0] * len(labels) for _ in labels]
    for human, judge in pairs:
        if human in idx and judge in idx:
            m[idx[human]][idx[judge]] += 1
    return {"labels": list(labels), "matrix": m}


def percent(part: int, whole: int) -> int:
    return (100 * part) // whole if whole else 0


# ------------------------------------------------------------------------------ layer 1


def check_report(
    defn: AgentDefinitionV1, report: Mapping[str, Any], tools: registry.ToolRegistry
) -> dict[str, list[str]]:
    """The per-report deterministic checks. Returns check id -> list of problems (empty = ok)."""
    out: dict[str, list[str]] = {
        "schema_valid": [],
        "evidence_exists": [],
        "tools_in_scope": [],
        "no_personal_data": [],
        "token_budget": [],
    }
    try:
        model = AssessmentReportV1.model_validate(dict(report))
    except ValidationError as exc:
        out["schema_valid"].append(f"{exc.error_count()} schema error(s)")
        return out
    if (
        model.agent_id != defn.id
        or model.agent_version != defn.lifecycle.version
        or model.dimension_id != defn.dimension_id
    ):
        out["schema_valid"].append("the report names another agent, version or dimension")
    ids = {c.id for c in defn.checklist}
    if {f.checklist_id for f in model.findings} != ids:
        out["schema_valid"].append("the findings do not cover the checklist exactly")
    loaded = set(model.harness_trace.context.source_refs)
    allowed = set(defn.evidence_rules.allowed_sources)
    for f in model.findings:
        if f.verdict in ("pass", "fail") and not f.evidence:
            out["evidence_exists"].append(f"{f.checklist_id}: {f.verdict} without evidence")
        for e in f.evidence:
            if e.ref not in loaded:
                out["evidence_exists"].append(f"{f.checklist_id}: {e.ref[:60]} was not loaded")
            if e.kind not in allowed:
                out["evidence_exists"].append(f"{f.checklist_id}: kind {e.kind} is not allowed")
        if trips(f.rationale) or any(trips(e.ref) for e in f.evidence):
            out["no_personal_data"].append(f"{f.checklist_id}: personal data in the output")
    out["tools_in_scope"].extend(tool_problems(defn, tools))
    if model.harness_trace.hitl.tool_calls_blocked:
        out["tools_in_scope"].append(
            f"{model.harness_trace.hitl.tool_calls_blocked} source(s) need a tool the agent lacks"
        )
    tr = model.harness_trace
    if tr.context.tokens_used > defn.harness.context.budget_tokens:
        out["token_budget"].append("a call was over the context budget")
    if tr.loop.tokens_used > defn.harness.loop.budget_tokens:
        out["token_budget"].append("the run was over the loop budget")
    return out


def trips(text: str) -> bool:
    return golden.trips_masker(text or "")


def tool_problems(defn: AgentDefinitionV1, tools: registry.ToolRegistry) -> list[str]:
    """Every tool is in the registry, visible to the owner group, and used in a mode it offers;
    no permission widens a tool; the registry check of the definition is clean."""
    out = []
    for field, msg in registry.check_definition(defn, tools, registry.load_groups()):
        out.append(f"{field}: {msg}"[:200])
    for t in defn.tools:
        reg = tools.get(t.tool_id)
        if reg is not None and t.mode not in reg.modes:
            out.append(f"tool {t.tool_id}: mode {t.mode} is not offered")
    return out


def layer1(
    defn: AgentDefinitionV1,
    results: Sequence[Mapping[str, Any]],
    components: Sequence[Mapping[str, Any]],
    tools: registry.ToolRegistry,
) -> dict[str, Any]:
    """Aggregate the per-case checks and the component tests. ``ok`` only at 100 percent."""
    checks: list[dict[str, Any]] = []
    ids = ("schema_valid", "evidence_exists", "tools_in_scope", "no_personal_data", "token_budget")
    cases_n = len(results)
    for cid in ids:
        bad = [r["case_id"] for r in results if r.get("problems", {}).get(cid)]
        extra = tool_problems(defn, tools) if cid == "tools_in_scope" and not results else []
        checks.append(
            {
                "id": cid,
                "kind": "case",
                "ok": not bad and not extra,
                "cases": cases_n,
                "cases_failed": len(bad),
                "failed_case_ids": bad[:20],
                "detail": (extra[0] if extra else "")[:200],
            }
        )
    checks.extend(dict(c) for c in components)
    passed = sum(1 for c in checks if c["ok"])
    return {
        "checks": checks,
        "checks_total": len(checks),
        "checks_passed": passed,
        "percent": percent(passed, len(checks)),
        "ok": passed == len(checks),
    }


# ------------------------------------------------------------------------------ layer 2


JUDGE_SYSTEM = (
    "You are a test judge for an assessment agent of a bank's AI governance platform. You only "
    "advise; a deterministic rule decides. Answer each question with yes or no and a short reason "
    "(at most 200 characters). Never write a personal name, number or address."
)
MATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict_matches_expected", "rationale_faithful_to_evidence"],
    "properties": {
        "verdict_matches_expected": {
            "type": "object",
            "required": ["answer", "reason"],
            "properties": {"answer": {"enum": ["yes", "no"]}, "reason": {"type": "string"}},
        },
        "rationale_faithful_to_evidence": {
            "type": "object",
            "required": ["answer", "reason"],
            "properties": {"answer": {"enum": ["yes", "no"]}, "reason": {"type": "string"}},
        },
    },
}
LABEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict", "reason"],
    "properties": {"verdict": {"enum": list(caps.VERDICTS)}, "reason": {"type": "string"}},
}


def _yes(block: Any) -> tuple[bool, str]:
    if isinstance(block, Mapping) and block.get("answer") in ("yes", "no"):
        return block["answer"] == "yes", clean(str(block.get("reason") or ""), 200)
    return False, ""


def exact_match(case: Mapping[str, Any], report: Mapping[str, Any]) -> bool:
    got = {f["checklist_id"]: f["verdict"] for f in report.get("findings") or []}
    return all(got.get(cid) == v for cid, v in (case.get("expected") or {}).items())


def judge_case(
    model: ChatModel,
    defn: AgentDefinitionV1,
    case: Mapping[str, Any],
    report: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Two yes/no answers with a reason for one case. A broken answer is ``no`` and counted."""
    texts = rt.loaded_texts(defn.model_dump(mode="json"), inputs, report)
    expected = dict(case.get("expected") or {})
    actual = [
        {"checklist_id": f["checklist_id"], "verdict": f["verdict"], "rationale": f["rationale"]}
        for f in report.get("findings") or []
        if f["checklist_id"] in expected
    ]
    user = {
        "question_1": "verdict_matches_expected: does the actual verdict of every item equal the "
        "expected verdict (use the rubric notes for edge cases)?",
        "question_2": "rationale_faithful_to_evidence: is every rationale supported by the cited "
        "evidence texts and nothing else?",
        "rubric_notes": case.get("rubric_notes") or "",
        "expected": expected,
        "expected_evidence_refs": case.get("expected_evidence_refs") or [],
        "actual": actual,
        "evidence_texts": {k: v[:400] for k, v in sorted(texts.items())[:20]},
    }
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, sort_keys=True)},
    ]
    try:
        reply = model.complete_json(
            messages, MATCH_SCHEMA, timeout_setting("factory_judge_timeout_s", JUDGE_TIMEOUT_S)
        )
        error = False
    except Exception:  # noqa: BLE001 - a judge that fails is a "no" and is counted
        reply, error = {}, True
    match, why1 = _yes(reply.get("verdict_matches_expected"))
    faith, why2 = _yes(reply.get("rationale_faithful_to_evidence"))
    return {
        "case_id": case["case_id"],
        "match": match,
        "faithful": faith,
        "exact": exact_match(case, report),
        "reason_match": why1,
        "reason_faithful": why2,
        "judge_error": error or not reply,
    }


def label_inputs(
    env: GateEnv, agent_id: str, label: Mapping[str, Any], cases: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
    """The run inputs a label refers to: a golden case, or the stored inputs of a simulation."""
    if label.get("source") == "simulation":
        run_id, _, name = str(label.get("ref") or "").partition("/")
        try:
            doc = read_json(
                gate_dir(env.data_dir, agent_id, run_id) / "sim_inputs" / f"{name}.json"
            )
        except GateError:
            return None
        return doc if isinstance(doc, dict) else None
    case = cases.get(str(label.get("case_id")))
    return dict(case["inputs"]) if case else None


def calibrate(
    env: GateEnv,
    model: ChatModel,
    defn: AgentDefinitionV1,
    cases: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """The judge labels the human-labelled findings; kappa against the human verdicts."""
    labels = golden.load_labels(env.data_dir, defn.id)
    definition = defn.model_dump(mode="json")
    pairs: list[tuple[str, str]] = []
    skipped = invalid = 0
    for lab in labels:
        cid = golden.checklist_of_finding(str(lab["finding_id"]))
        item = next((c for c in defn.checklist if c.id == cid), None)
        inputs = label_inputs(env, defn.id, lab, cases)
        if item is None or inputs is None:
            skipped += 1
            continue
        srcs = rt.item_context(definition, inputs, cid, env.tools)
        user = {
            "task": "Decide the verdict of this checklist item from the sources only: pass, fail, "
            "not_applicable or question (the sources do not decide it).",
            "question": item.question,
            "pass_rule": item.pass_rule,
            "sources": srcs,
        }
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, sort_keys=True)},
        ]
        try:
            reply = model.complete_json(
                messages, LABEL_SCHEMA, timeout_setting("factory_judge_timeout_s", JUDGE_TIMEOUT_S)
            )
        except Exception:  # noqa: BLE001
            reply = {}
        verdict = reply.get("verdict") if isinstance(reply, Mapping) else None
        if verdict not in caps.VERDICTS:
            invalid += 1
            continue
        pairs.append((str(lab["human_verdict"]), str(verdict)))
    cm = confusion(pairs)
    n = len(pairs)
    agree = sum(1 for h, j in pairs if h == j)
    kappa = cohen_kappa_hundredths(cm["matrix"])
    enough = n >= caps.CALIBRATION_MIN_LABELS
    return {
        "labels_total": len(labels),
        "labels_used": n,
        "labels_skipped": skipped,
        "judge_invalid": invalid,
        "min_labels": caps.CALIBRATION_MIN_LABELS,
        "agree": agree,
        "agreement_percent": percent(agree, n),
        "kappa_hundredths": kappa,
        "kappa_floor": caps.CALIBRATION_KAPPA_FLOOR,
        "confusion": cm,
        "ok": enough and kappa >= caps.CALIBRATION_KAPPA_FLOOR,
        "reason": "ok"
        if enough and kappa >= caps.CALIBRATION_KAPPA_FLOOR
        else ("calibration_too_small" if not enough else "kappa_below_floor"),
    }


def paired(candidate: Mapping[str, bool], live: Mapping[str, bool] | None) -> dict[str, Any]:
    """The paired comparison on the same cases: ``lost`` = the live version was accepted and the
    candidate was not; ``gained`` the other way round."""
    if live is None:
        return {
            "baseline": "none",
            "lost": 0,
            "gained": 0,
            "max_regression_cases": caps.MAX_REGRESSION_CASES,
            "lost_case_ids": [],
            "ok": True,
        }
    same = sorted(set(candidate) & set(live))
    lost = [c for c in same if live[c] and not candidate[c]]
    gained = [c for c in same if candidate[c] and not live[c]]
    return {
        "baseline": "live",
        "cases": len(same),
        "lost": len(lost),
        "gained": len(gained),
        "max_regression_cases": caps.MAX_REGRESSION_CASES,
        "lost_case_ids": lost[:30],
        "ok": len(lost) <= caps.MAX_REGRESSION_CASES,
    }


# ------------------------------------------------------------------------------ the case loop


def case_inputs(env: GateEnv, case: Mapping[str, Any]) -> dict[str, Any]:
    cid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(case["case_id"]))
    inputs = json.loads(json.dumps(case["inputs"]))
    inputs.setdefault("system_id", f"case-{cid}")
    inputs.setdefault("system", {"system_id": inputs["system_id"]})
    inputs["now"] = format_ts(env.clock.now())
    return inputs


def run_cases(
    env: GateEnv,
    defn: AgentDefinitionV1,
    cases: Sequence[Mapping[str, Any]],
    agent_model: ChatModel,
    judge_model: ChatModel,
    *,
    judge: bool = True,
    progress: Callable[[int, int], None] | None = None,
    store_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run the harness on each case; layer-1 checks and (optionally) the two judge questions."""
    out: list[dict[str, Any]] = []
    definition = defn.model_dump(mode="json")
    for i, case in enumerate(cases, start=1):
        inputs = case_inputs(env, case)
        row: dict[str, Any] = {"case_id": case["case_id"]}
        try:
            report = rt.run_agent(definition, inputs, agent_model, env.clock, tools=env.tools)
        except rt.AgentRuntimeError as exc:
            if exc.code == "model_not_configured":
                raise GateError("model_not_configured", rt.MODEL_OFF_TEXT) from exc
            row["problems"] = {"schema_valid": [exc.code]}
            out.append(row)
            continue
        except Exception as exc:  # noqa: BLE001 - one broken case is a failed check, not a crash
            row["problems"] = {"schema_valid": [f"run raised {type(exc).__name__}"]}
            out.append(row)
            continue
        row["problems"] = check_report(defn, report, env.tools)
        row["verdicts"] = {f["checklist_id"]: f["verdict"] for f in report["findings"]}
        if judge:
            row.update(judge_case(judge_model, defn, case, report, inputs))
        else:
            row["exact"] = exact_match(case, report)
        row["tokens"] = report["harness_trace"]["loop"]["tokens_used"]
        out.append(row)
        if progress:
            progress(i, len(cases))
    return out


def pick_sample(cases: Sequence[Mapping[str, Any]], n: int) -> list[Mapping[str, Any]]:
    """A deterministic stratified sample: round robin over the checklist items, by case id."""
    by_item: dict[str, list[Mapping[str, Any]]] = {}
    for c in sorted(cases, key=lambda c: str(c["case_id"])):
        by_item.setdefault(sorted(c["expected"])[0], []).append(c)
    picked: list[Mapping[str, Any]] = []
    queues = [by_item[k] for k in sorted(by_item)]
    while len(picked) < n and any(queues):
        for q in queues:
            if q and len(picked) < n:
                picked.append(q.pop(0))
    return picked


def tier_floor(defn: AgentDefinitionV1) -> tuple[str, int]:
    tier = promotion.tier_of(defn.model_dump(mode="json"))
    return tier, caps.TIER_FLOOR_PERCENT[tier]


def layer2(
    env: GateEnv,
    defn: AgentDefinitionV1,
    results: Sequence[Mapping[str, Any]],
    cases: Mapping[str, Mapping[str, Any]],
    judge_model: ChatModel,
    agent_model: ChatModel,
    *,
    full: bool,
    golden_sha: str,
) -> dict[str, Any]:
    n = len(results)
    ran = [r for r in results if "match" in r]
    match = sum(1 for r in ran if r["match"])
    faith = sum(1 for r in ran if r["faithful"])
    exact = sum(1 for r in ran if r["exact"])
    errors = sum(1 for r in ran if r["judge_error"])
    tier, floor = tier_floor(defn)
    match_pct, faith_pct = percent(match, n), percent(faith, n)
    floor_ok = n > 0 and match_pct >= floor and faith_pct >= floor
    out: dict[str, Any] = {
        "cases": n,
        "verdict_matches_expected": match,
        "rationale_faithful_to_evidence": faith,
        "exact_verdict_matches": exact,
        "judge_errors": errors,
        "match_percent": match_pct,
        "faithful_percent": faith_pct,
        "tier": tier,
        "tier_floor_percent": floor,
        "tier_floor_ok": floor_ok,
        "golden_sha256": golden_sha,
        "judge_model_id": str(getattr(judge_model, "model_id", "")),
        "judge_family": str(getattr(judge_model, "family", "")),
        "agent_family": str(getattr(agent_model, "family", "")),
        "same_family": getattr(judge_model, "family", "") == getattr(agent_model, "family", ""),
    }
    if not full:
        out.update(calibration={"status": "skipped"}, regression={"status": "skipped"})
        out["ok"] = floor_ok
        return out
    out["calibration"] = calibrate(env, judge_model, defn, cases)
    candidate = {r["case_id"]: bool(r["match"]) for r in ran}
    out["regression"] = regress(
        env, defn, candidate, list(cases.values()), agent_model, judge_model, golden_sha
    )
    out["ok"] = bool(floor_ok and out["calibration"]["ok"] and out["regression"]["ok"])
    return out


def regress(
    env: GateEnv,
    defn: AgentDefinitionV1,
    candidate: Mapping[str, bool],
    cases: Sequence[Mapping[str, Any]],
    agent_model: ChatModel,
    judge_model: ChatModel,
    golden_sha: str,
) -> dict[str, Any]:
    """The paired comparison with the live version of this agent on the same cases. The live
    results come from its newest passed full run on the same golden set, else they are computed."""
    live = env.store.live_version(defn.id)
    if live is None or live["version"] == defn.lifecycle.version:
        return paired(candidate, None)
    for r in reversed(promotion.runs_of(env.store, defn.id, live["version"])):
        if r["kind"] == "full" and r["status"] == "done" and r["verdict"] == "pass":
            l2 = (
                r["layer2_json"]
                if isinstance(r["layer2_json"], dict)
                else json.loads(r["layer2_json"] or "{}")
            )
            doc = read_json(gate_dir(env.data_dir, defn.id, r["run_id"]) / "cases.json")
            if l2.get("golden_sha256") == golden_sha and isinstance(doc, list):
                res = paired(candidate, {c["case_id"]: bool(c.get("match")) for c in doc})
                res["baseline_run_id"] = r["run_id"]
                return res
            break
    live_defn = AgentDefinitionV1.model_validate(live["definition"])
    again = run_cases(env, live_defn, cases, agent_model, judge_model)
    res = paired(candidate, {c["case_id"]: bool(c.get("match")) for c in again})
    res["baseline_run_id"] = "recomputed"
    return res


# ------------------------------------------------------------------------------ layer 3 (shadow)


def worst(findings: Sequence[Mapping[str, Any]]) -> str:
    present = {str(f["verdict"]) for f in findings}
    for v in sorted(VERDICT_RANK, key=lambda x: -VERDICT_RANK[x]):
        if v in present:
            return v
    return "question"


def stored_reports(data_dir: Path, dimension_id: str, limit: int) -> list[dict[str, Any]]:
    """The newest stored assessment reports of a dimension: ``DATA_DIR/assessments/<system>/
    <attempt>/<dimension>.json``, newest first by ``created_at``."""
    root = Path(data_dir) / "assessments"
    found: list[tuple[str, str, str, dict[str, Any]]] = []
    if not root.is_dir():
        return []
    for sys_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for att in sorted((p for p in sys_dir.iterdir() if p.is_dir()), key=lambda p: p.name):
            doc = read_json(att / f"{dimension_id}.json")
            if isinstance(doc, dict) and doc.get("findings") is not None:
                found.append((str(doc.get("created_at") or ""), sys_dir.name, att.name, doc))
    best: dict[str, tuple[str, str, str, dict[str, Any]]] = {}
    for item in found:  # the newest attempt per system
        if item[1] not in best or item[0] >= best[item[1]][0]:
            best[item[1]] = item
    ordered = sorted(best.values(), key=lambda t: (t[0], t[1]), reverse=True)
    return [{"system_id": s, "attempt": a, "report": d} for _, s, a, d in ordered[:limit]]


def person_verdict(env: GateEnv, system_id: str, dimension_id: str) -> str:
    """The status a person confirmed in ``risk_dimension_status`` (``pass`` or ``fail``), else
    an empty string. A row written by a rule (``updated_by`` starts ``rule:``) is a proposal."""
    for r in env.state.query(
        "risk_dimension_status", {"system_id": system_id, "dimension_id": dimension_id}
    ):
        if r["status"] in ("pass", "fail") and not str(r.get("updated_by") or "").startswith(
            "rule:"
        ):
            return str(r["status"])
    return ""


def shadow(
    env: GateEnv,
    defn: AgentDefinitionV1,
    agent_model: ChatModel,
    n: int,
    out_dir: Path,
) -> dict[str, Any]:
    n = max(1, min(int(n), caps.SHADOW_MAX))
    stored = stored_reports(env.data_dir, defn.dimension_id, n)
    live = env.store.live_version(defn.id)
    c = Counter()
    systems: list[dict[str, Any]] = []
    definition = defn.model_dump(mode="json")
    for item in stored:
        sid, base = item["system_id"], item["report"]
        if env.inputs_for is None:
            c["skipped"] += 1
            continue
        try:
            inputs = env.inputs_for(sid, defn.dimension_id)
            rep = rt.run_agent(
                definition,
                {**inputs, "report_id": f"shadow-{sid}"[:60]},
                agent_model,
                env.clock,
                tools=env.tools,
            )
        except rt.AgentRuntimeError as exc:
            if exc.code == "model_not_configured":
                raise GateError("model_not_configured", rt.MODEL_OFF_TEXT) from exc
            c["skipped"] += 1
            continue
        except Exception:  # noqa: BLE001 - a system that cannot be read is skipped and counted
            c["skipped"] += 1
            continue
        write_json(out_dir / "shadow" / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', sid)}.json", rep)
        cand, old = worst(rep["findings"]), worst(base["findings"])
        person = person_verdict(env, sid, defn.dimension_id)
        c["systems"] += 1
        c["agree_live"] += cand == old
        c["disagree_live"] += cand != old
        c["new_fails"] += cand == "fail" and old != "fail"
        c["fixed_fails"] += old == "fail" and cand != "fail"
        by_agent = str(base.get("agent_id") or "")
        c["stored_by_agent" if live and by_agent == defn.id else "stored_by_other"] += 1
        if person:
            c["compared_person"] += 1
            c["agree_person"] += cand == person
            c["disagree_person"] += cand != person
        systems.append(
            {"system_id": sid, "candidate": cand, "stored": old, "person": person or "none"}
        )
    keys = (
        "systems",
        "agree_live",
        "disagree_live",
        "new_fails",
        "fixed_fails",
        "compared_person",
        "agree_person",
        "disagree_person",
        "stored_by_agent",
        "stored_by_other",
        "skipped",
    )
    return {
        "requested": n,
        "available": len(stored),
        **{k: int(c[k]) for k in keys},
        "systems_detail": systems,
        "status": "ok" if c["systems"] else "no_data",
    }


# ------------------------------------------------------------------------------ report


def sign_report(doc: dict[str, Any], signer: Any) -> dict[str, Any]:
    """Add ``content_sha256`` and the Ed25519 ``signature`` of the evidence signer (like the
    regulator pack; verify with ``python -m supervisor.evidence.verify <file>``)."""
    from supervisor.evidence.verify import GATE_REPORT_SIGNING_PREFIX

    body = {k: v for k, v in doc.items() if k not in ("content_sha256", "signature")}
    digest = sha256_hex(body)
    doc["content_sha256"] = digest
    if signer is None:
        doc["signature"] = {
            "algorithm": "none",
            "key_id": "",
            "key_kind": "none",
            "signature": "",
            "public_key": "",
        }
        return doc
    raw = signer.sign(GATE_REPORT_SIGNING_PREFIX + digest.encode("ascii"))
    pem = getattr(signer, "public_key_pem", None)
    doc["signature"] = {
        "algorithm": getattr(signer, "algorithm", "ed25519"),
        "key_id": signer.key_id,
        "key_kind": getattr(signer, "key_kind", "dev"),
        "signature": base64.b64encode(raw).decode("ascii"),
        "public_key": pem() if callable(pem) else str(pem or ""),
    }
    return doc


# ------------------------------------------------------------------------------ rows and start


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default if value is None else value


def row_view(row: Mapping[str, Any]) -> dict[str, Any]:
    r = dict(row)
    for k in ("layer1_json", "layer2_json", "layer3_json", "cost_json"):
        r[k[:-5]] = _json(r.get(k), {})
    return r


def get_run(env: GateEnv, run_id: str) -> dict[str, Any] | None:
    row = env.state.get(TABLE, {"run_id": run_id})
    return row_view(row) if row is not None else None


def latest_runs(
    env: GateEnv, agent_id: str, version: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    rows = promotion.runs_of(env.store, agent_id, version)
    return [row_view(r) for r in rows[-limit:]][::-1]


def last_gate(env: GateEnv, agent_id: str) -> dict[str, Any] | None:
    """The newest finished run of any version, for the catalogue card."""
    done = [r for r in promotion.runs_of(env.store, agent_id) if r["status"] == "done"]
    return row_view(done[-1]) if done else None


def _save(env: GateEnv, run_id: str, changes: Mapping[str, Any]) -> None:
    row = env.state.get(TABLE, {"run_id": run_id})
    if row is not None:
        env.state.update(TABLE, {"run_id": run_id}, dict(changes), row["row_version"])


def preflight(
    env: GateEnv, row: Mapping[str, Any], kind: str, n: int, systems: Sequence[str]
) -> int:
    """All refusals before a row is written. Returns the case count to run."""
    state = row["state"]
    if kind == "shadow":
        if state not in ("draft", "tested"):
            raise GateError("bad_state", f"a {state} version cannot be run in shadow")
    elif state not in ("draft", "tested") or (kind != "full" and state != "draft"):
        raise GateError("bad_state", f"a {state} version cannot be tested; only a draft can")
    env.model()  # model_not_configured while LLM_BASE_URL is empty
    defn = row["definition"]
    if kind in ("full", "sample"):
        issues = linter.lint_definition(defn)
        if linter.has_errors(issues) or (kind == "full" and not linter.is_ready(issues)):
            raise GateError(
                "lint_not_ready",
                "the instructions must name every checklist item and pass the linter: "
                + ", ".join(promotion.unreferenced(row) or [i.rule for i in issues][:5]),
            )
        cases = golden.all_gate_cases(env.data_dir, row["id"])
        strat = golden.gate_stratification(cases, [c["id"] for c in defn["checklist"]])
        if kind == "full":
            if not strat["ready"]:
                raise GateError("golden_not_ready", "; ".join(strat["problems"]))
            return len(cases)
        if not cases:
            raise GateError("no_cases", "the agent has no golden case; upload a golden set first")
        size = n or caps.SAMPLE_DEFAULT
        if not 1 <= size <= caps.SAMPLE_MAX:
            raise GateError("bad_size", f"a sample has 1 to {caps.SAMPLE_MAX} cases")
        return min(size, len(cases))
    if kind == "simulation":
        if not 1 <= len(systems) <= caps.SIMULATION_MAX_SYSTEMS:
            raise GateError("bad_systems", f"choose 1 to {caps.SIMULATION_MAX_SYSTEMS} systems")
        if env.inputs_for is None:
            raise GateError("no_inventory", "this environment cannot read the inventory")
        return len(systems)
    size = n or caps.SHADOW_DEFAULT
    if not 1 <= size <= caps.SHADOW_MAX:
        raise GateError("bad_size", f"a shadow run has 1 to {caps.SHADOW_MAX} systems")
    return size


def start(
    env: GateEnv,
    agent_id: str,
    version: str,
    kind: str,
    by: str,
    *,
    n: int = 0,
    systems: Sequence[str] = (),
    background: bool = True,
) -> dict[str, Any]:
    """Write a ``queued`` row and run in a background thread (``background=False``: in this
    thread, for tests and the CLI). One run at a time per agent id."""
    require_on(env.settings)
    if kind not in caps.GATE_KINDS:
        raise GateError("bad_kind", f"kind must be one of {', '.join(caps.GATE_KINDS)}")
    row = env.store.get(agent_id, version or None)
    if row is None:
        raise GateError("not_found", f"agent {agent_id} does not exist")
    size = preflight(env, row, kind, n, systems)
    with _LOCK:
        if agent_id in _RUNNING:
            raise GateError(
                "run_in_progress", f"a gate run of {agent_id} is in progress; wait for it"
            )
        run_id = "gate_" + sha256_hex([agent_id, row["version"], kind, time.time_ns()])[:20]
        env.state.insert(
            TABLE,
            {
                "run_id": run_id,
                "agent_id": agent_id,
                "version": row["version"],
                "kind": kind,
                "status": "queued",
                "started_at": env.clock.now(),
                "finished_at": None,
                "layer1_json": {"progress": {"done": 0, "total": size}},
                "layer2_json": {},
                "layer3_json": {},
                "cost_json": {},
                "verdict": "not_run",
                "report_sha256": None,
                "signature": None,
                "definition_sha256": definition_sha256(row["definition"]),
                "created_by": by[:120],
            },
        )
        _RUNNING[agent_id] = run_id
    env.store.record_event(agent_id, row["version"], "gate_run", by, f"{kind} run {run_id} queued")
    args = (env, run_id, row, kind, size, tuple(systems))
    if background:
        th = threading.Thread(target=_thread, args=args, daemon=True)
        _THREADS[agent_id] = th
        th.start()
    else:
        _thread(*args)
    out = get_run(env, run_id)
    assert out is not None  # noqa: S101 - just inserted
    return out


def join(agent_id: str, timeout: float = 120.0) -> None:
    th = _THREADS.get(agent_id)
    if th is not None:
        th.join(timeout)


def _thread(
    env: GateEnv, run_id: str, row: dict[str, Any], kind: str, size: int, systems: tuple[str, ...]
) -> None:
    agent_id = row["id"]
    try:
        execute(env, run_id, row, kind, size, systems)
    except GateError as exc:
        _fail(env, run_id, exc.code)
    except Exception as exc:  # noqa: BLE001 - the thread must leave a row, never die silently
        log.warning("gate run failed (%s)", type(exc).__name__)
        _fail(env, run_id, f"run_broke_{type(exc).__name__}")
    finally:
        with _LOCK:
            if _RUNNING.get(agent_id) == run_id:
                del _RUNNING[agent_id]


def _fail(env: GateEnv, run_id: str, why: str) -> None:
    try:
        _save(
            env,
            run_id,
            {
                "status": "failed",
                "finished_at": env.clock.now(),
                "verdict": "not_run",
                "layer1_json": {"error": clean(why, 120)},
            },
        )
    except Exception:  # noqa: BLE001
        log.exception("gate: could not close the run row")


def execute(
    env: GateEnv, run_id: str, row: dict[str, Any], kind: str, size: int, systems: tuple[str, ...]
) -> None:
    """The run itself (also the unit under test)."""
    t0 = time.monotonic()
    _save(env, run_id, {"status": "running"})
    defn = AgentDefinitionV1.model_validate(row["definition"])
    agent_chat, judge_chat = MeteredModel(env.model()), MeteredModel(env.model())
    out_dir = gate_dir(env.data_dir, row["id"], run_id)
    write_json(out_dir / "definition.json", row["definition"])
    golden_sha = golden.golden_sha256(env.data_dir, row["id"])
    l1: dict[str, Any] = {}
    l2: dict[str, Any] = {}
    l3: dict[str, Any] = {}
    verdict = "not_run"

    def progress(done: int, total: int) -> None:
        _save(env, run_id, {"layer1_json": {"progress": {"done": done, "total": total}}})

    if kind in ("full", "sample"):
        all_cases = golden.all_gate_cases(env.data_dir, row["id"])
        cases = all_cases if kind == "full" else pick_sample(all_cases, size)
        by_id = {c["case_id"]: c for c in all_cases}
        results = run_cases(env, defn, cases, agent_chat, judge_chat, progress=progress)
        components = probe.run_component_tests(row["definition"], env.tools)
        l1 = layer1(defn, results, components, env.tools)
        l2 = layer2(
            env,
            defn,
            results,
            by_id,
            judge_chat,
            agent_chat,
            full=kind == "full",
            golden_sha=golden_sha,
        )
        write_json(
            out_dir / "cases.json",
            [
                {k: v for k, v in r.items() if k != "problems"}
                | {"problems": {k: len(v) for k, v in r["problems"].items()}}
                for r in results
            ],
        )
        if kind == "full":
            l3 = shadow(env, defn, agent_chat, caps.SHADOW_DEFAULT, out_dir)
        verdict = "pass" if l1["ok"] and l2["ok"] else "fail"
    elif kind == "shadow":
        l3 = shadow(env, defn, agent_chat, size, out_dir)
    elif kind == "simulation":
        from supervisor.factory import simulation

        l1, l2 = simulation.run(env, row, defn, agent_chat, list(systems), out_dir, run_id)
    cost = {
        "model_calls": agent_chat.calls + judge_chat.calls,
        "agent_calls": agent_chat.calls,
        "judge_calls": judge_chat.calls,
        "tokens_estimated": agent_chat.tokens + judge_chat.tokens,
        "seconds": int(time.monotonic() - t0),
        "cases": size if kind in ("full", "sample") else 0,
    }
    finished = env.clock.now()
    doc: dict[str, Any] = {
        "format": caps.GATE_REPORT_FORMAT,
        "version": 1,
        "banner": BANNER,
        "run_id": run_id,
        "agent_id": row["id"],
        "agent_version": row["version"],
        "kind": kind,
        "definition_sha256": definition_sha256(row["definition"]),
        "golden_sha256": golden_sha,
        "model_id": str(agent_chat.model_id),
        "started_at": format_ts(_started(env, run_id, finished)),
        "finished_at": format_ts(finished),
        "verdict": verdict,
        "thresholds": {
            "kappa_floor": caps.CALIBRATION_KAPPA_FLOOR,
            "max_regression_cases": caps.MAX_REGRESSION_CASES,
            "calibration_min_labels": caps.CALIBRATION_MIN_LABELS,
            "tier_floor_percent": caps.TIER_FLOOR_PERCENT,
        },
        "layer1": _public(l1),
        "layer2": _public(l2),
        "layer3": _public(l3),
        "cost": cost,
    }
    sign_report(doc, env.signer)
    write_json(out_dir / "report.json", doc)
    _save(
        env,
        run_id,
        {
            "status": "done",
            "finished_at": finished,
            "layer1_json": l1,
            "layer2_json": l2,
            "layer3_json": l3,
            "cost_json": cost,
            "verdict": verdict,
            "report_sha256": doc["content_sha256"],
            "signature": doc["signature"]["signature"] or None,
        },
    )
    done = get_run(env, run_id)
    assert done is not None  # noqa: S101
    _chain(env, done, l1, l2)
    if kind == "full":
        fresh = env.store.get(row["id"], row["version"])
        if fresh is not None:
            _after_full(env, fresh, done)


def _started(env: GateEnv, run_id: str, default: Any) -> Any:
    r = env.state.get(TABLE, {"run_id": run_id})
    return r["started_at"] if r is not None and r["started_at"] is not None else default


def _public(layer: Mapping[str, Any]) -> dict[str, Any]:
    """The layer as written into the signed report: no free text of a document, no per-case
    reasons; integers, ids and enums."""
    out = json.loads(json.dumps(layer))
    for c in out.get("checks") or []:
        if c.get("kind") == "case":
            c.pop("detail", None)
    return out


def _after_full(env: GateEnv, row: dict[str, Any], run: dict[str, Any]) -> None:
    """A full run ends: a pass moves a draft to tested; a fail sends tested or approved to draft."""
    try:
        if run["verdict"] == "pass" and row["state"] == "draft":
            promotion.mark_tested(env.store, env.sink, row, run)
        elif run["verdict"] == "fail":
            promotion.gate_failed(env.store, env.sink, row, run)
    except SupervisorError as exc:
        env.store.record_event(
            row["id"], row["version"], "gate_run", "gate", f"not applied: {exc}"[:280]
        )


def _chain(
    env: GateEnv, run: Mapping[str, Any], l1: Mapping[str, Any], l2: Mapping[str, Any]
) -> None:
    if env.sink is None:
        return
    cal = l2.get("calibration") or {}
    payload = {
        "run_id": run["run_id"],
        "factory_agent_id": run["agent_id"],
        "version": run["version"],
        "kind": run["kind"],
        "status": run["status"],
        "verdict": run["verdict"],
        "definition_sha256": run["definition_sha256"],
        "report_sha256": run.get("report_sha256") or "",
        "layer1_percent": int(l1.get("percent", 0)),
        "cases": int(l2.get("cases", 0)),
        "match_percent": int(l2.get("match_percent", 0)),
        "kappa_hundredths": int(cal.get("kappa_hundredths", 0)),
        "ts": format_ts(env.clock.now()),
    }
    try:
        check_no_floats(payload)
        env.sink.record(RECORD_TYPE, f"factory_gate_run:{run['run_id']}", payload)
    except Exception:  # noqa: BLE001 - the row and the report are stored; log and go on
        log.exception("gate chain record failed")


def verify_report(path: Path, signer: Any = None) -> bool:
    """True when the report's hash matches its content (offline check helper for tests)."""
    doc = read_json(path)
    if not isinstance(doc, dict):
        return False
    body = {k: v for k, v in doc.items() if k not in ("content_sha256", "signature")}
    return sha256_hex(body) == doc.get("content_sha256")
