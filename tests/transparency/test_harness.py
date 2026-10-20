"""WP31 harness: golden set, 24 adversarial probes, determinism, regression against the baseline.

Rubrics. Regulator inspector (SBV): the Decision 33 class and obligation ids are cited, every gap
(flag off, no data, mock judge, failed chain check) is stated and nothing is implied, a hash lets
the inspector check the file. Data protection officer: the customer version holds no agent id,
rule id, obligation id, hash or person; personal data in a case title is masked; a name in a
model card does not reach the regulator or customer version."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter

import pytest

from supervisor.transparency import harness as H
from tests.conftest import REPO_ROOT

FIX = REPO_ROOT / "tests" / "fixtures" / "transparency"
SPLITS = ("dev", "held_out")


def _generator():
    spec = importlib.util.spec_from_file_location(
        "transparency_fixture_generate", FIX / "generate.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_golden_set_is_what_the_generator_writes() -> None:
    assert (FIX / "golden.jsonl").read_text(encoding="utf-8") == _generator().render()


def test_golden_set_shape_and_provenance() -> None:
    items = H.load_golden(FIX / "golden.jsonl")
    assert len(items) == 54 and len({i["id"] for i in items}) == 54
    assert Counter(i["split"] for i in items) == {"dev": 36, "held_out": 18}
    assert {i["agent"] for i in items if i["split"] == "held_out"} == {"credit_prequal"}
    for i in items:
        for key in ("id", "source", "licence", "labeller", "rubric", "split", "expected"):
            assert i[key] not in (None, ""), (i["id"], key)
    assert {i["rubric"] for i in items} == {"regulator inspector (SBV)", "data protection officer"}


@pytest.mark.parametrize("split", SPLITS)
def test_golden_split_is_exact(split: str) -> None:
    out = H.run_golden(H.load_golden(FIX / "golden.jsonl"), split)
    assert out["failure_taxonomy"]["misses"] == []
    assert out["accuracy_bp"] == 10000 and out["leaks"] == 0


def test_a_wrong_expectation_is_reported_as_a_miss() -> None:
    items = H.load_golden(FIX / "golden.jsonl")
    bad = json.loads(json.dumps(items[0]))
    bad["expected"]["verify_state"] = "ok"
    bad["expected"]["avail"]["risks"] = False
    out = H.run_golden([bad])
    assert out["accuracy_bp"] == 0
    assert set(out["failure_taxonomy"]["by_kind"]) >= {"availability", "verify_state"}


def test_determinism() -> None:
    assert H.run_determinism()["bp"] == 10000


def test_adversarial_probes_all_pass() -> None:
    out = H.run_adversarial()
    assert out["n"] >= 20 and out["failed"] == [], out["failed"]


def test_cli_help_works(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        H.main(["--help"])
    assert stop.value.code == 0
    assert "transparency" in capsys.readouterr().out.lower()


def test_no_regression_against_the_recorded_baseline() -> None:
    base = json.loads((FIX / "baseline.json").read_text(encoding="utf-8"))["results"]
    now = H.run_all(FIX, SPLITS)
    for s in SPLITS:
        assert now["golden"][s]["accuracy_bp"] >= base["golden"][s]["accuracy_bp"], s
        assert now["golden"][s]["correct"] >= base["golden"][s]["correct"], s
        for v, d in base["golden"][s]["by_variant"].items():
            assert now["golden"][s]["by_variant"][v]["bp"] >= d["bp"], (s, v)
    assert now["adversarial"]["passed"] >= base["adversarial"]["passed"]
    assert now["determinism"]["bp"] >= base["determinism_bp"]
    assert all(v == "GO" for v in now["verdicts"].values())
