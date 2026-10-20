"""Rollup performance: 1,000,000 synthetic gate decisions on SQLite (WP22).

The rows are bulk loaded with a second SQLite connection (loading is not what is measured).
The rollup runs through the product code path, in 7-day chunks of grouped SQL, so no event
row is read into Python. Measured numbers go to the console with ``-s`` and to
``docs/tool-analytics.md``.

Run alone: RUN_PERF=1 uv run python -m pytest -q -s tests/analytics/test_perf.py
Rows: PERF_ROWS (default 1000000 with RUN_PERF=1; a smaller number only shortens the run, the
budget scales). Without RUN_PERF the normal suite runs 50,000 rows and checks the counts and
the memory bound only: a wall-clock budget is flaky on a loaded CI host, so it is opt-in.
"""

from __future__ import annotations

import os
import sqlite3
import time
import tracemalloc
from datetime import timedelta
from itertools import islice

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import build_adapters
from supervisor.analytics import tools
from supervisor.config import load_settings
from supervisor.core.canonical import format_ts
from supervisor.data import tool_usage
from supervisor.jobs import bootstrap_schema
from supervisor.monitors.common import MonitorContext
from tests.analytics.conftest import END, NOW
from tests.judge.conftest import MemoryEvidence

RUN_PERF = os.environ.get("RUN_PERF") == "1"
ROWS = int(os.environ.get("PERF_ROWS", "1000000" if RUN_PERF else "50000"))
# Measured on the dev box (see docs/tool-analytics.md): about 20 s per million rows with
# tracemalloc on. The budget is
# loose on purpose (a slow CI disk, a busy host) but still catches a quadratic mistake.
BUDGET_S_PER_MILLION = 90
PEAK_PYTHON_MB = 128
EVENT_COLS = (
    "event_id", "ts", "trace_id", "span_id", "agent_id", "caller_agent_id", "event_type",
    "tool_name", "args_masked", "status", "classification", "latency_ms", "latency_us", "env",
    "source", "capture_level",
)  # fmt: skip
PER_SCALE_UNIT = 5_330  # events for scale=1 over 90 days


@pytest.mark.perf
def test_rollup_one_million_decisions(tmp_path) -> None:
    settings = load_settings(data_dir=tmp_path / "data")
    adapters = build_adapters(settings, clock=FixedClock(NOW))
    bootstrap_schema.run(settings, adapters)
    scale = max(1, round(ROWS / PER_SCALE_UNIT))

    con = sqlite3.connect(str(settings.sqlite_path))
    marks = ", ".join("?" * len(EVENT_COLS))
    sql = f"INSERT INTO agent_event ({', '.join(EVENT_COLS)}) VALUES ({marks})"  # noqa: S608
    vsql = (
        "INSERT INTO verdict (verdict_id, ts, event_id, agent_id, tier, checker_id, is_mock, "
        "advisory, label, action) VALUES (?, ?, ?, ?, 0, ?, 0, 0, ?, ?)"
    )
    gen = tool_usage.generate(end_day=END, scale=scale)
    n = 0
    while chunk := list(islice(gen, 20_000)):
        con.executemany(
            sql,
            [tuple(format_ts(e[c]) if c == "ts" else e[c] for c in EVENT_COLS) for e, _ in chunk],
        )
        con.executemany(
            vsql,
            [
                (
                    v["verdict_id"],
                    format_ts(v["ts"]),
                    v["event_id"],
                    v["agent_id"],
                    v["checker_id"],
                    v["label"],
                    v["action"],
                )
                for _, v in chunk
                if v
            ],  # fmt: skip
        )
        n += len(chunk)
    con.commit()
    con.close()

    ctx = MonitorContext.from_adapters(adapters, MemoryEvidence())
    tracemalloc.start()
    t0 = time.perf_counter()
    out = tools.rollup(ctx, END - timedelta(days=89), END)
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    stored = ctx.state.query(tools.TABLE)
    total = sum(r["calls"] for r in stored)
    per_million = elapsed * 1_000_000 / n
    print(
        f"\n[OK] rollup of {n} decisions, 90 days: {elapsed:.1f} s "
        f"({per_million:.1f} s per million), {out['rows']} rows, "
        f"peak python memory {peak / 1e6:.0f} MB"
    )
    adapters.close()
    assert total == n, "every decision is counted exactly once"
    assert out["rows"] == len(stored) == out["inserted"]
    if RUN_PERF:
        assert per_million < BUDGET_S_PER_MILLION
    assert peak / 1e6 < PEAK_PYTHON_MB, "rollup must not load the events into memory"
    assert n > 0.9 * ROWS
