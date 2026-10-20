# REVIEW WP21: SIEM export, OCSF, alert engine, webhook notifier

Reviewer: Opus (SOC analyst / detection engineer, reliability engineer, senior Python engineer).
Branch `worktree-agent-aa18ba5bdc4aeb239`, base `main` bf3a23a. Review fixes are committed on the
branch (2 commits, see below). No history rewrite, no merge, no push.

## Verdict: APPROVE WITH FIXES

The design is sound. The engine is a pure function, alert ids are deterministic, the rule file is
validated strictly with no code, routes fail independently, and only ids, enums, counts and
hashes leave the product. Flags are off by default. I found two defects that would have made
alerts silently miss events in the bank deployment (the WP20 contract mismatch and the cursor
without a watermark). I also found one SIEM defect that made the feed resend forever, and an
unbounded dead-letter file. All four are fixed on the branch. What is left is recorded below. None
of it blocks a merge with the flags off.

## Findings

| # | Severity | File:line | Issue | Action |
|---|---|---|---|---|
| F1 | High | `alerts/signals.py` `load_signals`; WP20 `gateway/ingress_auth.py:662-690` | WP20 writes each ingress rejection as a `console_action` row (`permission=ingress.auth`, `outcome=denied`, `target_id`=claimed agent, `detail`=`<reason>[;suppressed=n]`). It writes no `ingress_reject` chain record. After the merge, `AL-INGRESS-REJECT-BURST` could never fire. | **Fixed**: `_ingress_rejects` reads those rows as `ingress_reject` signals. A throttled row counts 1 + n (cap 1000). The unverified claimed agent id is kept only when it looks like an id, and the reason only when it looks like a code. The chain-record path is kept. Test `test_wp20_ingress_rejections_from_console_action_raise_the_burst_alert`. |
| F2 | High | `jobs/alerts.py` `run` | The cursor was the newest `(ts, sid)` that was judged, and the job read up to `now`. A chain entry gets its `ts` before its rows commit: payload first, then the entry, which takes seconds on Delta. Lanes also commit in any order. So an entry that becomes visible after a run, with a `ts` behind the cursor, was skipped forever. A plain cursor is not acceptable for a SOC feed. It must be a watermark with a lag. | **Fixed**: new setting `ALERTS_LAG_S` (default 30, range 0..3600). The read stops at `now - lag`. Two tests: with the lag, a late entry is found; with lag 0, the same entry is missed. Existing job tests pin `alerts_lag_s=0` (behaviour unchanged). Residual: an entry that commits more than the lag after its `ts` is still missed (BACKLOG: per-lane seq cursors). |
| F3 | High | `adapters/integrations/transport.py` `post_json_mapped` | On a 2xx with a body that is not a JSON object (`OK`, HTML, a JSON list; common for collectors and relays), `post_json` raised `ValueError`. This was not mapped, so `ChainEventFeed.poll` raised after a successful delivery and the cursor did not move. The same batch then went out again on every poll (a duplicate flood). The webhook alert route also went `failed`, so `redeliver` re-paged on every run. | **Fixed**: `ValueError` after a 2xx means "accepted" and returns `{}`. Test `test_transport_treats_a_2xx_non_json_body_as_accepted`. |
| F4 | Medium | `adapters/integrations/deadletter.py` | The dead-letter file had no size limit. If the SIEM is down for a weekend, the http sink parks a batch on every poll and the file can fill the laptop disk (or `/tmp`-like App storage). | **Fixed**: `max_bytes` (default 64 MiB; `SIEM_DEAD_LETTER_MAX_BYTES`). When the file is full, `put` raises and stores nothing. The SIEM feed then keeps its cursor (the chain is the buffer). The webhook route reports `failed` and is retried. Tests `test_dead_letter_is_bounded_and_a_full_file_keeps_the_feed_cursor` and `test_build_siem_sink_passes_the_dead_letter_limit`. Docs and BACKLOG are updated. |
| F5 | Medium | `alerts/rules.py` `_rule` | The loader accepted the key `enabled` and then ignored it. A rule with `enabled: false` kept firing. | **Fixed**: `enabled` must be a bool. A disabled rule is still validated and then left out. A suppression may still name it. Documented. Test added. |
| F6 | Low | `alerts/rules.py` `parse_rules` | Unknown keys at the top level and in suppression entries were silently ignored. For example, the typo `suppresion:` dropped a whole maintenance block with no message. | **Fixed**: these are now errors. Test added. |
| F7 | Low | `docs/siem.md:53`, `siem.py` docstrings, `jobs/siem.py` | The docs said "a restart neither skips nor repeats events". The real guarantee is at least once: a crash between `emit` and the cursor save resends the batch, and the batch key can differ if the next batch is larger. | **Fixed** wording: at least once, and the receiver dedupes on `event_id` (the Delta sink does this by its primary key). |
| F8 | Medium | `config/alerts.yaml` `AL-FAILCLOSED-DRILL-FAIL` | No component writes a `failmode_drill` chain record. `supervisor.demo.drill` prints its result and records nothing. So this rule can never fire, which gives false assurance. | **Recorded**: `docs/alerts.md` and BACKLOG now say so. Fix: make the drill record `{ok}`. Same class as the known `AL-CHAIN-VERIFY-FAIL` limit (only failed audit-pack verifies are seen until the console "Verify chain" writes a `chain_verify` record). |
| F9 | Medium | `adapters/notify/__init__.py` `WebhookNotifier.notify` via `FanoutNotifier` | With `NOTIFY_WEBHOOK_ENABLED=1`, every notice (case actions in console requests too) does a synchronous POST with 3 attempts x 10 s timeout + 3 s back-off. When the hook is down, a console request can hang for about 33 s. | **Recorded** (design): send from a queue or only from the alert job; or use a short timeout and 1 attempt on the request path. |
| F10 | Low | `alerts/rules.py` suppressions | `until` has no upper bound, so `until: 2099-...` is a permanent mute that looks time-boxed. | **Recorded**: cap the duration (for example 30 days) or require an approver id. |
| F11 | Low | `alerts/engine.py`, `jobs/alerts.py` | Crash between storing alerts and saving the cursor: the replay inserts nothing (good), but `suppressed_existing` is added again, and the replayed trigger counts as its own repeat (`prev == s.ts`). Result: `suppressed_count` is too high by the replayed amount. | **Recorded** (cosmetic). Skip a candidate whose `ts` equals the stored alert ts for the same key. |
| F12 | Low | `siem.py` `CEF_EXT` `rt` | `rt` is an RFC 3339 string. ArcSight CEF expects ms since the epoch or `MMM dd yyyy HH:mm:ss`. This was already so in phase 2. | **Recorded**: switch to ms epoch when the bank picks the SIEM. |
| F13 | Low | `ocsf.py` | Class 6003 API Activity lists `src_endpoint` as required in OCSF 1.1, and it is not emitted. A `chain_verify` record with `ok: true` would be emitted as a Detection Finding (noise; no writer today). The class/category/type_uid pairs are consistent (`type_uid = class*100 + activity`), `severity_id` maps 0..5 monotonically, and `time` is ms epoch. | **Recorded**: the docs already claim a subset, not conformance. Add `src_endpoint` (for example `{"svc_name": "supervisor-gateway"}`) and drop the ok-verify findings. |
| F14 | Low | `deadletter.py` `replay` | Replay rewrites the file with `os.replace` under an in-process lock only. A `put` from the scheduler process during a CLI `--replay-dead-letter` can be lost. | **Recorded**: replay with the scheduler stopped (document), or use a file lock. |
| F15 | Low | `alerts/signals.py` job_run | Job runs come only from the scheduler `last:<job>` row. A job that fails and then succeeds between two alert runs (job interval shorter than `SCHED_ALERTS_S`) is never seen. | **Recorded**. |
| F16 | Info | F1 fix | With the WP20 audit throttle on, skipped rejections take the time of the next written row (late by up to `INGRESS_AUDIT_THROTTLE_S`). Counts near a window edge can shift. | Documented in code. |
| F17 | Info | `alerts.yaml` defaults | The windows and thresholds are sensible starting points (5 blocks in 10 min per agent; quarantine, chain fail and drill fail at 1; tier 2 at 1 with 1 h dedupe). `AL-INGRESS-REJECT-BURST` is global (10 in 5 min). One agent with an expired key trips it every 30 min, and that hides a real stuffing attempt inside the dedupe. | Suggest at merge time: a per-agent rule plus a global rule with a higher threshold. Bank SOC decision. |
| F18 | Info | SIEM | WP20 rejections are not chain records, so the SIEM feed has no `ingress_reject` events. `alert_ack` is not exported. | Recorded in BACKLOG (rejections). Integrator: decide whether WP20 also records a chain entry. If it does, the alert loader reads both, so dedupe by keeping only one source. |

### Checks that passed

- Order independence (test shuffles the input), alert id = SHA-256(`key|ts|sid`)[:32]. Signal ids are unique (`lane:seq`, `verdict:<id>`, `job:<name>@<ts>`, `ingress:<action_id>[#k]`), so identical replays give identical ids and the insert is a no-op. There is no collision path short of SHA-256.
- Time source: signal timestamps only in the engine. The job uses the clock only for the read window.
- Rule YAML: `yaml.safe_load`, no eval. Bounds are checked: window and dedupe 0..7 d, threshold 1..100000, and threshold > 1 needs a window.
- SIEM cursor is saved after `emit`. Retry: 429/5xx, connect errors, timeouts and protocol errors are retried. Other 4xx and 3xx are not (redirects are not followed). The token is in the header only, `repr` hides it, it is not in the dead letter (test), and errors carry only the status or exception class.
- Webhook: the URL comes from config only (no SSRF from data). httpx defaults to TLS verify. Timeout 10 s.
- CEF: the header escapes `\` and `|`. Extensions escape `\`, `=`, CR and LF.
- Grep of the diff: no rationale, statement text, reason or summary leaves. Only tests plant free text and a phone number, and assert that it is absent.
- R1: alerts never call the gate. R2: chain payloads are unchanged. R3: no network unless `SIEM_SINK=http` or the webhook is enabled with a URL. RBAC: `alert.ack` for operator and admin, person-only, 4xx on a bad, stale or repeat ack. CLI output is ASCII. No new dependency. No secrets (FILL-ME only).
- Both modes: `alert` table and Delta MERGE tested on `databricks_fake`. The new `console_action` read uses the generic `read_range`.

## Harness (honest limits)

`python -m supervisor.alerts.harness`: both splits, 7/7 alerts, precision, recall, dedupe and
triage all 10000 bp, Wilson 95 % for precision and recall 6456..10000 bp (n = 7), `[OK] all GO`.
`generate.py --check` passes.

The 100 % is by construction. The same generator writes both splits (only the seed and agent
names differ). Each hard negative is "threshold minus one" for the shipped rule (4 blocks against
5, 9 rejects against 10). The background noise (about 50 blocks spread over 12 agents and 4 h)
never comes near a threshold. So the held-out split is not independent evidence. It proves the
logic (window edges, grouping, dedupe, mock exclusion, order independence). It does not prove
detection quality or real alert rates.

The two "harness can fail" tests are real. Threshold 4 gives a false positive on the near miss
(NO-GO precision). Threshold 9 gives a miss (NO-GO recall). The README already states that n is
small. The bank must replay its own week of decisions with `python -m supervisor.alerts test`.

## Commands and counts

| Check | Result |
|---|---|
| Full suite before review (`PYTHONPATH=src .venv/bin/python -m pytest -q -x`) | 2892 passed, 26 skipped |
| Full suite after review fixes | 2900 passed, 26 skipped |
| `ruff check .` / `ruff format --check .` | clean |
| `python -m supervisor.alerts.harness` | `[OK] all GO` (both splits) |
| `python tests/fixtures/alerts/generate.py --check` | exit 0 |
| Offline verify of an export with `alert` + `alert_ack` records (`python -m supervisor.evidence.verify <export>`) | `RESULT: OK` (2 signed roots, lane agent:a1 8 entries, payloads re-hashed) |

Test counts: before 2892 passed, 26 skipped; after review fixes 2900 passed, 26 skipped (full suite, `-x`, 277 s).

New review tests (8): `tests/integrations/test_siem_wp21.py` (3), `tests/alerts/test_rules_engine.py` (2),
`tests/alerts/test_job_service.py` (3).

## Residual risks

1. Alerts miss entries that commit more than `ALERTS_LAG_S` after their timestamp (F2 residual).
2. Two rules can see little or nothing today: `AL-FAILCLOSED-DRILL-FAIL` (no producer) and `AL-CHAIN-VERIFY-FAIL` (only failed audit-pack verifies).
3. Webhook notices on the console request path are synchronous (F9).
4. Thresholds are illustrative. The harness shows the logic is correct, not that the alert rates suit a bank.
5. SIEM delivery is at least once. Each receiver must dedupe on `event_id`.
6. The SIEM feed and the alert loader scan the chain on every run (BACKLOG). This is heavy on a large Delta chain.

## Merge notes (for the integrator)

- `src/supervisor/config.py`: the WP21 block, plus the new `alerts_lag_s`, plus 2 validator path names. WP20 and WP24 also append blocks. Keep all of them and keep the validator name list as a union.
- `schema/model.yaml`, `schema/ddl/sqlite.sql`, `schema/ddl/databricks.sql`: `alert` and `siem_event` are appended at the tail, where WP22 and WP24 also append. Merge `model.yaml`, then regenerate both DDLs and `notebooks/bootstrap_and_smoke.py` (`python -m supervisor.databricks.notebook`). Do not hand-merge the DDL.
- `src/supervisor/core/rbac.py`: PERMISSIONS and ROUTES tails (`alert.ack`, `/console/alerts/{alert_id}/ack`). `tests/test_rbac.py` operator set and `tests/console/test_rbac_matrix.py` covered set: take the union.
- `src/supervisor/console/routes.py`: `_alerts_data` and `**_alerts_data(ctx)` in `_metrics_data`, plus the ack route near the inbox route. WP22 and WP24 add pages.
- `src/supervisor/scheduler.py`: two JobSpecs (`siem`, `alerts`) at the end of `build_jobs`. If WP24 moves case creation into a `case_service` helper, the jobs here do not open cases, so there is no logic overlap. Only the list tail conflicts. `tests/monitors/test_scheduler.py` all-flags test needs `siem_enabled` and `alerts_enabled` plus any WP24 flags.
- `src/supervisor/adapters/http_json.py`: WP21 adds a `headers=` kwarg and an empty-body check to `post_json`. WP20 appends `post_bytes`. The changes do not overlap: keep both. `post_bytes` has the same non-JSON-2xx behaviour that F3 fixed for SIEM. That is correct for the gate SDK (the gateway always answers JSON).
- WP20 contract: the F1 fix depends on WP20's `console_action` shape (`permission="ingress.auth"`, `outcome="denied"`, `target_kind="agent"`, `target_id`, `detail="<reason>[;suppressed=n]"`). If WP20 changes these names, update `alerts/signals.py` `_ingress_rejects` and the test helper `_ingress_denied`.
- `docs/threat-model.md`, `README.md`, `BACKLOG.md`, `docs/index.md`: additive rows, so expect text conflicts only.

## Review commits

1. `WP21 review: alert watermark lag, WP20 ingress rejections, strict rule loader`
2. `WP21 review: SIEM 2xx non-JSON accepted, bounded dead letter, at-least-once wording`
