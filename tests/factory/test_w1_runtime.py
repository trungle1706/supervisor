"""W1: visible model failures, parallel group calls, JSON record sub-sources, draft agents,
and the time-budget settings. Fake models only (no network)."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from supervisor.adapters.llm.errors import LLMError, LLMOutputError, LLMTimeoutError
from supervisor.config import Settings, load_settings
from supervisor.factory import catalog, gate, probe, registry
from supervisor.factory import runtime as rt
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from supervisor.factory.schemas.assessment_report_v1 import AssessmentReportV1
from supervisor.onboard import orchestrator as orch
from tests.factory.f3_helpers import FakeChat, make_env

TOOLS = registry.load_tools()
SECRET = "FAKE-KEY-MUST-NOT-LEAK-9f3a"  # a fake key: it must never reach a report


def three_group_agent(agent: dict[str, Any]) -> dict[str, Any]:
    """MR-01/MR-02 read the record, MR-03 reads facts, MR-04 reads the record again: 3 groups."""
    a = copy.deepcopy(agent)
    base = a["checklist"][1]
    a["checklist"].append({**base, "id": "MR-03", "evidence": ["fact"], "question": "Which tool?"})
    a["checklist"].append({**base, "id": "MR-04", "evidence": ["system_record"]})
    return a


def inputs_for(defn: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {**probe.probe_inputs(AgentDefinitionV1.model_validate(defn), TOOLS), **extra}


class Raising:
    family, model_id, is_mock = "fake", "fake-raising", False

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def complete_json(self, messages: Any, json_schema: Any, timeout_s: float) -> Any:
        self.calls += 1
        raise self.exc


class SafeProbe(probe.ProbeModel):
    """The probe model with a lock around its counters (calls come from several threads)."""

    def __init__(self, answer: Any) -> None:
        super().__init__(answer)
        self._lock = threading.Lock()

    def complete_json(self, messages: Any, json_schema: Any, timeout_s: float) -> Any:
        with self._lock:
            return super().complete_json(messages, json_schema, timeout_s)


# ------------------------------------------------------------------------------ 1. visible errors


def test_a_failed_call_is_named_in_the_rationale_and_the_report_stays_valid(
    agent: dict[str, Any],
) -> None:
    exc = LLMError(
        f"model endpoint https://x.example/v1 returned HTTP 400: bad body {SECRET} user text"
    )
    model = Raising(exc)
    diag: dict[str, Any] = {}
    report = rt.run_agent(agent, inputs_for(agent, diag=diag), model, tools=TOOLS)
    AssessmentReportV1.model_validate(report)
    assert model.calls >= 1
    for f in report["findings"]:
        assert f["verdict"] == "question"
        assert f["rationale"] == "The AI model call failed (HTTP 400). A person decides this item."
    blob = json.dumps(report) + json.dumps(diag)
    assert SECRET not in blob and "bad body" not in blob and "x.example" not in blob
    assert diag["model_calls_failed"] == model.calls == diag["model_calls"]
    assert diag["model_items_failed"] == 2
    assert diag["model_error"] == "LLMError: HTTP 400" and len(diag["model_error"]) <= 120


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (LLMTimeoutError("did not answer within 90 s"), "timeout"),
        (LLMOutputError("no valid JSON after one retry: boom"), "invalid reply"),
        (RuntimeError(f"secret {SECRET}"), "RuntimeError"),
    ],
)
def test_other_failures_get_a_short_reason_without_the_message(
    agent: dict[str, Any], exc: Exception, code: str
) -> None:
    report = rt.run_agent(agent, inputs_for(agent), Raising(exc), tools=TOOLS)
    assert f"({code})" in report["findings"][0]["rationale"]
    assert SECRET not in json.dumps(report)


def test_the_run_goes_on_after_one_failed_call(agent: dict[str, Any]) -> None:
    """The first call fails, the others answer: only the items of the failed group are open."""
    a = three_group_agent(agent)
    inner = SafeProbe(probe.answer_good)
    calls = {"n": 0}
    lock = threading.Lock()

    class Flaky:
        family, model_id, is_mock = "fake", "fake-flaky", False

        def complete_json(self, messages: Any, schema: Any, timeout_s: float) -> Any:
            with lock:
                calls["n"] += 1
                first = calls["n"] == 1
            if first:
                raise LLMError("model endpoint returned HTTP 529: overloaded")
            return inner.complete_json(messages, schema, timeout_s)

    diag: dict[str, Any] = {}
    report = rt.run_agent(a, inputs_for(a, diag=diag), Flaky(), tools=TOOLS, parallel=1)
    by_id = {f["checklist_id"]: f for f in report["findings"]}
    assert "HTTP 529" in by_id["MR-01"]["rationale"] and by_id["MR-01"]["verdict"] == "question"
    assert by_id["MR-03"]["verdict"] == "pass" and by_id["MR-04"]["verdict"] == "pass"
    assert diag["model_calls_failed"] == 1 and diag["model_items_failed"] == 2


def test_no_failure_leaves_the_diag_clean_and_the_report_unchanged(agent: dict[str, Any]) -> None:
    diag: dict[str, Any] = {}
    with_diag = rt.run_agent(
        agent, inputs_for(agent, diag=diag), SafeProbe(probe.answer_good), tools=TOOLS
    )
    without = rt.run_agent(agent, inputs_for(agent), SafeProbe(probe.answer_good), tools=TOOLS)
    assert with_diag == without
    assert diag["model_calls_failed"] == 0 and diag["model_error"] == ""


# ------------------------------------------------------------------------------ 2. parallel calls


def test_parallel_report_equals_the_one_after_another_report(agent: dict[str, Any]) -> None:
    a = three_group_agent(agent)
    one = rt.run_agent(a, inputs_for(a), SafeProbe(probe.answer_good), tools=TOOLS, parallel=1)
    four = rt.run_agent(a, inputs_for(a), SafeProbe(probe.answer_good), tools=TOOLS, parallel=4)
    assert one == four
    assert [f["checklist_id"] for f in four["findings"]] == ["MR-01", "MR-02", "MR-03", "MR-04"]
    assert (
        four["harness_trace"]["loop"]["tokens_used"] == one["harness_trace"]["loop"]["tokens_used"]
    )


def test_parallel_calls_really_overlap(agent: dict[str, Any]) -> None:
    """Two calls wait for each other at a barrier: only a parallel run gets past it."""
    a = three_group_agent(agent)
    barrier = threading.Barrier(2, timeout=3)
    inner = SafeProbe(probe.answer_good)

    class Meet:
        family, model_id, is_mock = "fake", "fake-meet", False

        def complete_json(self, messages: Any, schema: Any, timeout_s: float) -> Any:
            if "findings" in schema.get("properties", {}) and "MR-01" in json.dumps(messages):
                barrier.wait()  # MR-01's group meets another group's call
            elif "findings" in schema.get("properties", {}) and "MR-03" in json.dumps(messages):
                barrier.wait()
            return inner.complete_json(messages, schema, timeout_s)

    diag: dict[str, Any] = {}
    report = rt.run_agent(a, inputs_for(a, diag=diag), Meet(), tools=TOOLS, parallel=3)
    assert diag["model_calls_failed"] == 0
    assert all(f["verdict"] == "pass" for f in report["findings"])
    # one after another, the first call would wait for a partner that never comes
    barrier.reset()
    diag2: dict[str, Any] = {}
    report2 = rt.run_agent(a, inputs_for(a, diag=diag2), Meet(), tools=TOOLS, parallel=1)
    assert diag2["model_calls_failed"] >= 1
    assert "failed" in report2["findings"][0]["rationale"]


def test_parallel_budget_is_never_exceeded(agent: dict[str, Any]) -> None:
    a = three_group_agent(agent)
    model = SafeProbe(probe.answer_good)
    inputs = inputs_for(a, budget={"tokens": 2500, "seconds": 30})
    report = rt.run_agent(a, inputs, model, tools=TOOLS, parallel=4)
    assert model.total_tokens <= 2500
    assert report["harness_trace"]["loop"]["tokens_used"] <= 2500
    assert report["harness_trace"]["loop"]["stopped_by"] == "budget"
    AssessmentReportV1.model_validate(report)


def test_parallel_setting_is_read_from_the_settings_and_bounded() -> None:
    assert rt.parallel_calls({"settings": SimpleNamespace(factory_parallel_calls=4)}) == 4
    assert rt.parallel_calls({"settings": SimpleNamespace(factory_parallel_calls=99)}) == 8
    assert rt.parallel_calls({"settings": SimpleNamespace(factory_parallel_calls=0)}) == 1
    assert rt.parallel_calls({"settings": SimpleNamespace()}) == 1
    assert Settings(_env_file=None).factory_parallel_calls == 1
    assert Settings(_env_file=None, factory_parallel_calls=8).factory_parallel_calls == 8
    for bad in (0, 9):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, factory_parallel_calls=bad)


def test_run_agent_uses_the_setting_when_parallel_is_not_given(agent: dict[str, Any]) -> None:
    a = three_group_agent(agent)
    barrier = threading.Barrier(2, timeout=3)
    inner = SafeProbe(probe.answer_good)

    class Meet:
        family, model_id, is_mock = "fake", "fake-meet", False

        def complete_json(self, messages: Any, schema: Any, timeout_s: float) -> Any:
            text = json.dumps(messages)
            if "findings" in schema.get("properties", {}) and ("MR-01" in text or "MR-03" in text):
                barrier.wait()
            return inner.complete_json(messages, schema, timeout_s)

    settings = SimpleNamespace(factory_parallel_calls=2)
    diag: dict[str, Any] = {}
    rt.run_agent(a, inputs_for(a, settings=settings, diag=diag), Meet(), tools=TOOLS)
    assert diag["model_calls_failed"] == 0


# ------------------------------------------------------------------------------ 3. JSON fields


TAGS = json.dumps(
    {
        "ai_agentic": "1",
        "ai_generative": "1",
        "autonomy_limits": json.dumps(
            {
                "approval_above_vnd": 50000000,
                "daily_total_vnd": 100000000,
                "session_max_minutes": 120,
                "session_max_tool_calls": 100,
            }
        ),
        "kind": "app",
        "note": "x" * 300,
    }
)


def test_a_json_record_field_becomes_sub_sources(agent: dict[str, Any]) -> None:
    defn = AgentDefinitionV1.model_validate(agent)
    inputs = {"system_id": "s1", "system": {"system_id": "s1", "tags": TAGS, "purpose": "p"}}
    refs = {s.ref: s for s in rt.gather(inputs, defn)["system_record"]}
    assert "s1.tags" in refs  # the parent keeps its ref (cut as before)
    assert len(refs["s1.tags"].text) <= rt.FIELD_CHARS + 20
    limits = refs["s1.tags.autonomy_limits"]
    assert "approval_above_vnd" in limits.text and "session_max_tool_calls" in limits.text
    assert refs["s1.tags.ai_agentic"].text == "tags.ai_agentic = 1"
    assert "s1.tags.note" in refs and len(refs["s1.tags.note"].text) > 240
    assert "s1.purpose" in refs


def test_plain_fields_and_empty_values_are_as_before(agent: dict[str, Any]) -> None:
    defn = AgentDefinitionV1.model_validate(agent)
    system = {"system_id": "s1", "a": "text", "b": None, "c": "", "d": [1], "e": 3, "f": "{bad"}
    got = {
        s.ref: s.text
        for s in rt.gather({"system_id": "s1", "system": system}, defn)["system_record"]
    }
    assert got == {
        "s1.a": "a = text",
        "s1.e": "e = 3",
        "s1.f": "f = {bad",
        "s1.system_id": "system_id = s1",
    }


def test_the_evidence_check_accepts_a_sub_source(agent: dict[str, Any]) -> None:
    def answer(user: Any) -> dict[str, Any]:
        out = []
        for it in user["items"]:
            out.append(
                {
                    "checklist_id": it["checklist_id"],
                    "verdict": "pass",
                    "pass_rule_met": True,
                    "confidence": "high",
                    "rationale": "limits are set",
                    "evidence": [
                        {
                            "kind": "system_record",
                            "ref": "s1.tags.autonomy_limits",
                            "quote": "approval_above_vnd",
                        }
                    ],
                }
            )
        return {"findings": out}

    inputs = {
        "system_id": "s1",
        "system": {"system_id": "s1", "tags": TAGS},
        "facts": None,
    }
    report = rt.run_agent(agent, inputs, SafeProbe(answer), tools=TOOLS)
    f = next(f for f in report["findings"] if f["checklist_id"] == "MR-02")
    assert f["verdict"] == "pass" and f["evidence"][0]["ref"] == "s1.tags.autonomy_limits"
    # the cited text is the sub-source, so the review page can show it
    texts = rt.loaded_texts(agent, inputs, report)
    assert "session_max_minutes" in texts["s1.tags.autonomy_limits"]


# ------------------------------------------------------------------------------ 4. draft agents


@pytest.fixture
def env(adapters: Any, sink: Any, tmp_path: Path) -> gate.GateEnv:
    return make_env(adapters, sink, FakeChat(), tmp_path)


def test_drafts_are_off_by_default_and_the_off_path_is_unchanged(env: gate.GateEnv) -> None:
    env.store.create_from_template("model", "mr-agent", "Mine", "reviewer.an")
    for cat in (catalog.FactoryCatalog(env.store), catalog.FactoryCatalog(env.store, False)):
        assert cat.live_agent("model") is None  # a draft is never used
    assert Settings(_env_file=None).orch_run_draft_agents is False
    ctx = SimpleNamespace(
        settings=env.settings, state=env.state, tables=env.tables, clock=env.clock
    )
    assert catalog.for_console(ctx).run_drafts is False  # type: ignore[union-attr]
    p = orch.plan(
        {"system_id": "s"}, "high_self", {}, None, catalog=catalog.FactoryCatalog(env.store)
    )
    assert {i.agent_kind for i in p.items} == {"rule"}


def test_drafts_on_returns_the_newest_draft_marked_as_a_draft(env: gate.GateEnv) -> None:
    from tests.factory.f3_helpers import to_live

    env.store.create_from_template("model", "other-agent", "Other", "reviewer.an")  # draft 0.1
    live = to_live(env)  # mr-agent 0.1 live
    env.store.retire("mr-agent", "0.1", "reviewer.an", "replaced")
    env.store.new_version("mr-agent", live["version"], "reviewer.an")  # mr-agent draft 0.2
    cat = catalog.FactoryCatalog(env.store, run_drafts=True)
    got = cat.live_agent("model")
    assert got is not None and got.kind == "draft"
    assert (got.agent_id, got.version) == ("mr-agent", "0.2-draft")  # the highest version wins
    assert cat.live_agent("cybersecurity") is None  # no draft for that type: rule proposal
    p = orch.plan({"system_id": "s"}, "high_self", {}, None, catalog=cat)
    item = next(i for i in p.items if i.dimension_id == "model")
    assert item.agent_kind == "draft" and item.agent == "mr-agent@0.2-draft"
    assert item.to_dict()["agent_kind"] == "draft"
    assert next(i for i in p.items if i.dimension_id == "ethics").agent_kind == "rule"


def test_a_live_version_wins_over_a_draft(env: gate.GateEnv) -> None:
    from tests.factory.f3_helpers import to_live

    to_live(env)  # mr-agent 0.1 live
    cat = catalog.FactoryCatalog(env.store, run_drafts=True)
    got = cat.live_agent("model")
    assert got is not None and got.kind == "live" and got.version == "0.1"


def test_for_console_reads_the_setting(env: gate.GateEnv) -> None:
    env.settings.orch_run_draft_agents = True
    ctx = SimpleNamespace(
        settings=env.settings, state=env.state, tables=env.tables, clock=env.clock
    )
    cat = catalog.for_console(ctx)
    assert cat is not None and cat.run_drafts is True


# ------------------------------------------------------------------------------ 5. time budget


def test_time_budget_settings_default_to_the_old_constants_and_are_bounded() -> None:
    s = Settings(_env_file=None)
    assert (s.orch_agent_seconds, s.orch_total_seconds) == (120, 900)
    assert orch.settings_budget(s) == orch.Budget()
    b = orch.settings_budget(
        Settings(_env_file=None, orch_agent_seconds=600, orch_total_seconds=3000)
    )
    assert (b.agent_seconds, b.total_seconds, b.rule_seconds) == (600, 3000, orch.RULE_SECONDS)
    for field, bad in (
        ("orch_agent_seconds", 9),
        ("orch_agent_seconds", 3601),
        ("orch_total_seconds", 29),
        ("orch_total_seconds", 14401),
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: bad})


def test_time_budget_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCH_AGENT_SECONDS", "600")
    monkeypatch.setenv("ORCH_TOTAL_SECONDS", "1800")
    monkeypatch.setenv("FACTORY_PARALLEL_CALLS", "4")
    monkeypatch.setenv("ORCH_RUN_DRAFT_AGENTS", "1")
    s = load_settings(_env_file=None)
    assert (s.orch_agent_seconds, s.orch_total_seconds) == (600, 1800)
    assert s.factory_parallel_calls == 4 and s.orch_run_draft_agents is True


# ------------------------------------------------------------------------------ 6. unsourced items


def with_pack_item(agent: dict[str, Any]) -> dict[str, Any]:
    """MR-01, MR-05 (pack), MR-02: the pack item sits between two record items."""
    a = copy.deepcopy(agent)
    a["tools"].append({"tool_id": "read_pack_results", "mode": "read"})
    a["harness"]["context"]["sources"].append("pack_results")
    a["checklist"].insert(
        1,
        {
            "id": "MR-05",
            "question": "Does the pack truthfulqa_vi pass at the current version?",
            "evidence": ["pack"],
            "severity": "high",
            "pass_rule": "Pack truthfulqa_vi passed at the current version of the system.",
        },
    )
    return a


def test_a_pack_item_with_no_pack_result_makes_no_call(agent: dict[str, Any]) -> None:
    a = with_pack_item(agent)
    a["checklist"] = [c for c in a["checklist"] if c["id"] == "MR-05"]
    model = SafeProbe(probe.answer_good)
    diag: dict[str, Any] = {}
    report = rt.run_agent(a, inputs_for(a, packs=[], diag=diag), model, tools=TOOLS)
    AssessmentReportV1.model_validate(report)
    assert model.calls == 0
    (f,) = report["findings"]
    assert (f["verdict"], f["confidence"], f["evidence"]) == ("question", "high", [])
    assert f["rationale"] == (
        "No result for test truthfulqa_vi yet, so this cannot be decided. Run the test."
    )
    tr = report["harness_trace"]
    assert tr["verification"]["findings_checked"] == 1
    assert tr["verification"]["findings_rejected"] == 0
    assert diag["model_calls"] == 0 and diag["model_items_skipped"] == 1


def test_only_sourced_items_of_a_mixed_run_are_sent(agent: dict[str, Any]) -> None:
    a = with_pack_item(agent)
    model = SafeProbe(probe.answer_good)
    report = rt.run_agent(a, inputs_for(a, packs=[]), model, tools=TOOLS)
    assert model.calls == 1  # MR-01 and MR-02 now share one group; MR-05 is not sent
    assert model.seen_items() == {"MR-01", "MR-02"}
    by_id = {f["checklist_id"]: f for f in report["findings"]}
    assert by_id["MR-05"]["verdict"] == "question" and by_id["MR-05"]["confidence"] == "high"
    assert by_id["MR-01"]["verdict"] == "pass" and by_id["MR-02"]["verdict"] == "pass"
    assert report["summary"]["questions"] == 1


def test_a_pack_item_with_a_pack_result_is_sent(agent: dict[str, Any]) -> None:
    a = with_pack_item(agent)
    model = SafeProbe(probe.answer_good)
    rt.run_agent(a, inputs_for(a), model, tools=TOOLS)  # probe inputs hold pack results
    assert "MR-05" in model.seen_items()


def test_unsourced_wording_by_kind_and_parallel_equals_sequential(agent: dict[str, Any]) -> None:
    a = copy.deepcopy(agent)
    a["tools"].append({"tool_id": "search_documents", "mode": "read"})
    a["harness"]["context"]["sources"] = ["system_record", "document_sections"]
    a["checklist"] = [
        {**a["checklist"][0], "id": "MR-07", "evidence": ["document"]},
        {**a["checklist"][1], "id": "MR-02"},
    ]
    one = rt.run_agent(
        a, inputs_for(a, documents=[]), SafeProbe(probe.answer_good), tools=TOOLS, parallel=1
    )
    four = rt.run_agent(
        a, inputs_for(a, documents=[]), SafeProbe(probe.answer_good), tools=TOOLS, parallel=4
    )
    assert one == four
    f = next(f for f in one["findings"] if f["checklist_id"] == "MR-07")
    assert (
        f["rationale"] == "No document was provided for this check. The system owner supplies it."
    )


def test_the_switch_can_turn_the_short_circuit_off(agent: dict[str, Any]) -> None:
    a = with_pack_item(agent)
    a["checklist"] = [c for c in a["checklist"] if c["id"] == "MR-05"]
    model = SafeProbe(probe.answer_good)
    rt.run_agent(
        a,
        inputs_for(
            a, packs=[], settings=SimpleNamespace(llm_base_url="x", factory_skip_unsourced=False)
        ),
        model,
        tools=TOOLS,
    )
    assert model.calls == 1
    assert Settings(_env_file=None).factory_skip_unsourced is True


# ------------------------------------------------------------------------------ 7. re-ask open


def loop_inputs(defn: dict[str, Any], reask: bool | None) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if reask is not None:
        extra["settings"] = SimpleNamespace(llm_base_url="x", factory_reask_open=reask)
    return inputs_for(defn, **extra)


def test_reask_open_defaults_to_the_loop_of_before(loop_agent: dict[str, Any]) -> None:
    assert Settings(_env_file=None).factory_reask_open is True
    a = SafeProbe(probe.answer_question)
    b = SafeProbe(probe.answer_question)
    unset = rt.run_agent(loop_agent, loop_inputs(loop_agent, None), a, tools=TOOLS)
    on = rt.run_agent(loop_agent, loop_inputs(loop_agent, True), b, tools=TOOLS)
    assert unset == on
    assert (
        unset["harness_trace"]["loop"]["iterations"]
        == loop_agent["harness"]["loop"]["max_iterations"]
    )
    assert (
        len(a.users) == len(b.users) > len(set(map(json.dumps, a.users)))
    )  # the same prompts again


def test_reask_open_off_does_not_send_a_question_again(loop_agent: dict[str, Any]) -> None:
    on, off = SafeProbe(probe.answer_question), SafeProbe(probe.answer_question)
    rt.run_agent(loop_agent, loop_inputs(loop_agent, True), on, tools=TOOLS)
    report = rt.run_agent(loop_agent, loop_inputs(loop_agent, False), off, tools=TOOLS)
    AssessmentReportV1.model_validate(report)
    assert len(off.users) < len(on.users)
    assert len(off.users) == len(
        {json.dumps(u, sort_keys=True) for u in on.users}
    )  # first pass only
    assert report["harness_trace"]["loop"]["iterations"] == 1
    assert report["harness_trace"]["loop"]["stopped_by"] == "all_answered"
    assert all(f["verdict"] == "question" for f in report["findings"])


def test_reask_open_off_still_asks_a_rejected_item_again(loop_agent: dict[str, Any]) -> None:
    model = SafeProbe(probe.answer_plant("unloaded"))  # the first item cites a source not loaded
    report = rt.run_agent(loop_agent, loop_inputs(loop_agent, False), model, tools=TOOLS)
    assert report["harness_trace"]["loop"]["iterations"] > 1
    assert any("verifier_feedback" in u for u in model.users)


def test_reask_open_off_still_asks_a_failed_call_again(loop_agent: dict[str, Any]) -> None:
    exc = Raising(LLMError("model endpoint returned HTTP 529"))
    report = rt.run_agent(loop_agent, loop_inputs(loop_agent, False), exc, tools=TOOLS)
    assert report["harness_trace"]["loop"]["iterations"] > 1
    assert exc.calls > 2
