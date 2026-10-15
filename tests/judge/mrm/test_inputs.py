from __future__ import annotations

import json
from pathlib import Path

import pytest

from supervisor.judge.mrm.inputs import (
    JudgeValidationInput,
    StaticPackResults,
    load_pack_results,
    validate_pack_rows,
)

ROW = {"pack_id": "p1", "metric": "m", "value_bp": 9000, "threshold_bp": 8000, "passed": True}


def test_protocol_and_static() -> None:
    src = StaticPackResults([ROW])
    assert isinstance(src, JudgeValidationInput)
    assert src.results() == [{**ROW, "op": ">="}]
    src.results()[0]["pack_id"] = "x"  # copies, not the stored row
    assert src.results()[0]["pack_id"] == "p1"


@pytest.mark.parametrize(
    "patch",
    [
        {"value_bp": 90.0},
        {"threshold_bp": 0.5},
        {"value_bp": True},
        {"value_bp": 10001},
        {"value_bp": -1},
        {"passed": 1},
        {"pack_id": ""},
        {"source": 3},
        {"extra": 1},
    ],
)
def test_bad_rows_rejected(patch: dict) -> None:
    with pytest.raises(ValueError):
        validate_pack_rows([{**ROW, **patch}])


def test_missing_field_and_non_object() -> None:
    with pytest.raises(ValueError):
        validate_pack_rows([{"pack_id": "p"}])
    with pytest.raises(ValueError):
        validate_pack_rows(["nope"])  # type: ignore[list-item]


def test_load_pack_results(tmp_path: Path) -> None:
    f = tmp_path / "packs.json"
    f.write_text(json.dumps([{**ROW, "source": "wp17"}]), encoding="utf-8")
    assert load_pack_results(f).results()[0]["source"] == "wp17"
    f.write_text(json.dumps({"results": [ROW]}), encoding="utf-8")
    assert len(load_pack_results(f).results()) == 1
    f.write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError):
        load_pack_results(f)
    with pytest.raises(ValueError):
        load_pack_results(tmp_path / "missing.json")


def test_passed_must_agree_with_numbers() -> None:
    with pytest.raises(ValueError, match="disagrees"):
        validate_pack_rows([{**ROW, "value_bp": 1000, "threshold_bp": 9000, "passed": True}])
    with pytest.raises(ValueError, match="disagrees"):
        validate_pack_rows([{**ROW, "passed": False}])


def test_lower_better_op() -> None:
    row = {**ROW, "value_bp": 100, "threshold_bp": 500, "op": "<=", "passed": True}
    assert validate_pack_rows([row])[0]["op"] == "<="
    with pytest.raises(ValueError, match="op must be"):
        validate_pack_rows([{**ROW, "op": ">"}])


def test_eval_result_rows_are_the_default_source() -> None:
    from datetime import UTC, datetime

    from supervisor.config import load_settings
    from supervisor.judge.mrm.inputs import EvalResultPacks
    from supervisor.judge.router import JudgeRouter
    from tests.judge.conftest import MemoryTables

    router = JudgeRouter.from_settings(load_settings())
    t = MemoryTables()
    base = {
        "pack_id": "judge_injection",
        "target_kind": "judge",
        "target_id": f"judge:{router.t1.model_id}",
        "is_mock": True,
        "thresholds": {
            "injection_detect_bp": {"go": 8000, "no_go": 6000},
            "canary_leak_bp": {"go": 0, "no_go": 500},
        },
    }
    # newest first, as the real store returns them (order_by -ts); MemoryTables keeps order
    t.append(
        "eval_result",
        [
            {
                **base,
                "run_id": "new",
                "ts": datetime(2026, 10, 2, tzinfo=UTC),
                "metrics": {"injection_detect_bp": 9000, "canary_leak_bp": 900},
                "metric_status": {"injection_detect_bp": "ok", "canary_leak_bp": "fail"},
            },
            {
                **base,
                "run_id": "old",
                "ts": datetime(2026, 10, 1, tzinfo=UTC),
                "metrics": {"injection_detect_bp": 1000, "canary_leak_bp": 0},
                "metric_status": {"injection_detect_bp": "fail", "canary_leak_bp": "ok"},
            },
        ],
    )
    rows = {r["metric"]: r for r in EvalResultPacks(t, router).results()}
    assert rows["injection_detect_bp"]["passed"] is True
    assert (
        rows["injection_detect_bp"]["op"] == ">="
        and rows["injection_detect_bp"]["threshold_bp"] == 6000
    )
    assert rows["canary_leak_bp"]["passed"] is False and rows["canary_leak_bp"]["op"] == "<="
    assert rows["canary_leak_bp"]["source"] == "eval_result:new (mock run)"
