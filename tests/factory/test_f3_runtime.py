"""WP-F3: the harness runtime (``factory.runtime.run_agent``) with a scripted fake ChatModel.

The product has no mock path: with LLM_BASE_URL empty the run answers model_not_configured. Every
test model here is a test double that records what the runtime sent it."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.factory import caps, probe, registry
from supervisor.factory import runtime as rt
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from supervisor.factory.schemas.assessment_report_v1 import AssessmentReportV1

TOOLS = registry.load_tools()


def run(
    defn: dict[str, Any],
    answer: Any = probe.answer_good,
    *,
    big: bool = False,
    extra: dict[str, Any] | None = None,
    model: Any = None,
    log: list | None = None,
) -> tuple[dict[str, Any], probe.ProbeModel]:
    m = model or probe.ProbeModel(answer)
    inputs = {
        **probe.probe_inputs(AgentDefinitionV1.model_validate(defn), TOOLS, big=big),
        **(extra or {}),
    }
    report = rt.run_agent(defn, inputs, m, tools=TOOLS, log=log)
    return report, m


def finding(report: dict[str, Any], cid: str) -> dict[str, Any]:
    return next(f for f in report["findings"] if f["checklist_id"] == cid)


def only_ints(value: Any) -> bool:
    if isinstance(value, float):
        return False
    if isinstance(value, dict):
        return all(only_ints(v) for v in value.values())
    if isinstance(value, list):
        return all(only_ints(v) for v in value)
    return True


# ------------------------------------------------------------------------------ single pass


def test_single_pass_report_is_valid_and_the_trace_is_integers(agent: dict[str, Any]) -> None:
    report, model = run(agent)
    AssessmentReportV1.model_validate(report)
    assert only_ints(report["harness_trace"])
    assert report["harness_trace"]["loop"] == {
        "iterations": 1,
        "stopped_by": "single_pass",
        "tokens_used": report["harness_trace"]["loop"]["tokens_used"],
        "per_iteration": [],
    }
    assert finding(report, "MR-02")["verdict"] == "pass"
    assert finding(report, "MR-02")["evidence"][0]["kind"] == "system_record"
    assert report["model_id"] == "harness-probe" and model.calls >= 1
    # the preamble comes first, then the team instructions
    sent = json.dumps(model.users)  # users only; the system message is checked below
    assert sent
    assert report["harness_trace"]["system_prompt"]["preamble_version"] == 1


def test_preamble_first_then_instructions(agent: dict[str, Any]) -> None:
    seen: list[str] = []

    class Spy(probe.ProbeModel):
        def complete_json(self, messages: Any, json_schema: Any, timeout_s: float) -> Any:
            seen.append(messages[0]["content"])
            return super().complete_json(messages, json_schema, timeout_s)

    run(agent, model=Spy(probe.answer_good))
    assert seen[0].startswith(rt.PLATFORM_PREAMBLE)
    assert seen[0].index("Team instructions") > len(rt.PLATFORM_PREAMBLE) - 1
    assert agent["instructions"].strip() in seen[0]


def test_no_model_configured_never_a_mock(agent: dict[str, Any]) -> None:
    inputs = {"settings": SimpleNamespace(llm_base_url=""), "system": {"system_id": "s"}}
    with pytest.raises(rt.AgentRuntimeError) as exc:
        rt.run_agent(agent, inputs)
    assert exc.value.code == "model_not_configured"

    class Mock:
        family, model_id, is_mock = "mock", "mock", True

        def complete_json(self, *a: Any) -> Any:
            raise AssertionError("a mock model must never be called")

    with pytest.raises(rt.AgentRuntimeError) as exc2:
        rt.run_agent(agent, inputs, Mock())
    assert exc2.value.code == "model_not_configured"


def test_invalid_definition_is_refused(agent: dict[str, Any]) -> None:
    agent["guardians"] = []
    with pytest.raises(rt.AgentRuntimeError) as exc:
        rt.run_agent(agent, {}, probe.ProbeModel(probe.answer_good))
    assert exc.value.code == "invalid_definition"


# ------------------------------------------------------------------------------ budget


def test_context_budget_is_never_exceeded(agent: dict[str, Any]) -> None:
    agent["harness"]["context"]["budget_tokens"] = caps.CONTEXT_BUDGET_MIN
    report, model = run(agent, big=True)
    assert model.calls >= 1
    assert model.max_prompt_tokens <= caps.CONTEXT_BUDGET_MIN
    assert report["harness_trace"]["context"]["tokens_used"] <= caps.CONTEXT_BUDGET_MIN
    assert report["harness_trace"]["context"]["budget_tokens"] == caps.CONTEXT_BUDGET_MIN


def test_a_fixed_part_larger_than_the_budget_makes_no_call(agent: dict[str, Any]) -> None:
    agent["harness"]["context"]["budget_tokens"] = caps.CONTEXT_BUDGET_MIN
    agent["instructions"] = "MR-01 MR-02 " + ("kiem tra bang chung cho tung muc. " * 400)
    report, model = run(agent)
    assert model.calls == 0
    assert all(f["verdict"] == "question" for f in report["findings"])
    assert report["harness_trace"]["verification"]["findings_rejected"] == 2


def test_loop_token_budget_stops_the_run(loop_agent: dict[str, Any]) -> None:
    loop_agent["harness"]["loop"]["budget_tokens"] = caps.CONTEXT_BUDGET_MIN
    loop_agent["harness"]["context"]["budget_tokens"] = caps.CONTEXT_BUDGET_MIN
    report, _ = run(loop_agent, probe.answer_question, big=True)
    tr = report["harness_trace"]["loop"]
    assert tr["stopped_by"] == "budget"
    assert tr["tokens_used"] <= caps.CONTEXT_BUDGET_MIN


def test_orchestrator_budget_caps_the_run(agent: dict[str, Any]) -> None:
    m = probe.ProbeModel(probe.answer_good)
    inputs = {
        **probe.probe_inputs(AgentDefinitionV1.model_validate(agent), TOOLS),
        "budget": {"tokens": 50, "seconds": 5},
    }
    report = rt.run_agent(agent, inputs, m, tools=TOOLS)
    assert m.calls == 0
    assert report["harness_trace"]["loop"]["stopped_by"] == "budget"
    assert report["summary"]["questions"] == 2


# ------------------------------------------------------------------------------ hitl


def test_checklist_stop_point_stops_the_item_before_the_call(agent: dict[str, Any]) -> None:
    agent["harness"]["hitl"]["approval_points"] = [{"kind": "checklist", "ref": "MR-02"}]
    report, model = run(agent)
    f = finding(report, "MR-02")
    assert f["verdict"] == "question" and "STOP" in f["rationale"]
    assert "MR-02" not in model.seen_items()
    assert report["harness_trace"]["hitl"]["stop_points_fired"] == 1
    assert finding(report, "MR-01")["verdict"] == "pass"


def test_verdict_stop_point_stops_the_finding(agent: dict[str, Any]) -> None:
    agent["harness"]["hitl"]["approval_points"] = [{"kind": "verdict", "ref": "pass"}]
    report, _ = run(agent)
    assert all(f["verdict"] == "question" for f in report["findings"])
    assert all("STOP" in f["rationale"] for f in report["findings"])
    assert report["harness_trace"]["hitl"]["stop_points_fired"] == 2


def test_fail_on_a_high_item_needs_a_person(agent: dict[str, Any]) -> None:
    report, _ = run(agent, probe.answer_verdict("fail", "MR-01"))
    assert finding(report, "MR-01")["verdict"] == "fail"
    assert report["harness_trace"]["hitl"]["approvals_requested"] == 1
    assert "needs a person" in finding(report, "MR-01")["rationale"]
    # a fail on a medium item does not
    report2, _ = run(agent, probe.answer_verdict("fail", "MR-02"))
    assert report2["harness_trace"]["hitl"]["approvals_requested"] == 0


def test_tool_missing_for_a_source_is_a_blocked_call(agent: dict[str, Any]) -> None:
    agent["tools"] = [t for t in agent["tools"] if t["tool_id"] != "read_system_record"]
    report, model = run(agent)
    assert report["harness_trace"]["hitl"]["tool_calls_blocked"] >= 1
    assert model.calls == 0 or "MR-02" not in model.seen_items()
    assert finding(report, "MR-02")["verdict"] == "question"


def test_tool_scope_limits_the_regkb_rows(agent: dict[str, Any]) -> None:
    agent["checklist"][1]["evidence"] = ["regkb"]
    agent["checklist"][0]["evidence"] = ["system_record"]
    agent["evidence_rules"]["allowed_sources"] = ["fact", "system_record", "regkb", "pack"]
    agent["harness"]["context"]["sources"] = ["facts_v1", "system_record", "regkb_rows"]
    m = probe.ProbeModel(probe.answer_good)
    inputs = probe.probe_inputs(AgentDefinitionV1.model_validate(agent), TOOLS)
    inputs["regkb"] = [
        {"ref": "SBV-TT53-2025#1", "text": "Dieu 1 trong pham vi."},
        {"ref": "OTHER-LAW#9", "text": "Dieu 9 ngoai pham vi."},
    ]
    rt.run_agent(agent, inputs, m, tools=TOOLS)
    assert "SBV-TT53-2025#1" in m.seen_refs() and "OTHER-LAW#9" not in m.seen_refs()


# ------------------------------------------------------------------------------ verification


@pytest.mark.parametrize("plant", ["unloaded", "quote", "rule"])
def test_verifier_catches_a_planted_bad_finding(agent: dict[str, Any], plant: str) -> None:
    report, _ = run(agent, probe.answer_plant(plant))
    f = finding(report, "MR-01")
    assert f["verdict"] == "question" and f["evidence"] == []
    assert "verifier rejected" in f["rationale"]
    assert report["harness_trace"]["verification"]["findings_rejected"] == 1
    assert finding(report, "MR-02")["verdict"] == "pass"


def test_pass_without_evidence_is_rejected(agent: dict[str, Any]) -> None:
    def answer(user: Any) -> dict:
        out = probe.answer_good(user)
        out["findings"][0]["evidence"] = []
        return out

    report, _ = run(agent, answer)
    assert finding(report, "MR-01")["verdict"] == "question"


def test_document_evidence_needs_a_quote(agent: dict[str, Any]) -> None:
    agent["tools"].append({"tool_id": "search_documents", "mode": "read"})
    agent["owner_group"] = "model_risk"
    m_def = AgentDefinitionV1.model_validate(agent)
    inputs = probe.probe_inputs(m_def, TOOLS)

    def answer(user: Any) -> dict:
        out = {"findings": []}
        for it in user["items"]:
            doc = next((s for s in user["loaded_sources"] if s["kind"] == "document"), None)
            ev = [{"kind": "document", "ref": doc["ref"]}] if doc else []
            out["findings"].append(
                {
                    "checklist_id": it["checklist_id"],
                    "verdict": "pass" if ev else "question",
                    "pass_rule_met": bool(ev),
                    "confidence": "high",
                    "rationale": "doc",
                    "evidence": ev,
                }
            )
        return out

    report = rt.run_agent(agent, inputs, probe.ProbeModel(answer), tools=TOOLS)
    assert finding(report, "MR-01")["verdict"] == "question"  # no quote: rejected


def test_system_record_alias_is_normalised(agent: dict[str, Any]) -> None:
    def answer(user: Any) -> dict:
        out = probe.answer_good(user)
        for f in out["findings"]:
            for e in f["evidence"]:
                e["ref"] = e["ref"].split(".", 1)[
                    -1
                ]  # owner_user instead of probe-system.owner_user
        return out

    report, _ = run(agent, answer)
    assert finding(report, "MR-02")["evidence"][0]["ref"].startswith("probe-system.")


def test_rules_plus_judge_can_only_lower_the_confidence(loop_agent: dict[str, Any]) -> None:
    loop_agent["harness"]["hitl"]["approval_points"] = []
    loop_agent["harness"]["loop"] = {"mode": "single_pass"}
    loop_agent["harness"]["verification"] = {"verifier": "rules+judge"}

    class Judge(probe.ProbeModel):
        def complete_json(self, messages: Any, json_schema: Any, timeout_s: float) -> Any:
            if "reviews" in json_schema.get("properties", {}):
                self.calls += 1
                return {"reviews": [{"checklist_id": "CY-02", "agrees": False}]}
            return super().complete_json(messages, json_schema, timeout_s)

    report, _ = run(loop_agent, model=Judge(probe.answer_good))
    f = finding(report, "CY-02")
    assert f["verdict"] == "pass" and f["confidence"] == "low" and "judge re-read" in f["rationale"]
    assert report["harness_trace"]["verification"]["judge_calls"] == 1


def test_extra_validators(agent: dict[str, Any]) -> None:
    agent["harness"]["verification"]["validators"] = ["evidence_kind_allowed"]
    agent["checklist"][1]["evidence"] = [
        "pack"
    ]  # item MR-02 asks for packs, the model cites a record
    agent["evidence_rules"]["allowed_sources"] = [
        "fact",
        "system_record",
        "regkb",
        "pack",
        "document",
    ]

    def answer(user: Any) -> dict:
        out = probe.answer_good(user)
        return out

    report, _ = run(agent, answer)
    assert finding(report, "MR-02")["verdict"] == "question"  # pack source not readable here


def test_output_never_carries_personal_data(agent: dict[str, Any]) -> None:
    report, _ = run(agent, lambda u: probe.answer_good(u, rationale="goi 0912345678 hoac a@b.vn"))
    text = json.dumps(report)
    assert "0912345678" not in text and "a@b.vn" not in text


# ------------------------------------------------------------------------------ loop


def test_loop_stops_at_max_iterations_and_logs_each_reason(loop_agent: dict[str, Any]) -> None:
    loop_agent["harness"]["hitl"]["approval_points"] = []
    log: list = []
    report, model = run(loop_agent, probe.answer_question, log=log)
    tr = report["harness_trace"]["loop"]
    assert tr["iterations"] == 4 == loop_agent["harness"]["loop"]["max_iterations"]
    assert tr["stopped_by"] == "max_iterations"
    assert [i["iteration"] for i in tr["per_iteration"]] == [1, 2, 3, 4]
    assert all(i["evaluator_score"] == 0 for i in tr["per_iteration"])
    assert len(log) == 4 and all(entry["reason"] for entry in log)
    assert only_ints(report["harness_trace"])
    assert report["harness_trace"]["verification"]["judge_calls"] >= 4  # the evaluator judge


def test_loop_stops_when_all_answered(loop_agent: dict[str, Any]) -> None:
    loop_agent["harness"]["hitl"]["approval_points"] = []
    report, _ = run(loop_agent, probe.answer_good)
    tr = report["harness_trace"]["loop"]
    assert tr["iterations"] == 1 and tr["stopped_by"] == "all_answered"


def test_loop_only_asks_again_for_open_items(loop_agent: dict[str, Any]) -> None:
    loop_agent["harness"]["hitl"]["approval_points"] = []
    calls: list[list[str]] = []

    def answer(user: Any) -> dict:
        ids = [i["checklist_id"] for i in user["items"]]
        calls.append(ids)
        if len(calls) == 1:
            return probe.answer_question(user)
        return probe.answer_good(user)

    report, _ = run(loop_agent, answer)
    assert report["harness_trace"]["loop"]["stopped_by"] == "all_answered"
    assert report["harness_trace"]["loop"]["iterations"] == 2
    # two groups (two source sets) in iteration 1; only the open item again in iteration 2
    assert calls == [["CY-01"], ["CY-02"], ["CY-01"]]


def test_rules_evaluator_stops_without_a_judge_call(loop_agent: dict[str, Any]) -> None:
    loop_agent["harness"]["hitl"]["approval_points"] = []
    loop_agent["harness"]["loop"].update(
        {"loop_evaluator": "rules", "stop_when": ["evaluator_done"]}
    )
    loop_agent["harness"]["loop"].pop("min_score")
    loop_agent["harness"]["verification"] = {"verifier": "rules"}
    report, _ = run(loop_agent, probe.answer_good)
    assert report["harness_trace"]["loop"]["stopped_by"] == "evaluator_done"
    assert report["harness_trace"]["verification"]["judge_calls"] == 0


def test_judge_evaluator_with_min_score(loop_agent: dict[str, Any]) -> None:
    loop_agent["harness"]["hitl"]["approval_points"] = []
    loop_agent["harness"]["loop"]["stop_when"] = ["evaluator_done"]

    class Good(probe.ProbeModel):
        def complete_json(self, messages: Any, json_schema: Any, timeout_s: float) -> Any:
            if "score" in json_schema.get("properties", {}):
                self.calls += 1
                return {"score": 85, "reason": "complete"}
            return super().complete_json(messages, json_schema, timeout_s)

    report, _ = run(loop_agent, model=Good(probe.answer_question))
    tr = report["harness_trace"]["loop"]
    assert tr["stopped_by"] == "evaluator_done" and tr["iterations"] == 1
    assert tr["per_iteration"][0]["evaluator_score"] == 85


# ------------------------------------------------------------------------------ memory


def test_system_memory_is_masked_pruned_and_read_back(
    loop_agent: dict[str, Any], tmp_path: Path
) -> None:
    loop_agent["harness"]["hitl"]["approval_points"] = []
    loop_agent["harness"]["loop"] = {"mode": "single_pass"}
    report, _ = run(
        loop_agent,
        lambda u: probe.answer_good(u, rationale="goi 0912345678"),
        extra={"memory_dir": str(tmp_path)},
    )
    assert report["harness_trace"]["memory"]["rows_stored"] == 2
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1
    rows = json.loads(files[0].read_text())
    assert {r["kind"] for r in rows} == {"prior_verdicts"} and only_ints(rows)
    # the second run reads the first run's rows (system memory on) and hands them to the model
    m = probe.ProbeModel(probe.answer_good)
    inputs = {
        **probe.probe_inputs(AgentDefinitionV1.model_validate(loop_agent), TOOLS),
        "memory_dir": str(tmp_path),
    }
    report2 = rt.run_agent(loop_agent, inputs, m, tools=TOOLS)
    assert report2["harness_trace"]["memory"]["reads"] == 2
    assert any("memory" in u for u in m.users)


def test_memory_retention_drops_old_rows(tmp_path: Path) -> None:
    import datetime as dt

    now = dt.datetime(2026, 10, 28, 9, tzinfo=dt.UTC)
    store = rt.FileMemory(tmp_path, 30)
    old = (now - dt.timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = (now - dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.write(
        "s1",
        "a",
        [{"kind": "prior_verdicts", "checklist_id": "X", "value": "pass", "at": old}],
        now,
    )
    store.write(
        "s1",
        "a",
        [{"kind": "prior_verdicts", "checklist_id": "Y", "value": "fail", "at": new}],
        now,
    )
    assert [r["checklist_id"] for r in store.read("s1", "a", now)] == ["Y"]


def test_memory_off_stores_nothing(agent: dict[str, Any], tmp_path: Path) -> None:
    report, _ = run(agent, extra={"memory_dir": str(tmp_path)})
    assert report["harness_trace"]["memory"] == {"reads": 0, "writes": 0, "rows_stored": 0}
    assert not list(tmp_path.rglob("*.json"))


# ------------------------------------------------------------------------------ item context


def test_item_context_lists_what_a_call_would_load(agent: dict[str, Any]) -> None:
    inputs = probe.probe_inputs(AgentDefinitionV1.model_validate(agent), TOOLS)
    ctx = rt.item_context(agent, inputs, "MR-02", TOOLS)
    assert ctx and all(c["kind"] == "system_record" for c in ctx)
    assert rt.item_context(agent, inputs, "NOPE", TOOLS) == []


def test_run_does_not_change_the_definition(agent: dict[str, Any]) -> None:
    before = copy.deepcopy(agent)
    run(agent)
    assert agent == before
