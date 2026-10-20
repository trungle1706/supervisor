"""Rollup correctness: against a brute-force computation, percentiles, boundaries, idempotence."""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime, timedelta

import pytest

from supervisor.analytics import tools
from supervisor.analytics.tools import AnalyticsError, percentile_from_histogram, rollup
from supervisor.data import tool_usage
from supervisor.monitors.common import MonitorContext, as_dt, percentile
from tests.analytics.conftest import END
from tests.analytics.reference import brute_force

START = END - timedelta(days=89)


def _day(v: object) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else as_dt(v).date()


def _stored(ctx: MonitorContext) -> dict:
    return {
        (_day(r["usage_date"]), r["agent_id"], r["tool_name"]): r
        for r in ctx.state.query(tools.TABLE)
    }


def test_rollup_matches_brute_force(ctx, loaded) -> None:
    events, verdicts = loaded
    out = rollup(ctx, START, END)
    ref = brute_force(events, verdicts)
    stored = _stored(ctx)
    assert set(stored) == set(ref)
    assert out["rows"] == len(ref) == out["inserted"]
    for key, want in ref.items():
        got = stored[key]
        for col in (
            "calls", "allows", "blocks", "pauses", "errors", "p50_us", "p95_us",
            "distinct_callers", "distinct_users",
        ):  # fmt: skip
            assert got[col] == want[col], (key, col)
        assert as_dt(got["first_seen"]) == want["first_seen"]
        assert as_dt(got["last_seen"]) == want["last_seen"]
        assert got["calls"] == got["allows"] + got["blocks"] + got["pauses"]
    assert sum(r["calls"] for r in stored.values()) == len(events)


def test_rollup_is_idempotent_and_overwrites_a_day(ctx, loaded) -> None:
    rollup(ctx, START, END)
    before = _stored(ctx)
    again = rollup(ctx, START, END)
    assert (again["inserted"], again["updated"]) == (0, 0) and again["unchanged"] == len(before)
    # a late event for one day: that day is recomputed, others are untouched
    day = END - timedelta(days=3)
    late = _ev(1, datetime(day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=UTC))
    late["event_id"] = "late-1"
    ctx.tables.append("agent_event", [late])
    third = rollup(ctx, START, END)
    assert (third["inserted"], third["updated"]) == (0, 1)
    after = _stored(ctx)
    key = (day, "payments", "transfer")
    assert after[key]["calls"] == before[key]["calls"] + 1
    assert as_dt(after[key]["last_seen"]) == late["ts"]


def test_percentile_from_histogram_equals_expanded_list() -> None:
    rng = random.Random(5)
    for _ in range(200):
        values = [rng.randrange(0, 60) for _ in range(rng.randrange(1, 80))]
        hist: dict[int, int] = {}
        for v in values:
            hist[v] = hist.get(v, 0) + 1
        for p in (1, 25, 50, 75, 95, 99, 100):
            assert percentile_from_histogram(hist.items(), p) == percentile(values, p)
    assert percentile_from_histogram([], 50) is None
    with pytest.raises(ValueError):
        percentile_from_histogram([(1, 1)], 0)


def test_percentile_known_values() -> None:
    # nearest rank: ceil(p*n/100)-th smallest
    hist = [(10, 1), (20, 1), (30, 1), (40, 1), (1000, 1)]
    assert percentile_from_histogram(hist, 50) == 30
    assert percentile_from_histogram(hist, 95) == 1000
    assert percentile_from_histogram([(7, 100)], 95) == 7


def _ev(i: int, ts: datetime, **kw) -> dict:
    row = {
        "event_id": f"b{i}", "ts": ts, "trace_id": f"t{i}", "span_id": f"s{i}",
        "agent_id": "payments", "event_type": "gate_decision", "tool_name": "transfer",
        "status": "allowed", "classification": "allow", "latency_ms": 1, "latency_us": 1500,
        "env": "test", "source": "proxy", "capture_level": "digest",
    }  # fmt: skip
    row.update(kw)
    return row


def test_day_boundaries_are_utc_midnight(ctx) -> None:
    d = date(2026, 10, 10)
    mid = datetime(2026, 10, 10, 0, 0, 0, tzinfo=UTC)
    ctx.tables.append(
        "agent_event",
        [
            _ev(1, mid - timedelta(microseconds=1)),  # last instant of Oct 9
            _ev(2, mid),  # first instant of Oct 10
            _ev(3, mid + timedelta(days=1) - timedelta(microseconds=1)),  # last of Oct 10
            _ev(4, mid + timedelta(days=1)),  # first of Oct 11
            _ev(5, mid, event_type="tool_call"),  # not a gate decision: ignored
            _ev(6, mid, tool_name=None),  # no tool: ignored
        ],
    )
    rollup(ctx, d - timedelta(days=1), d + timedelta(days=1))
    calls = {k[0]: r["calls"] for k, r in _stored(ctx).items()}
    assert calls == {d - timedelta(days=1): 1, d: 2, d + timedelta(days=1): 1}
    assert tools.rollup(ctx, d, d)["rows"] == 1  # a narrower range touches one day only


def test_legacy_rows_use_millisecond_latency(ctx) -> None:
    t = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)
    ctx.tables.append(
        "agent_event",
        [_ev(1, t, latency_us=None, latency_ms=3), _ev(2, t, latency_us=None, latency_ms=None)],
    )
    rollup(ctx, date(2026, 10, 10), date(2026, 10, 10))
    (row,) = _stored(ctx).values()
    assert (row["calls"], row["p50_us"], row["p95_us"]) == (2, 3000, 3000)


def test_error_counts_only_rule_error_verdicts(ctx) -> None:
    t = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)
    ctx.tables.append("agent_event", [_ev(1, t), _ev(2, t), _ev(3, t)])
    base = {
        "ts": t, "agent_id": "payments", "tier": 0, "checker_id": "gate.tier0a",
        "is_mock": False, "advisory": False, "action": "allow",
    }  # fmt: skip
    ctx.tables.append(
        "verdict",
        [
            {**base, "verdict_id": "v1", "event_id": "b1", "label": "rule_error"},
            {**base, "verdict_id": "v2", "event_id": "b1", "label": "rule_error"},  # same event
            {**base, "verdict_id": "v3", "event_id": "b2", "label": "matched"},
        ],
    )
    rollup(ctx, date(2026, 10, 10), date(2026, 10, 10))
    (row,) = _stored(ctx).values()
    assert (row["calls"], row["errors"]) == (3, 1)


def test_distinct_counts_use_hashes_only(ctx) -> None:
    t = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)

    def keys(h: str | None) -> str:
        return json.dumps({"keys": {"customer_id": h}}) if h else "not json"

    ctx.tables.append(
        "agent_event",
        [
            _ev(1, t, args_masked=keys("aa"), caller_agent_id="x"),
            _ev(2, t, args_masked=keys("aa"), caller_agent_id="y"),
            _ev(3, t, args_masked=keys("bb"), caller_agent_id="x"),
            _ev(4, t, args_masked=keys(None)),  # malformed json must not break the query
            _ev(5, t, args_masked=None),
        ],
    )
    rollup(ctx, date(2026, 10, 10), date(2026, 10, 10))
    (row,) = _stored(ctx).values()
    assert (row["distinct_users"], row["distinct_callers"]) == (2, 2)
    assert "aa" not in repr(row)  # only counts are stored


def test_risk_class_comes_from_policy_catalogue(ctx, loaded) -> None:
    rollup(ctx, END - timedelta(days=1), END)
    risk = {r["tool_name"]: r["risk_class"] for r in ctx.state.query(tools.TABLE)}
    assert risk["transfer"] == "money" and risk["get_balance"] == "read_only"
    assert risk["decide_prequal"] == "credit" and risk["fetch_application"] == "pii_export"


def test_bad_range_is_a_user_error(ctx) -> None:
    with pytest.raises(AnalyticsError):
        rollup(ctx, END, END - timedelta(days=1))


def test_chunking_does_not_change_the_result(ctx, loaded, monkeypatch) -> None:
    events, verdicts = loaded
    monkeypatch.setattr(tools, "CHUNK_DAYS", 1)
    rollup(ctx, START, END)
    assert {k: v["calls"] for k, v in _stored(ctx).items()} == {
        k: v["calls"] for k, v in brute_force(events, verdicts).items()
    }


def test_generator_is_deterministic() -> None:
    def sig(**kw):
        return [e["event_id"] + e["ts"].isoformat() + str(e["latency_us"])
                for e, _ in tool_usage.generate(days=5, **kw)]  # fmt: skip

    assert sig() == sig() and sig() != sig(seed=1)
