"""WP18: the fail-mode drill passes on the real code and fails when the fail mode is wrong."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor.demo import drill
from supervisor.demo.__main__ import main as demo_main
from supervisor.gateway import policy as gate_policy


def test_drill_passes(tmp_path: Path) -> None:
    lines: list[str] = []
    rep = drill.run_drill(tmp_path / "drill", echo=lines.append)
    text = "\n".join(lines)
    assert rep.ok, text
    assert "[FAIL]" not in text
    for key in (
        "(a) baseline",
        "(c) money tool BLOCKED, fail mode closed",
        "(c) read-only tool passed with an alert, fail mode open",
        "(c) unknown tool BLOCKED",
        "(d) store restored",
        "(e) evidence chain verifies offline",
    ):
        assert any(line.startswith("[OK]") and key in line for line in lines), key
    assert all(line.isascii() for line in lines)


def test_drill_main_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert demo_main(["drill", "--data-dir", str(tmp_path / "d")]) == 0
    assert "all outcomes matched" in capsys.readouterr().out


def test_drill_default_uses_temp_dir_and_removes_it() -> None:
    lines: list[str] = []
    assert drill.run_drill(None, echo=lines.append).ok
    store = next(line for line in lines if "throwaway store" in line).split(": ", 1)[1]
    assert not Path(store).exists()


def test_drill_fails_when_money_fails_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(gate_policy.DEFAULT_FAIL_MODE, "money", "open")
    lines: list[str] = []
    rep = drill.run_drill(tmp_path / "drill", echo=lines.append)
    assert not rep.ok
    assert any(line.startswith("[FAIL]") and "money tool" in line for line in lines)
    assert drill.main(["--data-dir", str(tmp_path / "d2")]) == 1
