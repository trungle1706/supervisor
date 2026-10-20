# Gate latency (WP23)

How long the gate takes, how that was measured, what the numbers are, and what they do not say.
One tool makes every number here: `python -m tools.bench_latency`. The test
`tests/perf/test_gate_latency.py` runs the same code (`--quick`), so the test and this page cannot
drift. Design record: `docs/adr/D19-latency-benchmark.md`.

## Budgets

| Target | Budget | Status |
|---|---|---|
| Laptop, SQLite file | gate p99 under 50 ms | Asserted by `tests/perf/test_gate_latency.py` when `RUN_PERF=1` is set (about 25 s; the default suite skips it, like the WP22 rollup perf test). ILLUSTRATIVE until the bank sets it. Measured: 4.6 ms (19 rules), 6.8 ms (200 rules). |
| Databricks App, Delta | **FILL-ME: the owner must confirm** | Not measured (no workspace run yet). Candidates and the reason they differ are in "Delta" below. |

## Command

```
uv run python -m tools.bench_latency                  # full run, about 40 minutes, strict
uv run python -m tools.bench_latency --quick          # CI mode, about 40 seconds, no servers
uv run python -m tools.bench_latency --scenarios inproc,chain --backends sqlite_file --sizes 19
uv run python -m tools.bench_latency --compare bench\OLD.json bench\NEW.json
```

Output: `bench\latency-<commit>-<date>[-tag].json` and the same table as `.md`. Run it on a quiet
machine; the JSON records CPU, Python, versions, environment flags, commit, and the load average
before and after. Exit code 3 = the results were not reproducible (see "Reproducibility").

## What is measured

| Scenario | What one sample is |
|---|---|
| `gate_inproc` | `Gateway.check()` from call to answer, in process: agent-state and policy read, rule evaluation, verdict rows, `agent_event` row, signed evidence-chain record |
| `chain_append` | one `ChainWriter.record()` (hash, canonical JSON, two rows; a signed root every 100 entries) |
| `window_depth_N` | `gate_inproc` with N allowed events per tracked tool already in the 24-hour window (aggregate rules scan the window) |
| `asgi_gate`, `asgi_passthrough` | `POST /gate/check` through the real gate router and ops middleware, httpx ASGI transport (no socket), and the same request to a pass-through route |
| `uvicorn_gate`, `uvicorn_passthrough` | the same two requests to a real uvicorn process on a free local port (20000-29999) over loopback TCP |
| `otlp_inproc_Nspan`, `otlp_asgi_Nspan`, `otlp_uvicorn_Nspan` | `POST /v1/traces` (or the recorder call) with N = 1 or 20 spans: decode, normalise, mask, write |
| `mcp_direct`, `mcp_proxy` | one MCP `tools/call` over stdio to an echo server directly, and through `python -m supervisor.gateway.mcp_proxy` (which asks the gate over HTTP) |

Stack: the production composition root (`build_runtime`), so the policy comes from the rule table,
the chain is the signed `ChainWriter`, Tier 0b runs after the answer as in production. Only the clock
is fixed and moved by 120 s per gate call, which keeps the aggregate windows at a steady depth.
Policy sizes: 19 rules (`policies/baseline.yaml`) and 200 rules (baseline plus 181 generated:
50% simple predicates, 20% aggregate, 15% prior-call, 15% fact). The generated rules are scoped to
all three agents and never match the workload, so every call evaluates all 200 rules and the decision
is always the same. That is a worst case for evaluation cost, not a typical policy.
Workload: a seeded cycle of 8 calls over three agents (balance, transfer, fee waiver, application
fetch, ticket read, pre-qualification decision, payee list), unique ids, every call allowed; the
benchmark stops with an error if the gate denies a call, because a denied call is a different path.

Store backends:

| Backend | What it is |
|---|---|
| `sqlite_file` | the laptop default: SQLite file, WAL |
| `sqlite_memory` | SQLite in memory: code cost without disk |
| `databricks_fake` | **MOCK.** SQLite in memory plus the marshalling code of the Delta adapter (typed string parameters, the SDK's request and response classes, `from_db`). No warehouse, no network. It shows the code overhead of the Delta path and counts statements; it is not a Delta measurement. `--fake-rtt-ms N` adds a fixed sleep per statement to model a round trip |

## Method

- Clock: `time.perf_counter_ns` (monotonic). Values are integer microseconds.
- Percentiles: nearest rank, `sorted[ceil(p * n / 100) - 1]`, the same function as the product's
  `GateMetrics`. A test checks it against a definition-based reference on skewed samples.
- Warm-up (discarded), then a fixed count: 2,000 gate calls per repeat in process, 600 requests per
  repeat over HTTP (100 per second), 200 MCP calls per repeat.
- 3 repeats. The reported value is the median over the repeats of each statistic. Repeats take turns
  in slices of 100 calls (r1, r2, r3, r1, ...), so a slow moment on the shared host hits all three
  alike; the spread then measures the sampling noise of the statistic. Drift of the host between two
  runs is covered by the load average and by `--compare`.
- HTTP is open loop: requests leave on a fixed schedule and latency runs from the intended send time,
  so a slow reply cannot hide the queue behind it (coordinated omission; a unit test shows a stall
  is charged to the requests waiting behind it). The generator's own lateness is in the JSON
  (`generator_lag_us`, p99 about 1 ms). MCP over stdio is closed loop because a pipe carries one
  request at a time.
- GAF overhead, as in the Generative Application Firewall paper (arXiv 2601.15824, section on
  operational performance): `delta = p95(with gateway) - p95(without)`. "Without" is a pass-through
  route that decodes the same JSON, validates the same request model, takes the same thread hop and
  returns a fixed answer. The two arms alternate order.
- Components: one `breakdown` pass of 1,000 calls per combination: parse (JSON decode and request
  validation, timed on its own), policy evaluation (the gate's own decision time minus fact lookup),
  fact lookup, store write, chain append, the rest of the recording, and the thread hand-off. Fact
  lookup, store write and chain append come from wrappers around `facts.get`, `tables.append` and
  `evidence.record`; the decision time and total come from `Decision.latency_us` and `total_us`.
  Percentiles of components do not add up to the percentile of the total.

## Numbers

Machine: QEMU Virtual CPU version 2.5+ (16 vCPU virtual machine), Linux 6.8.0-147, CPython 3.11.17,
fastapi 0.143.1, uvicorn 0.54.0 (h11, no uvloop), httpx 0.28.1. A **shared** host: other projects'
services and test runs were active (load average 2.6 at the start). This is not a quiet lab machine.
Run 1 at commit `df28be5` (2026-10-20), file `bench\latency-df28be5-2026-10-20-run1.json`. Values are
integer microseconds, medians of 3 repeats; "p50 / p95 / p99 / max". The tool code at run 2 differs
from run 1 only by the `--tag` option.

### Gate, in process (the number the budget applies to)

| Store | Rules | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| sqlite_file (laptop) | 19 | 1527 | 2828 | **4635** | 7454 |
| sqlite_file (laptop) | 200 | 2424 | 4467 | **6777** | 54879 |
| sqlite_memory | 19 | 455 | 676 | 941 | 1526 |
| sqlite_memory | 200 | 991 | 1866 | 2498 | 15134 |
| databricks_fake (MOCK) | 19 | 682 | 1005 | 1372 | 3497 |
| databricks_fake (MOCK) | 200 | 1220 | 2137 | 3095 | 15584 |

Laptop SQLite p99 is about 10 times under the 50 ms budget with 19 rules and 7 times with 200. The
one 55 ms maximum is a single sample of 6,000 (a disk stall; the p99 is unaffected).

### Where the time goes (p50 / p95, one gate check, in process)

| Store | Rules | parse | policy eval | fact lookup | store write | chain append | other recording | thread hand-off | total |
|---|---|---|---|---|---|---|---|---|---|
| sqlite_file | 19 | 13 / 29 | 106 / 277 | 0 / 1 | 690 / 1166 | 616 / 944 | 99 / 154 | 50 / 153 | 1581 / 2552 |
| sqlite_file | 200 | 14 / 34 | 568 / 1470 | 0 / 8 | 785 / 1211 | 601 / 1073 | 154 / 194 | 56 / 166 | 2339 / 3787 |
| sqlite_memory | 200 | 11 / 23 | 516 / 1390 | 0 / 7 | 126 / 237 | 116 / 160 | 121 / 147 | 43 / 132 | 988 / 1867 |
| databricks_fake | 200 | 10 / 23 | 523 / 1403 | 0 / 7 | 281 / 414 | 213 / 253 | 125 / 148 | 48 / 142 | 1259 / 2158 |

- On a laptop the cost is writing, not thinking: store writes plus the chain are 80% of the p50 at
  19 rules. Evaluating 19 rules costs about 0.1 ms; 200 rules cost about 0.5 ms.
- Fact lookup is zero here because the fact source is an in-memory dict. A real system of record adds
  its own latency to every fact rule that fires (not measured).
- **Statements per check: 4.03 SQL statements, all writes**, in this order: `verdict`, `agent_event`,
  `chain_payload`, `chain_entry` (plus one signed root per 100 entries; Tier 0b adds one more
  asynchronous `verdict` row for tools that are not read-only, outside the caller's wait). Reads are cached: agent state for 1 s, the
  policy for 5 s, so on average one extra read per second per agent and per 5 s. This number is what
  the Delta estimate below multiplies.

### Aggregate window depth (200 rules, sqlite_memory)

| Allowed events per tool in the 24 h window | p50 | p95 | p99 | max |
|---|---|---|---|---|
| steady state of the other rows (about 100 to 200 per tool, 120 s per call) | 991 | 1866 | 2498 | 15134 |
| 1,000 | 1434 | 8971 | 9501 | 13302 |
| 10,000 | 3417 | **54907** | **58282** | 62045 |

Aggregate and prior-call rules scan the in-memory window, so cost grows with traffic, not with the
rule count alone. With 200 rules and 10,000 events per tool in the day (a tool called about 7 times a
minute around the clock), p99 passes the 50 ms budget. With 19 rules and 10,000 events the p99 is
5.2 ms. The window is also rebuilt from the store at start, which is not timed. Follow-up in
BACKLOG.md.

### HTTP, and the GAF overhead

| Transport | Store | Rules | gate p50 / p95 / p99 | pass-through p95 | delta p95 |
|---|---|---|---|---|---|
| uvicorn, loopback TCP | sqlite_file | 19 | 4699 / 6892 / 8432 | 3666 | **3226** |
| uvicorn, loopback TCP | sqlite_file | 200 | 5384 / 7560 / 11155 | 3566 | **3994** |
| uvicorn, loopback TCP | sqlite_memory | 19 | 3084 / 4133 / 5039 | 3626 | 507 |
| uvicorn, loopback TCP | sqlite_memory | 200 | 3733 / 5210 / 6583 | 3601 | 1609 |
| uvicorn, loopback TCP | databricks_fake (MOCK) | 200 | 4190 / 5665 / 7584 | 3585 | 2080 |
| ASGI transport | sqlite_file | 19 | 3937 / 7053 / 10521 | 2826 | 4227 |
| ASGI transport | sqlite_file | 200 | 4623 / 8075 / 28511 | 2839 | 5236 |

All rows are in the JSON and in `bench\*.md`. The pass-through itself costs about 2 ms at p50 because
the client, the ASGI stack, the JSON work and the thread hop are in it; the delta removes that.
The ASGI rows run the client and the server in one process and compete for the interpreter lock, so
they read higher than the uvicorn rows; quote the uvicorn rows. Conclusion: with the laptop store the
gate adds 3 to 4 ms at p95 to an HTTP call, and nearly all of it is the disk writes (0.5 to 1.6 ms
with the store in memory).

### MCP stdio proxy, per `tools/call`

| Store | Rules | direct p50 / p95 | via proxy p50 / p95 / p99 | delta p95 |
|---|---|---|---|---|
| sqlite_file | 19 | 45 / 66 | 8730 / 19905 / 24711 | 19839 |
| sqlite_file | 200 | 59 / 79 | 10536 / 21778 / 26916 | 21699 |

About 8.7 ms at p50. The proxy asks the gate over HTTP for every call (`HttpGate` calls `httpx.post`, which
builds a new client and a new connection for every call), so the cost is the gate's 4.7 ms plus the proxy's own connection, JSON and process hop. A keep-alive connection is a follow-up in
BACKLOG.md.

### HTTP MCP proxy, per `tools/call` (WP26)

Measured with `python -m supervisor.gateway.mcp_http_harness --gate-server -n 500 --repeats 3` on the
same method as above (monotonic clock, integer microseconds, warm-up of 100 calls discarded, nearest-rank
percentiles, median of 3 repeats, arms rotated between repeats). One closed-loop client over a kept-alive
connection, one `tools/call` of `get_balance` that the gate allows, loopback, SQLite file store, 19 rules.
Client, proxy, fake upstream, and gate run in ONE Python process (the interpreter lock is shared; the
stdio rows above use separate processes), so read the deltas, not the absolute values. The upstream is a
labelled MOCK (an in-process fake streamable-HTTP MCP server). Linux x86_64, 16 cores.

| Arm | p50 us | p95 us | What it is |
|---|---|---|---|
| `direct` | 177 | 290 | client to the fake server |
| `proxy_nolock_stubgate` | 1273 | 1559 | through the proxy, lock off, stub gate (MOCK): the cost of the extra hop, JSON, and one kept-alive upstream client |
| `proxy_lock_stubgate` | 1288 | 1539 | same, lock on (cached view): the lock costs 15 us at p50 |
| `proxy_lock_gate_inproc` | 3180 | 4410 | lock on, real `Gateway.check` in process (the 4.7 ms gate p50 of the stdio table is the same code plus its HTTP hop) |
| `proxy_lock_gate_http` | 11273 | 20222 | real gate over HTTP, a new connection per gate call, as `mcp_proxy` does |
| `proxy_lock_gate_http_pooled` | 5897 | 7155 | real gate over HTTP, kept-alive gate connection (`PooledJson`, the default of `mcp_http`) |

Delta of the default HTTP arm over direct: **p50 +5.7 ms, p95 +6.9 ms**. The pooled gate connection
halves the HTTP-gate cost (11.3 to 5.9 ms at p50). The lock alone is 15 us at p50 because `tools/call` reads
a cached view; every `MCP_LOCK_REFRESH_S` (60 s) one call also lists the upstream server and posts the
list to the app (one extra round trip). `tools/list` always lists the server and posts the list (about
the cost of two requests plus the hashing, no scan when nothing changed). Upstream connections reused:
3 TCP connections for about 10,000 calls.

Two measurement hazards found while building this (they apply to any arm that passes a socket to uvicorn
or serves with `http.server`): (1) a listening socket handed to `uvicorn.Server.run(sockets=...)` needs
`TCP_NODELAY` itself, otherwise every kept-alive answer waits 40 ms for the client's delayed ACK (a trivial
ASGI app measured 41 ms against 0.3 ms); (2) a `BaseHTTPRequestHandler` writes headers and body separately, so
the proxy and the fake server set `TCP_NODELAY` on every accepted socket. Not measured: TLS to the upstream
server, a real remote server, the Delta round trip (the `databricks_fake` backend is SQLite behind REST
marshalling and is only used for the quality metrics), OAuth, and a real network.

### OTLP ingest, `POST /v1/traces`

| Path | Store | 1 span p50 / p95 | 20 spans p50 / p95 | per span at p50 (20 / 20) |
|---|---|---|---|---|
| recorder in process | sqlite_file | 565 / 1393 | 3181 / 4506 | 159 |
| uvicorn, loopback TCP | sqlite_file | 3516 / 4946 | 7052 / 9077 | 353 |

Batching is worth it: over HTTP, 20 spans in one request cost 2 times a single span request, not 20 times.
Spans carry short synthetic texts with a phone and an account number so that the masker does its work.

### Evidence chain append

`chain_append`, sqlite_file, 19 rules: p50 573, p95 883, p99 1760, max 8372 us (in memory: p50 68).
Every 100th entry also writes a signed root.

## Delta (Databricks App): what is known and what is not

The benchmark cannot measure Delta. `databricks_fake` shows the code overhead of the Delta path
(gate p99 1.4 ms at 19 rules and 3.1 ms at 200 rules) and the number of statements. The round trip of
the Statement Execution API to a SQL warehouse needs the workspace. Run
`notebooks\latency_delta.py` there (replace every `FILL-ME`) from the same region as the App, once
quiet and once busy, once with a cold warehouse. It prints the same percentiles for a floor
`SELECT 1`, a state read, an insert-only `MERGE`, and the gate's statement sequence, and an estimate
of the gate p99.

What follows from the code, before any measurement:

1. A check issues **4 sequential write statements** (4.03 measured). Each is a REST call to the
   warehouse. Estimated gate latency is about `code overhead + 4 x statement round trip`. Statement
   round trip (p50 / p99) is **FILL-ME** until the notebook has run.
2. The recording is inside the caller's wait. `Gateway.check()` waits for the decision and the
   recording together, up to the 2 s hard timeout (`HARD_TIMEOUT_S`), then returns the decision that
   was already made. So on Delta the caller sees `min(4 x round trip, 2 s)` and never more than 2 s.
   Arithmetic only, not a measurement: at 100 ms per statement a check takes about 0.4 s, at 300 ms
   about 1.2 s, and from about 500 ms per statement the 2 s timeout is the typical answer time.
3. Budget candidates for the owner (ILLUSTRATIVE): (A) p99 within 2 s, the current ceiling, needs no
   code change but gives the agent a slow tool call at every step; (B) p99 within 500 ms, which needs
   recording moved off the response path (asynchronous or batched writes). B changes what the audit
   trail guarantees at the moment of the answer, so it needs an owner decision. See BACKLOG.md.

## Reproducibility

Rule (`reproducibility` in the JSON): across the 3 repeats of every result, p50 must stay within 10%
and p95 within 20%, ignoring spreads under 50 us (below the jitter of a virtual machine).
**This is a deviation from the phase 3 brief**, which asks for 10% on every reported number: here
only p50 has the 10% limit, p95 has 20% (ADR D19). p95 has the wider limit because it rests on the
slowest 5% of the samples. p99 and max are reported
and not gated: at 2,000 samples they stand on 20 observations or fewer.
In a full run a measurement that breaks the rule is run again, up to 4 tries; the tries used are in
the `tries` column and the `attempts` field. If a measurement never passes, the run prints the list
and exits with code 3 (the JSON is still written). `--quick` reports and does not enforce.

Run 1: 88 results; 72 passed at the first try, 16 needed 2 to 4 tries, and **2 never passed**:
`otlp_inproc_1span|sqlite_file|200` (p95 varied 57%) and `otlp_asgi_20span|databricks_fake|200`
(p50 varied 17%). Neither is a gate number. See "Run to run" for the second full run.

### Run to run

The two full runs were made 29 minutes apart on the same shared machine (commits `df28be5` and
`be69e65`; files `bench\latency-*-run1.json` and `-run2.json`; `--compare` prints the table).
Of 88 results, 75 have a p50 within 10% between the runs and 80 have a p95 within 20%. The
budget row repeats well:

| Gate in process | Rules | run 1 p50 / p95 / p99 | run 2 p50 / p95 / p99 |
|---|---|---|---|
| sqlite_file | 19 | 1527 / 2828 / 4635 | 1504 / 2199 / 4995 |
| sqlite_file | 200 | 2424 / 4467 / 6777 | 2226 / 4081 / 6580 |
| databricks_fake (MOCK) | 19 | 682 / 1005 / 1372 | 666 / 926 / 1331 |
| databricks_fake (MOCK) | 200 | 1220 / 2137 / 3095 | 1283 / 2299 / 3299 |

The results that moved most are the ones measured in tens of microseconds (`mcp_direct`), the
sub-millisecond in-memory rows (up to 17% in p50), and p95 on the disk store (up to 39% for
`uvicorn_gate` on `sqlite_file`, where a disk stall of a neighbour lands in the tail). Run 2 also
exited with code 3: three arms never passed (`asgi_gate|sqlite_file|19` p95, one sample set had a
52 ms stall; `otlp_uvicorn_20span|sqlite_file|200` p50 18%; `otlp_asgi_20span|sqlite_memory|200`
p50 14%). Take the p50 as good to about 10% and the p95 of the disk-backed rows as good to about
25% on this machine; p99 and max as indicative. A dedicated quiet host is the real fix (BACKLOG.md).

## Not measured

- Real Delta REST round trip: the warehouse, its queue, cold start, the network.
- Network: loopback and an in-process transport only; no router, proxy, load balancer or Databricks
  Apps front door.
- TLS: no handshake, no encryption.
- Ingress authentication (WP20) and SSO header checks are not in the request path.
- The agent's work, the tool call itself, any LLM or judge (judges are advisory and off the gate path).
- Tier 0b (the asynchronous regex classifier) runs as in production but after the answer; it shows only
  as contention in the next call.
- Real fact sources: an in-memory dict here.
- Many clients at once, several agents at once, more than one worker: one stream at a fixed rate.
  The chain has one writer by design, so a capacity test is a separate piece of work.
- Growth over days: the stores start empty in each combination.
- A quiet machine: all numbers come from a shared virtual machine.

## Files

`tools\bench_latency.py` (the benchmark), `tests\perf\test_gate_latency.py` (the 50 ms assertion on the
same code), `tests\perf\test_bench_latency.py` (the benchmark's own tests: percentile reference,
open-loop driver, stores agree, report shape), `notebooks\latency_delta.py` (Delta, in the
workspace), `bench\` (committed results).
