"""WP-F3: the three layers of the gate: each layer-1 check with a failing fixture, the harness
component tests, the judge layer (kappa, confusion matrix, regression, tier floor), preflight
refusals, the background job and the signed report."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

import pytest

from supervisor.evidence import verify as ev
from supervisor.factory import caps, gate, golden, probe, registry
from supervisor.factory import runtime as rt
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from tests.factory.f3_helpers import (
    FakeChat,
    create_agent,
    golden_cases,
    load_golden,
    make_env,
    to_live,
    to_tested,
)

TOOLS = registry.load_tools()


@pytest.fixture
def env(adapters: Any, sink: Any, tmp_path: Path) -> gate.GateEnv:
    return make_env(adapters, sink, FakeChat(), tmp_path)


def good_report(agent: dict[str, Any]) -> dict[str, Any]:
    defn = AgentDefinitionV1.model_validate(agent)
    inputs = probe.probe_inputs(defn, TOOLS)
    return rt.run_agent(agent, inputs, probe.ProbeModel(probe.answer_good), tools=TOOLS)


def problems(agent: dict[str, Any], report: dict[str, Any]) -> dict[str, list[str]]:
    return gate.check_report(AgentDefinitionV1.model_validate(agent), report, TOOLS)


# ------------------------------------------------------------------------------ kappa


def test_kappa_two_by_two_hand_computed() -> None:
    # n=50, agree=35, rows [25,25], cols [30,20]: S=1250, kappa=(1750-1250)/(2500-1250)=0.40
    assert gate.cohen_kappa_hundredths([[20, 5], [10, 15]]) == 40


def test_kappa_four_by_four_rounds_half_up() -> None:
    m = [[10, 2, 0, 0], [1, 8, 1, 0], [0, 1, 9, 0], [0, 0, 0, 5]]
    # n=37, agree=32, S=12*11+10*11+10*10+5*5=367 -> 81700/1002 = 81.54 -> 82
    assert gate.cohen_kappa_hundredths(m) == 82


def test_kappa_edges() -> None:
    assert gate.cohen_kappa_hundredths([[10, 0], [0, 10]]) == 100
    assert gate.cohen_kappa_hundredths([[0, 10], [10, 0]]) == -100
    assert gate.cohen_kappa_hundredths([[0, 0], [0, 0]]) == 0
    assert gate.cohen_kappa_hundredths([[7, 0], [0, 0]]) == 100  # one category, perfect
    assert gate.cohen_kappa_hundredths([[0, 0], [0, 7]]) == 100
    # high raw agreement, near-zero kappa: the anti-pattern the calibration exists for
    skew = [[90, 5], [5, 0]]
    assert 100 * 90 // 100 == 90 and gate.cohen_kappa_hundredths(skew) <= 0


def test_kappa_is_an_integer_and_the_matrix_is_ordered_by_verdict() -> None:
    cm = gate.confusion([("pass", "pass"), ("pass", "question"), ("fail", "fail")])
    assert cm["labels"] == list(caps.VERDICTS)
    assert cm["matrix"][0][0] == 1 and cm["matrix"][0][3] == 1 and cm["matrix"][1][1] == 1
    assert isinstance(gate.cohen_kappa_hundredths(cm["matrix"]), int)


# ------------------------------------------------------------------------------ layer 1 checks


def test_a_good_report_passes_every_case_check(agent: dict[str, Any]) -> None:
    assert not any(problems(agent, good_report(agent)).values())


def test_check_schema_valid(agent: dict[str, Any]) -> None:
    r = good_report(agent)
    r["findings"][0]["verdict"] = "maybe"
    assert problems(agent, r)["schema_valid"]
    r2 = good_report(agent)
    r2["agent_id"] = "other-agent"
    assert problems(agent, r2)["schema_valid"]
    r3 = good_report(agent)
    r3["findings"] = r3["findings"][:1]
    r3["summary"] = {"total": 1, "passed": 1, "failed": 0, "not_applicable": 0, "questions": 0}
    assert any("cover the checklist" in p for p in problems(agent, r3)["schema_valid"])


def test_check_evidence_exists(agent: dict[str, Any]) -> None:
    r = good_report(agent)
    r["findings"][0]["evidence"] = [{"kind": "system_record", "ref": "never.loaded"}]
    assert any("was not loaded" in p for p in problems(agent, r)["evidence_exists"])
    r2 = good_report(agent)
    r2["findings"][0]["evidence"][0]["kind"] = "pack"  # allowed by the schema, not by this agent
    agent2 = copy.deepcopy(agent)
    agent2["evidence_rules"]["allowed_sources"] = ["fact", "system_record", "regkb", "document"]
    agent2["checklist"][0]["evidence"] = ["system_record", "document"]
    assert any("not allowed" in p for p in problems(agent2, r2)["evidence_exists"])


def test_check_tools_in_scope(agent: dict[str, Any]) -> None:
    for t in agent["tools"]:
        if t["tool_id"] == "read_facts":
            t["mode"] = "propose"  # the registry offers read only
    assert any("mode propose" in p for p in problems(agent, _valid(agent))["tools_in_scope"])
    r = _valid(agent)
    r["harness_trace"]["hitl"]["tool_calls_blocked"] = 2
    assert any("need a tool" in p for p in problems(agent, r)["tools_in_scope"])


def _valid(agent: dict[str, Any]) -> dict[str, Any]:
    clean_agent = copy.deepcopy(agent)
    for t in clean_agent["tools"]:
        t["mode"] = "read"
    clean_agent["harness"]["hitl"]["permissions"] = []
    return good_report(clean_agent)


def test_check_no_personal_data(agent: dict[str, Any]) -> None:
    r = good_report(agent)
    r["findings"][0]["rationale"] = "Lien he 0912345678 de hoi them."
    assert problems(agent, r)["no_personal_data"]


def test_check_token_budget(agent: dict[str, Any]) -> None:
    r = good_report(agent)
    r["harness_trace"]["context"]["tokens_used"] = agent["harness"]["context"]["budget_tokens"] + 1
    assert problems(agent, r)["token_budget"]
    r2 = good_report(agent)
    r2["harness_trace"]["loop"]["tokens_used"] = caps.LOOP_BUDGET_DEFAULT + 1
    assert any("loop budget" in p for p in problems(agent, r2)["token_budget"])


def test_layer1_needs_one_hundred_percent(agent: dict[str, Any]) -> None:
    defn = AgentDefinitionV1.model_validate(agent)
    ok_case = {"case_id": "a", "problems": {}}
    bad_case = {"case_id": "b", "problems": {"no_personal_data": ["x"]}}
    comps = [{"id": "c1", "kind": "component", "ok": True, "detail": ""}]
    good = gate.layer1(defn, [ok_case], comps, TOOLS)
    assert good["ok"] and good["percent"] == 100
    bad = gate.layer1(defn, [ok_case, bad_case], comps, TOOLS)
    assert not bad["ok"] and bad["percent"] < 100
    failed = next(c for c in bad["checks"] if c["id"] == "no_personal_data")
    assert failed["cases_failed"] == 1 and failed["failed_case_ids"] == ["b"]
    comps[0]["ok"] = False
    assert not gate.layer1(defn, [ok_case], comps, TOOLS)["ok"]


def test_component_tests_all_pass_on_the_fixture_agents(
    agent: dict[str, Any], loop_agent: dict[str, Any]
) -> None:
    for d in (agent, loop_agent):
        out = probe.run_component_tests(d, TOOLS)
        assert [c["id"] for c in out] == [i for i, _ in probe.TESTS]
        assert all(c["ok"] for c in out), out


@pytest.mark.parametrize(
    ("patch", "failing"),
    [
        ("verify", "verifier_catches_planted"),
        ("stops", "stop_points_fire"),
        ("budget", "budget_never_exceeded"),
        ("retention", "memory_rows_masked"),
        ("loop", "loop_stops_at_cap"),
        ("cited", "cited_sources_loaded"),
    ],
)
def test_a_broken_harness_component_fails_its_test(
    patch: str, failing: str, loop_agent: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    if patch == "verify":
        monkeypatch.setattr(
            rt,
            "verify_finding",
            lambda run, item, raw, loaded: {
                "verdict": raw.get("verdict", "question"),
                "evidence": [],
                "confidence": "high",
                "rationale": "accepted without a check",
                "rejected": [],
            },
        )
    elif patch == "stops":
        monkeypatch.setattr(rt, "_apply_stops", lambda run: None)
    elif patch == "budget":

        def unchecked(run: Any, group: Any, items: Any) -> None:
            saved, run.budget = run.budget, 10**7  # the prompt is built without the budget
            messages, _ = run.build_prompt(group, items, {})
            run.budget = saved
            run.model.complete_json(messages, rt.RESPONSE_SCHEMA, 5)
            for it in items:
                run.results[it.id] = rt._reject(it, ["unchecked"])

        monkeypatch.setattr(rt, "_ask_group", unchecked)
    elif patch == "retention":
        monkeypatch.setattr(rt.FileMemory, "prune", lambda self, rows, now: [dict(r) for r in rows])
    elif patch == "loop":
        real_run = rt.run_agent

        def endless(*a: Any, **k: Any) -> dict[str, Any]:
            rep = real_run(*a, **k)
            rep["harness_trace"]["loop"]["iterations"] = 99
            return rep

        monkeypatch.setattr(rt, "run_agent", endless)
    else:
        real_run = rt.run_agent

        def phantom(*a: Any, **k: Any) -> dict[str, Any]:
            rep = real_run(*a, **k)
            for f in rep["findings"]:
                for e in f["evidence"]:
                    e["ref"] = "never-loaded"
            return rep

        monkeypatch.setattr(rt, "run_agent", phantom)
    out = {c["id"]: c for c in probe.run_component_tests(loop_agent, TOOLS)}
    assert not out[failing]["ok"], out[failing]


# ------------------------------------------------------------------------------ layer 2


def test_calibration_below_the_floor_fails_the_gate(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    env.chat.label_verdict = "fail"  # the judge disagrees with every human label
    run = gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    cal = run["layer2"]["calibration"]
    assert cal["kappa_hundredths"] <= 0 and not cal["ok"] and cal["reason"] == "kappa_below_floor"
    assert run["verdict"] == "fail" and env.store.get("mr-agent", "0.1")["state"] == "draft"
    assert run["layer1"]["ok"]  # layer 1 passed; layer 2 failed it


def test_calibration_needs_enough_labels(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row, labels=caps.CALIBRATION_MIN_LABELS - 1)
    run = gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    cal = run["layer2"]["calibration"]
    assert cal["reason"] == "calibration_too_small" and run["verdict"] == "fail"
    assert cal["labels_used"] == caps.CALIBRATION_MIN_LABELS - 1


def test_calibration_reports_kappa_in_hundredths_with_the_matrix(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    # make the judge call "question" for the last 6 of 24 labelled findings
    state = {"n": 0}
    real = env.chat.complete_json

    def flaky(messages: Any, schema: Any, t: float) -> Any:
        if "verdict" in schema.get("properties", {}) and "findings" not in schema["properties"]:
            state["n"] += 1
            if state["n"] > 18:
                return {"verdict": "question", "reason": "unsure"}
        return real(messages, schema, t)

    env.chat.complete_json = flaky  # type: ignore[method-assign]
    run = gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    cal = run["layer2"]["calibration"]
    assert cal["labels_used"] == 24 and cal["agree"] == 18
    assert cal["confusion"]["matrix"][0][0] == 18 and cal["confusion"]["matrix"][0][3] == 6
    assert cal["kappa_hundredths"] == 0  # all humans said pass: expected agreement = 0.75
    assert isinstance(cal["kappa_hundredths"], int)


def test_tier_floor_blocks_a_weak_agent(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    weak = {c["case_id"] for c in golden_cases(row["definition"])[:8]}  # 16 percent wrong

    def answer(user: Any) -> dict:
        if user["system_id"].removeprefix("case-") in {w.replace("c0", "c0") for w in weak}:
            return probe.answer_question(user)
        return probe.answer_good(user)

    env.chat.agent_answer = answer  # type: ignore[attr-defined]
    run = gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    l2 = run["layer2"]
    assert l2["tier"] == "high" and l2["tier_floor_percent"] == 90
    assert l2["match_percent"] == 84 and not l2["tier_floor_ok"]
    assert run["verdict"] == "fail"


def test_judge_errors_count_as_no_and_are_reported(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    env.chat.fail_judge = True  # type: ignore[attr-defined]
    run = gate.start(env, "mr-agent", "0.1", "sample", "x", n=5, background=False)
    assert run["layer2"]["judge_errors"] == 5 and run["layer2"]["match_percent"] == 0
    assert run["verdict"] == "fail"


def test_the_gate_verdict_is_deterministic_not_the_judge_alone(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    env.chat.judge_answer = "yes"  # type: ignore[attr-defined]
    env.chat.agent_answer = probe.answer_question  # type: ignore[attr-defined]
    run = gate.start(env, "mr-agent", "0.1", "sample", "x", n=10, background=False)
    # the judge says yes to everything, the exact comparison does not: both are reported
    assert run["layer2"]["match_percent"] == 100
    assert run["layer2"]["exact_verdict_matches"] < 10


def test_regression_against_the_live_version(env: gate.GateEnv) -> None:
    to_live(env)
    live_run = [r for r in gate.latest_runs(env, "mr-agent") if r["kind"] == "full"][0]
    row = env.store.new_version("mr-agent", "0.1", "reviewer.an")
    d = copy.deepcopy(row["definition"])
    d["instructions"] += " MR-01 MR-02 MR-03 MR-04 MR-05 MR-06 reworded."
    env.store.save_draft("mr-agent", "0.2", d, "reviewer.an", row["row_version"])
    cases = golden_cases(d)

    def degrade(n: int) -> Any:
        ids = {c["case_id"] for c in cases[:n]}
        return lambda user: (
            probe.answer_question(user)
            if any(f"case-{i}" == user["system_id"] for i in ids)
            else probe.answer_good(user)
        )

    # lose exactly max_regression_cases cases: still passes the regression rule
    env.chat.agent_answer = degrade(caps.MAX_REGRESSION_CASES)  # type: ignore[attr-defined]
    run = gate.start(env, "mr-agent", "0.2", "full", "x", background=False)
    reg = run["layer2"]["regression"]
    assert reg["baseline"] == "live" and reg["baseline_run_id"] == live_run["run_id"]
    assert (
        reg["lost"] == caps.MAX_REGRESSION_CASES and reg["ok"] and reg["max_regression_cases"] == 2
    )
    # one more lost case: fails
    env.chat.agent_answer = degrade(caps.MAX_REGRESSION_CASES + 1)  # type: ignore[attr-defined]
    run2 = gate.start(env, "mr-agent", "0.2", "full", "x", background=False)
    assert run2["layer2"]["regression"]["lost"] == 3 and not run2["layer2"]["regression"]["ok"]
    assert run2["verdict"] == "fail"
    assert len(run2["layer2"]["regression"]["lost_case_ids"]) == 3


def test_regression_recomputes_when_the_golden_set_changed(env: gate.GateEnv) -> None:
    to_live(env)
    extra = golden_cases(env.store.get("mr-agent", "0.1")["definition"], 52)[50:]
    ok, bad = golden.check_gate_cases(extra, ["MR-01", "MR-02", "MR-03", "MR-04", "MR-05", "MR-06"])
    assert not bad
    golden.store_gate_cases(env.data_dir, "mr-agent", ok)
    row = env.store.new_version("mr-agent", "0.1", "reviewer.an")
    d = copy.deepcopy(row["definition"])
    d["instructions"] += " MR-01 MR-02 MR-03 MR-04 MR-05 MR-06 reworded."
    env.store.save_draft("mr-agent", "0.2", d, "reviewer.an", row["row_version"])
    run = gate.start(env, "mr-agent", "0.2", "full", "x", background=False)
    assert run["layer2"]["regression"]["baseline_run_id"] == "recomputed"
    assert run["layer2"]["regression"]["cases"] == 52


# ------------------------------------------------------------------------------ refusals


def test_preflight_refusals(env: gate.GateEnv) -> None:
    row = create_agent(env)
    cases = golden_cases(row["definition"], 10)
    ok, _ = golden.check_gate_cases(cases, [c["id"] for c in row["definition"]["checklist"]])
    with pytest.raises(gate.GateError) as e0:
        gate.start(env, "mr-agent", "0.1", "sample", "x", background=False)
    assert e0.value.code == "no_cases"
    golden.store_gate_cases(env.data_dir, "mr-agent", ok)
    with pytest.raises(gate.GateError) as e1:
        gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    assert e1.value.code == "golden_not_ready" and "too_few_cases" in str(e1.value)
    with pytest.raises(gate.GateError) as e2:
        gate.start(env, "mr-agent", "0.1", "sample", "x", n=26, background=False)
    assert e2.value.code == "bad_size"
    with pytest.raises(gate.GateError) as e3:
        gate.start(env, "mr-agent", "0.1", "nonsense", "x", background=False)
    assert e3.value.code == "bad_kind"
    with pytest.raises(gate.GateError) as e4:
        gate.start(env, "nope", "0.1", "full", "x", background=False)
    assert e4.value.code == "not_found"
    with pytest.raises(gate.GateError) as e5:
        gate.start(env, "mr-agent", "0.1", "simulation", "x", systems=[], background=False)
    assert e5.value.code == "bad_systems"
    with pytest.raises(gate.GateError) as e6:
        gate.start(env, "mr-agent", "0.1", "simulation", "x", systems=["a"], background=False)
    assert e6.value.code == "no_inventory"
    with pytest.raises(gate.GateError) as e7:
        gate.start(env, "mr-agent", "0.1", "shadow", "x", n=26, background=False)
    assert e7.value.code == "bad_size"
    assert env.state.query("gate_run") == []  # nothing is written before every check passed


def test_model_not_configured_when_there_is_no_gateway(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    env.chat = None
    env.settings.llm_base_url = ""
    with pytest.raises(gate.GateError) as exc:
        gate.start(env, "mr-agent", "0.1", "sample", "x", background=False)
    assert exc.value.code == "model_not_configured"
    assert env.state.query("gate_run") == []


def test_flag_off_refuses_and_reads_no_gate_table(
    env: gate.GateEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_agent(env)
    env.settings.agent_factory_gate = False
    seen: list[str] = []
    real = env.state.query
    monkeypatch.setattr(
        env.state, "query", lambda t, *a, **k: (seen.append(t), real(t, *a, **k))[1]
    )
    with pytest.raises(gate.GateError) as exc:
        gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    assert exc.value.code == "factory_gate_off" and "gate_run" not in seen
    assert not gate.enabled(env.settings)


def test_a_retired_or_tested_version_cannot_run_a_sample(env: gate.GateEnv) -> None:
    to_tested(env)
    with pytest.raises(gate.GateError) as exc:
        gate.start(env, "mr-agent", "0.1", "sample", "x", background=False)
    assert exc.value.code == "bad_state"


# ------------------------------------------------------------------------------ the job


def test_a_run_is_a_background_job_with_a_status_row(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    release = threading.Event()
    entered = threading.Event()
    real = env.chat.complete_json

    def slow(messages: Any, schema: Any, t: float) -> Any:
        entered.set()
        release.wait(10)
        return real(messages, schema, t)

    env.chat.complete_json = slow  # type: ignore[method-assign]
    run = gate.start(env, "mr-agent", "0.1", "sample", "reviewer.an", n=3)
    assert run["status"] in ("queued", "running") and run["verdict"] == "not_run"
    assert entered.wait(10)
    assert gate.get_run(env, run["run_id"])["status"] == "running"
    with pytest.raises(gate.GateError) as exc:  # one run at a time per agent
        gate.start(env, "mr-agent", "0.1", "sample", "reviewer.an", n=3)
    assert exc.value.code == "run_in_progress"
    release.set()
    gate.join("mr-agent")
    done = gate.get_run(env, run["run_id"])
    assert done["status"] == "done" and done["verdict"] == "pass" and done["finished_at"]


def test_a_broken_run_leaves_a_failed_row(
    env: gate.GateEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = create_agent(env)
    load_golden(env, row)
    monkeypatch.setattr(gate, "run_cases", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    run = gate.start(env, "mr-agent", "0.1", "sample", "x", n=3, background=False)
    assert run["status"] == "failed" and run["verdict"] == "not_run"
    assert run["layer1"]["error"].startswith("run_broke_RuntimeError")
    # the lock is released: the next run starts
    monkeypatch.undo()
    assert (
        gate.start(env, "mr-agent", "0.1", "sample", "x", n=3, background=False)["status"] == "done"
    )


# ------------------------------------------------------------------------------ the report


def test_the_report_is_signed_json_with_integers_only(env: gate.GateEnv, sink: Any) -> None:
    row = create_agent(env)
    load_golden(env, row)
    run = gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    path = gate.gate_dir(env.data_dir, "mr-agent", run["run_id"]) / "report.json"
    assert ev.verify_signed_doc(path).failures == 0
    import json

    doc = json.loads(path.read_text())
    assert (
        doc["format"] == caps.GATE_REPORT_FORMAT and doc["content_sha256"] == run["report_sha256"]
    )
    assert doc["layer2"]["calibration"]["kappa_hundredths"] == 100
    assert doc["thresholds"]["kappa_floor"] == 70 and doc["thresholds"]["max_regression_cases"] == 2
    assert not _floats(doc) and "Vietnamese synthetic" not in json.dumps(doc)
    # a changed report no longer verifies
    doc["verdict"] = "fail"
    path.write_text(json.dumps(doc))
    assert ev.verify_signed_doc(path).failures > 0
    rec = sink.of("factory_gate_run")[0]
    assert rec["kind"] == "full" and rec["kappa_hundredths"] == 100 and not _floats(rec)


def _floats(v: Any) -> bool:
    if isinstance(v, float):
        return True
    if isinstance(v, dict):
        return any(_floats(x) for x in v.values())
    if isinstance(v, list):
        return any(_floats(x) for x in v)
    return False


def test_sample_is_stratified_and_never_calibrates(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    picked = gate.pick_sample(golden.all_gate_cases(env.data_dir, "mr-agent"), 6)
    items = sorted(next(iter(c["expected"])) for c in picked)
    assert items == ["MR-01", "MR-02", "MR-03", "MR-04", "MR-05", "MR-06"]
    run = gate.start(env, "mr-agent", "0.1", "sample", "x", background=False)
    assert run["cost"]["cases"] == caps.SAMPLE_DEFAULT == 10
    assert run["layer2"]["regression"] == {"status": "skipped"}
    assert env.store.get("mr-agent", "0.1")["state"] == "draft"
    assert run["layer3"] == {}
