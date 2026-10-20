# HANDOFF WP39: Activity and analytics parity, nine alert use cases

Branch `wp39-activity-parity`, built on `wp37-verdict-detectors` (merged head `bfc6e09`, the final WP37 head).
Flag `CONSOLE_DECISIONS_V2`, default off (off = the pages of v0.3.0). Nothing pushed, nothing merged
(except the WP37 head into this branch), no history rewritten. WP38 branch not merged (see section 7).
Author: Sonnet 5.5 engineer.

## 1. What was built

| Part | Where |
|---|---|
| Decisions drawer v2: tabs Request (masked request, fragments highlighted in place, formatted and JSON of the masked record), Response (status, decision, rule ids, reason, **Observed decision** line, payload after masking), Detections (row per finding with score and threshold in bp, masked entities and fragments, hint; row per `not_executed`; located and not located fragments; coverage), Metadata (request id, correlation id, latency split rules / detectors / overhead / per detector, links to trace span, same-correlation decisions, alerts, case). "Not evaluated" badge with reasons on the row and in the drawer. Deep links `?event=` (decision id or request id) and `?correlation=`, stripped from the address bar by `console.js` | `console/decisions_v2.py`, `templates/_decision_drawer_v2.html`, `_decisions_list_v2.html`, `decisions.html`, `routes.py`, `static/console.js` |
| List filters: status, detection code, not evaluated, consumer, direction, correlation id (`corr`); status tiles | `decisions_v2.py` |
| CSV export: POST (audited, 2 `console_action` rows, permission `decisions.export` for auditor and admin), 18 allow-listed columns, cap `CONSOLE_EXPORT_MAX_ROWS` (5000), ASCII `truncated: N of M rows`, formula and control character neutralising, download by GET | `decisions_v2.py`, `routes.py`, `core/rbac.py`, `_decisions_export_result.html` |
| Traces: correlation id on head and span detail, findings chip, link to the decision, list filter `corr` | `console/traces.py`, `trace.html`, `_span_detail.html`, `traces.html` |
| Analytics: Gate tab tables per agent, application, rule, detector and code with share in bp; "Policy actions over time" (4 sparklines); Detectors tab (p50 / p95 per detector, findings per code, harness verdict incl. `GO (indicative)`); all from `decision_daily` | `console/analytics_v2.py`, `analytics.py`, `_analytics_dd.html`, `_analytics_tab_detectors.html` |
| Rollup: table `decision_daily` (both DDLs, model.yaml, generator, notebook regenerated); `python -m supervisor.jobs.decision_rollup`; scheduler job (listed only with the flag), `SCHED_DECISION_ROLLUP_S` | `jobs/decision_rollup.py`, `scheduler.py`, `config.py`, `schema/` |
| Additive nullable facts (only with `DETECTORS_ENABLED=1`): `agent_event.request_id`, `consumer_id` (from `context.consumer_id`), `latency_rules_us`, `latency_detectors_us`, `detector_latency_json`; `alert.correlation_id` | `gateway/detector_gate.py` (+2 lines in `engine.py`), `core/models.py`, `schema/model.yaml` |
| Nine alert rules in `config/alerts.yaml`; engine gains `where_min` and `rate` (rule hashes of old rules unchanged); derived signals `gate_finding`, `gate_request`, `coverage_gap` (+ observe verdict rows); alert row, evidence record, triage text and SIEM event carry the correlation id | `alerts/rules.py`, `engine.py`, `signals.py`, `service.py`, `siem.py`, `jobs/alerts.py` |
| Drills in the alert harness (`python -m supervisor.alerts.harness`, `--no-drills` to skip): fire, quiet, suppress, SIEM correlation id, rate sweeps with Wilson intervals, storm | `alerts/drills.py`, `alerts/harness.py` |
| Console harness: all-pages probe (3 flag states x 4 roles x 2 languages), fingerprint with planted personal data, 22 adversarial probes, SOC and DPO metrics, baseline, `--check` | `console/activity_harness.py`, `demo/activity_seed.py`, `data/eval/activity/baseline.json` |
| Docs: `docs/console.md` section, `docs/alerts.md` (nine use cases, signals, drills), ADR `docs/adr/D32-activity-parity.md` (D23 is the highest on the branch; D24 to D31 left to other packages), README row, CHANGELOG line, 9 BACKLOG rows, `docs/siem.md`, `docs/api.md` (`context.consumer_id`), threat model 3.11 | `docs/`, `README.md`, `BACKLOG.md`, `CHANGELOG.md` |
| Screenshots (EN, VI, full page, plus one dark) | `docs/design/screens/wp39-*.png` |

## 2. Decisions I took (please check)

1. **The Request tab is rebuilt, not read.** The gate stores a keyed hash of the arguments only (R2), so the tab uses the recorder events of the same trace (`args_masked`, `result_masked`, level `masked`), masks them again, and locates each fragment by offset, else by token, else "not located". A gate-only client sees findings and fragments but not the text around them. The transformed payload (Response tab) is likewise rebuilt and labelled so. BACKLOG has "gate stores a masked payload".
2. **Every finding text is masked again on the way out** (fragments, entity tokens, reasons, verdict rationale), so a faulty detector row cannot leak (probe and test).
3. **Export is a POST plus a file download**, not a GET that writes: the console rule is "GETs never write", and the audit rows need a POST. The file stays in `CONSOLE_EXPORT_DIR` (wiped on App restart).
4. **Rate rules.** p95 above a budget is written as "more than 500 bp of calls above it". `rate.min_bp` plus `threshold` (minimum count) avoids "1 of 2" alerts.
5. **AL-ERROR-RATE is derived.** HTTP statuses of gate routes are not stored; the rule counts ingress rejections and fail-mode decisions. A plain 400 for a bad payload is invisible (BACKLOG).
6. **AL-REDACTION-SPIKE uses a fixed share (3000 bp)**, not a rolling baseline.
7. **AL-THREAT-NOT-ENFORCED** works on two record kinds (WP38 review fact): findings with hint `pause` / `block` on SHADOW agents, and tier 0 `verdict` rows labelled `observe_would_block` / `observe_would_pause` joined to `agent_event` by decision id. Written against the described rows; not run against WP38 code.
8. **Coverage gap** counts an agent seen under another id as a gap for the id the gate never saw. An id that is not a plain id is dropped.
9. **Commit trailers** use the brief's line (`Claude Fable 5.1`).
10. Flag off: no change to the old pages (test `test_flag_off_is_todays_drawer_and_list`); the detectors fingerprint test passes with the new null columns added to its ignore list (one edit in `tests/detectors/fingerprint.py`).

## 3. Flags and commands

| | |
|---|---|
| Flags | `CONSOLE_DECISIONS_V2=1` (default 0); `CONSOLE_EXPORT_MAX_ROWS` (5000); `SCHED_DECISION_ROLLUP_S` (3600). Verdict data needs `DETECTORS_ENABLED=1`; alerts need `ALERTS_ENABLED=1` |
| Rollup | `python -m supervisor.jobs.decision_rollup [--days N \| --from D --to D \| --backfill]` |
| Alert harness and drills | `python -m supervisor.alerts.harness` |
| Console harness | `python -m supervisor.console.activity_harness [--check] [--record --commit SHA --date DAY]` |
| Screenshots | `python tools/console_screenshots.py --wp39 --data-dir NEW_FOLDER` |
| Demo store | `python -m supervisor.demo.activity_seed --data-dir NEW_FOLDER` |
| Delta | run `python -m supervisor.jobs.bootstrap_schema` (new columns on `agent_event` and `alert`, new table `decision_daily`) |

## 4. Harness results (SQLite, synthetic, real gate with detectors on; thresholds ILLUSTRATIVE)

```
all pages: 360 requests (3 flag states x 4 roles x 2 languages), 0 bad, ok 10000 bp
DPO: 21 pages and the export scanned, leak_items=0, export columns exact=True
SOC: triage complete 15/15 decisions (10000 bp, Wilson 95% [7961, 10000])
adversarial probes: 22/22 (10000 bp, Wilson 95% [8513, 10000])
alert drills: GO  (9 rules fire / quiet / suppress / SIEM correlation id; 4 rate rules 40 of 40 above
                   and 40 of 40 quiet below, Wilson [9123, 10000] bp; storm 5000 signals -> 1 alert)
OVERALL: GO
```

Expert rubric: **SOC analyst on call** (triage from the drawer alone, the nine use cases fire and
stay quiet, hostile input does not break the page) and **data protection officer** (no planted
name, phone, ID number or e-mail on any page or in the export; export columns are exactly the
allow-list). Failure taxonomy: the first harness run found one wrong probe (malformed JSON written
into a json column poisons the store itself; replaced by "recorder text that is not JSON"); no
product defect was open at the end. Honest limits: n = 22 probes and 15 decisions are small (Wilson
lower bounds 8513 and 7961 bp); all data is synthetic; the drills prove the logic, not real rates.

## 5. Tests

| | Count |
|---|---|
| Before (WP37 head `bfc6e09`, a git checkout equivalent) | 3,829 passed, 29 skipped (measured on an unpacked archive as 3,801 passed + 3 tests that need a git checkout + 25 skipped for the same reason) |
| After (this branch, full suite) | **3,907 passed, 29 skipped** |
| New | 78 (decisions 47, analytics 20, harness 6, facts 3, plus 2 in the other files) and edits to 6 existing expectations (alert fields, rule list, triage line count, rbac audit list, fingerprint ignore list) |

```
$ uv sync
$ uv run python -m pytest -q -p no:cacheprovider -x
3907 passed, 29 skipped, 1 warning in 556.70s (0:09:16)
$ uv run python -m ruff check
All checks passed!
$ uv run python -m ruff format --check
700 files already formatted
$ uv run python -m supervisor.alerts.harness
[OK] drills GO
[OK] all GO
$ uv run python -m supervisor.console.activity_harness
OVERALL: GO
$ uv run python -m supervisor.detectors.harness --check     (WP37, unchanged)
```

Both modes: SQLite runs everywhere; the rollup SQL on the Delta dialect is tested on the recorded
fake (Delta functions, typed timestamp parameters, no SQLite functions); `alert` row on the fake is
covered by the existing test with the new column.

## 6. Files touched outside the package

`src/supervisor/gateway/engine.py` (2 lines: rules time measured in `_evaluate`, passed to `apply`),
`gateway/detector_gate.py` (WP37 file: consumer id, latency facts, 4 extra `agent_event` fields),
`core/models.py`, `core/rbac.py` (`decisions.export`), `config.py` (block `# --- WP39 ---`),
`scheduler.py`, `schema/model.yaml`, both DDLs, `notebooks/bootstrap_and_smoke.py`,
`adapters/integrations/siem.py` (one attr), `config/alerts.yaml`, `jobs/alerts.py`,
`console/routes.py`, `console/decisions.py` (delegates when the flag is on), `console/traces.py`,
`console/analytics.py`, `console/alerts_list.py`, `console/i18n.py`, `static/console.css` (5 lines:
`mark.hl`), `static/console.js` (9 lines: strip deep-link parameters), templates `base.html`,
`_ui.html`, `analytics.html`, `trace.html`, `traces.html`, `_span_detail.html`, `_alert_drawer.html`,
`tools/console_screenshots.py` (`--wp39`), docs and `data/eval/activity/`. Tests edited:
`tests/alerts/*` (3), `tests/console/test_rbac_matrix.py`, `tests/console/conftest.py`,
`tests/detectors/fingerprint.py`.

## 7. Merge notes and risks

* **WP38 conflict (expected).** WP38's review added an "Observed decision" line to `console/decisions.py` and
  `_decision_drawer.html` (the v1 drawer). Keep both. My v2 drawer has the same line under the
  Response tab (mode `enforce` / `shadow` / `observe`, observed decision from `observe_would_*`
  verdict rows, approvals from the chain record key `approvals` when present, else "-"). I could not
  see the WP38 code: **reconcile the field names at merge**.
* `decisions.py` is also edited by me (a delegation at the top of `list_view` and `drawer_view`).
* Existing alert tests count `judged`; derived signals are excluded from that count on purpose.
* Pre-existing, not mine: in the v1 no-JS fallback `?drawer=` the drawer has `hidden` set (base.html
  needs `drawer_open`); I set `drawer_open` only for v2.
* The WP37 reviewer's note F12 (correlation id recorded only with detectors on) holds: the new columns
  are written only with `DETECTORS_ENABLED=1`.

## 8. Not done (BACKLOG has the rows)

Gate-stored masked payload; HTTP status persistence for AL-ERROR-RATE; rolling baseline for
AL-REDACTION-SPIKE; a secrets detector (`secret.*`) for AL-SECRETS-OUTPUT; exact multi-day detector
percentiles; inventory alias map; streaming export to a UC volume; SQL push-down of list filters at
the scan cap. Vietnamese labels are my own wording and need a native review. Screenshots were
taken before the Observed-decision line was added to the Response tab.

## 9. Open questions for the owner

1. Is it acceptable that the Request tab needs the recorder event (the gate stores no masked payload)? Option: store a masked copy in the gate.
2. Export file location: keep `CONSOLE_EXPORT_DIR` (wiped on restart) or a UC volume path?
3. AL-ERROR-RATE: persist route statuses so plain 400s count too?
4. Thresholds of the nine rules (latency budget 50 ms, redaction 30 percent, detector failure 5 percent, PII output 3 in 10 minutes): set by the bank SOC?
5. Should `consumer_id` be required in the SDK (WP38) so the per-application table is never empty?
6. Coverage gap: should an agent id that is not in the registry raise a gap at all, or only a separate "unknown agent" alert?
