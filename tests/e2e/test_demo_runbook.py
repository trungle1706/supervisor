"""WP11 Definition of Done: the demo runbook completes 20 times in a row, with no network.

seed (run 1) -> DEMO-1..4 through the real agents + gateway -> tamper test on an export
copy -> reset to the snapshot; runs 2..20 start from the reset, so the reset is proven
20 times as well. Agents use MockChat scripts and the judge is the MockJudge (labelled).

Measured on the build host (2026-10-14): 20/20 in 6.7 s (median 0.28 s per run, run 1
with the seed 1.3 s). Budget 60 s for the 20 runs, so it stays in the normal suite (marker e2e).
"""

from __future__ import annotations

import socket
import time
from pathlib import Path
from typing import Any

import pytest

from supervisor.demo import runbook
from supervisor.demo.session import demo_settings

RUNS = 20
BUDGET_S = 60.0


class _NoNetwork(Exception):
    pass


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> None:
        raise _NoNetwork("network access attempted during the demo runbook")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.mark.e2e
def test_runbook_passes_20_of_20_within_budget(tmp_path: Path, no_network: None) -> None:
    settings = demo_settings(
        tmp_path / "demo", llm_base_url="", judge_t1_model="", judge_t2_model=""
    )
    lines: list[str] = []
    t0 = time.perf_counter()
    report = runbook.run_loop(settings, RUNS, echo=lines.append)
    elapsed = time.perf_counter() - t0
    fails = [ln for ln in lines if ln.startswith("[FAIL]")]
    assert report.passed == RUNS, "\n".join(fails or lines[-40:])
    assert report.ok and not fails
    assert not any(r.replayed for r in report.runs)  # live every time, no replay twin
    assert all(ln.isascii() for ln in lines)
    summary = lines[-1]
    assert summary.startswith(f"[OK] demo loop: {RUNS}/{RUNS} runs passed"), summary
    # every run shows the three live controls
    for marker in (
        "gate PAUSED payments",
        "gate_state=PAUSED",
        "verify TAMPERED copy: RESULT FAIL",
    ):
        assert sum(marker in ln for ln in lines) == RUNS, marker
    per_run = sorted(r.seconds for r in report.runs)
    print(  # noqa: T201 - the measured timing is part of the DoD evidence
        f"\n[OK] demo runbook {RUNS}/{RUNS} in {elapsed:.1f} s (budget {BUDGET_S:.0f} s); "
        f"per run min {per_run[0]:.2f} s, median {per_run[RUNS // 2]:.2f} s, "
        f"max {per_run[-1]:.2f} s"
    )
    assert elapsed < BUDGET_S, f"20 runs took {elapsed:.1f} s (budget {BUDGET_S} s)"
