"""(d) CLI smoke, (e) snapshots of the three demo agents.

Regenerate the snapshots with ``UPDATE_ADVISORY_SNAPSHOTS=1 uv run python -m pytest
tests/advisory/test_cli_snapshots.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from supervisor.advisory.integration.__main__ import main
from supervisor.advisory.integration.advise import Advice
from supervisor.advisory.integration.render import render_json
from tests.advisory.conftest import DEMO, target_of

SNAPSHOTS = Path(__file__).parent / "snapshots"


@pytest.mark.parametrize("agent", DEMO)
def test_demo_snapshot(agent: str, advices: dict[str, Advice]) -> None:
    text = render_json(advices[agent].report)
    path = SNAPSHOTS / f"{agent}.json"
    if os.environ.get("UPDATE_ADVISORY_SNAPSHOTS") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
    assert path.read_text(encoding="utf-8") == text, "run with UPDATE_ADVISORY_SNAPSHOTS=1"


def test_cli_smoke(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    code = main(["--target", str(target_of("injection_bill_pay")), "--out", str(out), "--mock-llm"])
    text = capsys.readouterr().out
    assert code == 0
    text.encode("ascii")
    assert "[OK] readiness:" in text and "[OK] patches:" in text
    assert (out / "integration_report.json").is_file()
    assert (out / "integration_report.md").is_file()
    assert (out / "integration_report.html").is_file()
    assert sorted(p.name for p in (out / "patches").iterdir())[0].startswith("01-")


def test_cli_bad_target(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--target", str(tmp_path / "nope"), "--out", str(tmp_path / "o"), "--mock-llm"])
    assert code == 2
    assert capsys.readouterr().out.startswith("[FAIL]")


def test_cli_refuses_out_inside_target(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import shutil

    repo = tmp_path / "repo"
    shutil.copytree(target_of("langchain_card_support"), repo)
    before = sorted(p.name for p in repo.rglob("*"))
    code = main(["--target", str(repo), "--out", str(repo / "out"), "--mock-llm"])
    assert code == 2 and "[FAIL]" in capsys.readouterr().out
    assert sorted(p.name for p in repo.rglob("*")) == before


def test_cli_without_llm_falls_back_to_mock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "")
    code = main(["--target", str(target_of("payments")), "--out", str(tmp_path / "o")])
    text = capsys.readouterr().out
    assert code == 0 and "[SKIP] no LLM configured" in text
