"""WP30 harness: golden set shape and provenance, baseline regression, adversarial probes,
starter consistency, determinism (rubrics: compliance officer, internal auditor under Three Lines)."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter

import pytest

from supervisor.controls import harness as H
from supervisor.risk.harness import load_golden
from tests.conftest import REPO_ROOT

FIX = REPO_ROOT / "tests" / "fixtures" / "controls"
SPLITS = ("dev", "held_out")


def _generator():
    spec = importlib.util.spec_from_file_location("controls_fixture_generate", FIX / "generate.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_golden_set_is_what_the_generator_writes() -> None:
    assert (FIX / "golden.jsonl").read_text(encoding="utf-8") == _generator().render()


def test_golden_set_shape_and_provenance() -> None:
    items = load_golden(FIX / "golden.jsonl")
    assert len(items) == 50 and len({i["id"] for i in items}) == 50
    assert Counter(i["split"] for i in items) == {"dev": 30, "held_out": 20}
    assert Counter(i["task"] for i in items) == {
        "status": 12,
        "bp": 8,
        "plan": 12,
        "gate": 10,
        "waive": 8,
    }
    for i in items:
        for key in ("id", "source", "licence", "labeller", "rubric", "split", "task", "expected"):
            assert i[key] not in (None, ""), (i["id"], key)
    assert {i["rubric"] for i in items} == {"compliance officer", "internal auditor (Three Lines)"}
    for split in SPLITS:  # every kind of scenario is in both splits
        assert len({i["task"] for i in items if i["split"] == split}) == 5


@pytest.mark.parametrize("split", SPLITS)
def test_golden_split_is_exact(split: str) -> None:
    out = H.run_golden(load_golden(FIX / "golden.jsonl"), split)
    assert out["failure_taxonomy"]["misses"] == [] and out["accuracy_bp"] == 10000
    lo, hi = out["accuracy_ci_bp"]
    assert lo < 10000 and hi == 10000


def test_golden_run_is_deterministic() -> None:
    items = load_golden(FIX / "golden.jsonl")
    assert H.run_golden(items)["result_hash"] == H.run_golden(items)["result_hash"]


def test_a_wrong_expectation_is_reported_as_a_miss() -> None:
    items = load_golden(FIX / "golden.jsonl")
    bad = json.loads(json.dumps(items[0]))
    bad["expected"] = {"status": "working", "reason": "x"}
    out = H.run_golden([bad])
    assert out["accuracy_bp"] == 0 and out["failure_taxonomy"]["misses"][0]["id"] == bad["id"]


def test_starter_catalogue_is_consistent_with_what_exists_today() -> None:
    out = H.check_starters()
    assert out["problems"] == []
    assert out["controls"] >= 25 and out["risks_covered"] == 19


def test_all_adversarial_probes_pass() -> None:
    out = H.run_adversarial()
    assert out["n"] >= 20 and out["failed"] == []


def test_task_config_hash_matches_the_baseline() -> None:
    base = json.loads((FIX / "baseline.json").read_text(encoding="utf-8"))
    assert base["tasks_config_sha256"] == H.tasks_config_sha256(), (
        "config/tasks.yaml changed: run tests/fixtures/controls/generate.py and "
        "python -m supervisor.controls.harness --write-baseline"
    )


def test_no_regression_against_the_recorded_baseline() -> None:
    base = json.loads((FIX / "baseline.json").read_text(encoding="utf-8"))["results"]
    res = H.run_all(FIX, SPLITS)
    for s in SPLITS:
        assert res["golden"][s]["accuracy_bp"] >= base["golden"][s]["accuracy_bp"]
        assert res["golden"][s]["result_hash"] == base["golden"][s]["result_hash"]
    assert res["adversarial"]["passed"] >= base["adversarial"]["passed"]
    assert res["starters"]["bp"] >= base["starters"]["bp"]
    assert res["starters"]["controls"] >= base["starters"]["controls"]
    assert res["determinism"]["bp"] >= base["determinism_bp"]
    assert all(v == "GO" for v in res["verdicts"].values())


def test_cli_help_works() -> None:
    with pytest.raises(SystemExit) as stop:
        H.main(["--help"])
    assert stop.value.code == 0
