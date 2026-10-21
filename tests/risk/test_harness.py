"""WP29 harness: the golden set, the starter consistency check, 20 adversarial probes, determinism
and a regression check against the recorded baseline (tests/fixtures/risk/baseline.json).

Rubrics. Operational risk manager: the score and band are right, an agent is as risky as the
worst risk it reaches, retired and draft things stay out. Internal auditor (Three Lines): a
lowered residual score is backed by working evidence with a recorded reason, a broken control
raises it again, and every link points at something that exists."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter

import pytest

from supervisor.risk import harness as H
from tests.conftest import REPO_ROOT

FIX = REPO_ROOT / "tests" / "fixtures" / "risk"
SPLITS = ("dev", "held_out")


def _generator():
    spec = importlib.util.spec_from_file_location("risk_fixture_generate", FIX / "generate.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_golden_set_is_what_the_generator_writes() -> None:
    assert (FIX / "golden.jsonl").read_text(encoding="utf-8") == _generator().render()


def test_golden_set_shape_and_provenance() -> None:
    items = H.load_golden(FIX / "golden.jsonl")
    assert len(items) == 50 and len({i["id"] for i in items}) == 50
    assert Counter(i["split"] for i in items) == {"dev": 30, "held_out": 20}
    assert Counter(i["task"] for i in items) == {
        "score": 20,
        "inherit": 12,
        "evidence": 12,
        "link": 6,
    }
    for i in items:
        for key in ("id", "source", "licence", "labeller", "rubric", "split", "task", "expected"):
            assert i[key] not in (None, ""), (i["id"], key)
    assert {i["rubric"] for i in items} == {
        "operational risk manager",
        "internal auditor (Three Lines)",
    }
    assert "synthetic" in (FIX / "README.md").read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("split", SPLITS)
def test_golden_split_is_exact(split: str) -> None:
    out = H.run_golden(H.load_golden(FIX / "golden.jsonl"), split)
    assert out["failure_taxonomy"]["misses"] == []
    assert out["accuracy_bp"] == 10000
    lo, hi = out["accuracy_ci_bp"]
    assert lo < 10000 and hi == 10000  # Wilson interval of a perfect small sample


def test_golden_run_is_deterministic() -> None:
    items = H.load_golden(FIX / "golden.jsonl")
    assert H.run_golden(items)["result_hash"] == H.run_golden(items)["result_hash"]


def test_a_wrong_expectation_is_reported_as_a_miss() -> None:
    items = H.load_golden(FIX / "golden.jsonl")
    bad = json.loads(json.dumps(items[0]))
    bad["expected"] = {"score": 99, "band": "low"}
    out = H.run_golden([bad])
    assert out["accuracy_bp"] == 0 and out["failure_taxonomy"]["misses"][0]["id"] == bad["id"]


def test_starter_risks_link_only_to_ids_that_exist_today() -> None:
    out = H.check_starters()
    assert out["problems"] == []
    assert out["risks"] == 19 and out["links"] > 60


def test_starter_profiles_cover_the_three_agents_and_a_shared_component() -> None:
    import yaml

    by_file = {
        p.stem: yaml.safe_load(p.read_text(encoding="utf-8"))["risks"]
        for p in (REPO_ROOT / "config" / "risks").glob("*.yaml")
    }
    assert set(by_file) == {"payments", "credit_prequal", "customer_service", "shared"}
    for name in ("payments", "credit_prequal", "customer_service"):
        assert len(by_file[name]) >= 5 and {r["agent"] for r in by_file[name]} == {name}
    assert all("node" in r for r in by_file["shared"])
    for risks in by_file.values():
        for r in risks:
            assert r["links"].get("matrix"), r["id"]  # every risk names a matrix row
            assert any(r["links"].get(k) for k in ("rule", "pack", "monitor")), r["id"]
            assert r["treatment"] == "mitigate" and r["status"] == "active"


def test_adversarial_probes_all_pass() -> None:
    out = H.run_adversarial()
    assert out["n"] == 20 and out["failed"] == [], out["failed"]
    assert out["bp"] == 10000


def test_cli_help_works(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        H.main(["--help"])
    assert stop.value.code == 0
    assert "risk" in capsys.readouterr().out.lower()


def test_no_regression_against_the_recorded_baseline() -> None:
    base = json.loads((FIX / "baseline.json").read_text(encoding="utf-8"))["results"]
    now = H.run_all(FIX, SPLITS)
    for s in SPLITS:
        assert now["golden"][s]["accuracy_bp"] >= base["golden"][s]["accuracy_bp"], s
        assert now["golden"][s]["correct"] >= base["golden"][s]["correct"], s
        assert now["golden"][s]["result_hash"] == base["golden"][s]["result_hash"], s
        for task, v in base["golden"][s]["by_task"].items():
            assert now["golden"][s]["by_task"][task]["bp"] >= v["bp"], (s, task)
    assert now["adversarial"]["passed"] >= base["adversarial"]["passed"]
    assert now["determinism"]["bp"] >= base["determinism_bp"]
    assert now["starters"]["risks"] >= base["starters"]["risks"]
    assert now["starters"]["problems"] == []
    assert all(v == "GO" for v in now["verdicts"].values())
