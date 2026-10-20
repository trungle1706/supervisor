# Databricks notebook source
# MAGIC %md
# MAGIC # Supervisor: gate latency on Delta (WP23 live test kit)
# MAGIC
# MAGIC `python -m tools.bench_latency` cannot measure Delta: its `databricks_fake` store is SQLite plus the
# MAGIC adapter's marshalling code, with no warehouse and no network. This notebook measures the part that is
# MAGIC missing: the round trip of the Statement Execution API (the path `adapters/sql/databricks_rest.py`
# MAGIC uses) from the place where the App runs, to the SQL warehouse the App uses, as your identity.
# MAGIC
# MAGIC What it does, in your own schema (scratch table `PREFIX + "probe"`, dropped at the end):
# MAGIC 1. `SELECT 1` = the floor (warehouse queue + network + TLS, no table);
# MAGIC 2. a state read: one row by key (what the gate does for agent state and policy refresh);
# MAGIC 3. an insert-only `MERGE` into an append-only table (the shape of `SqlTableStore.append`);
# MAGIC 4. the gate sequence: `READS_PER_CHECK` reads then `WRITES_PER_CHECK` writes, one after the other.
# MAGIC    Item 4 is the number to compare with the budget: it is what one `/gate/check` adds on Delta.
# MAGIC
# MAGIC Method is the same as the laptop benchmark: warm-up discarded, monotonic clock, integer microseconds,
# MAGIC nearest-rank p50/p95/p99/max, 3 repeats, median of the repeats, spread of p50 and p95 checked
# MAGIC against 10 percent. Closed loop (one statement at a time) on purpose: the gate itself runs its
# MAGIC statements in sequence.
# MAGIC
# MAGIC How to run: attach to any cluster in the same workspace and region as the App (the network path
# MAGIC matters), replace every `FILL-ME` in the next cell, Run all. Copy the table and the
# MAGIC `SUPERVISOR-LATENCY-JSON:` line into your reply. Run once at a quiet time and once at a busy time;
# MAGIC run it with a cold warehouse too (the first statement time is printed).
# MAGIC
# MAGIC Not measured: the App's own CPU time (see `docs/latency.md`: add the code overhead of the
# MAGIC `databricks_fake` rows), the agent, any LLM, the fact sources of the bank.

# COMMAND ----------

# SUPERVISOR-PARAMS (edit inline)
CATALOG = "FILL-ME-catalog"
SCHEMA = "FILL-ME-schema"
WAREHOUSE_ID = "FILL-ME-sql-warehouse-id"  # the warehouse bound to the App
PREFIX = "latency_"  # scratch table is PREFIX + "probe"; never the real Supervisor tables
ITERATIONS = 200
WARMUP = 20
REPEATS = 3
# From the laptop benchmark JSON, results of scenario "breakdown" (statements per check):
# bench/latency-<commit>-<date>.json -> breakdown[...].statements (x100 values -> divide by 100).
# At commit df28be5: 4 writes and 0 reads per check (agent state is cached 1 s, the policy 5 s;
# add one state read per second per agent and one policy read per 5 s on top).
READS_PER_CHECK = 0  # check: query_per_check_x100 / 100, rounded up
WRITES_PER_CHECK = 4  # check: execute_per_check_x100 / 100, rounded up
# From the same JSON, results[...] of "gate_inproc" on databricks_fake (code overhead, no network):
CODE_OVERHEAD_P99_US = 0  # FILL-ME: median p99 of gate_inproc / databricks_fake / your policy size
GATE_TIMEOUT_US = 2_000_000  # HARD_TIMEOUT_S in gateway/engine.py
BUDGET_P99_US = 0  # FILL-ME: the Databricks App budget the owner confirms (0 = not set)
DROP_AFTER = True

# COMMAND ----------

# ruff: noqa: F821, T201, E501, S608, E402
import json
import math
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    Disposition,
    ExecuteStatementRequestOnWaitTimeout,
    Format,
    StatementParameterListItem,
)

for name, value in (("CATALOG", CATALOG), ("SCHEMA", SCHEMA), ("WAREHOUSE_ID", WAREHOUSE_ID)):
    if "FILL-ME" in value:
        raise ValueError(f"set {name} in the parameter cell first")

w = WorkspaceClient()  # notebook identity; OAuth, no token in this file
TABLE = f"`{CATALOG}`.`{SCHEMA}`.`{PREFIX}probe`"


def run(sql, params=None):
    """One statement through the Statement Execution API, polled to the end (inline JSON)."""
    items = [
        StatementParameterListItem(name=k, value=str(v), type=t)
        for k, (v, t) in (params or {}).items()
    ]
    resp = w.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=WAREHOUSE_ID,
        catalog=CATALOG,
        schema=SCHEMA,
        parameters=items or None,
        wait_timeout="30s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
        disposition=Disposition.INLINE,
        format=Format.JSON_ARRAY,
    )
    delay = 0.2
    while resp.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(delay)
        delay = min(delay * 2, 2.0)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state.value != "SUCCEEDED":
        raise RuntimeError(
            f"{resp.status.state.value}: {getattr(resp.status.error, 'message', '')}"
        )
    return resp


def percentile(sorted_values, p):
    if not sorted_values:
        return 0
    rank = max(1, math.ceil(p * len(sorted_values) / 100))
    return int(sorted_values[rank - 1])


def summarise(samples):
    v = sorted(samples)
    return {
        "n": len(v),
        "p50": percentile(v, 50),
        "p95": percentile(v, 95),
        "p99": percentile(v, 99),
        "max": v[-1],
    }


def median_int(values):
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) // 2


def spread_bp(values):
    m = median_int(values)
    return (max(values) - min(values)) * 10_000 // m if m > 0 else 0


def timed(fn):
    t0 = time.perf_counter_ns()
    fn()
    return (time.perf_counter_ns() - t0) // 1000


# COMMAND ----------

# Set up the scratch table (append-only, like verdict and agent_event).
t_first = timed(lambda: run("SELECT 1"))  # includes a cold warehouse start when it was stopped
print(f"first statement (cold-start indicator): {t_first / 1000:.0f} ms")
run(f"DROP TABLE IF EXISTS {TABLE}")
run(
    f"CREATE TABLE {TABLE} (k STRING, ts TIMESTAMP, note STRING) "
    "TBLPROPERTIES ('delta.appendOnly' = 'true')"
)
run(f"INSERT INTO {TABLE} VALUES ('seed', current_timestamp(), 'seed')")

counter = {"i": 0}


def read_state():
    run(f"SELECT k, note FROM {TABLE} WHERE k = :k LIMIT 1", {"k": ("seed", "STRING")})


def write_merge():
    counter["i"] += 1
    key = f"k{time.perf_counter_ns()}-{counter['i']}"
    run(
        f"MERGE INTO {TABLE} AS tgt USING (SELECT :k AS k, current_timestamp() AS ts, :n AS note) AS src "
        "ON tgt.k = src.k WHEN NOT MATCHED THEN INSERT (k, ts, note) VALUES (src.k, src.ts, src.note)",
        {"k": (key, "STRING"), "n": ("probe", "STRING")},
    )


def gate_sequence():
    for _ in range(READS_PER_CHECK):
        read_state()
    for _ in range(WRITES_PER_CHECK):
        write_merge()


ARMS = [
    ("select_1", lambda: run("SELECT 1")),
    ("state_read", read_state),
    ("insert_merge", write_merge),
    ("gate_sequence", gate_sequence),
]

# COMMAND ----------

results = {}
for name, fn in ARMS:
    for _ in range(WARMUP):
        fn()
    reps = [summarise([timed(fn) for _ in range(ITERATIONS)]) for _ in range(REPEATS)]
    med = {k: median_int([r[k] for r in reps]) for k in ("p50", "p95", "p99", "max")}
    spread = {k: spread_bp([r[k] for r in reps]) for k in ("p50", "p95")}
    results[name] = {"median": med, "spread_bp": spread, "repeats": reps}

print("arm            p50 us     p95 us     p99 us     max us   spread p50/p95 (%)")
for name, r in results.items():
    m, s = r["median"], r["spread_bp"]
    print(
        f"{name:<14}{m['p50']:>10}{m['p95']:>11}{m['p99']:>11}{m['max']:>11}   {s['p50'] / 100:.1f} / {s['p95'] / 100:.1f}"
    )
unstable = [n for n, r in results.items() if max(r["spread_bp"].values()) > 1000]
if unstable:
    print(f"[WARN] spread above 10 percent for {unstable}: re-run at a quieter time before quoting")

# COMMAND ----------

# Projection: what one /gate/check adds on Delta = code overhead (laptop benchmark, no network)
# + the measured statement sequence. Percentiles of a sum are not sums of percentiles, so this is an
# upper-bound style estimate; the real end-to-end number needs the App under load (see docs/latency.md).
seq = results["gate_sequence"]["median"]
est_p99 = CODE_OVERHEAD_P99_US + seq["p99"]
print(
    f"estimated gate p99 on Delta ~ {est_p99 / 1000:.0f} ms (code {CODE_OVERHEAD_P99_US / 1000:.1f} ms + statements {seq['p99'] / 1000:.0f} ms)"
)
if est_p99 >= GATE_TIMEOUT_US:
    print(
        "[WARN] above the 2 s gate hard timeout: callers would see the timeout fail mode, not the decision time"
    )
if BUDGET_P99_US:
    print(
        "[OK] within budget"
        if est_p99 <= BUDGET_P99_US
        else f"[FAIL] over the budget of {BUDGET_P99_US / 1000:.0f} ms"
    )
else:
    print("[SKIP] no budget set (BUDGET_P99_US): the owner must confirm it")

if DROP_AFTER:
    run(f"DROP TABLE IF EXISTS {TABLE}")

print(
    "SUPERVISOR-LATENCY-JSON: "
    + json.dumps(
        {
            "first_statement_us": t_first,
            "arms": results,
            "estimated_gate_p99_us": est_p99,
            "reads": READS_PER_CHECK,
            "writes": WRITES_PER_CHECK,
        },
        sort_keys=True,
    )
)
