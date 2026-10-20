# INTEGRATION WAVE 1 (phase 3)

Branch `phase3-wave1` in worktree `/home/trung/supervisor/.claude/worktrees/agent-a1f4b3e7345d4debe`.
Base: main `bf3a23a` (v0.2.0). Not pushed. Not merged into main. `__version__` is still `0.2.0`.
Review this commit: see "Branch and commit" at the end.

## 1. Result

| Check | Result |
|---|---|
| Merges | 5 of 5 (`git merge --no-ff`), all conflicts resolved by union of the additive blocks |
| `ruff check .` / `ruff format --check .` | clean / clean (621 files) |
| Full suite `uv run python -m pytest -q` (no `-x`) | **3283 passed**, 28 skipped, 0 failed, 1 warning (main: 2791, so +492 new; more than the ~330 estimate because the review follow-ups added tests). Same count on the first run after the merges and on the final head |
| `python -m supervisor.pii_eval` (both splits) | same as the WP24b baseline (table in section 6) |
| `python -m supervisor.alerts.harness` | `[OK] all GO` on dev and held-out, 8 of 8 alerts |
| Offline chain verify after inventory + alert jobs (fresh SQLite) | `RESULT: OK`, 15 signed roots, 5 lanes incl. `agent:inventory` |
| Boot with all wave-1 flags on (port 18431) | /health, /ready, Tools, Inventory, Metrics 200; signed SDK check allowed; unsigned 401; all jobs `ok` |

## 2. Merge order and why

```
main bf3a23a
  |-- 1. WP20  ingress auth        (sdk, mcp_proxy, http_json, config, app, routes)   no conflict
  |-- 2. WP24b masker v3 + inline  (engine, sdk, mcp_proxy, routes)                    4 conflicts
  |-- 3. WP22  tool analytics      (engine latency_us, model.yaml first table)         1 conflict
  |-- 4. WP21  SIEM + alerts       (model.yaml, http_json, scheduler, rbac)           12 conflicts
  |-- 5. WP24  inventory           (model.yaml, rbac, console, app, scheduler)        12 conflicts
  `-- integration commits (ADR renumber, format, CHANGELOG, scheduler test)
```

Reason: the two WPs that change the gate path (WP20, WP24b) go first, so the SDK / MCP proxy
conflicts are solved once, on code without other changes. WP22 next puts its one `engine.py`
line on top of WP24b (the review said it applies clean; it did). The three schema WPs go last,
so `model.yaml` is merged in order and the DDL is generated twice only.

## 3. Conflicts and how I solved them

| Merge | File | Resolution |
|---|---|---|
| WP24b | `config.py` | WP20 block, then WP24b block (blank line between) |
| WP24b | `gateway/sdk.py` | imports union: `json` (WP20) + `logging`, `os` (WP24b) |
| WP24b | `gateway/mcp_proxy.py` | both CLI flags (`--key-file`, `--bearer-token-env`, `--inline-redaction`); `McpGateProxy(HttpGate(url, credential=credential), ..., inline_redaction=...)` |
| WP24b | `docs/index.md` | ingress-auth row kept; ADR range set (final value in the ADR commit) |
| WP22 | `config.py` | WP22 block appended after WP24b |
| WP21 | `config.py` | WP21 block appended; `_absolute` validator list = union (`ingress_*`, `alerts_config`, `notify_webhook_dead_letter`) |
| WP21 | `scheduler.py` | docstring table rows, imports and JobSpecs: union (`tool_analytics`, `siem`, `notify`, `alerts`) |
| WP21 | `tests/monitors/test_scheduler.py` | all-flags test sets the union of flags (tool analytics, siem, alerts, webhook + URL) |
| WP21 | `pyproject.toml` | T20 ignores: union (WP22 `analytics/tools.py`, WP21 `alerts/__main__.py`, `alerts/harness.py`) |
| WP21 | `schema/model.yaml` | `tool_usage_daily` (WP22), then `alert`, `siem_event` (WP21) |
| WP21 | README, BACKLOG, threat-model | rows and sections: union. WP21 section numbered `3.8` after WP22 `3.7` |
| WP24 | `config.py` | WP24 block appended; validator list + `inventory_allowlist_file`, `inventory_workspace_fixture` |
| WP24 | `app.py` | both routers: `tools_analytics_router` (prefix `/v1`) and `inventory_router` |
| WP24 | `ops/openapi.py` | `_is_human_path` prefixes: `/console`, `/gate/`, `/v1/gate/`, `/v1/analytics/`, `/v1/inventory/` |
| WP24 | `console/routes.py`, `i18n.py`, `templates/base.html` | Tools section then Inventory section; both i18n key sets; both nav entries |
| WP24 | `schema/model.yaml` | `inventory_node`, `inventory_edge` appended at the tail |
| WP24 | BACKLOG, threat-model gap table | union |
| WP21, WP24 | `schema/ddl/*.sql`, `notebooks/bootstrap_and_smoke.py` | not hand-merged: took one side, then regenerated |

Auto-merged without conflict, then checked by hand: `core/rbac.py` (PERMISSIONS, NON_USER_OK,
ROUTES of WP21, WP22, WP24 all present), `gateway/engine.py`, `gateway/routes.py`,
`adapters/http_json.py` (WP21 `headers=` on `post_json` + WP20 `post_bytes`), `wiring.py`.

## 4. Regenerated and integration commits

| What | How |
|---|---|
| `schema/ddl/sqlite.sql`, `schema/ddl/databricks.sql` | `PYTHONPATH=src python -m schema.generate` after the WP21 and after the WP24 merge |
| `notebooks/bootstrap_and_smoke.py` | `python -m supervisor.databricks.notebook` after each schema merge |
| `docs/console.md` role matrix | Compared with `rbac.matrix_markdown()`: git merged the rows, the table is equal (test `test_docs_table_equals_matrix_markdown` passes); no edit needed |
| ADR | `git mv docs/adr/D22-tool-analytics.md docs/adr/D18-tool-analytics.md`, title D18, links in README and `docs/tool-analytics.md`, `docs/index.md` range "D01 to D18". Final set: D14 ingress auth, D15 alerts, D16 inventory, D17 masker v3, D18 tool analytics |
| `ops/openapi.py` | `ruff format` of the merged prefix tuple |
| `CHANGELOG.md` (new) | v0.3.0-pre: feature table, flags table, behaviour changes with flags off, Delta deploy order. README: `INGRESS_AUTH_ENABLED` row (was missing from the flag table) and a CHANGELOG pointer; `docs/index.md` row |
| `tests/monitors/test_scheduler.py` | all-flags test also turns on `INVENTORY_ENABLED` with the workspace fixture and asserts `siem`, `notify`, `alerts`, `tool_analytics`, `inventory` are all in the job set (additive; nothing removed) |

No test was skipped, removed or made weaker. No merge-caused failure needed a code fix: the
first full run after the five merges was green.

## 5. Cross-WP contracts (checked)

| Contract | Status |
|---|---|
| WP21 alert signals read WP20 rejections | OK. Writer `ingress_auth.record_reject` -> `console_action(permission="ingress.auth", outcome="denied", target_kind="agent", target_id=<claimed>, detail="<reason>[;suppressed=n]")`. Reader `alerts/signals._ingress_rejects` filters on the same `permission` + `outcome` and parses the same `detail`. Boot run: 2 rejections audited |
| `engine.py`: WP22 `latency_us` + WP24b `_pre_redact` | OK. `_pre_redact` is called before `with self._lock:` in `_decide`; `latency_us` is in `Decision.as_result` and in the `agent_event` row. Note: `t0` is taken before `_pre_redact`, so for `pii_export` tools with inline redaction `latency_us` includes the masker time (honest gate latency; WP22 percentiles will show it) |
| `tests/test_ingress_contract.py` | OK. No other WP adds an agent (machine) ingress route: WP21 adds `POST /console/alerts/{id}/ack` (person, RBAC), WP22 and WP24 add `GET` routes under RBAC. `PINNED` and `RATE_LIMIT_EXEMPT` unchanged |
| `tests/test_rbac.py` role sets | OK, union: viewer has `inventory.view`, `tools.view`; operator has `alert.ack` |
| `tests/test_openapi.py` tags | OK (`analytics` tag from WP22) |
| Scheduler all-flags test | OK, now with all five wave-1 jobs (see section 4) |
| `mask_version` pins | OK, all at `vn_regex-3`; no other WP pins the version |

## 6. Harness results

PII eval (`python -m supervisor.pii_eval`; held-out honest figure with `--ablate-heldout-lexicon`),
leak recall in bp with Wilson 95%:

| Entity | dev | held-out (lexicon ablated) | held-out (production lexicon, information only) |
|---|---|---|---|
| PERSON | 9920 (9768-9973) | 5297 (4579-6004) | 9891 (9614-9971) |
| ADDRESS | 10000 | 10000 | 10000 |
| CCCD, CMND, PHONE, EMAIL, TAX_CODE, BANK_ACCOUNT, CARD_NUMBER | 10000 | 10000 | 10000 |
| Amounts intact / over-masked | 10000 / 0 | 10000 / 0 | 10000 / 0 |
| False mask on negatives | none (190 items) | PERSON 373 (160-844) of 134 items | same |

Same as `data/eval/pii_vn/baseline_vn_regex-3.json`.

Alerts (`python -m supervisor.alerts.harness`): dev and held-out each 587 signals, 8 of 8 alerts,
precision, recall, dedupe and triage 10000 bp, Wilson 6755-10000 bp (n = 8), `[OK] all GO`.

Chain verify (fresh SQLite `DATA_DIR`): demo seed, incidents 1, 2 and 3 x5, `bootstrap_schema`,
`python -m supervisor.jobs.inventory --fixture tests/fixtures/inventory/workspace_7.json` (3 managed,
4 unmanaged workspace items; the handoff fixture note says 3 unmanaged + 1 allow-listed, but the
allow-list file in `config/` is FILL-ME, so the allow-listed App counts as unmanaged here), `python -m supervisor.jobs.alerts` (`ALERTS_LAG_S=0`; one
`AL-BLOCK-BURST` alert on `credit_prequal`), `python -m supervisor.evidence.export`, then
`python -m supervisor.evidence.verify --strict`: manifest OK, 201 payloads re-hashed, 15 signed
roots, lanes root, credit_prequal, customer_service, inventory, payments: **RESULT: OK**.

## 7. Boot with all wave-1 flags (laptop mode)

`python -m uvicorn supervisor.app:app --host 127.0.0.1 --port 18431` with `SUPERVISOR_MODE=laptop`,
`AUTH_KIND=dev_header`, `INGRESS_AUTH_ENABLED=1` (hmac, file key store, key issued by
`python -m supervisor.gateway.ingress_auth issue credit_prequal --out-key-file ...`),
`SIEM_ENABLED=1` (`SIEM_SINK=file`, `SIEM_FORMAT=ocsf`), `ALERTS_ENABLED=1`,
`TOOL_ANALYTICS_ENABLED=1`, `CONSOLE_TOOLS_ENABLED=1`, `INVENTORY_ENABLED=1` (workspace fixture),
`INLINE_REDACTION_ENABLED=1`, demo-seeded data dir. Stopped with `fuser -k 18431/tcp`.

| Probe | Result |
|---|---|
| `GET /health` | 200 `{"status":"ok","version":"0.2.0"}` |
| `GET /ready` | 200, runtime, store, signer true, scheduler running |
| `GET /console/tools`, `/console/inventory`, `/console/metrics` (`X-Dev-User: admin.chi`) | 200, 200, 200 |
| `GET /v1/inventory/unmanaged`, `GET /v1/analytics/tools?view=summary` | 200, 200 |
| `POST /gate/check` with no credential | 401 `credential required` |
| SDK `HttpGate(credential=...)` `credit_score_lookup` (read_only) | allow |
| SDK signed `fetch_application` (pii_export) with a name and phone in args | allow, `transformed_args` present, `redaction_count=1`, raw phone not in the masked args |
| SDK with the credit key claiming `payments` | block `GATE-AUTH` (fail closed) |
| `/gate/metrics` | `ingress_accepted 2`, `ingress_rejected 2` (missing_credential 1, unknown_agent 1) |
| Scheduler after one tick (75 s) | `last:` status `ok` for ingest, anchor, case_intake, tool_analytics, siem, alerts, inventory; SIEM file has 143 OCSF lines |
| App log | no ERROR, no traceback, no 500 |

## 8. Open items across WPs

Owner questions (from the five handoffs and reviews):

1. WP20: key custody (file, env, secret scope, bank vault). The App rule says "no secret-scope resources": is an SDK runtime read of a secret scope allowed?
2. WP20: does the Databricks Apps proxy forward `Authorization`, or only `X-Forwarded-*` headers? Default in `databricks_app` mode is now `databricks_proxy` (X-Forwarded-Email / User). Live-kit check 1.
3. WP20: rotation overlap (24 h default) and key lifetime policy.
4. WP20: turn `INGRESS_AUTH_ENABLED` on by default for the bank deployment?
5. WP20: identity outage gives 401 today (SDK then fails closed even for read-only tools). 401 or 503? Audit throttle `INGRESS_AUDIT_THROTTLE_S`: 0 (every row) or 10?
6. WP21: which SIEM (Splunk, Sentinel, QRadar, Databricks-hosted), which default format, which OCSF version?
7. WP21: real thresholds, severities and on-call per route; re-page unacknowledged criticals after N minutes?
8. WP21: should an alert open a case on its own?
9. WP21: retention for `alert` and `siem_event`.
10. WP21 / WP20: should ingress rejections also be chain records so the SIEM feed carries them (today only `console_action` rows, read by the alert job)?
11. WP22: tool diff download role: `owner` only, or also `approver`?
12. WP22: 30-day window and 14-day minimum history: acceptable for tools used once a quarter (today they need an exception with an expiry)?
13. WP22: should "called but always blocked" count as used (today yes)?
14. WP24: allow-list content and `INVENTORY_SELF_APP` for the real workspace.
15. WP24: which UC schemas to scan (`INVENTORY_SCAN_SCHEMAS`).
16. WP24: shadow-AI case severity (low, or medium for model-serving endpoints).
17. WP24: should effective risk feed the Decision 33 task list (WP30) and the risk register (WP29)?
18. WP24: pseudo agent id `inventory` adds the chain lane `agent:inventory` (id is now reserved): confirm.
19. WP24b: PERSON recall threshold (illustrative 9500 bp) and the trade of more false masks for more recall.
20. WP24b: `MASK_AMOUNTS` on for the `masked` capture level of some agents?
21. WP24b: who supplies the bank labelled PII sample, and when?
22. WP24b: should the `agent:<id>` sandbox mock stop echoing context PII, or should `pii_canary` keep failing it on purpose?

Integration notes (not owner decisions):

- WP23 (latency benchmark) is not merged. Expected touch points: `tests/perf/`, `tools/bench_latency.py`, `docs/latency.md`, README line, CHANGELOG feature row. WP22 registered the pytest marker `perf` in `pyproject.toml` and gates its 1M-row timing on `RUN_PERF=1`; WP23 should reuse that marker. `latency_us` now includes the inline-redaction pass for pii_export tools.
- Delta deploy order: run `python -m supervisor.jobs.bootstrap_schema` BEFORE the new app (column `agent_event.latency_us`; tables `alert`, `siem_event`, `tool_usage_daily`, `inventory_node`, `inventory_edge`). In `CHANGELOG.md`.
- Nothing in wave 1 ran against a live workspace: SCIM `Me`, `DatabricksSecretReader`, Apps proxy headers, Delta SQL of the rollup, workspace inventory listing, SIEM Delta sink. Add to the live kit.
- WP20 uses Starlette private `request._body` (pinned Starlette 1.8.0 behaviour; route and e2e tests catch a change).
- `tests/monitors/test_scheduler.py::test_start_and_stop_apscheduler` prints a `PytestUnhandledThreadExceptionWarning` (APScheduler `JobLookupError` for `supervisor-startup` on shutdown). The test passes; the start/stop code is unchanged by wave 1, so this is a pre-existing race.
- WP24 reported one flaky run of `tests/integrations/test_integrations.py::test_chain_feed_writes_schema_events_once` on main (a random 10-digit run in a hash matched the PII regex). It passed in both full runs here.
- `docs/assurance.md` pack table row for `pii_canary` is not regenerated (lists 2 metrics, the pack has 4).
- WP20 author commits carry a Sonnet `Co-Authored-By` trailer, not the Fable line. History was not rewritten.
- HANDOFF_* and REVIEW_* files of the five WPs are at the branch root (they came with the merges). Delete or move them to `docs/handoff/phase3/` before the release if you prefer.

## 9. Branch and commit

| | |
|---|---|
| Branch | `phase3-wave1` |
| Worktree | `/home/trung/supervisor/.claude/worktrees/agent-a1f4b3e7345d4debe` |
| Head | the last commit on `phase3-wave1` (report-only commits on top of `e1730f3`; code and tests are final at `e1730f3`) |
| Diff vs main | 200+ files, about 28,200 insertions, 226 deletions |

Commits on top of main (first parent):

```
e1730f3 Integration wave 1: all-flags scheduler test also runs the inventory job and pins the wave-1 job set
5ee034c Integration wave 1: CHANGELOG v0.3.0-pre (flags, behaviour changes, Delta deploy order), README ingress flag row
476f796 Integration wave 1: ruff format openapi human-path prefixes
932bdbe Integration wave 1: renumber WP22 ADR D22 to D18, ADR range D01 to D18
4c145c5 Merge WP24 inventory + shadow AI (worktree-agent-ae8b65441b4910e06)
6cd837a Merge WP21 SIEM + alerts (worktree-agent-aa18ba5bdc4aeb239)
dc1e67a Merge WP22 tool analytics (worktree-agent-acbc98f924c30cb6f)
d59ca9d Merge WP24b masker v3 + inline redaction (worktree-agent-a44bc574614ace41d)
3a9fba1 Merge WP20 ingress auth (worktree-agent-a038a49e4b494fc59)
```

Merged branch heads: WP20 `edd5efb`, WP24b `cbe57ce`, WP22 `684f4ef`, WP21 `34d1552`, WP24 `0b87bb3`.
