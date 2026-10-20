# HANDOFF WP23: latency benchmark

Branch: this worktree (base `bf3a23a`, v0.2.0). Commits: `cfd66e8`, `683ccb2`, `f88348e`, `b4a03cf`, `df28be5`, `be69e65` and the final one with docs, results and this file.

## What was built

| Item | File |
|---|---|
| Benchmark, `python -m tools.bench_latency` | `tools/bench_latency.py` |
| Perf test on the same code path (`--quick` options), 50 ms p99 assertion kept | `tests/perf/test_gate_latency.py` |
| Tests of the benchmark itself (22 in `tests/perf`) | `tests/perf/test_bench_latency.py` |
| Page: method, numbers, budgets, what is not measured | `docs/latency.md` |
| ADR D14 (method decisions) | `docs/adr/D14-latency-benchmark.md` |
| Delta round-trip notebook, `FILL-ME` names | `notebooks/latency_delta.py` |
| Results, two full runs, JSON and Markdown | `bench/latency-df28be5-2026-10-20-run1.*`, `bench/latency-be69e65-2026-10-20-run2.*` |

No new setting, no new dependency, no schema change, no change under `src/`. The benchmark builds the production
composition root (`build_runtime`) and drives it. Nothing is on or off by flag; it only runs when you start it.

## Commands

```
uv run python -m tools.bench_latency                 # full, strict, about 40 min, exit 3 if not reproducible
uv run python -m tools.bench_latency --quick         # CI, about 40 s, no servers, spread reported not enforced
uv run python -m tools.bench_latency --compare bench\A.json bench\B.json
uv run python -m pytest -q tests/perf                # 22 tests, about 30 s
make bench / make bench-quick
```

Scenarios: gate in process, chain append, window depth, HTTP `/gate/check` (httpx ASGI and a real uvicorn child on a
free port in 20000-29999 started through `sandbox.start_pipes`), OTLP `/v1/traces` (1 and 20 spans; in process, ASGI,
uvicorn), MCP stdio proxy per `tools/call` (with and without the proxy). Stores: `sqlite_file`, `sqlite_memory`,
`databricks_fake` (MOCK: SQLite plus the Delta adapter's marshalling code; labelled mock everywhere). Policy sizes 19
and 200 (181 generated rules: simple, aggregate, prior, fact).

Method points the SRE reviewer asked for: monotonic clock, integer microseconds, discarded warm-up, fixed counts,
3 repeats with median reported, repeats interleaved in slices, open-loop HTTP with latency from the intended send
time (unit test proves a stall is charged to the requests behind it), nearest-rank percentiles tested against a
definition-based reference and against `GateMetrics.percentile`, GAF delta `p95(gate) - p95(pass-through)`,
per-component breakdown, CPU/Python/commit/env flags/load average in the JSON, reproducibility rule enforced with
retries and exit code 3.

## Headline numbers (this machine: QEMU Virtual CPU 2.5+, 16 vCPU shared VM, CPython 3.11.17, load 2 to 3)

Gate in process, laptop SQLite file, p99: 4.6 ms (19 rules), 6.8 ms (200 rules) against the 50 ms budget. Run 2:
5.0 and 6.6 ms. HTTP GAF delta p95 over uvicorn: +3.2 ms (19 rules), +4.0 ms (200 rules); with the store in memory
+0.5 and +1.6 ms. MCP proxy per call: p50 8.7 ms. Statements per gate check: 4.03, all writes. Code overhead of the
Delta path (`databricks_fake`): p99 1.4 ms (19) and 3.1 ms (200). Details: `docs/latency.md`.

## Findings that matter to the owner or to other WPs

1. **Delta latency is unknown and structurally large.** Each check does 4 sequential write statements, inside the
   caller's wait and the 2 s `HARD_TIMEOUT_S`. The caller sees `min(code + 4 x round trip, 2 s)`. From about 500 ms
   per statement the timeout is the typical answer time (arithmetic, not a measurement). The Databricks App budget
   is left as FILL-ME in `docs/latency.md`; candidates A (within 2 s) and B (within 500 ms, needs recording off the
   response path) are in the page. Owner decision.
2. **Aggregate and prior-call rules scan the in-memory window**: with 200 rules and 10,000 allowed events per tool in
   the day, p99 is 58 ms (over the 50 ms budget); at 1,000 events p99 is 9.5 ms. At 19 rules it is 5.2 ms. Outside
   WP23 to fix (`gateway/engine.py` `WindowStore`); in BACKLOG.
3. **MCP stdio proxy** calls the gate through `HttpGate` -> `httpx.post`, a new client and connection for every call.
   p50 8.7 ms against 4.7 ms for the gate call. Outside WP23 (WP26 builds the HTTP MCP gateway; keep-alive belongs
   there); in BACKLOG.
4. Gate timeout semantics on Delta are worth a design look when WP20/WP21 touch the response path.

## Test counts

Before (main, per brief): 2791 pass. After: `2810 passed, 28 skipped` (`python -m pytest -q -x`, 5 min 40 s), ruff
check and format clean. `tests/perf`: 1 test before, 22 now. No existing test was reduced or skipped.

## Reproducibility result, stated plainly

Run 1: 88 results, 72 passed the spread rule at the first try, 16 needed 2 to 4 tries, 2 never passed (not gate
numbers) and the run exited 3. Run 2: 21 needed retries, 3 never passed, exit 3. Run to run (29 minutes apart): 75 of
88 p50 within 10%, 80 of 88 p95 within 20%; the budget rows agree within 8%. Cause: a shared VM with other projects
running; disk-backed p95 and microsecond-scale arms move most. The rule is p50 within 10% and p95 within 20%, spreads
under 50 us ignored (p95 has the wider limit because it rests on the slowest 5% of samples; this is a deviation from
"10% on everything" in the brief and is argued in D14). A quiet, dedicated host would be the proper fix (BACKLOG).
Both JSON files are committed with their failures listed; nothing was edited by hand.

## Not done

- Real Delta numbers (needs the workspace; notebook ready). Databricks App budget (owner).
- Capacity and multi-client tests, TLS, ingress auth (WP20) in the path, network, real fact-source latency, growth over
  days (all listed in `docs/latency.md` "Not measured").
- The 200-rule policy is a worst case for evaluation (all rules scoped to all agents, none match); a real policy mix
  from the bank would be more honest.
- The ASGI arms run client and server in one process (GIL contention), so quote the uvicorn arms.
- No threat-model paragraph: the benchmark starts only a loopback server and local child processes in a temp dir and
  touches no trust boundary of the product.

## Open questions for the owner

1. The Databricks App p99 budget (A: within 2 s, B: within 500 ms with asynchronous recording).
2. Should recording move off the response path on Delta (changes the audit guarantee at answer time)?
3. Is 10% p50 and 20% p95 acceptable as the reproducibility rule, or is a dedicated benchmark host available?
4. Is a 200-rule worst case the right size to publish, or does the bank have a realistic policy to use?

## Files touched

New: `tools/bench_latency.py`, `tests/perf/test_bench_latency.py`, `docs/latency.md`, `docs/adr/D14-latency-benchmark.md`,
`notebooks/latency_delta.py`, `bench/*` (4 files), `HANDOFF_WP23.md`.
Changed: `tests/perf/test_gate_latency.py` (owned), `README.md` (one Capabilities row, minimal), `BACKLOG.md` (6 rows
appended), `docs/index.md` (one row, ADR range D01 to D14), `Makefile` (two targets `bench`, `bench-quick`).
Shared files `config.py`, `app.py`, DDL, `schema/model.yaml`: not touched.

## Self-review

R1 (judges never block): not touched. R2 (no PII in chain or prompts): the benchmark's OTLP text carries synthetic
phone and account numbers on purpose; they go through the masker and the recorder, not into the chain; no LLM is
called. R3 (offline): loopback only, no outbound call. No `.env` or token read (`SUPERVISOR_ENV_FILE` points to an
absent file inside the temp dir; `isolated_env` clears inherited backend variables). No `eval`, `exec`, `subprocess`
(child processes go through `sandbox.start_pipes`). Ports: 20000-29999 only, checked against the forbidden list. No
`pkill`. No 500s added. Output is ASCII. Nothing is on by default.
