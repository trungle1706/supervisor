"""WP-D1: the harness rows document_injection_vi, document_pii_vi and url_ssrf."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.detectors import harness as H
from supervisor.detectors import intake_eval as E

pytest.importorskip("pypdf")  # the PDF items of the golden set need the optional extra


@pytest.fixture(scope="module")
def rows() -> dict[str, dict[str, Any]]:
    return E.run_rows()


def test_every_row_has_at_least_50_items_per_split_with_both_labels() -> None:
    for row in E.ROWS:
        for sp in ("dev", "heldout"):
            items = E.load(row, sp)
            assert len(items) >= 50, (row, sp)
            assert {i["label"] for i in items} == {0, 1}, (row, sp)
    for row in ("document_injection_vi", "url_ssrf"):
        probes = E.load(row, "adversarial")
        assert len(probes) >= 15 and {i["label"] for i in probes} == {0, 1}


def test_items_have_provenance_and_unique_ids() -> None:
    seen: set[str] = set()
    for row in E.ROWS:
        for sp in E.SPLITS:
            for i in E.load(row, sp):
                assert i["id"] not in seen
                seen.add(i["id"])
                assert i["licence"] == E.LICENCE and i["labeller"] == "synthetic" and i["source"]
                assert i["row"] == row and i["split"] == sp


def test_manifest_hashes_match_the_files() -> None:
    manifest = json.loads((E.DATA_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    for name, meta in manifest["files"].items():
        data = (E.DATA_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], name
        assert len(data.splitlines()) == meta["n_items"]


def test_generator_is_deterministic(tmp_path: Path) -> None:
    m = E.write_all(tmp_path)
    committed = json.loads((E.DATA_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    assert m == committed
    for name in m["files"]:
        assert (tmp_path / name).read_bytes() == (E.DATA_DIR / name).read_bytes()


def test_dev_and_heldout_do_not_share_templates() -> None:
    dev = {x[1] for x in E.INJ_DEV}
    held = {x[1] for x in E.INJ_HELD}
    assert not dev & held
    a = {i["url"] for i in E.load("url_ssrf", "dev")}
    b = {i["url"] for i in E.load("url_ssrf", "heldout")}
    assert len(a & b) <= 3  # a few generic literals (127.0.0.1 class) may repeat; the hosts differ


def test_document_specs_cover_every_supported_kind() -> None:
    kinds = {
        s["kind"]
        for row in ("document_injection_vi", "document_pii_vi")
        for sp in E.SPLITS
        for i in E.load(row, sp)
        for s in i["docs"]
    }
    assert {"txt", "md", "json", "csv", "html", "docx", "pdf", "png", "raw"} <= kinds


def test_every_row_is_go_on_dev_and_heldout(rows: dict[str, dict[str, Any]]) -> None:
    assert set(rows) == set(E.ROWS)
    for name, d in rows.items():
        assert d["verdict"] == "GO", (
            name,
            {k: v for k, v in d["go_no_go"].items() if v["verdict"] == "NO-GO"},
        )
        for sp in ("dev", "heldout"):
            s = d["splits"][sp]
            assert s["leak_items"] == 0 and s["fn"] == 0, (name, sp)


def test_ssrf_never_sends_a_request_to_a_forbidden_target(rows: dict[str, dict[str, Any]]) -> None:
    for sp, s in rows["url_ssrf"]["splits"].items():
        assert s["leak_items"] == 0, sp
        assert s["recall_bp"] == 10_000 or sp == "adversarial", sp


def test_dpo_rubric_no_raw_value_in_findings_fragments_or_masked_documents(
    rows: dict[str, dict[str, Any]],
) -> None:
    for sp in ("dev", "heldout", "adversarial"):
        for name in ("document_injection_vi", "document_pii_vi"):
            if sp in rows[name]["splits"]:
                assert rows[name]["splits"][sp]["leak_items"] == 0
    assert rows["document_pii_vi"]["splits"]["dev"]["fragment_exact_bp"] >= 9900


def test_known_gaps_are_named_in_the_adversarial_taxonomy(rows: dict[str, dict[str, Any]]) -> None:
    tax = rows["document_injection_vi"]["splits"]["adversarial"]["taxonomy"]
    for gap in ("missed:base64", "missed:leetspeak", "missed:split-across-documents"):
        assert gap in tax  # a phrase split over two files, encoded or leetspeak is not found


def test_all_numbers_are_integers(rows: dict[str, dict[str, Any]]) -> None:
    def walk(v: Any) -> None:
        assert not isinstance(v, float)
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(rows)


def test_the_harness_includes_the_rows_and_the_baseline_holds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = H.run(["url_ssrf"], ["dev"])
    assert list(report["detectors"]) == ["url_ssrf"]
    assert H.main(["--check", "--detector", "url_ssrf", "--split", "dev"]) == 0
    out = capsys.readouterr().out
    assert "no drop below the baseline" in out and out.isascii()
    assert H.main(["--check", "--detector", "document_pii_vi"]) == 0


def test_a_drop_below_the_baseline_is_caught(rows: dict[str, dict[str, Any]]) -> None:
    assert E.compare_baseline(rows) == []
    worse = json.loads(json.dumps(rows))
    worse["url_ssrf"]["splits"]["dev"]["recall_bp"] -= 100
    assert any("recall_bp" in p for p in E.compare_baseline(worse))


def test_markdown_report_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    md = tmp_path / "r.md"
    assert E.main(["--row", "url_ssrf", "--md", str(md)]) == 0
    text = md.read_text(encoding="utf-8")
    assert "Document and URL intake" in text and "url_ssrf" in text
    assert capsys.readouterr().out.isascii()
    with pytest.raises(SystemExit):
        E.main(["--help"])


def test_thresholds_are_declared_for_every_row() -> None:
    assert set(E.THRESHOLDS) == set(E.ROWS)
    assert (
        E.THRESHOLDS["url_ssrf"]["recall_bp"] == 10_000
        and E.THRESHOLDS["url_ssrf"]["leak_items_max"] == 0
    )
    for t in E.THRESHOLDS.values():
        assert all(isinstance(v, int) for v in t.values())
