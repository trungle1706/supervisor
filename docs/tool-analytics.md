# Tool analytics and least privilege (WP22)

Closes NeuralTrust gap row 23. Off by default. The feature has four parts: a daily rollup of
gate decisions per agent and tool, a least-privilege suggestion, a console page, and a JSON
route with a Databricks notebook. Design decision: `docs/adr/D18-tool-analytics.md`.

```
agent_event (gate_decision rows) + verdict (rule_error)
        |  python -m supervisor.analytics.tools rollup   (or the scheduler job)
        v
tool_usage_daily  (one row per UTC day, agent, tool)  --> GET /v1/analytics/tools
        |                                              --> notebooks/tool_usage_analytics.py
        |  suggest: allow-list in policies/*.yaml + manifest  vs  tools used in the window
        v
least_privilege_<date>.yaml + .diff   (a SUGGESTION; a person applies it through a policy PR)
        |
        v
console "Tools" page (table per agent, suggestion panel, download diff)
```

## Commands

All output is ASCII. The commands work with `SUPERVISOR_MODE=laptop` (SQLite) and
`databricks_app` (Delta). They do not need `TOOL_ANALYTICS_ENABLED`.

```
uv run python -m supervisor.analytics.tools rollup --backfill
uv run python -m supervisor.analytics.tools rollup                  # last 2 days (default)
uv run python -m supervisor.analytics.tools rollup --from 2026-09-01 --to 2026-09-30
uv run python -m supervisor.analytics.tools report  --days 30
uv run python -m supervisor.analytics.tools suggest --days 30 --out out\tools
```

`rollup` is idempotent: a day is recomputed and overwritten, and an unchanged day writes
nothing. `report` prints one table per agent (about 20 columns wide of numbers, one screen per
agent). `suggest` writes two files and prints the same table with a status per tool.

## Flags and settings (all off or safe by default)

| Setting | Default | Effect |
|---|---|---|
| `TOOL_ANALYTICS_ENABLED` | `0` | The scheduler job `tool_analytics` (rollup of yesterday and today, then the suggestion files) and `GET /v1/analytics/tools` |
| `CONSOLE_TOOLS_ENABLED` | `0` | The "Tools" console page and its nav link. Off = HTTP 400 with a message |
| `SCHED_TOOL_ANALYTICS_S` | `3600` | Job interval |
| `TOOL_ANALYTICS_WINDOW_DAYS` | `30` | The "used" look-back window (1 to 366 days) |
| `TOOL_ANALYTICS_MIN_HISTORY_DAYS` | `14` | Less history than this = confidence `low` |
| `TOOL_ANALYTICS_EXCEPTIONS_FILE` | `config/tool_exceptions.yaml` | Documented exceptions |
| `TOOL_ANALYTICS_DIR` | `<DATA_DIR>/analytics` | Where the scheduler writes the suggestion files |

## The rollup table `tool_usage_daily`

Defined in `schema/model.yaml` (both DDL files regenerated). Integers only.

| Column | Meaning |
|---|---|
| `usage_date`, `agent_id`, `tool_name` | Key. The day is the UTC day of the decision |
| `risk_class` | From the policy `tools:` catalogue, else the agent manifests, else `unknown` |
| `calls` | Gate decisions. Always `allows + blocks + pauses` |
| `allows` | `status = allowed` (includes alert and log outcomes, and SHADOW) |
| `pauses` | denied with outcome `pause` |
| `blocks` | every other denied decision |
| `errors` | decisions that carry a `rule_error` verdict (a rule raised; its fail mode decided) |
| `p50_us`, `p95_us` | Gate latency, integer microseconds, nearest-rank percentile (same method as `monitors.common.percentile`) |
| `distinct_callers` | Distinct `caller_agent_id` that day |
| `distinct_users` | Distinct HMAC hashes of `customer_id` (from `agent_event.args_masked`). Only the count is stored |
| `first_seen`, `last_seen` | First and last decision of that day |

Limits you should know:

- Latency comes from the new column `agent_event.latency_us` (added by WP22, written by the
  gate). Older rows have only `latency_ms`; the rollup uses `latency_ms * 1000` for them, so
  their percentiles have 1 ms steps.
- `distinct_users` reads `args_masked`. The retention job (ADR D13) nulls that column after
  `RETENTION_MASKED_DAYS` (365). The rollup of a day is done long before, and a stored day is
  not recomputed unless you ask for it; do not recompute days older than the masked TTL.
- Distinct counts do not add across days. Window views show the largest single-day value.
  The window p95 is the worst daily p95; the window p50 is the call-weighted median of the
  daily p50 values. The table says so in its column titles.
- Gate failures that never reach the event table (the gate could not decide and had no event
  to write) have a `verdict` row without a tool name. They cannot be attributed to a tool and
  are not in the rollup (see BACKLOG).

### How the rollup scales

The work is grouped SQL, not Python loops over rows: one query for counts, first/last and
distinct counts; one for the latency histogram (`latency_us, count` per group, which gives
exact percentiles); one for rule errors. It runs in chunks of 7 days. The Delta statements
use `date_format`, `to_utc_timestamp` and `get_json_object`; SQLite uses `substr` and
`json_extract`. A test replays the SQLite answers to the Databricks executor and checks the
statements and the parsed result.

Measured on the dev host, SQLite, `tests/analytics/test_perf.py` (1,002,040 synthetic
decisions, 90 days, 3 agents, 1,005 rollup rows; Python tracemalloc on):

| Measure | Value | Budget in the test |
|---|---|---|
| Rollup time | 20.7 s (20.6 s per million decisions) | 90 s per million |
| Peak Python memory during the rollup | 41 MB | 128 MB |

Run it with `RUN_PERF=1 uv run python -m pytest -q -s tests/analytics/test_perf.py`
(`PERF_ROWS=100000` shortens it). The time budget is loose (about 4x) and is enforced only
with `RUN_PERF=1`: in the normal suite the test loads 50,000 decisions and checks the counts
and the memory bound, so a busy CI host cannot make it flaky. On Delta the cost is the warehouse
scan of `agent_event` for the days recomputed; the daily job reads only 2 days.

## Least-privilege suggestion

The reviewer rubric is NIST SP 800-53 AC-6 (least privilege) and bank access recertification:
every allowed tool is justified by use or by a documented exception, and the answer fits on
one screen per agent.

**Declared tools** (what the agent may call): the allow-list rule of the agent in
`policies/*.yaml`, that is a `pause` or `block` rule with `when.tool.not_in: [...]` and the
agent in scope (PAY-07, SVC-07, CRD-07 in the baseline). Only unconditional rules count: a
rule that also has `when.all` / `when.any`, an `aggregate` or a `prior` stops other tools only
in some cases, so it does not declare the allowed set. If an agent has several such rules, a
tool must pass all of them (intersection). If it has none, the tools of its manifest
(`src/supervisor_agents/<id>/manifest.yaml`). Tools that are in the manifest but not in the
allow-list, or the reverse, are reported as `drift`.

**Status per tool** in the window (default 30 days, the last day is today, UTC):

| Status | Meaning | Suggestion |
|---|---|---|
| `used` | At least one gate decision in the window | keep |
| `exception` | No use, but an unexpired entry in `config/tool_exceptions.yaml` | keep, show approver and expiry |
| `unused` | No decision in the window and no exception | remove. Order: `money`, `credit`, `pii_export`, then `read_only` |
| `undeclared` | Called in the window but not declared (the gate paused or blocked it) | flag for a human; never added |

A tool whose calls were all blocked still counts as `used` (the agent tried to use it);
the table shows `allow`, `block` and `pause` so the reviewer can decide.

**Confidence.** `ok`; `low` when the rollup holds fewer than `TOOL_ANALYTICS_MIN_HISTORY_DAYS`
days for the agent (the first day to the last day, inclusive); `no_data` when the window has
no rows at all, in which case nothing is proposed. A missing rollup therefore never produces
a "remove everything" diff. If every declared tool is unused the output warns that the agent
may be ready to retire. If the newest stored rollup day of any agent is more than 2 days
before the "as of" day, the rollup has probably stopped: confidence drops to `low` with a
"stale" warning, because "unused" would only mean "not rolled up".

**Exceptions** (`config/tool_exceptions.yaml`): `agent_id`, `tool`, `reason`, `approver`,
`expires` (YYYY-MM-DD). An exception holds through its `expires` day. After that the tool is
`unused` again, so the exception is reviewed on a fixed date. A malformed file is an error
(`[FAIL]` / HTTP 400), not a silent skip.

### Output files

`suggest` (and the scheduler job) write, next to each other:

- `least_privilege_<as_of>[_<agent>].yaml`: the YAML patch. Per agent: `confidence`, the rule
  and its `version` bump (`current` to `proposed`), `current` and `proposed` tool lists,
  `remove` (with risk class and reason), `flag_undeclared`, `keep_by_exception`, `drift`,
  `warnings`. Same input gives the same bytes.
- `least_privilege_<as_of>[_<agent>].diff`: one unified diff for all agents. It edits the
  `not_in` list of each allow-list rule, raises that rule's `version` by one (the gate refuses
  a deployed version with other content), and removes the tool blocks from the manifest.
  Each file appears once. Every text edit is checked by parsing the file before and after:
  the result must equal the intended change (that list minus the tools, version plus one;
  or the manifest minus the tool blocks) and nothing else. The diff is all or nothing per
  agent: if a rule cannot be edited exactly (a list on several lines, a comment with a
  bracket, the file not found) or the rule also applies to other agents (`agent_scope: "*"`
  or a list of several agents; removing a tool there would affect them), the agent gets NO
  diff, not even the manifest part, and the YAML warns "NO DIFF, edit by hand: ...".

**Nothing is applied.** No code path edits `policies/` or a manifest; a test hashes the files
before and after.

### Applying a suggestion (the policy change path)

The suggestion is evidence for a change, not the change. A person applies it the way every
policy change goes (threat model, "Policy deploy not on the chain"):

1. The agent owner reviews the table and the diff. For each `unused` tool they confirm it can
   go, or add an exception with reason, approver and expiry in `config/tool_exceptions.yaml`.
   For each `undeclared` tool they decide: investigate (possible misuse), or start a normal
   request to add it.
2. Apply the diff in a branch: `git apply least_privilege_<date>.diff`.
3. Open a pull request. The rules are `pause` rules, so they carry two approver ids in
   `approvals`; those two people (and the bank change process) approve the PR. Attach the
   `.yaml` and the report as the justification.
4. Merge and deploy. The gateway loads `policies/*.yaml` at start; the new rule version
   replaces the old one in the `rule` table (`effective_to` closes the old version), and
   every later gate decision carries the new `policy_hash`.
5. Run the existing policy tests (`python -m pytest tests/gateway`); they pin tool names
   between the policy and the manifests.

## Console page "Tools"

`/console/tools` (flag `CONSOLE_TOOLS_ENABLED`; off = HTTP 400 and no nav link). Per agent:
a table (tool, risk, status, calls, allow, block, pause, err, p50, p95, users, last seen) with
plain numbers, sortable by clicking a column title (`?sort=calls&dir=desc`), then the
suggestion panel: tools to remove (risky first), the before and after lists, undeclared tools,
warnings, and "Download diff". `?agent_id=` shows one agent, `?days=` changes the window.
No chart, no non-ASCII symbol in the numbers.

| Who | Can |
|---|---|
| any signed-in role (`tools.view`) | read the page and `/v1/analytics/tools` |
| owner, admin (`tools.download`) | download the diff (`/console/tools/<agent>/diff`, built in memory, a text file) |

## JSON route and notebook

`GET /v1/analytics/tools?agent_id=payments&days=30&view=daily|summary` (flag
`TOOL_ANALYTICS_ENABLED`; needs `tools.view`; a service principal may call it, so a notebook
or dashboard job can use its App identity).

- `view=daily` (default): the rollup rows in the window.
- `view=summary`: one row per agent and tool, plus the suggestions (without the diff text).

Errors (`days` not 1 to 366, unknown `view`, bad `agent_id`, feature off) are HTTP 400 with
`{"error": ...}`.

`notebooks/tool_usage_analytics.py` reads the Delta table directly. Edit the first cell
(`CATALOG`, `SCHEMA`, optional `PREFIX`; values are `FILL-ME-...` placeholders), attach to a
cluster, Run all. It shows usage per agent and tool, a daily series for a chart, and the tools
that were called but never allowed.

## Test evidence

`tests/analytics/` (run: `uv run python -m pytest -q tests/analytics`):

| Test | Proves |
|---|---|
| `test_rollup.py` | Rollup equals a brute-force computation over 90 days and 3 agents (every column); percentile from the histogram equals the sorted-list percentile; UTC midnight boundaries; legacy ms rows; rule errors; hashes only; idempotence; chunking |
| `test_suggest.py` | The exact diff (policy, manifest, rule version bump); the whole YAML patch against a golden file; window boundaries to the day; exceptions through their expiry day; risky first; low and no data; undeclared flagged and not added; combined diff; patched policy still parses; files unchanged |
| `test_databricks_fake.py` | Delta statements and typed parameters; results replayed as REST strings give the same groups; one MERGE per row |
| `test_regression.py` | Recorded baseline (`tests/fixtures/tool_analytics/baseline.json`, exact); CLI; scheduler wiring and flag; the real `Gateway.check` feeds the rollup; notebook template |
| `test_console_api.py` | Page off by default, nav, roles, sorting, 400s, owner-only download, API views |
| `test_perf.py` | 1,002,040 decisions in 20.7 s, 41 MB |

The synthetic set is `supervisor.data.tool_usage.generate(seed=20261020)`: `add_payee` stops
40 days before the end, `open_dispute` 45 days before, `ext_transfer_api` is called and paused
by PAY-07, `request_documents` is rare. The expected suggestion is therefore known.
Labeller of the "labels": synthetic (the generator defines the truth). Thresholds: none; the
window and minimum history are settings, not model outputs. No model or classifier is used,
so there is no model card.
