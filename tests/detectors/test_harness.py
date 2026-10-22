"""WP37 harness (team brief section 3): golden set shape, determinism, regression gate."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from supervisor.detectors import golden
from supervisor.detectors import harness as H

SLUGS = ("dlp_vn", "injection_regex", "judge_advisory")
FIELDS = (
    "id",
    "split",
    "detector",
    "direction",
    "payload",
    "meta",
    "label",
    "expect_codes",
    "sensitive",
    "category",
    "lang",
    "source",
    "licence",
    "labeller",
    "tags",
)


@lru_cache(maxsize=1)
def _report() -> dict[str, Any]:
    return H.run(list(SLUGS))  # WP25: the classifier has its own tests


def _texts(item: dict[str, Any]) -> str:
    return json.dumps(item["payload"], ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------- golden set


@pytest.mark.parametrize("slug", SLUGS)
def test_each_detector_has_at_least_50_items_per_split_with_both_labels(slug: str) -> None:
    for split in ("dev", "heldout"):
        items = golden.load(slug, split)
        assert len(items) >= 50, (slug, split)
        assert {i["label"] for i in items} == {0, 1}
        assert sum(i["label"] for i in items) >= 25


def test_items_have_provenance_and_unique_ids() -> None:
    items = golden.load()
    assert len({i["id"] for i in items}) == len(items)
    for i in items:
        assert set(FIELDS) <= set(i), i["id"]
        assert i["labeller"] in ("synthetic", "expert rubric", "human")
        assert i["licence"] and i["source"] and i["direction"] in ("input", "output")
        assert i["split"] in ("dev", "heldout", "adversarial")
        assert i["detector"] in SLUGS


def test_there_are_at_least_20_adversarial_probes_outside_the_templates() -> None:
    probes = golden.load(split="adversarial")
    assert len(probes) >= 20
    assert {p["detector"] for p in probes} == set(SLUGS)
    template_text = " ".join(_texts(i) for i in golden.load() if i["split"] != "adversarial")
    for p in probes:
        assert p["labeller"] == "expert rubric" and "probe" in p["tags"]
        value = json.dumps(p["payload"], ensure_ascii=False)
        # a probe is not a copy of a template item
        assert value not in template_text, p["id"]
    kinds = {p["category"] for p in probes}
    for needed in (
        "typo",
        "telex",
        "no-diacritics",
        "mixed-language",
        "split-across-fields",
        "base64",
    ):
        assert needed in kinds, needed
    assert any(p["label"] == 0 for p in probes)  # benign look-alikes are in


@pytest.mark.parametrize("slug", ["injection_regex", "judge_advisory"])
def test_dev_and_heldout_templates_do_not_overlap(slug: str) -> None:
    dev = {_texts(i) for i in golden.load(slug, "dev")}
    held = {_texts(i) for i in golden.load(slug, "heldout")}
    assert not dev & held


def test_manifest_hashes_match_the_files() -> None:
    manifest = json.loads((golden.DATA_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["licence"].startswith("own")
    for name, meta in manifest["files"].items():
        data = (golden.DATA_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], name
        assert len(data.decode("utf-8").splitlines()) == meta["n_items"]


def test_generator_is_deterministic(tmp_path: Path) -> None:
    out = tmp_path / "again"
    golden.write_all(out)
    for f in sorted(out.iterdir()):
        assert f.read_bytes() == (golden.DATA_DIR / f.name).read_bytes(), f.name


def test_golden_text_is_synthetic_not_real_ids() -> None:
    blob = " ".join(_texts(i) for i in golden.load())
    assert "FILL-ME" not in blob and "@vietcombank" not in blob.lower()


# ---------------------------------------------------------------------------- the run


def _stable(report: dict[str, Any]) -> str:
    """The report without anything measured in time."""
    r = json.loads(json.dumps(report))
    for d in r["detectors"].values():
        for s in d["splits"].values():
            s.pop("latency_us")
        d["go_no_go"] = {k: v for k, v in d["go_no_go"].items() if not k.startswith("p95")}
    return json.dumps(r, sort_keys=True)


def test_run_is_deterministic_apart_from_latency() -> None:
    assert _stable(H.run(list(SLUGS))) == _stable(_report())


def test_report_has_what_the_brief_asks_for() -> None:
    rep = _report()
    assert rep["mode"] == "mock" and "ILLUSTRATIVE" in rep["thresholds_note"]
    for slug, d in rep["detectors"].items():
        assert d["verdict"] in ("GO", "NO-GO") and d["detector_id"].startswith(slug)
        assert set(d["splits"]) == {"dev", "heldout", "adversarial"}
        for s in d["splits"].values():
            assert s["recall_ci_bp"] and len(s["recall_ci_bp"]) == 2  # Wilson interval
            assert set(s["latency_us"]) >= {"p50", "p95", "max"}
            assert isinstance(s["taxonomy"], dict)
        assert d["go_no_go"]["adversarial_recall_bp"]["verdict"] in ("GO", "NO-GO")
    assert rep["detectors"]["judge_advisory"]["model"]["kind"] == "mock"


def test_all_numbers_are_integers() -> None:
    def walk(v: Any, path: str = "") -> None:
        assert not isinstance(v, float), path
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")

    walk(_report())


def test_dpo_rubric_no_raw_sensitive_string_in_any_answer() -> None:
    for slug, d in _report()["detectors"].items():
        for sp, s in d["splits"].items():
            assert s["leak_items"] == 0, (slug, sp)


def test_soc_rubric_fragments_sit_on_the_masked_text() -> None:
    for slug in ("dlp_vn", "injection_regex"):
        for sp, s in _report()["detectors"][slug]["splits"].items():
            assert s["fragments_checked"] > 0
            assert s["fragment_exact_bp"] == 10_000, (slug, sp)


def test_judge_findings_are_labelled_mock() -> None:
    for s in _report()["detectors"]["judge_advisory"]["splits"].values():
        assert s["mock_labelled_bp"] == 10_000


def test_a_detector_that_passes_only_its_own_templates_is_no_go() -> None:
    """The adversarial row decides: lower the recorded probe result and the verdict flips."""
    d = json.loads(json.dumps(_report()["detectors"]["dlp_vn"]["splits"]))
    d["adversarial"]["recall_bp"] = 0
    v = H.verdicts("dlp_vn", d, False)
    assert v["adversarial_recall_bp"]["verdict"] == "NO-GO"


def test_wilson_interval() -> None:
    assert H.wilson_bp(40, 40) == [9123, 10000]
    assert H.wilson_bp(0, 0) is None
    low, high = H.wilson_bp(5, 10) or [0, 0]
    assert low < 5000 < high


# ---------------------------------------------------------------------------- regression


def test_no_drop_below_the_recorded_baseline() -> None:
    """Fails on any drop in recall, precision, typed recall or fragment exactness, on a new
    leak, or when the golden set changed under the baseline. After a deliberate change run
    ``python -m supervisor.detectors.harness --record --commit <sha> --date <day>`` and commit."""
    base = json.loads(H.BASELINE.read_text(encoding="utf-8"))
    assert (
        base["preset"] == "balanced" and base["commit"] != "unknown" and base["date"] != "unknown"
    )
    assert H.compare(_report(), base) == []


def test_compare_catches_a_drop() -> None:
    base = json.loads(H.BASELINE.read_text(encoding="utf-8"))
    worse = json.loads(json.dumps(_report()))
    worse["detectors"]["dlp_vn"]["splits"]["dev"]["recall_bp"] -= 1
    worse["detectors"]["injection_regex"]["splits"]["heldout"]["leak_items"] = 1
    problems = H.compare(worse, base)
    assert any("dlp_vn.dev.recall_bp" in p for p in problems)
    assert any("injection_regex.heldout.leak_items" in p for p in problems)


# ---------------------------------------------------------------------------- command


def test_command_help_and_ascii_output(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        H.main(["--help"])
    assert exc.value.code == 0
    capsys.readouterr()
    assert H.main(["--detector", "dlp_vn", "--split", "dev"]) == 0
    out = capsys.readouterr().out
    assert out.isascii() and "dlp_vn@1.0.0" in out and "ILLUSTRATIVE" in out
    assert H.main(["--catalogue"]) == 0
    cat = json.loads(capsys.readouterr().out)
    assert [c["slug"] for c in cat] == [
        *SLUGS[:2],
        "injection_classifier",
        SLUGS[2],
        "judge_moderation",  # WP-D4
        "guard_model",  # WP-D3
        "document_intake",  # WP-D1
    ]


def test_check_flag_passes_on_the_committed_baseline(capsys: pytest.CaptureFixture[str]) -> None:
    assert H.main(["--check", "--detector", "dlp_vn"]) == 0
    assert "no drop below the baseline" in capsys.readouterr().out


def test_report_files(tmp_path: Path) -> None:
    j, m = tmp_path / "r.json", tmp_path / "r.md"
    assert H.main(["--detector", "judge_advisory", "--json", str(j), "--md", str(m)]) == 0
    assert json.loads(j.read_text(encoding="utf-8"))["detectors"]["judge_advisory"]
    assert "MockJudge" in m.read_text(encoding="utf-8")
