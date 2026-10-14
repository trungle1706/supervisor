"""Drift monitor: seeded normal week then drifted week -> exactly one drift case, no rule."""

from __future__ import annotations

from datetime import timedelta

import pytest

from supervisor.monitors.common import MonitorContext, median, percentile, scaled_mad
from supervisor.monitors.drift import DriftConfig, DriftMonitor, make_band, window_metrics
from supervisor.monitors.seed import as_rows, drift_weeks
from tests.judge.conftest import assert_no_floats
from tests.monitors.conftest import T0


def _ctx(adapters, evidence) -> MonitorContext:
    return MonitorContext.from_adapters(adapters, evidence)


def _run_daily(monitor: DriftMonitor, clock, days: int) -> list[str]:
    opened: list[str] = []
    for _ in range(days):
        clock.advance(86400)
        opened += monitor.run().cases_opened
    return opened


def test_integer_stats() -> None:
    assert percentile([5, 1, 3, 2, 4], 50) == 3
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile([1, 2, 3, 4], 90) == 4
    assert median([7]) == 7
    assert scaled_mad([10, 10, 10, 20], 10) == 0
    assert scaled_mad([8, 10, 12], 10) == 2 * 14826 // 10000
    with pytest.raises(ValueError):
        percentile([], 50)
    band = make_band("block_rate_bp", [0, 0, 0], 3, DriftConfig())
    assert (band.low, band.high) == (-300, 300)  # absolute floor keeps the band open


def test_seeded_drift_week_opens_exactly_one_case(adapters, clock, evidence) -> None:
    events = drift_weeks(T0, normal_days=7, drift_days=7)
    adapters.tables.append("agent_event", as_rows(events))
    monitor = DriftMonitor(_ctx(adapters, evidence))

    opened = _run_daily(monitor, clock, 7)  # baseline week: collecting, then the band
    assert opened == []
    bands = adapters.state.query("policy_baseline", {"agent_id": "payments"})
    assert {b["metric"] for b in bands} >= {
        "tool_share_bp:transfer",
        "amount_p50",
        "amount_p90",
        "block_rate_bp",
        "latency_p50_ms",
    }
    assert all(isinstance(b["band_low"], int) and isinstance(b["band_high"], int) for b in bands)

    opened = _run_daily(monitor, clock, 7)  # drifted week
    assert len(opened) == 1, opened
    cases = adapters.state.query("cases", {"agent_id": "payments"})
    assert len(cases) == 1
    case = cases[0]
    assert (case["case_type"], case["severity"], case["status"]) == ("drift", "medium", "open")
    assert "no rule fired" in case["summary"]
    # No gate rule fired: every seeded call was allowed.
    assert all(e.status == "allowed" for e in events if e.event_type == "gate_decision")

    payloads = [p for t, _, p in evidence.entries if t == "case_opened"]
    assert len(payloads) == 1
    p = payloads[0]
    assert_no_floats(p)
    assert p["monitor"] == "drift" and p["consecutive"] == 3
    breached = {m["metric"] for m in p["metrics"]}
    assert breached & {"tool_share_bp:transfer", "amount_p50", "amount_p90"}
    for m in p["metrics"]:
        assert m["value"] < m["band_low"] or m["value"] > m["band_high"]
        assert all(isinstance(m[k], int) for k in ("center", "mad", "band_low", "band_high"))
    assert [t for t, _, _ in evidence.entries].count("drift_baseline") == 1
    events_rows = adapters.tables.query("case_event", {"case_id": case["case_id"]})
    assert [r["action"] for r in events_rows] == ["opened"]
    print(
        f"[OK] drift: 1 case {case['case_id']} after windows "
        f"{p['window_from']}..{p['window_to']} metrics={sorted(breached)}"
    )


def test_two_normal_weeks_open_no_case(adapters, clock, evidence) -> None:
    events = drift_weeks(T0, normal_days=14, drift_days=0, seed=3)
    adapters.tables.append("agent_event", as_rows(events))
    monitor = DriftMonitor(_ctx(adapters, evidence))
    assert _run_daily(monitor, clock, 14) == []
    assert adapters.state.query("cases", {"agent_id": "payments"}) == []


def test_catch_up_in_one_run_and_threshold_override(adapters, clock, evidence) -> None:
    adapters.tables.append("agent_event", as_rows(drift_weeks(T0, normal_days=7, drift_days=7)))
    adapters.state.insert(
        "policy_threshold",
        {
            "agent_id": "*",
            "metric": "drift.consecutive",
            "threshold": 10,
            "unit": "windows",
            "effective_from": T0,
        },
    )
    monitor = DriftMonitor(_ctx(adapters, evidence))
    clock.advance(14 * 86400)  # app was down: one run catches up every missed window
    res = monitor.run()
    assert res.windows_checked == 7 and res.cases_opened == []  # 7 < 10 consecutive
    clock.advance(86400 * 3)
    assert monitor.run().cases_opened == []  # no new data: windows have no values


def test_window_metrics_need_min_samples() -> None:
    rows = as_rows(drift_weeks(T0, normal_days=1, drift_days=0, per_day=10))
    assert window_metrics(rows, [], min_n=20) == {}
    m = window_metrics(rows, [], min_n=5)
    assert sum(v for k, v in m.items() if k.startswith("tool_share_bp:")) <= 10000
    assert all(isinstance(v, int) for v in m.values())


def test_new_version_gets_its_own_baseline(adapters, clock, evidence) -> None:
    rows = as_rows(drift_weeks(T0, normal_days=7, drift_days=0))
    rows += as_rows(
        drift_weeks(T0 + timedelta(days=7), version="2.0.0", normal_days=0, drift_days=7)
    )
    adapters.tables.append("agent_event", rows)
    monitor = DriftMonitor(_ctx(adapters, evidence))
    _run_daily(monitor, clock, 14)
    # v2 traffic forms v2's own baseline: a new version is not drift of the old one.
    assert adapters.state.query("cases", {"agent_id": "payments"}) == []
    versions = {b["agent_version"] for b in adapters.state.query("policy_baseline", {})}
    assert versions == {"1.0.0", "2.0.0"}
