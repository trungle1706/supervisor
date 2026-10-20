"""WP23: the benchmark's own correctness (statistics, open-loop driver, stores, policy, report).

A latency number is only worth quoting when the tool that made it is checked. These tests run
in the normal suite and take a few seconds."""

from __future__ import annotations

import asyncio
import json
import random
import re
from fractions import Fraction
from pathlib import Path

import pytest

from supervisor.gateway.policy import load_policy_dir
from tools import bench_latency as bl

# --------------------------------------------------------------------------- percentiles


def reference_percentile(values: list[int], p: int) -> int:
    """Definition of the nearest-rank percentile, no sorting tricks and no index arithmetic:
    the smallest sample x such that at least p percent of all samples are <= x."""
    n = len(values)
    for x in sorted(set(values)):
        if Fraction(sum(1 for v in values if v <= x), n) >= Fraction(p, 100):
            return x
    raise AssertionError("unreachable")


def test_percentile_known_values() -> None:
    uniform = list(range(1, 101))  # 1..100: the p-th percentile is p
    assert [bl.percentile(uniform, p) for p in (50, 95, 99, 100)] == [50, 95, 99, 100]
    thousand = list(range(1, 1001))
    assert [bl.percentile(thousand, p) for p in (50, 95, 99)] == [500, 950, 990]
    spike = [10] * 99 + [1_000_000]  # one outlier: p99 ignores it, max shows it
    assert bl.percentile(sorted(spike), 99) == 10
    assert bl.summarise(spike)["max"] == 1_000_000
    assert bl.percentile([], 99) == 0
    assert bl.percentile([7], 50) == bl.percentile([7], 99) == 7


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_percentile_matches_reference_on_skewed_distributions(seed: int) -> None:
    rng = random.Random(seed)
    for n in (1, 2, 3, 10, 99, 100, 101, 997, 2000):
        samples = [int(rng.expovariate(1 / 800)) + rng.choice([0, 0, 0, 5000]) for _ in range(n)]
        ordered = sorted(samples)
        for p in (1, 25, 50, 90, 95, 99):
            assert bl.percentile(ordered, p) == reference_percentile(samples, p), (seed, n, p)


def test_percentile_matches_gate_metrics() -> None:
    """The benchmark and the product report the same statistic."""
    from supervisor.gateway.engine import GateMetrics

    rng = random.Random(9)
    ordered = sorted(rng.randrange(1, 10_000) for _ in range(777))
    for p in (50, 95, 99):
        assert bl.percentile(ordered, p) == GateMetrics.percentile(ordered, p)


def test_median_spread_and_repeats() -> None:
    assert bl.median_int([3, 1, 2]) == 2
    assert bl.median_int([1, 2, 3, 10]) == 2  # lower integer mean of 2 and 3
    assert bl.spread_bp([100, 100, 100]) == 0
    assert bl.spread_bp([95, 100, 105]) == 1000  # +-5 percent = 10 percent wide = 1000 bp
    reps = [bl.summarise(range(1, 101)), bl.summarise(range(2, 102)), bl.summarise(range(3, 103))]
    agg = bl.aggregate_repeats(reps)
    assert agg["median"]["p50"] == 51 and agg["median"]["max"] == 101


def test_reproducibility_rule_flags_and_passes() -> None:
    steady = {"id": "a", "repeats": [{"p50": 100, "p95": 200}, {"p50": 104, "p95": 195}] * 2}
    noisy = {"id": "b", "repeats": [{"p50": 100, "p95": 200}, {"p50": 100, "p95": 300}]}
    assert bl.reproducibility_failures([steady], 1000) == []
    msgs = bl.reproducibility_failures([noisy], 1000)
    assert len(msgs) == 1 and "b: p95 varies" in msgs[0] and "tolerance 10%" in msgs[0]
    assert bl.reproducibility_failures([noisy], 1000, abs_floor_us=200) == []
    # p95 has its own, wider tolerance: 200 -> 300 is a 40% spread
    assert bl.reproducibility_failures([noisy], 1000, tolerance_p95_bp=5000) == []
    assert len(bl.reproducibility_failures([noisy], 1000, tolerance_p95_bp=2000)) == 1
    # p50 keeps the tight tolerance even when p95 is wide
    wobbly_p50 = {"id": "c", "repeats": [{"p50": 100, "p95": 200}, {"p50": 130, "p95": 200}]}
    assert (
        "c: p50 varies" in bl.reproducibility_failures([wobbly_p50], 1000, tolerance_p95_bp=5000)[0]
    )


def test_stable_retries_until_the_spread_is_small() -> None:
    calls = {"n": 0}

    def good(p50: int) -> dict[str, int]:
        return {
            "n": 10,
            "min": 1,
            "p50": p50,
            "p95": 2 * p50,
            "p99": 3 * p50,
            "max": 4 * p50,
            "mean": p50,
        }

    def measure() -> dict[str, tuple[list[dict[str, int]], dict]]:
        calls["n"] += 1
        # the first two tries are noisy, the third is steady
        reps = [good(1000), good(1500), good(1000)] if calls["n"] < 3 else [good(1000)] * 3
        return {"arm": (reps, {})}

    opts = bl.Options(attempts=4, strict=True)
    out, tries = bl._stable(opts, "unit", measure)
    assert tries == 3 and out["arm"][0][1]["p50"] == 1000
    calls["n"] = 0
    out, tries = bl._stable(bl.Options(attempts=2, strict=True), "unit", measure)
    assert tries == 2  # gives up after the allowed tries; the caller then reports the failure
    calls["n"] = 0
    assert bl._stable(bl.Options(attempts=4, strict=False), "unit", measure)[1] == 1


# --------------------------------------------------------------------------- open loop


def test_open_loop_driver_does_not_hide_a_stall() -> None:
    """Coordinated omission: a closed loop that waits for the slow reply sends nothing during the
    stall, so it records one slow sample. The open-loop driver keeps the schedule and charges
    the waiting requests with the time they spent in the queue."""

    async def run() -> bl.DriveResult:
        lock = asyncio.Lock()
        first = {"done": False}

        async def send(_: bytes) -> bool:
            async with lock:  # one request at a time, like a single-threaded server
                if not first["done"]:
                    first["done"] = True
                    await asyncio.sleep(0.25)  # the stall
                else:
                    await asyncio.sleep(0.002)
            return True

        return await bl.drive_open_loop(send, [b"x"] * 25, rate_hz=50)

    res = asyncio.run(run())
    lat = sorted(res.latency_us)
    assert res.errors == 0
    # 12 requests are due during the 250 ms stall; every one of them reports a wait >= 100 ms
    assert sum(1 for v in lat if v >= 100_000) >= 8
    assert bl.percentile(lat, 95) >= 150_000
    # the schedule itself held: the generator was never late by more than a few ms
    assert bl.percentile(sorted(res.lag_us), 99) < 50_000


def test_open_loop_counts_errors_and_denials() -> None:
    async def run() -> bl.DriveResult:
        n = {"i": 0}

        async def send(_: bytes) -> bool | None:
            n["i"] += 1
            return None if n["i"] == 2 else (False if n["i"] == 3 else True)

        return await bl.drive_open_loop(send, [b"x"] * 5, rate_hz=500)

    res = asyncio.run(run())
    assert (res.errors, res.denied) == (1, 1)
    with pytest.raises(bl.BenchError, match="failed"):
        bl._check_drive(res, "unit")


# --------------------------------------------------------------------------- policy + workload


def test_generated_policy_has_all_rule_types(tmp_path: Path) -> None:
    for size in (19, 200):
        d = tmp_path / str(size)
        assert bl.write_policy_dir(d, size) == size
        policy = load_policy_dir(d)
        assert len(policy.rules) == size
    kinds = {"aggregate": 0, "prior": 0, "fact": 0, "simple": 0}
    for r in policy.rules:
        if r.aggregate:
            kinds["aggregate"] += 1
        elif r.prior:
            kinds["prior"] += 1
        elif any(p.arg.startswith("fact.") for p in (r.when.all or [])):
            kinds["fact"] += 1
        else:
            kinds["simple"] += 1
    assert all(v >= 5 for v in kinds.values()), kinds
    assert len({r.id for r in policy.rules}) == 200


def test_workload_is_deterministic_and_unique() -> None:
    a, b = bl.Workload(7), bl.Workload(7)
    seq_a = [a.next() for _ in range(300)]
    assert seq_a == [b.next() for _ in range(300)]
    ids = [c[3].get("account_id") or c[3].get("application_id") for c in seq_a]
    fetched = {c[3]["application_id"] for c in seq_a if c[2] == "fetch_application"}
    decided = [c[3]["application_id"] for c in seq_a if c[2] == "decide_prequal"]
    assert decided and all(x in fetched for x in decided)  # every decision reads a fetched app
    assert len(set(ids) - {None}) > 100


def test_git_head_is_a_commit_hash() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", bl.git_head())


# --------------------------------------------------------------------------- stores


def test_stores_agree_and_fake_delta_is_labelled(tmp_path: Path) -> None:
    """The same call stream gets the same decisions on every backend; the fake says it is a mock."""
    decisions: dict[str, list[tuple[str, str | None]]] = {}
    for backend in bl.BACKENDS:
        wd = tmp_path / backend
        wd.mkdir()
        with bl.isolated_env(wd):
            stack = bl.build_stack(backend, 19, wd)
            try:
                wl = bl.Workload(3)
                out = []
                for _ in range(120):
                    stack.clock.advance(stack.sim_step_s)
                    a, v, t, args = wl.next()
                    r = stack.gateway.check(a, v, t, args)
                    out.append((r["action"], r["rule_id"]))
                decisions[backend] = out
                assert stack.executor.n_execute > 0 and stack.executor.n_query >= 0
                if backend == "databricks_fake":
                    assert "MOCK" in stack.executor.describe()
            finally:
                stack.close()
    assert decisions["sqlite_file"] == decisions["sqlite_memory"] == decisions["databricks_fake"]
    assert all(act == "allow" for act, _ in decisions["sqlite_file"])


def test_breakdown_components_are_consistent(tmp_path: Path) -> None:
    with bl.isolated_env(tmp_path):
        stack = bl.build_stack("sqlite_memory", 19, tmp_path)
        try:
            bd = bl.run_breakdown(stack, bl.Workload(5), 60, 20)
        finally:
            stack.close()
    comps = bd["components_us"]
    assert set(comps) >= {"parse", "policy_eval", "fact_lookup", "store_write", "chain_append"}
    assert comps["total"]["p50"] >= comps["chain_append"]["p50"] > 0
    assert comps["total"]["p50"] >= comps["store_write"]["p50"] > 0
    assert bd["statements"]["execute_per_check_x100"] > 0


def test_http_pair_and_otlp_through_asgi(tmp_path: Path) -> None:
    """Gate and pass-through both answer 200 through the real routers; OTLP spans are stored."""
    with bl.isolated_env(tmp_path):
        stack = bl.build_stack("sqlite_memory", 19, tmp_path)
        try:
            from supervisor.gateway import wiring

            app = bl.build_bench_app(stack)
            make = bl.asgi_client_factory(app)
            plan = bl.HttpPlan(n=20, warm=5, rate_hz=200)
            out = bl.run_http_gate_pair(make, plan, bl.Workload(2), 0)
            assert len(out["gate"][0]) == len(out["passthrough"][0]) == 20
            lat, meta = bl.run_http_otlp(make, plan, 3, 1)
            assert len(lat) == 20 and meta["spans_per_request"] == 3
            rows = stack.runtime.adapters.tables.query("agent_event", {"event_type": "tool_call"})
            assert len(rows) >= 20 * 3
            wiring.set_gateway(None)
        finally:
            stack.close()


# --------------------------------------------------------------------------- report


def test_quick_report_shape_and_outputs(tmp_path: Path) -> None:
    opts = bl.Options.quick_mode(
        scenarios=("inproc", "chain"), sizes=(19,), n=60, warm=20, repeats=3
    )
    report = bl.run_suite(opts)
    assert report["schema"] == bl.SCHEMA and report["mode"] == "quick"
    env = report["environment"]
    for key in ("commit", "python", "cpu_model", "env_flags", "date_utc", "load_avg_1_5_15"):
        assert key in env
    assert len(report["results"]) == 2
    for res in report["results"]:
        assert len(res["repeats"]) == 3
        for stat in ("p50", "p95", "p99", "max"):
            assert isinstance(res["median"][stat], int) and res["median"][stat] > 0
        assert res["median"]["p50"] <= res["median"]["p95"] <= res["median"]["p99"]
        assert res["median"]["p99"] <= res["median"]["max"]
    assert report["not_measured"] and "Delta" in report["not_measured"][0]
    jpath, mpath = bl.write_outputs(report, tmp_path)
    assert jpath.name.startswith("latency-") and jpath.suffix == ".json"
    assert json.loads(jpath.read_text(encoding="utf-8"))["schema"] == bl.SCHEMA
    assert "| Scenario |" in mpath.read_text(encoding="utf-8")


def test_unknown_backend_and_scenario_are_user_errors(tmp_path: Path) -> None:
    with bl.isolated_env(tmp_path), pytest.raises(bl.BenchError, match="unknown backend"):
        bl.build_stack("oracle", 19, tmp_path)
    assert bl.main(["--quick", "--scenarios", "nope", "--out-dir", str(tmp_path)]) == 2
