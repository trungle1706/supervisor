from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from supervisor.regkb import DISCLAIMER
from supervisor.regkb.cli import ascii_text, main
from tests.regkb.conftest import instrument, kb_file, obligation, write_file

OID = "VN-TEST-2026-A1-01"


def run(capsys, *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    out = capsys.readouterr().out
    assert out.isascii()
    assert out.splitlines()[0] == DISCLAIMER
    return code, out


def test_ascii_text() -> None:
    assert ascii_text("Đồng đồng") == "Dong dong"
    assert ascii_text("a–b → c") == "a-b ? c"


def test_validate_real_data(capsys) -> None:
    code, out = run(capsys, "validate")
    assert code == 0 and "[OK]" in out and "version" in out


def test_validate_fixture_and_failure(root: Path, capsys) -> None:
    code, out = run(capsys, "--root", str(root), "validate")
    assert code == 0 and "[OK] 1 instruments, 1 obligations" in out
    write_file(
        root / "vn",
        "bad.yaml",
        kb_file(instrument("VN-BAD"), [obligation("VN-BAD-A1-01", duties=["zzz"], sources=[])]),
    )
    code, out = run(capsys, "--root", str(root), "validate")
    assert code == 1
    assert out.count("[FAIL]") >= 1 and "bad.yaml" in out and "VN-BAD-A1-01" in out


def test_list_filters(root: Path, capsys) -> None:
    write_file(
        root / "intl",
        "fw.yaml",
        kb_file(
            instrument(
                "INTL-FW", jurisdiction="INTL", kind="standard", status="reference", binding=False
            ),
            [obligation("INTL-FW-G1-01")],
        ),
    )
    _, out = run(capsys, "--root", str(root), "list")
    assert OID in out and "INTL-FW-G1-01" in out and "human_oversight" in out
    _, out = run(capsys, "--root", str(root), "list", "--jurisdiction", "INTL")
    assert OID not in out and "INTL-FW-G1-01" in out
    _, out = run(capsys, "--root", str(root), "list", "--instrument", "VN-TEST-2026")
    assert OID in out and "INTL-FW" not in out


def test_show_obligation_instrument_unknown(root: Path, capsys) -> None:
    write_file(root / "vn", "test.yaml", kb_file(obs=[obligation(text_vi="Quy định tiếng Việt")]))
    code, out = run(capsys, "--root", str(root), "show", OID)
    assert code == 0 and "Quy dinh tieng Viet" in out and "(diacritics stripped; see file)" in out
    code, out = run(capsys, "--root", str(root), "show", "VN-TEST-2026")
    assert code == 0 and OID in out
    code, out = run(capsys, "--root", str(root), "show", "VN-NOPE-A1-01")
    assert code == 1 and "[FAIL]" in out and "VN-NOPE-A1-01" in out


def test_show_real_first_obligation(capsys) -> None:
    from supervisor.regkb import load_kb

    kb = load_kb()
    if not kb.obligations:
        pytest.skip("no regulation data yet")
    code, _ = run(capsys, "show", next(iter(kb.obligations)))
    assert code == 0


def test_coverage_table(root: Path, capsys) -> None:
    code, out = run(capsys, "--root", str(root), "coverage")
    assert code == 0
    for col in (
        "instrument",
        "kind",
        "status",
        "binding",
        "obligations",
        "P/S/A",
        "primary text",
        "last checked",
    ):
        assert col in out
    assert "VN-TEST-2026" in out and "1/0/0" in out
    assert "only partial controls:     1" in out and "version " in out


def test_coverage_levels_real_data(capsys) -> None:
    code, out = run(capsys, "coverage", "--levels")
    assert code == 0 and "Control levels per instrument" in out
    line = [ln for ln in out.splitlines() if ln.startswith("VN-DEC142-2026 ")][-1]
    assert "1/19/6" in line and "1/24/1" in line


def test_coverage_real_data(capsys) -> None:
    code, out = run(capsys, "coverage")
    assert code == 0 and "Control coverage" in out


def test_diff_same_and_modified(root: Path, tmp_path: Path, capsys) -> None:
    code, out = run(capsys, "diff", str(root), str(root))
    assert code == 0 and "no changes" in out
    other = tmp_path / "copy" / "regulations"
    shutil.copytree(root, other)
    write_file(
        other / "vn",
        "test.yaml",
        kb_file(obs=[obligation(summary_en="Changed."), obligation("VN-TEST-2026-A2-01")]),
    )
    code, out = run(capsys, "diff", str(root), str(other))
    assert code == 0
    assert "added obligation: VN-TEST-2026-A2-01" in out
    assert f"changed obligation: {OID}: summary_en" in out
    code, out = run(capsys, "diff", str(other), str(root))
    assert "removed obligation: VN-TEST-2026-A2-01" in out


def test_export_and_diff_export(root: Path, tmp_path: Path, capsys) -> None:
    target = tmp_path / "out" / "snap.json"
    code, out = run(capsys, "--root", str(root), "export", str(target))
    assert code == 0 and "[OK]" in out
    data = json.loads(target.read_text("utf-8"))
    assert OID in data["obligations"] and len(data["version"]) == 64
    code, out = run(capsys, "diff", str(target), str(root))
    assert code == 0 and "no changes" in out
    assert data["version"][:12] in out


def test_diff_errors(tmp_path: Path, capsys) -> None:
    code, out = run(capsys, "diff", str(tmp_path / "nope"), str(tmp_path))
    assert code == 1 and "[FAIL]" in out
    junk = tmp_path / "junk.json"
    junk.write_text("[1]", "utf-8")
    code, out = run(capsys, "diff", str(junk), str(junk))
    assert code == 1 and "[FAIL]" in out


def test_bad_command_no_traceback(capsys) -> None:
    assert main(["frobnicate"]) == 2
    assert "Traceback" not in capsys.readouterr().out


def test_bad_root(tmp_path: Path, capsys) -> None:
    code, out = run(capsys, "--root", str(tmp_path / "missing"), "validate")
    assert code == 1 and "[FAIL]" in out
