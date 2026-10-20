"""WP25: golden set, harness run and regression against the recorded baseline."""

from __future__ import annotations

import json
from collections import Counter
from functools import cache
from typing import Any

import pytest

from supervisor.detectors import harness
from supervisor.detectors.injection_classifier import golden as G
from supervisor.detectors.injection_classifier import validation as V


@cache
def _report() -> dict[str, Any]:
    return harness.run(["injection_classifier"], commit="test", date="test")


def test_golden_files_are_intact_and_current() -> None:
    assert G.verify_files() == []


def test_golden_set_sizes_provenance_and_disjoint_templates() -> None:
    man = G.manifest()
    assert man["licence"] == "synthetic, this repo"
    sets = {sp: G.load(sp) for sp in ("train", "dev", "heldout", "evasion", "adversarial")}
    for sp in ("dev", "heldout"):
        c = Counter((x["surface"], x["label"]) for x in sets[sp])
        for surface in ("args", "tool_results", "tool_description"):
            assert c[(surface, 1)] >= 100, (sp, surface)
    adv = sets["adversarial"]
    assert sum(x["label"] for x in adv) >= 30 and len(adv) >= 50
    for sp, items in sets.items():
        for x in items:
            assert x["id"] and x["source"] and x["licence"] == "synthetic, this repo"
            assert x["labeller"] in {
                "synthetic",
                "synthetic, LLM-paraphrased",
                "human (hand-written probe)",
            }
            assert x["split"] == sp
    # no template is shared between splits (template ids are pool-local strings of one pool;
    # the TEXT of a template must not appear in two pools)
    import importlib.util

    spec = importlib.util.spec_from_file_location("tpl", G.DATA_DIR / "templates.py")
    assert spec and spec.loader
    tpl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tpl)
    texts: dict[str, set[str]] = {}
    for pool, d in tpl.POOLS.items():
        texts[pool] = {t for sec in d.values() for lst in sec.values() for t in lst if len(t) > 20}
    assert not texts["train"] & texts["dev"] and not texts["train"] & texts["heldout"]
    assert not texts["dev"] & texts["heldout"]
    # train data never contains a held-out item text
    held = {x["payload"]["args"].get("memo") for x in sets["heldout"]}
    assert not held & {x["payload"]["args"].get("memo") for x in sets["train"]} - {None}


def test_item_ids_are_unique() -> None:
    ids = [
        x["id"] for sp in ("train", "dev", "heldout", "evasion", "adversarial") for x in G.load(sp)
    ]
    assert len(ids) == len(set(ids))


def test_report_has_the_mrm_sections_and_integer_metrics() -> None:
    d = _report()["detectors"]["injection_classifier"]
    assert d["model"]["weights_verified"] is True and d["model"]["network_calls"] == 0
    mrm = d["mrm"]
    assert set(mrm["per_code"]["heldout"]) == {
        "injection.direct_injection",
        "injection.indirect_injection",
        "injection.tool_poisoning",
    }
    assert "typo" in mrm["evasion"]["kinds"] and len(mrm["evasion"]["kinds"]) == 16
    assert mrm["determinism"]["mismatches"] == 0
    assert mrm["adversarial"]["n_pos"] >= 30

    def no_float(v: Any) -> None:
        assert not isinstance(v, float)
        if isinstance(v, dict):
            for x in v.values():
                no_float(x)
        elif isinstance(v, list):
            for x in v:
                no_float(x)

    no_float(d)
    for g in d["go_no_go"].values():
        assert g["verdict"] in {"GO", "NO-GO", "NO-DATA", "MOCK", "REAL"}


def test_no_raw_sensitive_string_leaks_and_fragments_are_exact() -> None:
    d = _report()["detectors"]["injection_classifier"]
    for sp, s in d["splits"].items():
        assert s["leak_items"] == 0, sp
        if s["fragment_exact_bp"] is not None:
            assert s["fragment_exact_bp"] >= 9000, sp


def test_threshold_checks_stay_declared_before_the_run() -> None:
    th = harness.THRESHOLDS["injection_classifier"]
    assert th["recall_bp"] == 8500 and th["p95_us"] == 2000
    assert V.THRESHOLDS["false_alarm_bp_max"] == 500


def test_no_drop_below_the_recorded_baseline() -> None:
    problems = V.compare_baseline(_report()["detectors"]["injection_classifier"])
    assert problems == [], problems


def test_baseline_file_has_date_and_commit() -> None:
    b = json.loads(V.BASELINE.read_text(encoding="utf-8"))
    assert b["date"] and b["commit"] and b["weights_sha256"]


def test_the_classifier_beats_the_regex_on_typos_and_overall_evasions() -> None:
    ev = _report()["detectors"]["injection_classifier"]["mrm"]["evasion"]
    assert ev["kinds"]["typo"]["classifier_recall_bp"] > ev["kinds"]["typo"]["regex_recall_bp"]
    assert ev["all"]["classifier_recall_bp"] > ev["all"]["regex_recall_bp"]


def test_cli_help_and_catalogue(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        harness.main(["--help"])
    assert "--detector" in capsys.readouterr().out
    assert harness.main(["--catalogue"]) == 0
    assert "injection_classifier" in capsys.readouterr().out
