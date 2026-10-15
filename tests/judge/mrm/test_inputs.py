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
    assert src.results() == [ROW]
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
