from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from supervisor.regkb.validator import validate
from tests.conftest import REPO_ROOT

REG = REPO_ROOT / "regulations"
SCHEMA_PATH = REG / "schema" / "obligation.schema.json"
DATA_FILES = sorted([*(REG / "vn").glob("*.yaml"), *(REG / "intl").glob("*.yaml")])


def test_schema_is_json_draft_2020_12() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "instrument_file" in schema["$defs"]


def test_schema_uses_only_supported_keywords() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    # validating anything walks the keywords it meets; an empty instrument_file touches the top.
    validate({}, {"$ref": "#/$defs/instrument_file"}, schema)
    validate({}, schema)


def test_vocab_files_load() -> None:
    for name in ("duties.yaml", "controls.yaml"):
        data = yaml.safe_load((REG / "schema" / name).read_text(encoding="utf-8"))
        assert data["schema_version"] == 1


@pytest.mark.skipif(not DATA_FILES, reason="no regulation data files exist yet")
@pytest.mark.parametrize("path", DATA_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_data_file_matches_schema(path: Path) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    issues = validate(data, {"$ref": "#/$defs/instrument_file"}, schema)
    assert issues == [], "\n".join(str(i) for i in issues)
