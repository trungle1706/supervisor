# D19 - Latency benchmark method

Status: Accepted (WP23, 2026-10-20). Budgets for the Databricks App are open (owner).

## Context

`tests/perf/test_gate_latency.py` asserted p99 under 50 ms on SQLite only and published no numbers. The NeuralTrust paper (Generative Application Firewall) defines overhead as `delta = p95(with gateway) - p95(without)`. A bank reviewer (SRE, performance engineer) needs numbers that can be reproduced, with the method and the gaps stated.

## Decision

- One tool, `python -m tools.bench_latency`, is the only source of latency numbers. `tests/perf/test_gate_latency.py` calls the same functions (`run_suite`, `--quick` options), so the test and the published table cannot drift. The 50 ms p99 assertion stays (laptop SQLite, ILLUSTRATIVE until the bank sets it).
- The stack under test is the production composition root (`build_runtime`): real policy store, `StorePolicyProvider`, signed `ChainWriter`, gateway with Tier 0b on. Only the clock is fixed and moved by a fixed step per call, so aggregate windows have a bounded, repeatable depth. Window depth is a separate scenario (`window_depth_*`), because aggregate rules scan the window.
- Time: `perf_counter_ns` (monotonic), integer microseconds. Percentiles: nearest rank, the same function as `GateMetrics.percentile`; a test checks it against a definition-based reference on skewed distributions.
- Warm-up discarded, fixed iteration counts, 3 repeats, reported value = median of the repeats of each statistic, all repeats kept in the JSON.
- HTTP arms are open loop on a fixed schedule; latency runs from the intended send time (no coordinated omission). The MCP stdio arm is closed loop because a stdio pipe carries one request at a time.
- GAF delta: gate endpoint against a pass-through endpoint that does the same JSON decode, the same request validation and the same thread hop, then returns a fixed answer. Arms alternate order across repeats.
- Reproducibility rule: across the 3 repeats of every result, p50 must stay within 10 percent and p95 within 20 percent; spreads under 50 us are ignored. This deviates from the phase 3 brief, which asks for 10 percent on every reported number. Reason: p95 rests on the slowest 5 percent of the samples, and on a shared VM a single disk stall of a neighbour lands there; with 10 percent on p95 the two full runs failed on disk-backed rows that are not gate budget rows. The p50 keeps the 10 percent limit. A dedicated quiet host would allow 10 percent on both (BACKLOG). Strict (full) runs repeat a failing measurement (all its arms, 3 repeats each) up to 4 times and fail with a message if it never holds; the tries used are stored with each result and the host load average is in the JSON. `--quick` reports but does not enforce. p99 and max are reported, not gated: with 2,000 samples they rest on 20 or fewer observations.
- `databricks_fake` = SQLite in memory plus the REST marshalling code of the Delta adapter (`to_param`, SDK parameter and response classes, `from_db`). It measures code overhead and counts statements per check. It is labelled MOCK everywhere. Real Delta latency comes from `notebooks/latency_delta.py`, run in the workspace.

## Consequences

- A full run takes about 30 minutes and needs a quiet host; the JSON records the load average so a reader can judge it.
- The number of SQL statements per check is a result in its own right: on Delta, check latency is roughly code overhead plus statements times the Statement Execution round trip (see `docs/latency.md`).
- Recording (verdict rows, agent_event row, chain entry) happens inside the 2 s gate timeout, in the caller's wait. See `docs/latency.md` for the consequence on Delta and the BACKLOG entry.

## Open

1. The p99 budget for the Databricks App (owner).
2. Whether recording should leave the response path on Delta (asynchronous or batched), which changes what "decision latency" means for the audit trail.
