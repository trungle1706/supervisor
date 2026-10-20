# REVIEW WP22: tool analytics and least-privilege suggestion

Reviewer: Opus (IAM / least-privilege per NIST SP 800-53 AC-6 and access recertification; data
engineer; senior Python engineer). Branch `worktree-agent-acbc98f924c30cb6f`, base main bf3a23a.
Reviewed: HANDOFF_WP22.md, docs/tool-analytics.md, the full `git diff main...HEAD` (3 commits).

## Verdict: APPROVE WITH FIXES (fixes applied on the branch)

The rollup is correct and well tested. The patcher had one bug that made a wrong diff with no
warning, and one design gap: an allow-list rule that is shared by more agents was edited
because of the usage of one agent. I fixed both and added tests, in 3 small commits
(03e43c3, f1bc384, 1d0556c). No history rewrite, no merge, no push.

## Findings

| # | Sev | File:line | Issue | Action |
|---|---|---|---|---|
| 1 | HIGH | `analytics/tools_suggest.py` `patch_rule_list` (258) | The text patch had no check after the edit. A comment that holds `]` (`not_in: [a, b]  # see [doc]`) gave a diff that raised the `version` but kept the tool. The YAML said "remove b" and the diff did not remove it. There was no warning. | FIXED. `verify_rule_patch` / `verify_manifest_patch` parse the file before and after. The text edit must give exactly the intended edit (list minus tools, version + 1), or the result is None. Tests added. |
| 2 | HIGH | `tools_suggest.py` `allow_rules` (93), `attach_diff` (392) | A rule with `agent_scope: "*"` or with more agents was edited from the usage of ONE agent. This removes tools that the other agents use. In the combined diff the version went up 2 times. | FIXED. A rule that is not scoped to `[agent_id]` only is never edited. The agent gets "NO DIFF, edit by hand: rule X applies to more agents". |
| 3 | MED | `tools_suggest.py` `attach_diff` | Partial diffs: when the policy rule could not be edited, the manifest part was still sent. A missing manifest edit was silent. If you apply that diff, the policy and the manifest do not agree. | FIXED. All or nothing per agent. Each problem goes into `warnings` with the prefix `NO DIFF`. `combined_diff` now raises `AnalyticsError` and does not keep the old text silently (`_must`). |
| 4 | MED | `tools_suggest.py` `allow_rules` | A rule with `when.all`/`when.any`, `aggregate` or `prior` was read as the declared tool set. Such a rule stops other tools only in some cases. | FIXED. Only rules without conditions count. Test added. |
| 5 | MED | `tools_suggest.py` `build_all` (`STALE_DAYS`, 48) | When the rollup stops (job off or failing), confidence stays `ok`. A tool that the agent uses in the days that are not rolled up then shows as `unused` and gets a removal proposal. | FIXED. If the newest rollup day of any agent is more than 2 days before `as_of`: confidence `low` and a "stale" warning. Also one table read in place of one read per agent. |
| 6 | MED | `tests/analytics/test_perf.py` | The 1M-row test (34 s) was in the default suite with a wall-clock assert. It can flake on a busy CI host, and the `perf` marker was not registered. | FIXED. The time budget is enforced only with `RUN_PERF=1` (1M rows). The normal suite uses 50k rows and checks counts and memory. Marker registered in `pyproject.toml`. |
| 7 | LOW | `notebooks/tool_usage_analytics.py` | `AGENT_ID`, `CATALOG`, `SCHEMA` and `PREFIX` went into SQL text with no check. The editor can only harm themselves (their UC rights apply), but a quote breaks the query. | FIXED. Each value must match an identifier regex, and `WINDOW_DAYS` must be an int. |
| 8 | MED (deploy) | `gateway/engine.py:827`, `schema/model.yaml` | New column `agent_event.latency_us`. SQLite: safe. I checked it: a DB from the main DDL plus `bootstrap_schema` gives "1 columns added" (the app bootstraps SQLite at start). Delta: the app does NOT migrate at start. If the new app is deployed before `python -m supervisor.jobs.bootstrap_schema` (ALTER TABLE ADD COLUMNS) has run, gate inserts fail on an unknown column. | RECORDED. Release note: run bootstrap_schema (or the notebook migration step) BEFORE you deploy the app. |
| 9 | LOW | `analytics/tools.py` `_write` | When a day is computed again, a stored (agent, tool) row that is gone from the new result is not deleted. This is not possible today because `agent_event` is append-only, but it is not the documented "overwritten". | RECORDED (BACKLOG candidate). |
| 10 | LOW | `analytics/tools.py` `load_daily` | Reads the full table and then filters dates in Python. The size grows by days x agents x tools (about 10k rows per year for the demo). | RECORDED. Push a date range into `StateStore.query` when it supports ranges. |
| 11 | INFO | `tools.py` `_day_expr` | Delta `date_format(to_utc_timestamp(ts, current_timezone()), 'yyyy-MM-dd')` gives the UTC day for any session time zone. SQLite `substr(ts,1,10)` is correct because ts is RFC 3339 `Z`. Parameters are bound (`:r_from`/`:r_to`, typed). No agent or tool name is put into SQL. YAML uses `safe_dump`. The download file name is regex-checked. | OK |
| 12 | INFO | `tools.py` `percentile_from_histogram` | `ceil(p*n/100)` nearest rank on the expanded histogram is the same as `monitors.common.percentile`. The "exact" claim is true for daily values. Window p50/p95 are documented as approximations (weighted median / worst day). Distinct counts are exact per day (`COUNT(DISTINCT)`), with max over days in the window (documented). | OK |
| 13 | INFO | semantics | "Blocked but called = used" is acceptable for AC-6: the tool is on the allow-list, so other rules (limits) stopped it. The table shows allow/block/pause. A used tool with an exception stays `used`. An exception holds through its `expires` day. Removal order is money, credit, pii_export, read_only. `no_data` proposes nothing. | OK |
| 14 | INFO | RBAC / flags | `tools.view` for all roles plus a service principal (read-only counts), and `tools.download` for owner and admin, are suitable. Both flags are off by default. Flag off and bad input give HTTP 400. CLI output is ASCII. No new dependency, no secrets, no network. R1-R3 are not affected (no model, nothing blocks). | OK |
| 15 | INFO (merge) | `docs/adr/` | WP20 (`D14-ingress-auth`) and WP24b (`D14-masker-v3-inline-redaction`) both use D14. WP22 uses D22, so it has no clash. | For the integrator |

## Tests

| Run | Result |
|---|---|
| Full suite before my fixes (`python -m pytest -q -x`) | 2842 passed, 28 skipped (5 min 33 s) |
| Full suite after my fixes | **2847 passed, 28 skipped** (4 min 58 s), 5 new tests |
| `tests/analytics` | 55 passed |
| `ruff check .` / `ruff format --check .` | clean |

New tests (`tests/analytics/test_suggest.py`): the patch refuses edits it cannot make exactly
(bracket in a comment; a block list in the last rule, followed by another `not_in`); a shared
rule gets no diff; an unpatchable rule holds back the whole agent diff (and the combined diff
has no payments manifest); a conditional allow-list is not a declaration; a stale rollup gives
low confidence.

## Residual risks

- Delta has not been run live. The SQL is checked only against the recorded fake. Run
  `rollup --backfill` once in the live kit (see the handoff).
- The Delta deploy order for `latency_us` (finding 8).
- The diff covers one-line flow lists only. It now fails closed. Other forms, shared rules and
  conditional rules always need a human.
- Gate failures with no event row are not counted in `errors` (BACKLOG).
- Staleness is a whole-system signal. A system with no gate traffic for more than 2 days is
  also shown as stale (confidence low, with a warning). This is safe.
- The open questions for the owner in the handoff stay open (download role, 30/14-day defaults
  for tools used once a quarter, blocked = used, ADR number).

## Merge notes

| File | Conflict risk | Note |
|---|---|---|
| `gateway/engine.py` | low | The WP22 one-line hunk (`"latency_us": d.latency_us` in `_append_event`) applies cleanly on WP24b (`git apply --check` on worktree agent-a44bc574614ace41d: clean). WP24b changes `_event_keys` / `Decision`, not the event row dict. |
| `core/models.py` | low | One field at the end of `AgentEvent`. No other wave-1 WP touches it. |
| `core/rbac.py`, `tests/test_rbac.py` | medium | WP21 and WP24 also add permissions and routes. Keep all entries. Regenerate the role table in `docs/console.md`. |
| `config.py` | medium | WP20, WP21, WP24 and WP24b all add blocks. WP22 also adds 2 names to the `_absolute` validator list and one default in `_rules`. Keep all of them. |
| `schema/model.yaml`, `schema/ddl/*.sql` | medium | WP21 and WP24 add tables at the end. Merge model.yaml, then regenerate with `python -m schema.generate`. Do not merge the DDL by hand. |
| `notebooks/bootstrap_and_smoke.py` | medium | WP21 and WP24 also touch it. Regenerate with `python -m supervisor.databricks.notebook` after the schema merge. |
| `console/routes.py`, `i18n.py`, `readmodels.py`, `base.html`, `ops/openapi.py`, `scheduler.py`, `app.py` | medium | Additive blocks from WP21 and WP24. Keep all of them. Nav order is a cosmetic choice. |
| `pyproject.toml` | low | WP21 also edits it. WP22 adds a T20 per-file ignore and the `perf` marker. |
| README, BACKLOG, docs/index.md, docs/threat-model.md | low | Additive rows and sections. Check the threat-model section numbers (WP22 uses 3.7). |
