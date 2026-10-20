# HANDOFF WP22: Tool analytics and least privilege

Branch: this worktree (fresh copy of main bf3a23a, v0.2.0). Not pushed, not merged.
Rubric used: IAM / least-privilege reviewer (NIST SP 800-53 AC-6, bank access recertification).
Docs: `docs/tool-analytics.md`. ADR: `docs/adr/D22-tool-analytics.md` (numbered by WP to avoid a clash; renumber if you prefer).

## What was built

1. **Rollup** `src/supervisor/analytics/tools.py` -> table `tool_usage_daily` (per UTC day, agent, tool):
   calls, allows, blocks, pauses, errors, p50/p95 latency (integer us, nearest rank, exact from a
   histogram), distinct callers, distinct users (counts of HMAC hashes, never stored), first/last seen,
   risk class. Grouped SQL in 7-day chunks (no event row is loaded). Idempotent (unchanged rows write
   nothing). CLI `python -m supervisor.analytics.tools rollup|report|suggest`. Scheduler job
   `tool_analytics` (flag `TOOL_ANALYTICS_ENABLED`, default off) = rollup of 2 days + suggestion files.
2. **Least-privilege suggestion** `src/supervisor/analytics/tools_suggest.py`: declared tools
   (allow-list rule PAY-07/SVC-07/CRD-07, else manifest) vs tools used in the window (default 30 days).
   Status used / unused / exception / undeclared. Removal list ordered money, credit, pii_export, read_only.
   Output `least_privilege_<date>.yaml` (patch) and `.diff` (unified; also bumps the rule `version`,
   because `deploy_policy` refuses a deployed version with other content). Never applied. Documented
   exceptions in `config/tool_exceptions.yaml` (agent, tool, reason, approver, expiry). Confidence
   ok / low / no_data (no data = nothing proposed). Policy change path is documented in section
   "Applying a suggestion".
3. **Console "Tools" page** (`CONSOLE_TOOLS_ENABLED`, default off): table per agent, sortable, plain
   numbers, suggestion panel, "Download diff" (owner/admin only). Viewer reads.
4. **API** `GET /v1/analytics/tools?agent_id=&days=&view=daily|summary` (needs `tools.view`; flag
   `TOOL_ANALYTICS_ENABLED`); notebook `notebooks/tool_usage_analytics.py` (FILL-ME names).
5. Docs, README rows, BACKLOG rows, ADR D22, threat-model section 3.7, console.md, api.md, index.

## Flags and settings (all in a `# --- WP22 ---` block in `config.py`)
`TOOL_ANALYTICS_ENABLED=0`, `CONSOLE_TOOLS_ENABLED=0`, `SCHED_TOOL_ANALYTICS_S=3600`,
`TOOL_ANALYTICS_WINDOW_DAYS=30`, `TOOL_ANALYTICS_MIN_HISTORY_DAYS=14`,
`TOOL_ANALYTICS_EXCEPTIONS_FILE=config/tool_exceptions.yaml`, `TOOL_ANALYTICS_DIR=<DATA_DIR>/analytics`.

## Commands
```
uv run python -m supervisor.analytics.tools rollup --backfill
uv run python -m supervisor.analytics.tools report --days 30
uv run python -m supervisor.analytics.tools suggest --days 30 --out out\tools
uv run python -m pytest -q tests/analytics
uv run python -m pytest -q -s tests/analytics/test_perf.py     # 1M decisions
```

## Tests
- Before (main, per brief): 2791 passed. After: **2842 passed, 28 skipped** (full suite, 5 min 50 s).
  `ruff check .` and `ruff format --check .` clean.
- New: `tests/analytics/` (50 tests): rollup vs brute force (every column, 90 days, 3 agents), percentile
  from histogram vs sorted list, exact expected diff (policy + manifest, with version bump) and a golden
  YAML, window boundaries to the day, exceptions through expiry, risky-first, low/no data, undeclared
  flagged not added, combined diff, patched policy still parses, files never edited, Databricks fake
  (Delta statements, typed params, replayed results, MERGE per row), recorded baseline
  (`tests/fixtures/tool_analytics/baseline.json`, exact), CLI, scheduler flag, real `Gateway.check`
  feeding the rollup, console + API (flag off, roles, sorting, 400s), notebook template.
- Existing tests edited (additive only): `tests/test_rbac.py` (viewer now also holds `tools.view`),
  `tests/test_openapi.py` (new tag `analytics`), `tests/monitors/test_scheduler.py` (all-flags test also
  sets `tool_analytics_enabled`). Four existing tests failed until I added `AgentEvent.latency_us` and
  regenerated the smoke notebook (`python -m supervisor.databricks.notebook`).
- **Performance (recorded):** SQLite, 1,002,040 synthetic decisions over 90 days, 1,005 rollup rows:
  **20.7 s** (20.6 s per million), peak Python memory **41 MB** (tracemalloc on). Budget in the test:
  90 s per million and 128 MB (about 4x headroom). Whole perf test incl. loading: 34 s.

## Decisions to know
- New column `agent_event.latency_us` (nullable, additive) and one line in `Gateway._append_event`
  (`gateway/engine.py`, WP24b's area; minimal). Reason: `latency_ms` is 0 for every sub-millisecond gate
  call, so percentiles in us were impossible. Rows without it fall back to `latency_ms * 1000`.
- Reading `/v1/analytics/tools` is allowed for service principals (`tools.view` in `NON_USER_OK`) so a
  Databricks job can call it. On the laptop the dev provider's default user applies as for other views.
- No new dependency. The AST rule is respected (no sqlite3 import outside adapters, no subprocess).

## Not done (also in BACKLOG)
- Gate failures with no event row (`Gateway._fail`) are not in `errors` (no tool name on `verdict`).
- Distinct callers/users are per day (window views show the largest day; window p95 = worst day).
- The patcher edits one-line `not_in: [..]` lists only; other shapes need a human.
- 90-day backfill writes one MERGE per row on Delta (about 1,000 rows).
- Exceptions are a YAML file approved by PR; no console screen.
- Not run against a real workspace (no live test): Delta SQL is checked with the recorded fake only.
  The functions used (`date_format`, `to_utc_timestamp`, `current_timezone`, `get_json_object`) are
  standard Databricks SQL; please run `rollup --backfill` once in the live kit.

## Open questions for the owner
1. Is `owner` the right download role, or should `approver` also download? (matrix in `core/rbac.py`)
2. Default window 30 days and minimum history 14 days: acceptable for quarterly-use tools such as
   year-end batch tools? Those need an exception with an expiry today.
3. Should "called but always blocked" count as used? Today yes (the agent tried); the table shows
   allow/block/pause so a reviewer can decide.
4. ADR number: D22 chosen to avoid a clash; renumber at integration if needed.

## Self-review (R1-R3, secrets, 500s, ASCII, defaults off)
R1: no judge or model involved; nothing blocks or pauses. R2: no PII; only counts of hashes are
stored; no LLM. R3: no network. No secrets or workspace ids (notebook uses FILL-ME). User errors are
HTTP 400 / `[FAIL]` (bad agent id, days, view, sort, malformed exceptions file, unknown agent, flag
off). CLI output is ASCII (`ascii_line`). All flags default off, with a test. No existing test was
reduced or skipped.

## Files touched
New: `src/supervisor/analytics/{__init__,tools,tools_suggest,tools_routes}.py`,
`src/supervisor/console/tools_views.py`, `src/supervisor/console/templates/tools.html`,
`src/supervisor/data/tool_usage.py`, `config/tool_exceptions.yaml`, `notebooks/tool_usage_analytics.py`,
`docs/tool-analytics.md`, `docs/adr/D22-tool-analytics.md`, `tests/analytics/*`,
`tests/fixtures/tool_analytics/*`, `HANDOFF_WP22.md`.

Shared files (minimal, additive; merge hints):
- `schema/model.yaml` (+ column `latency_us` at the end of `agent_event`; new table `tool_usage_daily`
  at the end), `schema/ddl/sqlite.sql`, `schema/ddl/databricks.sql` (regenerate with `python -m schema.generate`
  after merging other WPs' tables), `notebooks/bootstrap_and_smoke.py` (regenerate with
  `python -m supervisor.databricks.notebook`).
- `src/supervisor/config.py` (`# --- WP22 ---` block after `console_assurance_enabled`; two names added to the
  `_absolute` validator list; one default in `_rules`).
- `src/supervisor/app.py` (import + `include_router(..., prefix="/v1")`), `src/supervisor/scheduler.py`
  (docstring row, import, one `JobSpec`), `src/supervisor/core/rbac.py` (2 permissions, `tools.view` in
  `NON_USER_OK`, 3 routes), `src/supervisor/console/routes.py` (import + a Tools section), `console/i18n.py`
  (keys `nav_tools`, `tl_*`), `console/readmodels.py` (`"tools"` in shell), `console/templates/base.html` (nav),
  `src/supervisor/ops/openapi.py` (tag `analytics`, human-path prefix), `src/supervisor/core/models.py`
  (`AgentEvent.latency_us`), `src/supervisor/gateway/engine.py` (one line), `pyproject.toml` (ruff T20 ignore
  for `analytics/tools.py`).
- Docs: `README.md` (feature row + 2 flag rows), `BACKLOG.md` (6 rows), `docs/index.md`, `docs/api.md`,
  `docs/console.md` (Tools row + role matrix table regenerated), `docs/threat-model.md` (section 3.7).
- Tests edited: `tests/test_rbac.py`, `tests/test_openapi.py`, `tests/monitors/test_scheduler.py`.
