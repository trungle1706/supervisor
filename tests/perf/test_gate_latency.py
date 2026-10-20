"""Tier 0a latency budget (ADR D02, WP23): p99 under 50 ms on the laptop SQLite path.

The test runs the benchmark itself (``python -m tools.bench_latency --quick``, scenario
``inproc``), so the test and the published numbers use one code path and cannot drift apart.
Each check is the full gate path: policy and agent state read, rule evaluation (19 rules and
200 mixed rules), verdict and agent_event append, signed evidence chain record.
Run alone: uv run python -m pytest -q -s tests/perf
Full benchmark and the numbers: docs/latency.md.
"""

from __future__ import annotations

import pytest

from tools import bench_latency as bl

P99_BUDGET_US = bl.GATE_BUDGET_P99_US  # 50_000


@pytest.mark.perf
def test_gate_latency_p99_under_50ms() -> None:
    opts = bl.Options.quick_mode(
        backends=("sqlite_file",), sizes=(19, 200), scenarios=("inproc",), n=800, warm=100
    )
    report = bl.run_suite(opts)
    results = report["results"]
    assert {r["rules"] for r in results} == {19, 200}
    for res in results:
        med = res["median"]
        print(
            f"\n[OK] gate end to end, {res['backend']}, {res['rules']} rules, "
            f"{med['n']} checks x {len(res['repeats'])} repeats (us): "
            f"p50={med['p50']} p95={med['p95']} p99={med['p99']} max={med['max']}"
        )
        assert all(isinstance(med[k], int) for k in ("p50", "p95", "p99"))
        # the reported statistic is the median over the repeats (one disk stall on a shared
        # host can move a single repeat's p99; the median cannot be moved by one repeat)
        assert med["p99"] < P99_BUDGET_US, f"{res['id']}: p99 {med['p99']} us over budget"
