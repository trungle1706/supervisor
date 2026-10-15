"""WP17 framework: loader, registry, engine (thresholds, validation, storage), reports."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.assurance.engine import (
    apply_thresholds,
    metric_verdict,
    run_packs,
)
from supervisor.assurance.gates import assurance_launch_items, assurance_launch_notes
from supervisor.assurance.loader import PackError, load_packs, manifest_sha256
from supervisor.assurance.model import EvalPack, RunContext, RunnerOutput
from supervisor.assurance.registry import RegistryError, resolve_runner, select
from supervisor.assurance.report import render_json, render_markdown, result_line
from supervisor.assurance.results import (
    latest_results,
    load_results_json,
    summary_from_dict,
    summary_from_store,
)
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from tests.assurance.fakes import FakeAgent, FakeJudge, FakeTraces, ctx
from tests.conftest import REPO_ROOT

RUNNER = "supervisor.assurance.runners.fake_demo:FakeRunner"


def manifest(pack_id: str = "demo_acc", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": pack_id,
        "version": 2,
        "dimension": "accuracy",
        "title": "Demo accuracy pack",
        "description": "Test pack. Thresholds are illustrative.",
        "source": {"name": "own", "url": "https://example.invalid/demo"},
        "licence": "own",
        "data_modes": ["synthetic"],
        "targets": ["agent", "traces", "judge"],
        "runner": RUNNER,
        "metrics": [
            {"name": "hit_rate", "direction": "higher_better", "unit": "bp", "description": "hits"},
            {
                "name": "miss_rate",
                "direction": "lower_better",
                "unit": "bp",
                "description": "misses",
            },
            {
                "name": "info_count",
                "direction": "higher_better",
                "unit": "count",
                "description": "n",
            },
        ],
        "thresholds": [
            {"metric": "hit_rate", "go": 8000, "no_go": 6000},
            {"metric": "miss_rate", "go": 1000, "no_go": 3000},
        ],
        "maps_to": {"regkb_duties": ["independent_validation"]},
        "launch_gate": "advisory",
        "judge_gate": False,
        "min_items": 5,
    }
    base.update(over)
    return base


def write_pack(directory: Path, data: Mapping[str, Any], name: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name or data['id']}.yaml"
    path.write_text(
        yaml.safe_dump(dict(data), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


class FnRunner:
    """Runner whose output comes from a callable (a test double, never shipped)."""

    def __init__(self, fn: Callable[[EvalPack, RunContext], RunnerOutput]) -> None:
        self.fn = fn

    def run(self, pack: EvalPack, context: RunContext) -> RunnerOutput:
        return self.fn(pack, context)


def ok_output(**kw: Any) -> RunnerOutput:
    metrics = kw.pop("metrics", {"hit_rate": 9000, "miss_rate": 500, "info_count": 7})
    base = {
        "status": "ok",
        "metrics": metrics,
        "n_items": 20,
        "data_mode": "synthetic",
        "dataset_id": "demo-set",
        "dataset_sha256": "ab" * 32,
        "is_mock": True,
        "details": {"slices": {"vi": 12, "en": 8}},
    }
    base.update(kw)
    return RunnerOutput(**base)


def pack_of(**over: Any) -> EvalPack:
    return EvalPack.model_validate(manifest(**over))


class MemorySink:
    """In-memory EvidenceSink."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        self.entries.append((record_type, record_ref, copy.deepcopy(dict(payload))))
        return f"{len(self.entries):064x}"


def has_float(v: Any) -> bool:
    if isinstance(v, float):
        return True
    if isinstance(v, Mapping):
        return any(has_float(x) for x in v.values())
    if isinstance(v, list | tuple):
        return any(has_float(x) for x in v)
    return False


@pytest.fixture
def store(tmp_path: Path):
    data = tmp_path / "store"
    settings = load_settings(sql_backend="sqlite", data_dir=data, sqlite_path=data / "t.sqlite")
    adapters: Adapters = build_adapters(settings)
    bootstrap_schema.run(settings, adapters)
    yield adapters
    adapters.close()


# --------------------------------------------------------------------------- loader


def test_load_packs_sorted_and_hash(tmp_path: Path) -> None:
    write_pack(tmp_path, manifest("zeta_pack"))
    p = write_pack(tmp_path, manifest("alpha_pack"))
    packs = load_packs(tmp_path)
    assert [x.id for x in packs] == ["alpha_pack", "zeta_pack"]
    assert manifest_sha256(p) == manifest_sha256(p) and len(manifest_sha256(p)) == 64


def test_real_packs_dir_loads_when_present() -> None:
    from supervisor.assurance.loader import PACKS_DIR

    if not list(PACKS_DIR.glob("*.yaml")):
        pytest.skip("no packs committed yet")
    packs = load_packs()
    assert len({p.id for p in packs}) == len(packs)


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d["thresholds"][0].update(go=8000.5), "integers only"),
        (lambda d: d["maps_to"].update(owasp_llm=["LLM99"]), "unknown taxonomy"),
        (
            lambda d: d.update(licence="CC-BY-SA-4.0", data_modes=["synthetic", "vendored_sample"]),
            "never vendored",
        ),
        (lambda d: d.update(data_modes=["bank_supplied_path"], importer="files"), "synthetic"),
        (lambda d: d["thresholds"][0].update(go=5000, no_go=6000), "go >= no_go"),
    ],
)
def test_loader_rejects_bad_manifests(
    tmp_path: Path, mutate: Callable[[dict], None], needle: str
) -> None:
    data = manifest()
    mutate(data)
    write_pack(tmp_path, data)
    with pytest.raises(PackError) as exc:
        load_packs(tmp_path)
    assert needle in str(exc.value)
    assert "demo_acc.yaml" in str(exc.value)


def test_loader_rejects_name_mismatch_and_collects_all(tmp_path: Path) -> None:
    write_pack(tmp_path, manifest("one_pack"), name="other_name")
    bad = manifest("two_pack")
    bad["thresholds"][0]["go"] = 1.5
    write_pack(tmp_path, bad)
    with pytest.raises(PackError) as exc:
        load_packs(tmp_path)
    problems = exc.value.problems
    assert any("other_name.yaml" in p and "file name must equal" in p for p in problems)
    assert any("two_pack.yaml" in p for p in problems)
    assert len(problems) >= 2


def test_loader_rejects_big_missing_and_non_mapping(tmp_path: Path) -> None:
    (tmp_path / "big_pack.yaml").write_text("x: " + "a" * 70_000, encoding="utf-8")
    (tmp_path / "list_pack.yaml").write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(PackError) as exc:
        load_packs(tmp_path)
    text = str(exc.value)
    assert "big_pack.yaml" in text and "limit" in text and "mapping" in text
    with pytest.raises(PackError):
        load_packs(tmp_path / "nope")


# --------------------------------------------------------------------------- registry


def test_select_by_id_dimension_all_and_unknown(tmp_path: Path) -> None:
    write_pack(tmp_path, manifest("acc_one"))
    write_pack(tmp_path, manifest("sec_one", dimension="security", targets=["agent"]))
    packs = load_packs(tmp_path)
    assert [p.id for p in select(packs, "all")] == ["acc_one", "sec_one"]
    assert [p.id for p in select(packs, "security")] == ["sec_one"]
    assert [p.id for p in select(packs, "acc_one")] == ["acc_one"]
    assert [p.id for p in select(packs, "all", "judge")] == ["acc_one"]
    with pytest.raises(RegistryError) as exc:
        select(packs, "nonsense")
    msg = str(exc.value)
    assert "acc_one" in msg and "security" in msg and "all" in msg


def test_resolve_runner_rules() -> None:
    pack = pack_of()
    fake = FnRunner(lambda p, c: ok_output())
    assert resolve_runner(pack, {RUNNER: fake}) is fake
    with pytest.raises(RegistryError):
        resolve_runner(pack, {RUNNER: object()})
    with pytest.raises(RegistryError, match="not found"):
        resolve_runner(pack)  # module does not exist
    evil = pack.model_copy(update={"runner": "os:system"})
    with pytest.raises(RegistryError, match="runners"):
        resolve_runner(evil)


# --------------------------------------------------------------------------- thresholds


@pytest.mark.parametrize(
    "direction,value,expected",
    [
        ("higher_better", 8000, "pass"),
        ("higher_better", 9500, "pass"),
        ("higher_better", 7000, "warn"),
        ("higher_better", 6000, "warn"),
        ("higher_better", 5999, "fail"),
        ("lower_better", 1000, "pass"),
        ("lower_better", 0, "pass"),
        ("lower_better", 2000, "warn"),
        ("lower_better", 3000, "warn"),
        ("lower_better", 3001, "fail"),
        ("higher_better", None, "na"),
    ],
)
def test_metric_verdict_both_directions(direction: str, value: int | None, expected: str) -> None:
    go, no_go = (8000, 6000) if direction == "higher_better" else (1000, 3000)
    assert metric_verdict(direction, value, go, no_go) == expected


def test_pack_status_from_metrics() -> None:
    pack = pack_of()
    assert apply_thresholds(pack, {"hit_rate": 9000, "miss_rate": 500})[2] == "ok"
    ms, reasons, status = apply_thresholds(pack, {"hit_rate": 7000, "miss_rate": 500})
    assert status == "warn" and ms["hit_rate"] == "warn" and "warn band" in reasons[0]
    ms, reasons, status = apply_thresholds(pack, {"hit_rate": 7000, "miss_rate": 4000})
    assert status == "fail" and ms["miss_rate"] == "fail"
    assert ms["info_count"] == "na"  # no threshold: informational
    ms, reasons, status = apply_thresholds(pack, {"hit_rate": 9000, "miss_rate": None})
    assert status == "skip" and ms["miss_rate"] == "na"
    assert reasons == ["metric miss_rate not measured"]
    ms, reasons, status = apply_thresholds(
        pack, {"hit_rate": 9000, "miss_rate": None}, not_applicable={"miss_rate"}
    )
    assert status == "ok" and ms["miss_rate"] == "na" and reasons == []
    # a fail still wins over an unmeasured metric
    assert apply_thresholds(pack, {"hit_rate": 100, "miss_rate": None})[2] == "fail"
    # everything not applicable or missing -> skip, never ok
    _, _, st = apply_thresholds(
        pack, {"hit_rate": None, "miss_rate": None}, not_applicable={"hit_rate", "miss_rate"}
    )
    assert st == "skip"
    assert apply_thresholds(pack, {"hit_rate": None, "miss_rate": None})[2] == "skip"
    assert apply_thresholds(pack, {})[2] == "skip"


def test_pack_without_thresholds_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one threshold"):
        pack_of(thresholds=[])


def test_requires_capabilities_validated() -> None:
    assert pack_of(requires_capabilities=["decide"]).requires_capabilities == ["decide"]
    with pytest.raises(ValueError, match="unknown capabilities"):
        pack_of(requires_capabilities=["telepathy"])


def test_unmeasured_metric_makes_the_pack_skip_in_the_engine() -> None:
    out = ok_output(metrics={"hit_rate": 9000, "miss_rate": None, "info_count": 3})
    _, r = run_one(lambda p, c: out)
    assert r.status == "skip" and r.reasons == ["metric miss_rate not measured"]
    declared = ok_output(
        metrics={"hit_rate": 9000, "miss_rate": None, "info_count": 3},
        not_applicable_metrics={"miss_rate"},
    )
    assert run_one(lambda p, c: declared)[1].status == "ok"


def test_requires_capabilities_gives_structured_not_applicable_skip() -> None:
    pack = pack_of(requires_capabilities=["decide"], launch_gate="required")
    called: list[int] = []

    def fn(p: EvalPack, c: RunContext) -> RunnerOutput:
        called.append(1)
        return ok_output()

    sink = MemorySink()
    no_decide = FakeAgent(capabilities=frozenset({"chat"}))
    s = run_packs([pack], no_decide, ctx(no_decide), overrides={RUNNER: FnRunner(fn)}, sink=sink)
    r = s.results[0]
    assert r.status == "skip" and not called
    assert r.reasons == ["not applicable: target lacks decide"]
    assert r.details["not_applicable"] is True
    assert sink.entries[0][2]["not_applicable"] is True
    assert assurance_launch_items([r], [pack]) == []
    assert len(assurance_launch_notes([r], [pack])) == 1
    with_decide = FakeAgent(capabilities=frozenset({"chat", "decide"}))
    r2 = run_packs([pack], with_decide, ctx(with_decide), overrides={RUNNER: FnRunner(fn)}).results[
        0
    ]
    assert r2.status == "ok" and called
    judge = FakeJudge(
        lambda e: {"score_bp": 0, "label": "ok", "tier": 1}
    )  # the rule is for agent targets only
    r3 = run_packs([pack], judge, ctx(judge), overrides={RUNNER: FnRunner(fn)}).results[0]
    assert r3.status == "ok"


def test_error_payload_carries_only_the_exception_class() -> None:
    def boom(p: EvalPack, c: RunContext) -> RunnerOutput:
        raise ValueError("secret 0912345678 in message")

    sink = MemorySink()
    target = FakeAgent()
    s = run_packs([pack_of()], target, ctx(target), overrides={RUNNER: FnRunner(boom)}, sink=sink)
    assert s.results[0].reasons == ["ValueError: secret 0912345678 in message"]
    payload = sink.entries[0][2]
    assert payload["reasons"] == ["error: ValueError"]
    assert "0912345678" not in json.dumps(payload)


# --------------------------------------------------------------------------- engine


def run_one(fn: Callable[[EvalPack, RunContext], RunnerOutput], **kw: Any):
    pack = pack_of()
    target = FakeAgent()
    summary = run_packs(
        [pack], target, ctx(target), overrides={RUNNER: FnRunner(fn)}, run_id="run-t1", **kw
    )
    return summary, summary.results[0]


def test_engine_ok_warn_fail() -> None:
    _, r = run_one(lambda p, c: ok_output())
    assert r.status == "ok" and r.metric_status["hit_rate"] == "pass" and r.is_mock
    _, r = run_one(lambda p, c: ok_output(metrics={"hit_rate": 7000, "miss_rate": 500}))
    assert r.status == "warn"
    _, r = run_one(lambda p, c: ok_output(metrics={"hit_rate": 9000, "miss_rate": 3500}))
    assert r.status == "fail" and "miss_rate=3500" in r.reasons[0]


def test_engine_skips_packs_for_other_target_kinds() -> None:
    pack = pack_of(targets=["judge"])
    target = FakeAgent()
    s = run_packs(
        [pack], target, ctx(target), overrides={RUNNER: FnRunner(lambda p, c: ok_output())}
    )
    assert s.results == [] and s.counts["ok"] == 0


def test_runner_exception_is_error() -> None:
    def boom(p: EvalPack, c: RunContext) -> RunnerOutput:
        raise ValueError("bad dataset line 3")

    summary, r = run_one(boom)
    assert r.status == "error" and "ValueError: bad dataset line 3" in r.reasons[0]
    assert summary.counts["error"] == 1 and summary.failed


@pytest.mark.parametrize(
    "out,needle",
    [
        (ok_output(metrics={"hit_rate": 0.9, "miss_rate": 1}), "float"),
        (ok_output(metrics={"hit_rate": True, "miss_rate": 1}), "bool"),
        (ok_output(metrics={"hit_rate": 9000, "other": 1}), "not declared"),
        (ok_output(details={"x": 0.5}), "float"),
        (ok_output(details={"x": {1, 2}}), "not JSON-safe"),
        (ok_output(n_items=-1), "n_items"),
        ("not an output", "RunnerOutput"),
    ],
)
def test_invalid_runner_output_is_error(out: Any, needle: str) -> None:
    _, r = run_one(lambda p, c: out)
    assert r.status == "error" and needle in r.reasons[0]


def test_too_few_items_runner_skip_and_all_none() -> None:
    _, r = run_one(lambda p, c: ok_output(n_items=3))
    assert r.status == "skip" and r.reasons == ["too few items: 3 < 5"]
    _, r = run_one(lambda p, c: RunnerOutput.skip("no bank data at /x", is_mock=True))
    assert r.status == "skip" and r.reasons == ["no bank data at /x"]
    assert r.status != "ok"
    _, r = run_one(lambda p, c: ok_output(metrics={"hit_rate": None, "miss_rate": None}))
    assert r.status == "skip" and r.reasons == ["metrics not computable"]


def test_unresolvable_runner_is_error() -> None:
    pack = pack_of()
    target = FakeAgent()
    s = run_packs([pack], target, ctx(target))  # no override and no such module
    assert s.results[0].status == "error"


def test_rows_written_to_tables(store: Adapters) -> None:
    pack = pack_of()
    other = pack_of(id="demo_two", dimension="security", targets=["agent"], launch_gate="required")
    target = FakeAgent(target_id="agent_x")
    runners = {RUNNER: FnRunner(lambda p, c: ok_output())}
    s = run_packs(
        [pack, other],
        target,
        ctx(target),
        overrides=runners,
        tables=store.tables,
        run_id="run-rows",
        selector="all",
    )
    rows = store.tables.query("eval_result", {"run_id": "run-rows"}, order_by=["pack_id"])
    assert [r["pack_id"] for r in rows] == ["demo_acc", "demo_two"]
    r0 = rows[0]
    assert r0["status"] == "ok" and r0["metrics"]["hit_rate"] == 9000
    assert r0["metric_status"]["hit_rate"] == "pass"
    assert r0["thresholds"]["hit_rate"] == {"go": 8000, "no_go": 6000}
    assert r0["is_mock"] is True and r0["judge_gate"] is False and r0["launch_gate"] == "advisory"
    assert r0["details"]["slices"]["vi"] == 12 and r0["dataset_sha256"] == "ab" * 32
    assert rows[1]["launch_gate"] == "required"
    run_rows = store.tables.query("eval_run", {"run_id": "run-rows"})
    assert len(run_rows) == 1
    rr = run_rows[0]
    assert (rr["packs_total"], rr["ok"], rr["fail"], rr["is_mock"]) == (2, 2, 0, True)
    assert rr["selector"] == "all" and rr["target_spec"] == "agent:agent_x"
    assert s.counts["ok"] == 2
    # append-only: the same run id cannot be written twice
    with pytest.raises(Exception, match="exist|UNIQUE|constraint"):
        run_packs(
            [pack], target, ctx(target), overrides=runners, tables=store.tables, run_id="run-rows"
        )


def test_latest_results_newest_per_pack(store: Adapters) -> None:
    pack = pack_of()
    target = FakeAgent(target_id="agent_y")
    clock = FixedClock(datetime(2026, 3, 1, tzinfo=UTC))
    good = FnRunner(lambda p, c: ok_output())
    bad = FnRunner(lambda p, c: ok_output(metrics={"hit_rate": 100, "miss_rate": 9000}))
    run_packs(
        [pack],
        target,
        ctx(target),
        overrides={RUNNER: bad},
        tables=store.tables,
        run_id="r-old",
        clock=clock,
    )
    clock.advance(3600)
    run_packs(
        [pack],
        target,
        ctx(target),
        overrides={RUNNER: good},
        tables=store.tables,
        run_id="r-new",
        clock=clock,
    )
    rows = latest_results(store.tables, "agent", "agent_y")
    assert len(rows) == 1 and rows[0]["run_id"] == "r-new" and rows[0]["status"] == "ok"
    assert latest_results(store.tables, "agent", "agent_y", pack_ids=["nope"]) == []
    assert latest_results(store.tables, "agent", "someone_else") == []


def test_evidence_payload_shape() -> None:
    pack = pack_of()
    target = FakeAgent(target_id="agent_z")
    sink = MemorySink()
    s = run_packs(
        [pack],
        target,
        ctx(target),
        overrides={RUNNER: FnRunner(lambda p, c: ok_output())},
        sink=sink,
        run_id="run-ev",
    )
    assert len(sink.entries) == 1
    rtype, ref, payload = sink.entries[0]
    assert rtype == "assurance_result" and ref == "run-ev:demo_acc:agent_z"
    assert set(payload) == {
        "run_id", "pack_id", "pack_version", "manifest_sha256", "dimension", "target_kind",
        "target_id", "status", "metrics", "metric_status", "thresholds", "n_items", "data_mode",
        "dataset_id", "dataset_sha256", "is_mock", "launch_gate", "judge_gate", "reasons",
        "not_applicable",
    }  # fmt: skip
    assert not has_float(payload)
    assert all(type(v) is int or v is None for v in payload["metrics"].values())
    assert payload["thresholds"] == {
        "hit_rate": {"go": 8000, "no_go": 6000},
        "miss_rate": {"go": 1000, "no_go": 3000},
    }
    assert payload["pack_version"] == 2 and payload["is_mock"] is True
    assert len(payload["manifest_sha256"]) == 64
    assert s.results[0].evidence_hash == f"{1:064x}"
    assert json.dumps(payload)  # JSON-safe


def test_evidence_recorded_for_skip_and_error() -> None:
    pack = pack_of()
    target = FakeAgent()
    sink = MemorySink()
    run_packs(
        [pack],
        target,
        ctx(target),
        overrides={RUNNER: FnRunner(lambda p, c: RunnerOutput.skip("no data"))},
        sink=sink,
    )
    assert sink.entries[0][2]["status"] == "skip" and sink.entries[0][2]["reasons"] == ["no data"]


def test_manifest_hash_uses_file_when_present(tmp_path: Path) -> None:
    path = write_pack(tmp_path, manifest())
    pack = load_packs(tmp_path)[0]
    target = FakeAgent()
    sink = MemorySink()
    run_packs(
        [pack],
        target,
        ctx(target),
        overrides={RUNNER: FnRunner(lambda p, c: ok_output())},
        sink=sink,
        packs_dir=tmp_path,
    )
    assert sink.entries[0][2]["manifest_sha256"] == manifest_sha256(path)


def test_out_dir_files_and_reload(tmp_path: Path, store: Adapters) -> None:
    pack = pack_of()
    target = FakeAgent(target_id="agent_o")
    out = tmp_path / "out"
    s = run_packs(
        [pack],
        target,
        ctx(target),
        overrides={
            RUNNER: FnRunner(lambda p, c: ok_output(metrics={"hit_rate": 7000, "miss_rate": 500}))
        },
        out_dir=out,
        tables=store.tables,
        run_id="run-out",
    )
    assert s.out_dir == str(out)
    data = load_results_json(out)
    assert data["run_id"] == "run-out" and data["counts"]["warn"] == 1
    assert not has_float(data)
    assert data["results"][0]["thresholds"]["hit_rate"]["go"] == 8000
    back = summary_from_dict(data)
    assert (
        back.results[0].status == "warn" and back.thresholds["demo_acc"]["hit_rate"]["go"] == 8000
    )
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Assurance eval report" in md and "MOCK RUN" in md
    assert "Thresholds are illustrative defaults until the bank sets its own." in md
    assert "demo_acc" in md and "hit_rate=7000 (go>=8000)" in md
    again = summary_from_store(store.tables, "run-out")
    assert again.counts["warn"] == 1 and again.results[0].metrics["hit_rate"] == 7000
    assert json.loads(render_json(again))["run_id"] == "run-out"
    assert "run-out" in render_markdown(again)


def test_report_marks_skipped_and_no_mock_banner() -> None:
    pack = pack_of()
    target = FakeAgent()
    s = run_packs(
        [pack],
        target,
        ctx(target),
        overrides={RUNNER: FnRunner(lambda p, c: RunnerOutput.skip("no bank data at /x"))},
    )
    md = render_markdown(s)
    assert "Skipped packs" in md and "no bank data at /x" in md
    line = result_line(s.results[0], s.thresholds)
    assert line.startswith("[SKIP]") and line.isascii()


def test_all_three_target_kinds_run() -> None:
    pack = pack_of()
    runners = {RUNNER: FnRunner(lambda p, c: ok_output(is_mock=False))}
    for target in (
        FakeAgent(),
        FakeTraces(),
        FakeJudge(score_fn=lambda e: {"score_bp": 0, "label": "x", "tier": 1}),
    ):
        s = run_packs([pack], target, ctx(target), overrides=runners)
        assert s.results[0].target_kind == target.kind
        assert s.results[0].is_mock  # target is a mock even when the runner forgot


def test_repo_root_constant() -> None:
    assert (REPO_ROOT / "schema" / "model.yaml").is_file()
