# D22 - Tool analytics and least-privilege suggestions

Status: Accepted (WP22, phase 3). Numbered after the work package to avoid a clash with other
phase 3 ADRs; the integrator may renumber.

## Context

The gate stores every decision (`agent_event` with `event_type = gate_decision`, plus `verdict`
rows), and `/gate/metrics` has in-process counters. Nobody can see per tool how an agent behaves,
and nobody can tell which allowed tools are never used. NIST SP 800-53 AC-6 and bank access
recertification ask that every allowed tool is justified by use or by a documented exception.

## Decisions

1. **Rollup table, computed from stored decisions.** `tool_usage_daily` (state table, key
   `usage_date, agent_id, tool_name`), integers only. Idempotent: a day is recomputed and
   overwritten; unchanged rows are not written. The source of truth stays `agent_event`; the rollup
   can be rebuilt at any time (`rollup --backfill`). A state table (not append-only) is used because
   a late event changes an old day.
2. **Grouped SQL with a latency histogram.** Counts, first/last and distinct counts come from
   one GROUP BY; percentiles come from `(latency_us, count)` per group, which is exact (nearest
   rank, the product's definition) and needs no row-by-row read. Chunks of 7 days bound memory.
   Alternatives rejected: loading rows and sorting (memory), approximate sketches (not exact,
   harder to test against a brute-force reference), a percentile function (SQLite has none; Delta
   has one, but two code paths would give two answers).
3. **New column `agent_event.latency_us`.** `latency_ms` is `latency_us // 1000`, so a gate
   call under 1 ms is 0 and percentiles would be useless. The column is nullable and additive
   (migration adds it); the gate writes it in one line of `Gateway._append_event`. Older rows fall
   back to `latency_ms * 1000`.
4. **Declared = the allow-list rule, else the manifest.** The policy rule (PAY-07, SVC-07,
   CRD-07: `when.tool.not_in`, `pause`/`block`) is what the gate enforces, so it is the declared set.
   Manifest-only tools and policy-only tools are reported as drift, not as use.
5. **The suggestion can only remove.** It never adds a tool. Tools called but not declared are
   flagged. This keeps a poisoned or noisy log from widening access. With no data, or little
   history, it proposes nothing or marks the proposal low confidence.
6. **A diff, never an action.** Output is a YAML patch and a unified diff in files. No code path
   edits policy or manifests. The diff bumps the rule `version` because `deploy_policy` refuses a
   deployed version with other content; so the change must pass the normal policy PR with the two
   approvers already named in the rule.
7. **Documented exceptions in a file with an expiry** (`config/tool_exceptions.yaml`), reviewed
   by pull request. Expiry makes recertification a date, not a habit.
8. **RBAC.** `tools.view` for every role and service principals (read, like the other
   views); `tools.download` for `owner` and `admin` (the person accountable for the agent).
   The API and the page are off by default (flags) and answer HTTP 400 with a message when off.
9. **Window semantics.** A window of N days is the N UTC days ending today, both ends included.
   Window views are derived from daily rows: calls add, p95 is the worst day, distinct counts are
   the largest day. The table says so.

## Consequences

- The rollup depends on `args_masked` for `distinct_users`; the retention job nulls it after the
  masked TTL, so old days must not be recomputed after that date.
- `_fail` decisions have no event row and no tool name, so their errors are not attributed (BACKLOG).
- The patcher edits one-line flow lists only; other shapes are left to a human (the YAML says so).
- Delta cost is the scan of `agent_event` for the recomputed days; the daily job reads 2 days.
