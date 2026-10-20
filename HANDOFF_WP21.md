# HANDOFF WP21: SIEM and alerts live

Branch: `worktree-agent-aa18ba5bdc4aeb239` (base `bf3a23a`, v0.2.0). Not pushed, not merged.

## What was built

1. **SIEM export, production grade** (`adapters/integrations/siem.py`, `ocsf.py`, `transport.py`, `deadletter.py`)
   - Sinks: `file` (JSONL, size rotation `SIEM_FILE_MAX_BYTES` / `SIEM_FILE_BACKUPS`, rotation failure on Windows keeps appending), `http` (`WebhookSiemSink`: 3 attempts, 1 s / 2 s back-off, 429 and 5xx retried, other 4xx not, dead-letter file, batch idempotency key in body and `Idempotency-Key` header, `event_ids` list, `--replay-dead-letter`), `delta` (`DeltaSiemSink`: table `siem_event`, insert-only MERGE through the SQL adapter, OCSF document stored per row).
   - Formats `SIEM_FORMAT=jsonl|cef|ocsf` (`json` alias). OCSF 1.1: gate decisions, state changes, chain seal as 6003; cases, alerts, chain anomalies as 2004; ingress rejections as 3002. Hashes and ids only (test plants free text and a phone number).
   - Cursor per lane in `monitor_state` (monitor `siem`), saved after the sink accepts; restart test, failing-sink test, batch-cap test.
   - New event types `alert`, `ingress_reject`, `chain_anomaly`; new optional field `attrs` (always present in jsonl, null for old types).
   - Scheduler job `siem` (`python -m supervisor.jobs.siem`).
2. **Alert engine** `src/supervisor/alerts/` (`rules.py`, `signals.py`, `engine.py`, `service.py`, `harness.py`, `__main__.py`), job `jobs/alerts.py`, rules `config/alerts.yaml` (7 rules: block burst, quarantine, chain verify fail, judge escalation, ingress reject burst, fail-closed drill fail, job failure). `yaml.safe_load`, strict validation, no eval. Pure deterministic engine (time from signals, ids = SHA-256, cursor so each signal counts once, dedupe by time after a fire with `suppressed_count`, time-boxed policy suppressions). Alert row in new table `alert` (both DDLs and `schema/model.yaml`), one `alert` evidence record, routes inbox / siem / webhook / pager with per-route status and redelivery. CLI: `python -m supervisor.alerts list | validate | test <rule_id> [--signals FILE | --since-s N]` (dry run, writes nothing).
3. **Webhook notifier** `WebhookNotifier` sends when `NOTIFY_WEBHOOK_ENABLED=1` and `NOTIFY_WEBHOOK_URL` is filled (retry, idempotency key = notice id, dead letter at `NOTIFY_WEBHOOK_DEAD_LETTER`, token `NOTIFY_WEBHOOK_TOKEN` as SecretStr). Flag with no URL keeps the old queue-only stub. `StubNotifier("pager"|"itsm")` share the `Notifier` interface and only queue.
4. **Console**: Alerts section on Metrics (open and acknowledged counts, table with rule, severity, agent, window, repeats, case link, chain seq and hash), `POST /console/alerts/{id}/ack`, permission `alert.ack` (operator, admin), two `console_action` rows, `alert_ack` chain record, audit target kind `alert`. Vietnamese labels added.
5. **Docs**: `docs/siem.md`, `docs/alerts.md`, `docs/adr/D15-alerts.md`, README flag rows, index rows, `docs/bank-integration.md` pointer, `docs/console.md` Alerts note and regenerated role matrix, `docs/threat-model.md` paragraph (new outbound trust boundary), BACKLOG (7 WP21 rows).

## Harness and expert view (SOC analyst / detection engineer)

`python -m supervisor.alerts.harness` (also `tests/alerts/test_harness.py`). Fixture `tests/fixtures/alerts/`: dev (seed 2101) and held-out (seed 2121) splits, each 570 signals with 500 gate decisions, 6 planted incidents (7 expected alerts: incident 1 raises block burst and quarantine), hard negatives (4 blocks in 9 min, 5 blocks over 20 min, pause, mock tier 2, tier 1, 9 ingress rejects, good verify, good drill). Provenance, rubric, limits in `README.md` there; `generate.py --check` proves the files. Rules/thresholds were fixed on dev, held-out only scored.

Baseline (`baseline.json`, 2026-10-20, base bf3a23a), both splits: precision 10000 bp, recall 10000 bp, exact dedupe 10000 bp, triage completeness 10000 bp, 7 alerts for 7 expected, 0 FP, 0 FN, 55-57 matching signals collapse to 7 alerts (9 repeats absorbed), false alert rate upper bound 67 bp over 570 signals. Wilson 95 percent for precision and recall: 6456-10000 bp (n = 7, small; stated). Verdict GO on all four metrics (ILLUSTRATIVE thresholds). The harness is shown to fail: tests lower and raise a threshold and see NO-GO. No model is used: no mock path, no model card needed.

Also tested: OCSF required fields and class/category/type consistency for every event type; retry with a failing fake HTTP sink (back-off values, dead letter, replay with the same key, 401 not retried, token never in dead-letter file); Delta sink on SQLite and on `databricks_fake` (MERGE statement, partial duplicate fallback); alert table insert/read/ack on `databricks_fake`; dedupe collapse and re-fire after the window; stable field names (alert columns, SIEM attrs, 14 triage lines); chain still verifies offline with `alert` records; console RBAC (operator and admin ok; reviewer, approver, auditor, viewer 403 with `denied` rows; bad id, missing or stale version, repeat ack give 4xx).

## Flags and commands

| Flag | Default | Notes |
|---|---|---|
| `SIEM_ENABLED` | off | + `SIEM_SINK`, `SIEM_FORMAT`, `SIEM_FILE_*`, `SIEM_WEBHOOK_URL` (alias `SIEM_HTTP_URL`), `SIEM_HTTP_TOKEN`, `SIEM_HTTP_AUTH_SCHEME`, `SIEM_DEAD_LETTER_PATH`, `SCHED_SIEM_S` |
| `ALERTS_ENABLED` | off | + `ALERTS_CONFIG`, `SCHED_ALERTS_S` |
| `NOTIFY_WEBHOOK_ENABLED` | off | + `NOTIFY_WEBHOOK_URL`, `NOTIFY_WEBHOOK_TOKEN`, `NOTIFY_WEBHOOK_DEAD_LETTER` |

    python -m supervisor.alerts validate | list | test AL-BLOCK-BURST --since-s 86400
    python -m supervisor.jobs.alerts ; python -m supervisor.jobs.siem [--replay-dead-letter]
    python -m supervisor.alerts.harness [--write-baseline]
    python tests/fixtures/alerts/generate.py --check

## Test counts

Before: 2791 passed, 26 skipped (main bf3a23a). After: 2892 passed, 26 skipped (full suite, run from this worktree with the repo venv, `PYTHONPATH=src`). Ruff check and format clean. New tests: about 101 in `tests/alerts/`, `tests/integrations/test_siem_wp21.py`, `tests/integrations/test_webhook_notifier.py`, `tests/console/test_alerts_panel.py`.

## Existing tests I had to change (all additive, none weakened)

- `tests/test_rbac.py::test_new_roles`: operator now also holds `alert.ack`.
- `tests/console/test_rbac_matrix.py::test_every_post_route_is_covered_by_an_audit_test`: added `alert.ack` to the covered set (covered by `test_alerts_panel.py`).
- `tests/monitors/test_scheduler.py::test_build_jobs_all_flags_run`: added `siem_enabled=True, alerts_enabled=True` because two new jobs exist.
- `notebooks/bootstrap_and_smoke.py` regenerated (`python -m supervisor.databricks.notebook`) because the DDL changed.

## Not done (also in BACKLOG)

- Splunk HEC strict per-event format (http sink posts a batch envelope; use file + forwarder or a relay), QRadar LEEF, live test against a real SIEM, OCSF validation against the official JSON schema.
- Full chain scan per poll (SIEM feed and alert signals) instead of a pushed-down range read.
- Console "Verify chain" does not write a `chain_verify` record, so `AL-CHAIN-VERIFY-FAIL` sees only failed audit-pack verifies today. The `ingress_reject` record is a contract with WP20 (payload `agent_id`, `reason_code`); align at merge.
- Alert lifecycle: no auto-close, no re-page of unacknowledged critical alerts, no alert-to-case promotion, pager and ITSM routes are stubs (queued notice only).
- Late chain entries behind the alert cursor are missed; no retention class for `alert` / `siem_event`; dead-letter files are not rotated.

## Open questions for the owner

1. Which SIEM (Splunk, Sentinel, QRadar, Databricks-hosted) and which format by default? OCSF version to target?
2. Real thresholds, severities and on-call for each route; should unacknowledged criticals re-page after N minutes?
3. Should an alert open a case on its own?
4. Retention for alert history and the SIEM Delta table?

## Files touched (for the integrator)

New: `src/supervisor/alerts/*`, `src/supervisor/jobs/alerts.py`, `src/supervisor/jobs/siem.py`, `src/supervisor/adapters/integrations/{ocsf,transport,deadletter}.py`, `src/supervisor/console/templates/_alerts_panel.html`, `config/alerts.yaml`, `docs/{siem,alerts}.md`, `docs/adr/D15-alerts.md`, `tests/alerts/*`, `tests/fixtures/alerts/*`, `tests/integrations/test_siem_wp21.py`, `tests/integrations/test_webhook_notifier.py`, `tests/console/test_alerts_panel.py`.

Rewritten: `src/supervisor/adapters/integrations/siem.py`. Edited: `adapters/integrations/__init__.py` (settings), `adapters/notify/__init__.py`, `adapters/http_json.py` (optional headers, empty body ok), `adapters/auth/audit.py` (target kind `alert`), `scheduler.py` (two jobs), `console/{context,routes,i18n}.py`, `console/templates/metrics.html`, `core/rbac.py` (`alert.ack`, route), `config.py` (block `# --- WP21 ---` before the validator, plus validator names), `schema/model.yaml` and both DDLs (appended `alert`, `siem_event`), `pyproject.toml` (ruff T20 ignores for `alerts/__main__.py` and `alerts/harness.py`), `config/users.yaml` (comment), `notebooks/bootstrap_and_smoke.py` (generated), `README.md`, `BACKLOG.md`, `docs/{index,bank-integration,console,threat-model}.md`, and the three tests listed above.

Merge hints: `config.py` and DDL/model.yaml additions are at the end of their blocks; expect conflicts with WP20 (`config.py`, `app.py` untouched by me, DDL tail) and WP22/WP24 (DDL tail, `console/routes.py` near the end of the metrics block, `core/rbac.py` PERMISSIONS and ROUTES tails, `tests/test_rbac.py` operator set). Regenerate DDL and the smoke notebook after merging `model.yaml`.

## Self-review (R1-R3, secrets, 500s, ASCII, defaults)

R1: alerts never call the gate; judge alerts exclude mock verdicts. R2: alert, SIEM and webhook text are built from fixed fields (ids, enums, counts, hashes); tests plant free text and a phone number. R3: no network unless `SIEM_SINK=http` or the webhook is switched on with a filled URL. Tokens are SecretStr, header only, never in repr, logs or dead-letter files. No exec/eval/subprocess. User errors on the new route are 4xx. CLI output is ASCII (asserted). All flags default off; off path tested.

Neighbouring-area notes (not fixed): `post_json` used by the gate SDK now returns `{}` for an empty 2xx body instead of raising on `resp.json()` (needed for collectors; behaviour for non-empty bodies is unchanged). The old `WebhookSiemSink` default transport raised raw `httpx` errors that `with_retry` did not retry; that is fixed through `transport.post_json_mapped`. Commit trailers follow TEAM_BRIEF (Fable 5.1), which differs from the session attribution reminder.


## Review follow-up (after REVIEW_WP21.md)

Done on top of the two review commits. Full suite: 2907 passed, 26 skipped (2900 after the review fixes; 2791 on main). Ruff check and format clean.

| Finding | What changed |
|---|---|
| F8 | The console **Verify chain** button writes a `chain_verify` record `{ok, failures, scope}` (root lane) after each verify (`console/auditpack.py`, a write failure is logged and never hides the result). `python -m supervisor.demo drill` writes `failmode_drill` `{ok, failures}` on its own throwaway chain and, with the new `--record` option (or `run_drill(sink=...)`), on the configured chain. The SIEM now sends only failed verifies (an ok verify is no finding). Tests in `tests/console/test_alerts_followup.py`: a failing verify raises `AL-CHAIN-VERIFY-FAIL`, a failing drill record raises `AL-FAILCLOSED-DRILL-FAIL`, passing ones are quiet. The drill is not scheduled, so the alert needs `--record` runs; BACKLOG row updated. |
| F9 | `WebhookNotifier.notify` only queues (`notice` row `webhook:<channel>`, status `queued`). New `WebhookNotifier.drain()` and scheduler job `notify` (`jobs/notify.py`, `python -m supervisor.jobs.notify`, `SCHED_NOTIFY_S` default 15, on only with `NOTIFY_WEBHOOK_ENABLED` and a filled URL) send queued rows with retry and dead letter: `queued` to `sent` or `dead_letter`. Alert webhook routes already run in the alert job, so they are unchanged. Tests: a hook that sleeps 4 s costs a console request nothing (`test_a_dead_webhook_does_not_slow_a_console_request`) and 5 queued notices take under 1 s; drain, retry and dead letter tests rewritten for the queue. |
| F10 | `ALERTS_SUPPRESSION_MAX_S` (default 30 days). A `suppressions` entry whose `until` is more than that ahead of the load time is a validation error naming the setting. The job passes the scheduler clock; the CLI uses the setting. Tests for 29 d ok, 31 d error, year 2099 error, custom cap. |
| F12 | CEF `rt` is milliseconds since the epoch (`rt=1792396800500`). |
| F13 | OCSF class 6003 has `src_endpoint` `{svc_name, hostname}` from `SIEM_SRC_APP` (default `supervisor`) and `SIEM_SRC_HOST` (default this host); never a user address. Class 3002 and 2004 are unchanged. Applies to the file, http and delta sinks. |
| F17 | New rule `AL-INGRESS-REJECT-AGENT` (per agent, 5 in 300 s, high, dedupe 1800 s, inbox and siem). The global `AL-INGRESS-REJECT-BURST` threshold is now 20. Fixture changed: INC-4 is now 24 rejects in 276 s (8 on one agent, 16 spread over 7 agents) and raises both ingress alerts (2 alerts, 3 and 4 repeats absorbed); new near misses (12 spread rejects, 4 rejects of one agent). Still 6 incidents per split; now 8 expected alerts, 587 signals. New baseline: precision, recall, dedupe and triage 10000 bp on both splits, 8 of 8, 0 FP, 0 FN, Wilson 6755 to 10000 bp, false alert rate bound 66 bp. |

Other test edits: `tests/monitors/test_scheduler.py::test_build_jobs_all_flags_run` also sets the webhook flag and a URL (the new `notify` job); rule counts 7 to 8 in `tests/alerts`.

Not done from the review: F11 (cosmetic over-count of `suppressed_count` after a crash replay), F14 (dead-letter replay lock between processes; replay with the scheduler stopped), F15, F16, F18 (stay in the review file and BACKLOG).
