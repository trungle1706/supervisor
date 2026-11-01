"""W8: a short drift window for the demo (DRIFT_WINDOW_S, DRIFT_SETTLE_S). The defaults are
unchanged; with a 60 s window and a 5 s settle time the check judges a window a few seconds after it
closes, so a demo does not wait ten minutes per window."""

from __future__ import annotations

from datetime import timedelta

from supervisor.config import load_settings
from supervisor.monitors.common import MonitorContext
from supervisor.monitors.drift import DriftConfig, DriftMonitor
from supervisor.monitors.seed import as_rows, event
from tests.monitors.conftest import T0


def _rows(windows: int, per: int = 30) -> list[dict]:
    events = []
    for w in range(windows):
        for i in range(per):
            ts = T0 + timedelta(seconds=60 * w + 1 + i)
            events.append(
                event(
                    ts,
                    "w8-agent",
                    "1",
                    "gate_decision",
                    tool="transfer" if i % 2 else "reconcile",
                    amount=5_000_000 if i % 2 else None,
                    status="allowed",
                )  # fmt: skip
            )
    return as_rows(events)


def test_settings_feed_the_drift_config() -> None:
    s = load_settings(sql_backend="sqlite", _env_file=None)
    assert (s.drift_window_s, s.drift_settle_s) == (86400, 600)
    short = DriftConfig.from_settings(
        load_settings(sql_backend="sqlite", _env_file=None, drift_window_s=60, drift_settle_s=5)
    )
    assert (short.window_s, short.settle_s) == (60, 5)


def test_short_settle_judges_a_window_seconds_after_it_closes(adapters, clock, evidence) -> None:
    adapters.tables.append("agent_event", _rows(8))
    ctx = MonitorContext.from_adapters(adapters, evidence)
    now = T0 + timedelta(seconds=60 * 7 + 6)  # 6 s after the seventh window closed
    slow = DriftMonitor(ctx, DriftConfig(window_s=60, min_n=20)).run(now)
    assert slow.baselines_built == [] and slow.collecting == ["w8-agent@1"]  # default settle: wait
    fast = DriftMonitor(ctx, DriftConfig(window_s=60, min_n=20, settle_s=5)).run(now)
    assert len(fast.baselines_built) == 1
    bands = adapters.state.query("policy_baseline", {"agent_id": "w8-agent"})
    assert bands and all(b["window_s"] == 60 for b in bands)
