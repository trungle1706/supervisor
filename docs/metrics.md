# Oversight metrics (`oversight_metric`)

Owner: WP7. Reader: WP8 console metrics panel.
Job: `python -m supervisor.jobs.metrics` (or the in-process scheduler, `METRICS_ENABLED=1`).

## Row

One row per `(metric_date, agent_id)`. `metric_date` is a UTC day. Each run recomputes
yesterday and today, so the values for today change during the day.
The fairness job also writes `fairness_gap_bp` (and `fairness_gap`) into the row of the
day it runs.

Agents: every agent in the `agent` table, plus every agent with events that day.

## Columns

All new columns are integers. Use them. The float columns are kept for older readers
and hold the same value divided by 10000. Floats never go to the evidence chain.

| Column | Type | Unit | Definition |
|---|---|---|---|
| `metric_date` | date | UTC day | Key. |
| `agent_id` | string | | Key. |
| `events_seen` | int | count | Tool calls seen that day: recorder `tool_call` events; if there are none, gate decisions. |
| `events_gated` | int | count | `gate_decision` events that day. |
| `coverage_bp` | int | bp | `events_gated * 10000 / events_seen`, floor, capped at 10000. Null when `events_seen` = 0. |
| `ttd_ms` | int | ms | Time to detect. Nearest-rank median of (verdict `ts` - flagged event `ts`) over verdicts with action alert, block, pause, open_case or raise_severity. Null when none. |
| `tth_s` | int | s | Time to human. Nearest-rank median of (first `case_event` with `actor_kind` user - case `opened_at`) over cases opened that day that a human touched. Null when none. |
| `catch_rate_bp` | int | bp | Judge catch rate from `data/golden/eval_report.json` (held-out section, else dev). Same for every agent. Placeholder until the bank golden set exists. |
| `false_alarm_bp` | int | bp | Judge false-alarm rate from the same report. Placeholder. |
| `chain_ok` | bool | | Null when the lane has no entries. Else the last in-store walk of the agent's chain lane (`agent:<id>`): sequence, `prev_hash` links and `entry_hash`. A broken lane stays false. This is a health check, not the proof: the proof is `supervisor-verify` over an export. |
| `judge_verdicts` | int | count | Tier 1/2 verdicts with role primary or challenger. |
| `judge_disagree_bp` | int | bp | Tier 2 primary verdicts labelled `tiers_disagree` / all Tier 2 primary verdicts. Null when no Tier 2 verdict. |
| `judge_human_pairs` | int | count | WP19. Cases closed by a reviewer that day (signoff `close:confirmed` or `close:false_alarm`, UTC day of the sign-off) that are linked to at least one judge verdict (tier 1 or 2). 0 when none. |
| `judge_human_agree_bp` | int | bp | WP19. Pairs where the reviewer confirmed the case / pairs, round half up. Null when no pairs. The judge's label on every pair is "suspicious" (it opened or raised the case), so this is precision-type agreement only: judge misses are measured by the golden set, not here. When pairs >= `MRM_MIN_AGREEMENT_PAIRS` and the value is below `MRM_MIN_AGREEMENT_BP`, the metrics job opens one medium case per agent and day through `CaseService.open_from_monitor` (monitor id `judge_human_agreement`; the incident clock applies). It advises a human to run `python -m supervisor.judge.mrm triggers`; it never touches the gate. |
| `groundedness_bp` | int | bp | Nearest-rank median of `quality.groundedness` verdict scores. Null when none (quality scoring is off by default). |
| `fairness_gap_bp` | int | bp | Largest approval-rate gap of the last fairness run that day (see `fairness_slice` for the cells). |
| `cases_opened` | int | count | Cases opened that day for the agent (all types). |
| `blocks` | int | count | Gate decisions with status denied, blocked or paused. |
| `llm_calls` | int | count | Agent `llm_call` events (cost proxy). |
| `judge_latency_ms` | int | ms | Sum of judge verdict latency (cost proxy). |
| `computed_at` | timestamp | UTC | Last write. |
| `coverage`, `catch_rate`, `false_alarm_rate`, `groundedness`, `fairness_gap` | float | ratio | Legacy. Same value as the `_bp` column / 10000. |
| `row_version`, `updated_at` | | | State-table columns (optimistic concurrency). |

`bp` = basis points, 0 to 10000. "Nearest-rank median" is always one of the observed
values (no interpolation).

## Monitor status (WP1b-B)

Column `monitor_status` (JSON, nullable): one entry per monitor (`quality`, `fairness`,
`drift`, `multiagent`) with `status` (`ok`, `not_applicable`, `no_data`), `code`, `reason` and
`n`. A monitor that cannot run for an agent says so here instead of writing nothing. The
Metrics page shows it in the section "Monitor status". Bindings, defaults and codes:
`docs/monitors.md`. Not on the evidence chain.

## Evidence

When the integer columns of a row change, the job records one `oversight_metric` entry on
the agent's chain lane (integers, booleans and nulls only).

## Related tables (WP7)

| Table | Kind | Use |
|---|---|---|
| `fairness_slice` | append-only | One row per fairness cell per run. Cells under n = 30 have null counts and rates (`suppressed` true). |
| `policy_baseline` | state | Drift band per agent version and metric (integers), with the breach streak. |
| `policy_threshold` | state | Overrides: `drift.k`, `drift.consecutive` per agent (`*` = all). |
| `monitor_state` | state | Cursors and dedupe marks of the monitors. |
| `scheduler_lease` | state | Single-instance lock of the scheduler on Databricks. |
| `cases.case_type` | column | rule, judge, drift, fairness, multiagent, manual. |

## Read example (WP8)

```sql
SELECT metric_date, agent_id, coverage_bp, ttd_ms, tth_s, catch_rate_bp,
       false_alarm_bp, chain_ok, judge_disagree_bp, fairness_gap_bp, cases_opened
FROM oversight_metric
WHERE metric_date >= :since
ORDER BY metric_date DESC, agent_id
```
