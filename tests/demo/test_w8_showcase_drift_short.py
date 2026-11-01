"""W8 follow-up: the drift scenario with a short demo window (10 s) on a temporary store.

The past modes write 9 normal windows and the shift through the real gate; the live mode runs
in real time and must reach Watch, then Unstable with a drift case, in under a minute."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.factory import build_adapters
from supervisor.console import stability_view as sv
from supervisor.demo import showcase_drift as sd
from supervisor.governance.systems import SystemService

from .test_showcase_journeys import settings_for
from .test_w8_showcase_drift import SID, make_system

WIN = 10


@pytest.fixture(autouse=True)
def _showcase_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOWCASE_ENABLED", "1")


def short_settings(tmp_path: Path) -> Any:
    return settings_for(
        tmp_path / "data",
        drift_window_s=WIN,
        drift_settle_s=2,
        stability_tab=True,
        showcase_enabled=True,
    )


def light_ctx(settings: Any) -> Any:
    """A read-only context (no chain writer, so it never meets the one of the running scenario)."""
    a = build_adapters(settings)
    return a, SimpleNamespace(
        settings=settings,
        tables=a.tables,
        state=a.state,
        clock=a.clock,
        systems=SystemService.from_adapters(a),
    )


def read_state(settings: Any) -> tuple[str, dict[str, Any]]:
    a, ctx = light_ctx(settings)
    try:
        system = dict(ctx.systems.get(SID))
        stab = sv.page_data(ctx, system, {})["stab"]
        return str(stab["state"]), stab
    finally:
        a.close()


def drift_cases(settings: Any) -> list[dict[str, Any]]:
    a, ctx = light_ctx(settings)
    try:
        rows = ctx.state.query("cases", {"agent_id": sd.CID})
        return [dict(c) for c in rows if c["case_type"] == "drift"]
    finally:
        a.close()


def test_the_short_window_is_for_the_demo_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("DRIFT_WINDOW_S", "10")
    monkeypatch.delenv("SHOWCASE_ENABLED", raising=False)
    assert sd.main(["baseline"]) != 0
    assert "SHOWCASE_ENABLED" in capsys.readouterr().out
    monkeypatch.setenv("SHOWCASE_ENABLED", "1")
    monkeypatch.setenv("DRIFT_WINDOW_S", "20")
    assert sd.check_window(load(20)) == ""
    assert sd.check_window(SimpleNamespace(drift_window_s=9)) != ""
    assert sd.shift_windows(SimpleNamespace(drift_window_s=10)) == sd.SHORT_SHIFT_WINDOWS
    assert sd.shift_windows(SimpleNamespace(drift_window_s=60)) == sd.SHIFT_WINDOWS


def load(window: int) -> Any:
    from supervisor.config import load_settings

    return load_settings(
        sql_backend="sqlite", _env_file=None, drift_window_s=window, showcase_enabled=True
    )


def test_past_modes_with_ten_second_windows(tmp_path: Path) -> None:
    settings = short_settings(tmp_path)
    make_system(settings)
    lines: list[str] = []
    sent = sd.past_phase(
        settings,
        [(sd.NORMAL, sd.BASELINE_WINDOWS), (sd.SHIFT, sd.SHORT_SHIFT_WINDOWS)],
        seed=7,
        system_id=SID,
        say=lines.append,
    )
    assert sent.calls == (sd.BASELINE_WINDOWS + sd.SHORT_SHIFT_WINDOWS) * 60
    state, stab = read_state(settings)
    assert state == "unstable" and stab["view"] == "live" and stab["refresh_s"] == 5
    assert stab["b"]["banded"] is True and stab["b"]["window_s"] == WIN
    cases = drift_cases(settings)
    assert len(cases) == 1 and cases[0]["status"] == "open"
    assert any("windows of 10 s written" in line for line in lines)


def test_live_shift_reaches_watch_then_unstable_in_under_a_minute(tmp_path: Path) -> None:
    settings = short_settings(tmp_path)
    make_system(settings)
    sd.past_phase(
        settings, [(sd.NORMAL, sd.BASELINE_WINDOWS)], seed=7, system_id=SID, say=lambda _t: None
    )
    assert read_state(settings)[0] == "stable" and drift_cases(settings) == []
    seen: list[tuple[float, str]] = []
    t0 = time.monotonic()

    def say(text: str) -> None:  # a look at the page after every window and every drift check
        if "window" in text or "drift check" in text:
            seen.append((time.monotonic() - t0, read_state(settings)[0]))

    sd.live_phase(settings, sd.SHIFT, 3, seed=8, system_id=SID, say=say)
    states = [s for _, s in seen]
    assert "watch" in states, seen
    assert states.index("watch") < len(states) - 1 - states[::-1].index("unstable"), seen
    first_unstable = next(t for t, s in seen if s == "unstable")
    assert first_unstable < 60, seen  # Stable to Unstable, with the page open, in under a minute
    final, _ = read_state(settings)
    assert final == "unstable" and len(drift_cases(settings)) == 1
