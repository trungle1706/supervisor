from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from supervisor.config import load_settings
from supervisor.judge.mrm import validation as val
from supervisor.judge.mrm.inputs import StaticPackResults
from tests.judge.conftest import MemoryEvidence, MemoryTables, assert_no_floats

NOW = datetime(2026, 10, 15, tzinfo=UTC)
LOW = {
    "mrm_min_catch_bp": 0,
    "mrm_max_false_alarm_bp": 10000,
    "mrm_min_lang_catch_bp": 0,
    "mrm_min_injection_detect_bp": 0,
    "mrm_max_injection_lowered_bp": 10000,
    "mrm_max_canary_leak_bp": 10000,
    "mrm_max_challenger_disagree_bp": 10000,
    "mrm_max_stability_range_bp": 10000,
}


@pytest.fixture(scope="module")
def default_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    s = load_settings(data_dir=tmp_path_factory.mktemp("d"))
    return val.run_validation(s, runs=2, now=NOW, record=False)


def _failed(rep: dict[str, Any]) -> list[str]:
    return rep["failed_checks"]


def test_default_is_no_go_on_heldout_catch(default_report: dict[str, Any]) -> None:
    assert default_report["decision"] == "NO_GO"
    assert "heldout_catch" in _failed(default_report)
    assert default_report["is_mock"] is True
    assert default_report["packs"]["status"] == "none_supplied"
    assert default_report["agreement"]["status"] == "no_store"
    assert "judge_human_agreement" in default_report["skipped_checks"]


def test_report_has_no_floats(default_report: dict[str, Any]) -> None:
    assert_no_floats(default_report)


def test_go_with_lowered_thresholds(tmp_path: Path) -> None:
    s = load_settings(data_dir=tmp_path, **LOW)
    rep = val.run_validation(s, runs=2, now=NOW, record=False)
    assert rep["decision"] == "GO", rep["failed_checks"]


def test_failed_pack_forces_no_go(tmp_path: Path) -> None:
    s = load_settings(data_dir=tmp_path, **LOW)
    row = {"pack_id": "p", "metric": "m", "value_bp": 10, "threshold_bp": 500, "passed": False}
    rep = val.run_validation(s, runs=1, now=NOW, packs=StaticPackResults([row]), record=False)
    assert rep["decision"] == "NO_GO"
    assert _failed(rep) == ["pack:p:m"]


def test_none_value_fails_check() -> None:
    c = val._check("x", None, 0, "<=")
    assert c["passed"] is False


def test_hash_stable_and_recording(tmp_path: Path) -> None:
    s = load_settings(data_dir=tmp_path)
    ev, tb = MemoryEvidence(), MemoryTables()
    a = val.run_validation(s, runs=2, now=NOW, tables=tb, evidence=ev)
    b = val.run_validation(s, runs=2, now=NOW, tables=tb, record=False)
    assert a["report_hash"] == b["report_hash"]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["validation_id"] == "jval-" + a["report_hash"][:16]
    rows = tb.tables["model_validation"]
    assert len(rows) == 1 and rows[0]["decision"] == "NO_GO" and rows[0]["passed"] is False
    assert rows[0]["report_hash"] == a["report_hash"]
    assert rows[0]["validator"] == s.mrm_validator
    ev_rows = ev.of_type("judge_validation")
    assert len(ev_rows) == 1 and ev_rows[0]["report_hash"] == a["report_hash"]
    assert_no_floats(rows[0]["metrics"])


def test_cli_no_record_writes_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    rc = val.main(["--out", str(out), "--runs", "1", "--no-record", "--now", NOW.isoformat()])
    assert rc == 0
    rep = json.loads((out / "judge_validation.json").read_text())
    assert rep["decision"] == "NO_GO"
    assert (out / "judge_validation.md").read_text().isascii()
    text = capsys.readouterr().out
    assert "[FAIL] heldout_catch" in text and "[OK] validation written" in text


def test_cli_bad_packs_file_exit_2(tmp_path: Path) -> None:
    bad = tmp_path / "p.json"
    bad.write_text('[{"pack_id": "p"}]')
    assert val.main(["--out", str(tmp_path / "o"), "--packs", str(bad), "--no-record"]) == 2
