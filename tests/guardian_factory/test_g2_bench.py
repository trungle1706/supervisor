"""WP-G2: packs, generator, runner numbers, gate, transitions, chain record, trace import."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from supervisor.guardian_factory import bench, caps
from supervisor.guardian_factory.bench import Case, Pack
from supervisor.guardian_factory.bench_service import BenchService
from supervisor.guardian_factory.definition import (
    GuardianDefinition,
    GuardianFactoryError,
    validate_definition,
)
from supervisor.guardian_factory.store import GuardianDefStore

from .conftest import FakeChat, ListSink, person, regex_def

AN = person("reviewer.an", "reviewer")  # reviewer in the data group
EM = person("approver.em", "approver")  # not in the data group
VIEWER = person("viewer.hoa", "viewer")


def jl(rows: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"


def att(i: int, text: str, **over: Any) -> dict[str, Any]:
    return {
        "case_id": f"a{i}",
        "stage": "input",
        "text": text,
        "expected": True,
        "label": "x",
        **over,
    }


def ben(i: int, text: str, **over: Any) -> dict[str, Any]:
    return {"case_id": f"b{i}", "stage": "input", "text": text, "expected": False, **over}


def definition(**over: Any) -> GuardianDefinition:
    data = regex_def(**over)
    data["created_by"] = "u"
    return validate_definition(data)


def mkpack(attack: list[str], benign: list[str], stage: str = "input") -> Pack:
    return Pack(
        "p",
        [Case(f"a{i}", stage, True, "x", t) for i, t in enumerate(attack)],
        [Case(f"b{i}", stage, False, "", t) for i, t in enumerate(benign)],
        {"pack_sha256": "f" * 64},
    )


@pytest.fixture
def svc(store: GuardianDefStore, gadapters: Any, sink: ListSink) -> BenchService:
    return BenchService(store, data_dir=gadapters.settings.data_dir, evidence=sink)


# ============================================================ numbers


def test_hand_built_pack_gives_the_expected_integers() -> None:
    # 9 attack cases: 7 hold a 9-14 digit run, 2 do not. 30 benign cases: 1 holds one.
    attack = [f"so tai khoan {190312345000 + i}" for i in range(7)] + ["a 12345", "b 99"]
    benign = [f"don hang so {i}" for i in range(29)] + ["ma 1234567890"]
    res = bench.run_benchmark(definition(), mkpack(attack, benign), live="").to_dict()
    row = next(x for x in res["levels"] if x["sensitivity"] == 2)
    assert (row["tp"], row["fn"], row["fp"], row["tn"]) == (7, 2, 1, 29)
    assert row["tpr_pct"] == 77  # 77.7 rounded down
    assert row["fpr_pct"] == 4  # 3.3 rounded up
    assert res["counts"] == {"attack": 9, "benign": 30, "other_stage": 0}
    assert [x["sensitivity"] for x in res["levels"]] == [1, 2, 3, 4]
    assert res["live"] is None


def test_every_number_of_a_result_is_an_integer_and_no_text() -> None:
    res = bench.run_benchmark(definition(), mkpack(["tai khoan 190312345678"], ["xin chao"]))
    text = json.dumps(res.to_dict())

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        else:
            assert not isinstance(v, float), v

    walk(res.to_dict())
    assert "190312345678" not in text and "xin chao" not in text


def test_latency_is_integer_microseconds_from_the_timer() -> None:
    ticks = iter(range(0, 10**9, 7_500))  # 7,500 ns per timer call -> 7 us per case
    res = bench.run_benchmark(
        definition(), mkpack(["tai khoan 190312345678"], ["xin chao"]), timer=lambda: next(ticks)
    ).to_dict()
    for lv in res["levels"]:
        assert lv["p50_us"] == 7 and lv["p95_us"] == 7 and type(lv["p95_us"]) is int
    assert bench.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
    assert bench.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50) == 5
    assert bench.percentile([], 95) == 0


def test_real_latency_is_measured_and_small_for_a_regex() -> None:
    res = bench.run_benchmark(definition(), mkpack(["tai khoan 190312345678"], ["xin chao"]))
    for lv in res.to_dict()["levels"]:
        assert 0 <= lv["p50_us"] <= lv["p95_us"] < 50_000


def test_live_detector_row_is_present_and_follows_the_stage() -> None:
    # tool_call stage: dlp_vn sees a phone number; the guardian regex looks for the same thing
    d = definition(
        stage="tool_call",
        action_on_fail="log",
        config={"pattern": r"(?<!\d)(?:\+84|0)[35789]\d{8}(?!\d)"},
    )
    pack = Pack(
        "p",
        [Case("a1", "tool_call", True, "", "goi 0912345678 de xac nhan")],
        [Case("b1", "tool_call", False, "", "xin chao ban")],
        {"pack_sha256": "f" * 64},
    )
    res = bench.run_benchmark(d, pack).to_dict()
    assert res["live"]["slug"] == "dlp_vn"
    assert (res["live"]["tp"], res["live"]["fp"]) == (1, 0) and res["live"]["tpr_pct"] == 100
    assert bench.default_live(definition()) == "injection_regex"  # input stage
    assert bench.default_live(definition(compare_with="dlp_vn")) == "dlp_vn"
    assert bench.default_live(definition(compare_with="none")) == ""
    # a detector object is accepted too
    res = bench.run_benchmark(d, pack, live=bench.live_detector("injection_regex")).to_dict()
    assert res["live"]["slug"] == "injection_regex" and res["live"]["tp"] == 0


def test_compare_with_is_validated() -> None:
    with pytest.raises(GuardianFactoryError) as e:
        definition(compare_with="guard_model")
    assert "compare_with" in str(e.value)


def test_pack_without_cases_of_the_stage_is_refused() -> None:
    with pytest.raises(GuardianFactoryError) as e:
        bench.run_benchmark(definition(), mkpack(["x"], ["y"], stage="output"))
    assert e.value.code == "pack_empty"


# ============================================================ gate


def test_gate_names_the_failing_threshold() -> None:
    attack = [f"so tai khoan {190312345000 + i}" for i in range(7)] + ["a 12345", "b 99"]
    benign = [f"don hang so {i}" for i in range(29)] + ["ma 1234567890"]
    res = bench.run_benchmark(definition(), mkpack(attack, benign), live="")
    assert res.gate == "fail" and res.failing == ["min_tpr_pct"]  # 77 < 90, FPR 4 <= 5
    assert res.to_dict()["gate"]["checked"] == {
        "tpr_pct": 77,
        "fpr_pct": 4,
        "p95_us": res.to_dict()["gate"]["checked"]["p95_us"],
    }
    d = definition(thresholds={"min_tpr_pct": 70, "max_fpr_pct": 3, "max_p95_ms": 50})
    res = bench.run_benchmark(d, mkpack(attack, benign), live="")
    assert res.gate == "fail" and res.failing == ["max_fpr_pct"]
    d = definition(thresholds={"min_tpr_pct": 70, "max_fpr_pct": 5, "max_p95_ms": 50})
    assert bench.run_benchmark(d, mkpack(attack, benign), live="").gate == "pass"


def test_gate_p95_threshold_uses_microseconds() -> None:
    ticks = iter(range(0, 10**12, 5_000_000))  # 5,000 us per case
    d = definition(thresholds={"min_tpr_pct": 0, "max_fpr_pct": 100, "max_p95_ms": 1})
    res = bench.run_benchmark(d, mkpack(["x"], ["y"]), timer=lambda: next(ticks), live="")
    assert res.gate == "fail" and res.failing == ["max_p95_ms"]


def test_gate_is_read_at_the_chosen_sensitivity_only() -> None:
    res = bench.run_benchmark(definition(), mkpack(["tai khoan 190312345678"], ["x"]), (1, 3))
    assert res.gate == "not_run" and res.to_dict()["gate"]["verdict"] == "not_run"
    with pytest.raises(GuardianFactoryError):
        bench.run_benchmark(definition(), mkpack(["x"], ["y"]), (5,))


def test_model_types_are_advisory_with_a_cost() -> None:
    cfg = {
        "prompt": "Is it a threat?",
        "verdict_labels": ["ok", "threat"],
        "fail_labels": ["threat"],
    }
    d = definition(type="judge_prompt", action_on_fail="log", config=cfg)
    chat = FakeChat({"label": "threat", "score_bp": 9000})
    res = bench.run_benchmark(
        d, mkpack(["pay or else"], ["hello there"]), (2,), chat=chat
    ).to_dict()
    row = res["levels"][0]
    assert res["advisory"] is True and row["cost_tokens"] > 0 and type(row["cost_tokens"]) is int
    assert (row["tp"], row["fp"]) == (1, 1)  # a judge that says threat to all
    assert res["gate"]["verdict"] == "fail" and "max_fpr_pct" in res["gate"]["failing"]
    # no model: every case is a gap, never a pass
    res = bench.run_benchmark(d, mkpack(["a"], ["b"]), (2,)).to_dict()
    assert res["levels"][0]["not_executed"] == 2 and res["gate"]["failing"][0] == "not_executed"
    assert (
        bench.run_benchmark(definition(), mkpack(["x"], ["y"]), (2,)).to_dict()["levels"][0][
            "cost_tokens"
        ]
        == 0
    )


# ============================================================ packs


def test_upload_limits_and_masker_refusal(svc: BenchService, store: GuardianDefStore) -> None:
    store.create(regex_def(), AN)
    ok = svc.upload(
        "account-numbers", "p1", jl([att(1, "ma ZX12345")]), jl([ben(1, "xin chao")]), AN
    )
    assert ok["attack"] == 1 and ok["benign"] == 1 and len(ok["pack_sha256"]) == 64
    # personal data (a phone number, a person's name with title) refuses the whole file
    for text in ("goi 0912345678 ngay", "khach hang Nguyen Van An ngụ tại 12 Le Loi"):
        with pytest.raises(GuardianFactoryError) as e:
            svc.upload("account-numbers", "p2", None, jl([ben(1, "fine"), ben(2, text)]), AN)
        assert e.value.code == "pack_invalid" and "personal data" in str(e.value)
    assert [p["id"] for p in svc.list_packs("account-numbers")] == ["p1"]  # nothing stored
    bad = [
        ("{nope", "not valid JSON"),
        (json.dumps({**att(1, "x"), "extra": 1}), "unknown key"),
        (json.dumps(att(1, "x", stage="middle")), "stage"),
        (json.dumps(att(1, "x", expected=False)), "expected"),
        (json.dumps({**att(1, "x"), "arguments": {"a": 1}}), "text or arguments"),
        (json.dumps({k: v for k, v in att(1, "x").items() if k != "text"}), "text or arguments"),
        (json.dumps(att(1, "x" * (caps.BENCH_TEXT_MAX + 1))), "longer than"),
        (json.dumps(att(1, "x", meta={"colour": "red"})), "meta"),
        (json.dumps(att(1, "x", case_id="bad id!")), "case_id"),
        (jl([att(1, "x"), att(1, "y")]), "twice"),
    ]
    for line, why in bad:
        with pytest.raises(GuardianFactoryError) as e:
            svc.upload("account-numbers", "p3", line, None, AN)
        assert e.value.code == "pack_invalid" and why in str(e.value), (line, str(e.value))
    many = jl([att(i, "x") for i in range(caps.BENCH_MAX_CASES + 1)])
    with pytest.raises(GuardianFactoryError) as e:
        svc.upload("account-numbers", "p3", many, None, AN)
    assert e.value.code == "pack_too_large"
    big = ("x" * 1000 + "\n") * 5_100
    with pytest.raises(GuardianFactoryError) as e:
        svc.upload("account-numbers", "p3", big, None, AN)
    assert e.value.code == "pack_too_large"
    with pytest.raises(GuardianFactoryError):
        svc.upload("account-numbers", "BAD ID", jl([att(1, "x")]), None, AN)
    with pytest.raises(GuardianFactoryError):
        svc.upload("account-numbers", "p3", None, None, AN)


def test_upload_keeps_the_other_file_and_bumps_the_version(
    svc: BenchService, store: GuardianDefStore
) -> None:
    store.create(regex_def(), AN)
    svc.upload("account-numbers", "p1", jl([att(1, "a")]), jl([ben(1, "b")]), AN)
    out = svc.upload("account-numbers", "p1", jl([att(1, "a"), att(2, "c")]), None, AN)
    assert (out["version"], out["attack"], out["benign"]) == (2, 2, 1)
    arguments = {
        "case_id": "a9",
        "stage": "input",
        "arguments": {"note": "ma ZX12345"},
        "expected": True,
    }
    svc.upload("account-numbers", "p1", jl([arguments]), None, AN)
    pack = bench.load_pack(svc.data_dir, "account-numbers", "p1")
    assert pack.attack[0].payload()["args"] == {"note": "ma ZX12345"}
    assert pack.meta["files"]["attack.jsonl"]["sha256"] and pack.sha256


def test_pack_on_disk_is_checked_against_its_sha(
    svc: BenchService, store: GuardianDefStore
) -> None:
    store.create(regex_def(), AN)
    svc.upload("account-numbers", "p1", jl([att(1, "a")]), jl([ben(1, "b")]), AN)
    f = bench.pack_root(svc.data_dir, "account-numbers") / "p1" / "attack.jsonl"
    f.write_text(f.read_text("utf-8") + "\n" + json.dumps(att(2, "tampered")), "utf-8")
    with pytest.raises(GuardianFactoryError) as e:
        bench.load_pack(svc.data_dir, "account-numbers", "p1")
    assert e.value.code == "pack_changed"
    with pytest.raises(GuardianFactoryError) as e:
        bench.load_pack(svc.data_dir, "account-numbers", "missing")
    assert e.value.code == "no_pack"


def test_pack_rights_group_and_state(svc: BenchService, store: GuardianDefStore) -> None:
    from supervisor.cases.service import PermissionDenied

    store.create(regex_def(), AN)
    for who in (VIEWER, EM):
        with pytest.raises(PermissionDenied):
            svc.generate("account-numbers", "p1", who)
    store.retire("account-numbers", AN)
    with pytest.raises(GuardianFactoryError) as e:
        svc.generate("account-numbers", "p1", AN)
    assert e.value.code == "not_draft"


# ============================================================ generator


def test_generator_pack_for_the_library_regex_is_valid_and_measured(
    svc: BenchService, store: GuardianDefStore
) -> None:
    store.create(regex_def(), AN)  # the account_number pattern of the library
    out = svc.generate("account-numbers", "starter", AN)
    assert out["attack"] == 100 and out["benign"] == 140 and out["version"] == 1
    pack = bench.load_pack(svc.data_dir, "account-numbers", "starter")
    assert pack.meta["origin"] == "generated"
    res = bench.run_benchmark(definition(), pack, live="").to_dict()
    row = next(x for x in res["levels"] if x["sensitivity"] == 2)
    assert row["tpr_pct"] >= 90 and row["fpr_pct"] <= 5
    assert (row["tp"], row["fn"], row["fp"], row["tn"]) == (100, 0, 0, 140)
    assert res["gate"]["verdict"] == "pass"


@pytest.mark.parametrize("entry", [e.id for e in bench.LIBRARY])
def test_generator_every_library_pattern(entry: str) -> None:
    lib = next(e for e in bench.LIBRARY if e.id == entry)
    d = definition(
        id=entry.replace("_", "-"), config={"pattern": lib.pattern}, action_on_fail="log"
    )
    attack, benign = bench.generate_cases(d)
    res = bench.run_benchmark(
        d, Pack("g", attack, benign, {"pack_sha256": "0" * 64}), (2,), live=""
    )
    row = res.to_dict()["levels"][0]
    assert row["tpr_pct"] >= 90, (entry, row)
    assert row["fpr_pct"] <= 5, (entry, row)
    assert len({c.text for c in attack}) > 90  # varied, not 100 copies


def test_generator_keyword_list_and_unsupported(svc: BenchService, store: GuardianDefStore) -> None:
    kw = regex_def(
        id="kw",
        type="keyword_list",
        config={"words": ["khẩn cấp", "chuyển gấp"]},
        action_on_fail="log",
    )
    store.create(kw, AN)
    svc.generate("kw", "starter", AN)
    d = definition(
        id="kw",
        type="keyword_list",
        config={"words": ["khẩn cấp", "chuyển gấp"]},
        action_on_fail="log",
    )
    res = bench.run_benchmark(
        d, bench.load_pack(svc.data_dir, "kw", "starter"), (2,), live=""
    ).to_dict()
    assert res["levels"][0]["tpr_pct"] == 100 and res["levels"][0]["fpr_pct"] == 0
    store.create(regex_def(id="custom", config={"pattern": r"ZX\d{4}"}), AN)
    with pytest.raises(GuardianFactoryError) as e:
        svc.generate("custom", "starter", AN)
    assert e.value.code == "generator_unsupported"
    pol = regex_def(
        id="pol",
        type="policy",
        action_on_fail="block",
        stage="tool_call",
        config={
            "rules": [
                {"id": "r", "when": [{"kind": "tool", "op": "eq", "value": "x"}], "then": "forbid"}
            ],
            "default": "permit",
        },
    )
    store.create(pol, AN)
    with pytest.raises(GuardianFactoryError):
        svc.generate("pol", "starter", AN)


# ============================================================ traces


def test_import_benign_from_stored_traces(
    svc: BenchService, store: GuardianDefStore, gadapters: Any
) -> None:
    store.create(regex_def(scope={"agents": ["payments"], "tools": "*", "data_classes": []}), AN)
    with pytest.raises(GuardianFactoryError) as e:
        svc.import_traces("account-numbers", "traces", AN)
    assert e.value.code == "no_traces"
    t0 = datetime(2026, 10, 1, tzinfo=UTC)

    def ev(i: int, agent: str, args: str, etype: str = "gate_decision") -> dict[str, Any]:
        return {
            "event_id": f"e{i:05d}",
            "ts": t0,
            "trace_id": f"t{i}",
            "span_id": f"s{i}",
            "agent_id": agent,
            "event_type": etype,
            "tool_name": "lookup",
            "args_masked": args,
            "env": "test",
            "source": "proxy",
            "capture_level": "masked",
        }

    rows = [ev(i, "payments", f"balance enquiry number {i}") for i in range(30)]
    rows += [
        ev(100, "other", "ignored agent"),
        ev(101, "payments", "goi 0912345678 gap"),
        ev(102, "payments", ""),
    ]
    gadapters.tables.append("agent_event", rows)
    out = svc.import_traces("account-numbers", "traces", AN, limit=10)
    assert out["benign"] == 10 and out["attack"] == 0 and out["origin"] == "traces"
    assert out["dropped_masker"] <= 1
    pack = bench.load_pack(svc.data_dir, "account-numbers", "traces")
    assert all(c.meta["agent_id"] == "payments" and not c.expected for c in pack.benign)
    assert not any("0912345678" in c.flat_text() for c in pack.benign)
    full = svc.import_traces("account-numbers", "traces", AN)
    assert full["benign"] >= 30 and full["benign"] <= caps.BENCH_TRACE_SAMPLE_MAX
    with pytest.raises(GuardianFactoryError):
        svc.import_traces("account-numbers", "traces", AN, limit=0)
    # the attack set of an existing pack is kept
    svc.upload("account-numbers", "traces", jl([att(1, "ma ZX12345")]), None, AN)
    again = svc.import_traces("account-numbers", "traces", AN, limit=5)
    assert again["attack"] == 1 and again["benign"] == 5


# ============================================================ runs, states, chain


def test_run_pass_mark_benchmarked_and_change_resets(
    svc: BenchService, store: GuardianDefStore, sink: ListSink
) -> None:
    store.create(regex_def(benchmark_pack="starter"), AN)
    with pytest.raises(GuardianFactoryError) as e:  # no run yet
        store.mark_benchmarked("account-numbers", AN)
    assert e.value.code == "no_passing_run"
    svc.generate("account-numbers", "starter", AN)
    run = svc.start_run("account-numbers", AN, background=False)
    assert run["status"] == "done" and run["gate"] == "pass" and run["failing_threshold"] == ""
    assert run["result"]["levels"][1]["sensitivity"] == 2
    got = svc.get_run("account-numbers", run["run_id"])
    assert got["pack_sha256"] == run["pack_sha256"] and len(got["def_sha256"]) == 64
    out = store.mark_benchmarked("account-numbers", AN)
    assert out["state"] == "benchmarked"
    # same content: stays benchmarked (a save of the same definition is not a change)
    same = store.save("account-numbers", regex_def(benchmark_pack="starter"), AN)
    assert same["state"] == "benchmarked"
    # any other change: back to draft; a pass of the old sha does not count
    changed = store.save("account-numbers", regex_def(benchmark_pack="starter", name="Renamed"), AN)
    assert changed["state"] == "draft"
    with pytest.raises(GuardianFactoryError) as e:
        store.mark_benchmarked("account-numbers", AN)
    assert e.value.code == "no_passing_run" and "changed" in str(e.value)
    events = [
        r["action"] for r in store.tables.query("guardian_def_event", {"def_id": "account-numbers"})
    ]
    assert (
        "reset_to_draft" in events and "benchmarked" in events and "bench_pack_generate" in events
    )
    # run again on the new definition and mark again
    svc.start_run("account-numbers", AN, background=False)
    assert store.mark_benchmarked("account-numbers", AN)["state"] == "benchmarked"
    # benchmarked -> shadow is WP-G3
    with pytest.raises(GuardianFactoryError) as e:
        store._move("account-numbers", "shadow", "x", AN)
    assert e.value.code == "transition_not_yet_allowed"
    # chain: one guardian_bench record per finished run, integers and ids only
    recs = sink.of("guardian_bench")
    assert len(recs) == 2
    r = recs[0]
    assert r["gate"] == "pass" and r["attack_n"] == 100 and r["benign_n"] == 140
    assert all(not isinstance(v, float) for v in r.values())
    assert set(r) >= {
        "run_id",
        "def_id",
        "version",
        "pack_id",
        "pack_sha256",
        "def_sha256",
        "tp",
        "fn",
        "fp",
        "tn",
        "tpr_pct",
        "fpr_pct",
        "p95_us",
    }
    assert "190312345678" not in json.dumps(r)


def test_failing_run_cannot_be_marked_and_names_the_threshold(
    svc: BenchService, store: GuardianDefStore
) -> None:
    store.create(regex_def(benchmark_pack="weak", config={"pattern": r"ZX\d{4,8}"}), AN)
    attack = [att(i, f"ma ZX{12345 + i}") for i in range(3)] + [att(9, "no digits here")]
    svc.upload("account-numbers", "weak", jl(attack), jl([ben(1, "xin chao")]), AN)
    run = svc.start_run("account-numbers", AN, background=False)
    assert run["gate"] == "fail" and run["failing_threshold"] == "min_tpr_pct"  # 75 < 90
    with pytest.raises(GuardianFactoryError) as e:
        store.mark_benchmarked("account-numbers", AN)
    assert e.value.code == "no_passing_run" and "min_tpr_pct" in str(e.value)


def test_only_the_newest_run_counts_and_the_pack_must_match(
    svc: BenchService, store: GuardianDefStore
) -> None:
    store.create(regex_def(benchmark_pack="starter"), AN)
    svc.generate("account-numbers", "starter", AN)
    svc.upload("account-numbers", "weak", jl([att(1, "no digits")]), jl([ben(1, "x")]), AN)
    svc.start_run("account-numbers", AN, background=False)  # passes
    bad = svc.start_run("account-numbers", AN, "weak", background=False)  # newer, fails
    assert bad["gate"] == "fail"
    with pytest.raises(GuardianFactoryError):
        store.mark_benchmarked("account-numbers", AN)
    svc.generate("account-numbers", "other", AN)
    svc.start_run("account-numbers", AN, "other", background=False)  # passes, wrong pack
    with pytest.raises(GuardianFactoryError) as e:
        store.mark_benchmarked("account-numbers", AN)
    assert "another pack" in str(e.value)
    svc.start_run("account-numbers", AN, background=False)
    assert store.mark_benchmarked("account-numbers", AN)["state"] == "benchmarked"


def test_run_errors_and_background_thread(svc: BenchService, store: GuardianDefStore) -> None:
    store.create(regex_def(), AN)
    with pytest.raises(GuardianFactoryError) as e:  # no benchmark_pack and no pack id
        svc.start_run("account-numbers", AN)
    assert e.value.code == "invalid_pack_id"
    with pytest.raises(GuardianFactoryError) as e:
        svc.start_run("account-numbers", AN, "ghost")
    assert e.value.code == "no_pack"
    svc.generate("account-numbers", "starter", AN)
    queued = svc.start_run("account-numbers", AN, "starter")  # a thread
    assert queued["status"] in ("queued", "running", "done")
    svc.join("account-numbers")
    assert svc.get_run("account-numbers", queued["run_id"])["status"] == "done"
    # a pack with no case of the stage: the run row is failed with the message, not a 500
    svc.upload(
        "account-numbers",
        "wrong",
        jl([att(1, "x", stage="output")]),
        jl([ben(1, "y", stage="output")]),
        AN,
    )
    failed = svc.start_run("account-numbers", AN, "wrong", background=False)
    assert (
        failed["status"] == "failed"
        and failed["gate"] == "not_run"
        and "pack_empty" in failed["result"]["error"]
    )
    from supervisor.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        svc.get_run("account-numbers", "gbr_missing")
    assert len(svc.list_runs("account-numbers")) == 2


def test_stale_running_row_is_closed(svc: BenchService, store: GuardianDefStore) -> None:
    store.create(regex_def(benchmark_pack="starter"), AN)
    svc.generate("account-numbers", "starter", AN)
    store.state.insert(
        bench.RUNS,
        {
            "run_id": "gbr_stale",
            "def_id": "account-numbers",
            "version": 1,
            "pack_id": "starter",
            "pack_sha256": "a" * 64,
            "def_sha256": "b" * 64,
            "status": "running",
            "started_at": datetime(2026, 10, 1, tzinfo=UTC),
            "finished_at": None,
            "result_json": "{}",
            "gate": "not_run",
            "failing_threshold": None,
            "created_by": "x",
        },
    )
    run = svc.start_run("account-numbers", AN, background=False)
    assert run["status"] == "done"
    assert svc.get_run("account-numbers", "gbr_stale")["status"] == "failed"


def test_draft_state_only_marks_and_retired_cannot_run(
    svc: BenchService, store: GuardianDefStore
) -> None:
    store.create(regex_def(benchmark_pack="starter"), AN)
    svc.generate("account-numbers", "starter", AN)
    svc.start_run("account-numbers", AN, background=False)
    store.mark_benchmarked("account-numbers", AN)
    with pytest.raises(GuardianFactoryError) as e:  # benchmarked -> benchmarked
        store.mark_benchmarked("account-numbers", AN)
    assert e.value.code == "bad_transition"
    assert store.retire("account-numbers", AN)["state"] == "retired"
    with pytest.raises(GuardianFactoryError):
        svc.start_run("account-numbers", AN, background=False)
