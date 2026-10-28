"""Harness component tests of the test gate (WP-F3, plan section 2.0, layer 1).

Each test runs the real harness runtime (``factory.runtime.run_agent``) on the definition under
test with a scripted *probe model* and synthetic inputs, and checks one component of the harness:

* ``budget_never_exceeded``    no call is larger than ``context.budget_tokens`` and the run stays
                               inside ``loop.budget_tokens`` (measured at the model, not read from
                               the trace);
* ``cited_sources_loaded``     every evidence pointer of the report was loaded into a prompt;
* ``memory_rows_masked``       a stored memory row passes the masker and retention is enforced;
* ``stop_points_fire``         every approval point fires in a replay, and the locked rule (a fail
                               on a ``high`` item needs a person) fires;
* ``verifier_catches_planted`` a finding that cites an unloaded source, quotes text that is not
                               there, or breaks the pass rule becomes ``question``;
* ``loop_stops_at_cap``        a loop that never converges stops at ``max_iterations`` (or the
                               token budget); a single pass stops after one iteration.

The probe model is not a mock of the product path: it tests the harness, not the agent, and its
answers are never stored as an assessment. The verdict quality of the agent is judged on the
gateway model (layer 2).
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from supervisor.factory import caps, registry
from supervisor.factory import runtime as rt
from supervisor.factory.golden import trips_masker
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1

Answer = Callable[[Mapping[str, Any]], Mapping[str, Any]]
PROBE_NOW = "2026-10-28T09:00:00Z"
PHONE = "0912345678"


class ProbeModel:
    """A scripted model for the component tests. Records every prompt it sees."""

    family = "probe"
    model_id = "harness-probe"
    is_mock = False

    def __init__(self, answer: Answer) -> None:
        self.answer = answer
        self.users: list[dict[str, Any]] = []
        self.max_prompt_tokens = 0
        self.total_tokens = 0
        self.calls = 0

    def complete_json(
        self,
        messages: Any,
        json_schema: Mapping[str, Any],
        timeout_s: float,
    ) -> Mapping[str, Any]:
        tokens = caps.estimate_tokens(json.dumps(list(messages)))
        self.max_prompt_tokens = max(self.max_prompt_tokens, tokens)
        self.total_tokens += tokens
        self.calls += 1
        props = (json_schema or {}).get("properties", {})
        if "findings" in props:
            user = json.loads(messages[1]["content"])
            self.users.append(user)
            reply = dict(self.answer(user))
        elif "score" in props:
            reply = {"score": 0, "reason": "probe evaluator: not good enough"}
        else:
            reply = {"reviews": []}
        self.total_tokens += caps.estimate_tokens(json.dumps(reply))
        return reply

    def seen_refs(self) -> set[str]:
        return {s["ref"] for u in self.users for s in u.get("loaded_sources", [])}

    def seen_items(self) -> set[str]:
        return {i["checklist_id"] for u in self.users for i in u.get("items", [])}


# ------------------------------------------------------------------------------ probe inputs


def _scope_prefix(defn: AgentDefinitionV1, tools: registry.ToolRegistry, kind: str) -> str:
    for t in defn.tools:
        reg = tools.get(t.tool_id)
        if reg is not None and reg.kind == kind and t.scope and ":" in t.scope:
            value = t.scope.partition(":")[2]
            if value and value != "own":
                return value
    return ""


def probe_inputs(
    defn: AgentDefinitionV1, tools: registry.ToolRegistry, *, big: bool = False
) -> dict[str, Any]:
    """Synthetic inputs that every source of the definition can load (refs honour tool scopes)."""
    regkb = _scope_prefix(defn, tools, "read_regkb") or "probe-regkb"
    pack = _scope_prefix(defn, tools, "read_pack_results") or "probe-pack"
    docs = _scope_prefix(defn, tools, "search_documents") or "probe-doc"
    sections = []
    n, size = (60, 2400) if big else (3, 120)
    many = 150 if big else 3  # facts, pack results and RegKB rows: more than any budget holds
    pad = " " + "x" * 500 if big else ""
    for i in range(1, n + 1):
        text = (
            (f"Phan {i} cua tai lieu thu nghiem. " * 80)[:size]
            if big
            else (f"Phan {i}: he thong co chu so huu va nguoi kiem dinh duoc ghi ro.")
        )
        sections.append({"ref": f"{docs}#{i}", "text": text})
    return {
        "system_id": "probe-system",
        "system": {
            "system_id": "probe-system",
            "owner_user": "probe-owner",
            "name": "probe",
            **({f"field_{i}": "v" * 200 for i in range(many)} if big else {}),
        },
        "facts": {
            "version": 1,
            "node_id": "probe-system",
            "facts": [
                {
                    "fact_id": f"fct_probe_{i}",
                    "kind": "tool",
                    "name": f"tool_{i}",
                    "detail": "risk_class=money; approval=none" + pad,
                    "file": "agent.py",
                    "line": 10 + i,
                    "quote": f"def tool_{i}():",
                }
                for i in range(1, many + 1)
            ],
        },
        "packs": [
            {"ref": f"{pack}:{i}", "label": f"pack {i}", "text": "passed at version 3" + pad}
            for i in range(1, many + 1)
        ],
        "regkb": [
            {
                "ref": f"{regkb}#probe-{i}",
                "text": f"Dieu {i}: to chuc phai danh gia rui ro mo hinh." + pad,
            }
            for i in range(1, many + 1)
        ],
        "documents": [{"doc_id": docs, "sections": sections}],
        "now": PROBE_NOW,
    }


# ------------------------------------------------------------------------------ answers


def _quote(text: str) -> str:
    return " ".join(text.split())[:30]


def _evidence_for(user: Mapping[str, Any], item: Mapping[str, Any]) -> list[dict[str, Any]]:
    for s in user.get("loaded_sources", []):
        if s["kind"] in item["evidence_kinds"]:
            ev: dict[str, Any] = {"kind": s["kind"], "ref": s["ref"], "quote": _quote(s["text"])}
            return [ev]
    return []


def answer_good(user: Mapping[str, Any], *, rationale: str = "probe: supported by source") -> dict:
    out = []
    for it in user["items"]:
        ev = _evidence_for(user, it)
        if ev:
            out.append(
                {
                    "checklist_id": it["checklist_id"],
                    "verdict": "pass",
                    "pass_rule_met": True,
                    "confidence": "high",
                    "rationale": rationale,
                    "evidence": ev,
                }
            )
        else:
            out.append(_question(it))
    return {"findings": out}


def _question(it: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "checklist_id": it["checklist_id"],
        "verdict": "question",
        "pass_rule_met": False,
        "confidence": "low",
        "rationale": "probe: nothing decides this",
        "evidence": [],
    }


def answer_question(user: Mapping[str, Any]) -> dict:
    return {"findings": [_question(it) for it in user["items"]]}


def answer_verdict(verdict: str, only: str | None = None) -> Answer:
    """``verdict`` with valid evidence for ``only`` (or the first item); pass for the others."""

    def fn(user: Mapping[str, Any]) -> dict:
        out = []
        for idx, it in enumerate(user["items"]):
            ev = _evidence_for(user, it)
            target = it["checklist_id"] == only if only else idx == 0
            v = verdict if target else "pass"
            if v in ("pass", "fail") and not ev:
                out.append(_question(it))
                continue
            out.append(
                {
                    "checklist_id": it["checklist_id"],
                    "verdict": v,
                    "pass_rule_met": v == "pass",
                    "confidence": "high",
                    "rationale": "probe",
                    "evidence": ev if v in ("pass", "fail") else [],
                }
            )
        return {"findings": out}

    return fn


def answer_plant(kind: str) -> Answer:
    """The first item gets a planted bad finding of ``kind``."""

    def fn(user: Mapping[str, Any]) -> dict:
        res = answer_good(user)
        first = res["findings"][0]
        ev = first["evidence"][:1] or [{"kind": "document", "ref": "x", "quote": "x"}]
        if kind == "unloaded":
            first.update(
                verdict="pass",
                pass_rule_met=True,
                evidence=[{"kind": ev[0]["kind"], "ref": "never-loaded#99", "quote": "x"}],
            )
        elif kind == "quote":
            first.update(
                verdict="pass",
                pass_rule_met=True,
                evidence=[{**ev[0], "quote": "text that is not in the source zz9"}],
            )
        elif kind == "rule":
            first.update(verdict="pass", pass_rule_met=False, evidence=ev)
        return res

    return fn


# ------------------------------------------------------------------------------ the tests


def _run(
    defn: AgentDefinitionV1,
    tools: registry.ToolRegistry,
    answer: Answer,
    *,
    big: bool = False,
    extra: Mapping[str, Any] | None = None,
    definition: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ProbeModel]:
    model = ProbeModel(answer)
    inputs = {**probe_inputs(defn, tools, big=big), **(extra or {})}
    report = rt.run_agent(
        definition if definition is not None else defn.model_dump(mode="json"),
        inputs,
        model,
        tools=tools,
        log=[],
    )
    return report, model


def _finding(report: Mapping[str, Any], cid: str) -> Mapping[str, Any]:
    return next(f for f in report["findings"] if f["checklist_id"] == cid)


def test_budget(defn: AgentDefinitionV1, tools: registry.ToolRegistry) -> tuple[bool, str]:
    report, model = _run(defn, tools, answer_good, big=True)
    budget = defn.harness.context.budget_tokens
    run_budget = defn.harness.loop.budget_tokens
    if model.calls == 0:
        return False, "no model call was made (nothing could be loaded)"
    if model.max_prompt_tokens > budget:
        return False, f"a call of {model.max_prompt_tokens} tokens is over the budget {budget}"
    if model.total_tokens > run_budget:
        return False, f"the run used {model.total_tokens} tokens, over the run budget {run_budget}"
    trace = report["harness_trace"]
    if trace["context"]["tokens_used"] > budget:
        return False, "the trace reports a call over the budget"
    return (
        True,
        f"max call {model.max_prompt_tokens} of {budget}; run {model.total_tokens} of {run_budget}",
    )


def test_cited_loaded(defn: AgentDefinitionV1, tools: registry.ToolRegistry) -> tuple[bool, str]:
    report, model = _run(defn, tools, answer_good)
    seen = model.seen_refs()
    if not seen:
        return False, "no source was loaded into a prompt"
    cited = {e["ref"] for f in report["findings"] for e in f["evidence"]}
    bad = sorted(cited - seen)
    trace_refs = set(report["harness_trace"]["context"]["source_refs"])
    if bad:
        return False, f"{len(bad)} cited source(s) were never loaded"
    if not trace_refs <= seen:
        return False, "the trace lists a source that was not loaded"
    return True, f"{len(cited)} cited, {len(seen)} loaded"


def test_memory(defn: AgentDefinitionV1, tools: registry.ToolRegistry) -> tuple[bool, str]:
    mem = defn.harness.memory
    if not mem.system_memory:
        return True, "system memory is off (nothing is stored)"
    with tempfile.TemporaryDirectory() as tmp:
        report, _ = _run(
            defn,
            tools,
            lambda u: answer_good(u, rationale=f"probe {PHONE}"),
            extra={"memory_dir": tmp, "waivers": [defn.checklist[0].id]},
        )
        text = "".join(p.read_text(encoding="utf-8") for p in Path(tmp).rglob("*.json"))
        if not text:
            return False, "no memory row was stored"
        if trips_masker(text):
            return False, "a stored memory row holds personal data"
        store = rt.FileMemory(Path(tmp), int(mem.retention_days or 1))
        now = dt.datetime.strptime(PROBE_NOW, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
        old = (now - dt.timedelta(days=int(mem.retention_days or 1) + 5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        store.write(
            "stale-system",
            defn.id,
            [
                {
                    "kind": "prior_verdicts",
                    "checklist_id": defn.checklist[0].id,
                    "value": "pass",
                    "at": old,
                }
            ],
            now,
        )
        if store.read("stale-system", defn.id, now):
            return False, "a row older than retention_days was not pruned"
        rows = report["harness_trace"]["memory"]["rows_stored"]
    return True, f"{rows} row(s) stored, masked; retention enforced"


def test_stop_points(defn: AgentDefinitionV1, tools: registry.ToolRegistry) -> tuple[bool, str]:
    fired = 0
    for ap in defn.harness.hitl.approval_points:
        if ap.kind == "checklist":
            report, model = _run(defn, tools, answer_good)
            f = _finding(report, ap.ref)
            if f["verdict"] != "question" or "STOP" not in f["rationale"]:
                return False, f"checklist stop point {ap.ref} did not stop the item"
            if ap.ref in model.seen_items():
                return False, f"checklist stop point {ap.ref}: the model was still asked"
        elif ap.ref == "question":
            continue  # a question already waits for a person
        else:
            first = defn.checklist[0].id
            report, _ = _run(defn, tools, answer_verdict(ap.ref, first))
            f = _finding(report, first)
            if f["verdict"] != "question" or "STOP" not in f["rationale"]:
                return False, f"verdict stop point {ap.ref} did not stop the finding"
        if report["harness_trace"]["hitl"]["stop_points_fired"] < 1:
            return False, f"stop point {ap.kind}:{ap.ref} did not count"
        fired += 1
    high = next((c for c in defn.checklist if c.severity == "high"), None)
    if high is not None and not any(
        ap.kind == "checklist" and ap.ref == high.id for ap in defn.harness.hitl.approval_points
    ):
        report, _ = _run(defn, tools, answer_verdict("fail", high.id))
        f = _finding(report, high.id)
        if f["verdict"] == "fail" and report["harness_trace"]["hitl"]["approvals_requested"] < 1:
            return False, "a fail on a high item did not ask for a person"
        if f["verdict"] not in ("fail", "question"):
            return False, "a fail on a high item was lost"
        fired += 1
    return True, f"{fired} stop point(s) fired in replay"


def test_verifier(defn: AgentDefinitionV1, tools: registry.ToolRegistry) -> tuple[bool, str]:
    first = defn.checklist[0].id
    caught = 0
    for plant in ("unloaded", "quote", "rule"):
        report, model = _run(defn, tools, answer_plant(plant))
        if not model.seen_refs():
            return False, "nothing was loaded, so a planted finding cannot be tested"
        f = _finding(report, first)
        if f["verdict"] != "question":
            if plant == "rule" and first in {
                ap.ref for ap in defn.harness.hitl.approval_points if ap.kind == "checklist"
            }:
                continue  # a stopped item is never asked
            return False, f"the planted '{plant}' finding passed the verifier"
        if report["harness_trace"]["verification"]["findings_rejected"] < 1 and (
            first
            not in {ap.ref for ap in defn.harness.hitl.approval_points if ap.kind == "checklist"}
        ):
            return False, f"the planted '{plant}' finding was not counted as rejected"
        caught += 1
    return True, f"{caught} planted finding(s) caught"


def test_loop_cap(defn: AgentDefinitionV1, tools: registry.ToolRegistry) -> tuple[bool, str]:
    loop = defn.harness.loop
    report, model = _run(defn, tools, answer_question)
    tr = report["harness_trace"]["loop"]
    if loop.mode == "single_pass":
        if tr["iterations"] != 1 or tr["stopped_by"] not in ("single_pass", "budget"):
            return False, f"a single pass ran {tr['iterations']} iteration(s)"
        return True, "single pass: 1 iteration"
    if tr["iterations"] > loop.max_iterations:
        return False, f"{tr['iterations']} iterations, over the cap {loop.max_iterations}"
    if tr["stopped_by"] not in ("max_iterations", "budget"):
        return False, f"a loop that never converges stopped by {tr['stopped_by']}"
    if tr["tokens_used"] > loop.budget_tokens:
        return False, f"the loop used {tr['tokens_used']} tokens, over {loop.budget_tokens}"
    if len(tr["per_iteration"]) != tr["iterations"]:
        return False, "the trace does not log every iteration"
    return (
        True,
        f"{tr['iterations']} iteration(s) of {loop.max_iterations}, stopped by {tr['stopped_by']}",
    )


TESTS: tuple[tuple[str, Callable[..., tuple[bool, str]]], ...] = (
    ("budget_never_exceeded", test_budget),
    ("cited_sources_loaded", test_cited_loaded),
    ("memory_rows_masked", test_memory),
    ("stop_points_fire", test_stop_points),
    ("verifier_catches_planted", test_verifier),
    ("loop_stops_at_cap", test_loop_cap),
)


def run_component_tests(
    definition: Mapping[str, Any], tools: registry.ToolRegistry | None = None
) -> list[dict[str, Any]]:
    """All six tests. A test that raises is a failed test with the exception name."""
    tools = tools or registry.load_tools()
    defn = AgentDefinitionV1.model_validate(dict(definition))
    out = []
    for check_id, fn in TESTS:
        try:
            ok, detail = fn(defn, tools)
        except Exception as exc:  # noqa: BLE001 - a broken harness component fails its test
            ok, detail = False, f"the test raised {type(exc).__name__}"
        out.append({"id": check_id, "kind": "component", "ok": bool(ok), "detail": detail[:300]})
    return out
