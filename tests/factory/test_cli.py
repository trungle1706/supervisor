"""python -m supervisor.factory: validate and schema. Never a traceback."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from supervisor.factory.__main__ import main
from supervisor.factory.schemas import MODELS

from .conftest import DATA

VALID = [
    "agent_single_pass.yaml",
    "agent_loop_memory.yaml",
    "report_valid.yaml",
    "facts_export.json",
]
INVALID = {
    "invalid_inline_tool.yaml": "tools[2]",
    "invalid_missing_guardian.yaml": "guardians",
    "invalid_loop_over_cap.yaml": "harness.loop.max_iterations",
    "invalid_finding_no_evidence.yaml": "evidence",
    "invalid_float_confidence.yaml": "findings[0].confidence",
}


@pytest.mark.parametrize("name", VALID)
def test_valid_files_exit_0(name: str, capsys: pytest.CaptureFixture) -> None:
    assert main(["validate", str(DATA / name)]) == 0
    assert capsys.readouterr().out.startswith("[OK]")


@pytest.mark.parametrize(("name", "field"), INVALID.items())
def test_invalid_files_exit_1_and_name_the_field(
    name: str, field: str, capsys: pytest.CaptureFixture
) -> None:
    assert main(["validate", str(DATA / name)]) == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out and field in out and "Traceback" not in out
    out.encode("ascii")


def test_missing_file_is_a_message(capsys: pytest.CaptureFixture) -> None:
    assert main(["validate", "/nonexistent/x.yaml"]) == 1
    assert "[FAIL] file:" in capsys.readouterr().out


def test_not_yaml_is_a_message(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("a: [unclosed\n", encoding="utf-8")
    assert main(["validate", str(p)]) == 1
    assert "[FAIL] file:" in capsys.readouterr().out


def test_unknown_document_and_non_object(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    p = tmp_path / "x.yaml"
    p.write_text("- 1\n- 2\n", encoding="utf-8")
    assert main(["validate", str(p)]) == 1
    assert "--schema" in capsys.readouterr().out


def test_explicit_schema_flag(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    p = tmp_path / "x.yaml"
    p.write_text("{}\n", encoding="utf-8")
    assert main(["validate", str(p), "--schema", "assessment_report_v1"]) == 1
    assert "report_id" in capsys.readouterr().out


def test_registry_check_runs_for_definitions(
    tmp_path: Path, capsys: pytest.CaptureFixture, agent: dict
) -> None:
    import yaml

    agent["tools"][0]["tool_id"] = "run_python"
    p = tmp_path / "a.yaml"
    p.write_text(yaml.safe_dump(agent), encoding="utf-8")
    assert main(["validate", str(p)]) == 1
    assert "tools[0].tool_id" in capsys.readouterr().out


@pytest.mark.parametrize("name", sorted(MODELS))
def test_schema_prints_json_schema(name: str, capsys: pytest.CaptureFixture) -> None:
    assert main(["schema", name]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["type"] == "object" and doc["additionalProperties"] is False


def test_schema_output_is_stable(capsys: pytest.CaptureFixture) -> None:
    main(["schema", "agent_definition_v1"])
    first = capsys.readouterr().out
    main(["schema", "agent_definition_v1"])
    assert capsys.readouterr().out == first


def test_module_entry_point_runs_as_python_dash_m() -> None:
    """The real entry point, without a subprocess: runpy executes ``__main__``."""
    import runpy

    argv = sys.argv
    sys.argv = ["supervisor.factory", "validate", str(DATA / "report_valid.yaml")]
    try:
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("supervisor.factory", run_name="__main__")
    finally:
        sys.argv = argv
    assert exc.value.code == 0
