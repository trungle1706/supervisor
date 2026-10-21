# INTEGRATION WAVE 2 AND 3 (phase 3)

Branch `phase3-wave2` in worktree `/home/trung/supervisor/.claude/worktrees/agent-a28c62b5d9020b7a5`.
Base: main `3aed7f9` (v0.3.0). Not pushed. Not merged into main. `__version__` is still `0.3.0`.
Ten packages merged: WP37, WP26, WP28, WP29, WP38, WP27, WP30, WP31, WP39, WP25 (WP40 not started).

## 1. Result

| Check | Result |
|---|---|
| Merges | 10 of 10, `git merge --no-ff`, in the order of the integrator prompt; conflicts resolved by keeping both sides |
| Full suite `uv run python -m pytest -q -p no:cacheprovider` (no `-x`) | **5108 passed, 30 skipped, 1 warning** (v0.3.0: 3684 passed, 29 skipped). The extra skip is the WP31 PDF test (`fpdf2` is the optional extra `pdf`, not in the default sync). The warning is the old APScheduler `JobLookupError` thread warning of `test_start_and_stop_apscheduler` |
| `uv run python -m ruff check` / `ruff format --check` | `All checks passed!` / `909 files already formatted` |
| Harnesses (13 commands, section 6) | all exit 0, no drop below any baseline; the WP25 classifier stays NO-GO (expected, shipped disabled) |
| Flaky SIEM test looped 30 times | `loop: 30 passed, 0 failed of 30` |
| Console smoke, port 8143, all wave-2 flags on | 99 GET routes 200 as admin (console pages, tabs, drawers, new `/v1/...`), 0 x 500, 0 tracebacks in the app log; the other 10 answers are 4xx user errors on made-up file names or missing query params (section 7) |
| Databricks path | databricks_fake modules of every package together: `429 passed`; `bootstrap_schema` on a SQLite file made from the v0.3.0 DDL: 13 new tables, 12 new columns, old row kept, second run adds nothing |
| Assurance packs, demo agents, mock mode | same 24 ok / 3 warn / 13 fail as v0.3.0 on the same command (the fails are the known v0.3.0 ones); WP26 F13 changes nothing for them |

## 2. Merge order and commit ids

```
main 3aed7f9 (v0.3.0)
  |-- 2f4fa5b  Merge WP37 verdict v2 + detectors      (wp37-verdict-detectors bfc6e09)   no conflict
  |-- 5a593fb  Merge WP26 HTTP MCP + tool lock         (wp26-mcp-http 0e5460f)             7 files
  |-- 89da9a2  Merge WP28 multi-turn red team          (wp28-redteam-multiturn 1ec5936)    4 files
  |-- 911bf59  Merge WP29 risk register                (wp29-risk-register 5c0d887)       15 files
  |-- 1555ceb  Merge WP38 collectors + policy modes    (wp38-collectors 71a79f8)           8 files
  |-- f19e3f4  Merge WP27 session monitor              (wp27-session-monitor a9907e0)     12 files
  |-- ef7b6c9  Merge WP30 controls + tasks             (wp30-controls 2432f60)             9 files
  |-- c971806  Merge WP31 transparency report          (wp31-transparency 8bc25a1)        22 files
  |-- 7ee4aa4  Integration: WP31 tests expect the merged WP30
  |-- 2e22ac8  Merge WP39 activity parity, 9 alerts    (wp39-activity-parity 21a4bec)     18 files
  |-- b6d31cd  Merge WP25 injection classifier         (wp25-classifier ec535ee)           7 files
  |-- ece5fc4  Integration: WP25 scorer in the WP26 tool lock (+ config.py blocks in WP order)
  |-- f0b188d  Integration: ADR registry, flaky SIEM test
  |-- 4d21071  Integration: CHANGELOG v0.4.0-pre, BACKLOG
  |-- 2e339ca  Integration: threat-model numbering, one Agent row in console.md
  |-- 3e3cb08  Integration: HANDOFF / REVIEW files moved to docs/phase3/wave2/
  |-- 63f6c90  Integration: screenshots --wave2, 42 reference screens
  `-- (head)   Integration: this report
```

WP25 was merged last, as asked. At merge time `HANDOFF_WP25.md` on `wp25-classifier` had the
"WP25c" section that names G4, G5 and G6 closed (head `ec535ee`, the coordinator's final head).
The classifier entry stays `enabled: false` in `config/detectors.yaml`. The fail-closed switch is
now the setting `classifier_fail_closed_approved` (env `CLASSIFIER_FAIL_CLOSED_APPROVED`) in the
WP25 block of `config.py`, and the model card carries an `approval` block (approver plus the
`weights_sha256` it approves); a changed weight file withdraws the approval.

## 3. Conflicts and how I solved them

Every conflict was resolved by keeping both sides; generated files were never hand-merged
(regenerated after each merge, section 4). After every merge I re-ran the tests of the touched
areas (logs `wave2_int_m*.txt` in the scratchpad) and two full runs in the middle (after WP31:
6 failures, all WP31 tests written with WP30 absent, fixed in `7ee4aa4`; after WP25: 5100 passed).

| Merge | File | Resolution |
|---|---|---|
| all | `config.py` | one `# --- WPnn ---` block per package; at the end re-ordered by WP number (WP25, 26, 27, 28, 29, 30, 31, 37, 38, 39) in `ece5fc4`; `_absolute` validator list = union (33 entries, no duplicate); AST check: 278 fields, no duplicate name |
| all | `schema/model.yaml` | union of the table blocks and of the `agent_event` columns (WP37, WP27, WP39) |
| all | `schema/ddl/*.sql`, `notebooks/bootstrap_and_smoke.py`, `policies/schema.json`, `docs/console.md` role matrix | took one side, then regenerated |
| WP29, WP38, WP27, WP30, WP31 | `core/rbac.py` | union of PERMISSIONS and ROUTES blocks; the union left the closing `),` of the previous permission out four times, re-inserted (scripted, then checked by the RBAC matrix test) |
| WP29, WP30, WP31 | `ops/openapi.py` human-path prefixes, `adapters/auth/authz.py` audited POST prefixes | one tuple with every prefix: `/v1/mcp/tools`, `/v1/risks`, `/v1/controls`, `/v1/tasks`, `/v1/transparency` |
| WP29, WP27, WP30, WP31 | `tests/console/test_rbac_matrix.py` | JSON-API prefix `/v1/` (WP27's general form covers WP26, WP29, WP30, WP31); audit coverage list = union (`collectors.add`, `transparency.generate`, `decisions.export`); path params union |
| WP27, WP30, WP31, WP39 | `scheduler.py` | docstring rows union; job blocks union, each listed only under its flag (closing parens of the WP30 and WP31 blocks re-inserted) |
| WP27 | `gateway/engine.py` | WP38 `sem` / `observed` / `observe_approved` / `consumer_id` and WP27 `sess` on `Decision`; both `as_result` blocks; `_observe` (WP38) then `d.sess = sess` (WP27) in `_evaluate`; WP38 `_observe` / `_apply_mode` and WP27 `_pre_session` / `_session_observe` methods; both chain-payload blocks |
| WP25 | `gateway/engine.py` | imports union (`CLASSIFIER_PAUSE_RULE`, `FAILED_RULE`); `classifier_pause` field; `would_pause` = `d.observed is None and (pause rule matched or d.classifier_pause)` |
| WP27 | `gateway/policy.py` | hash dump drops unset WP38 keys and an unset `monitors.session` |
| WP30 | `cases/service.py` | `NO_CLOCK_SOURCES = ("inventory", "mcp_tool_review", "task")`. WP27's `session_escalation` cases open through `monitors.common.open_case`, which sets no clock, so it needs no entry (checked); WP29 and WP31 open no cases |
| WP31 | `console/agent_detail.py`, `context.py`, `nav.py`, `routes.py`, `templates/agent.html`, `i18n.py` | Controls and Tasks (WP30) then Transparency (WP31) tabs, pages, nav items (codes CT, TK, TP), contexts and i18n blocks; the union split one `_T.update({...})` in `i18n.py` and two blocks in `agent_detail.py` / `context.py`, closed by hand |
| WP39 | `config/alerts.yaml`, `alerts/rules.py` | 18 rules: WP21 8 + WP27 `AL-SESSION-ESCALATION` + WP39 9; the hash of every rule from v0.3.0, WP27 and WP39 is unchanged (checked by loading the three source files: `changed: []`); `case` source keeps `case_type`, plus the WP39 sources |
| WP39 | `core/models.py`, `tests/detectors/fingerprint.py` | WP27 and WP39 nullable `agent_event` fields; both sets in the fingerprint ignore list |
| WP39 | `tests/alerts/*` | rule list union, `[OK] 18 rule(s)` |
| WP39 | `console/i18n.py` | `mode_enforce` and `mode_observe` were defined by WP38 and WP39 with the same text (duplicate-key test failed); the WP39 copy is removed |
| WP39 vs WP38 | `console/decisions.py`, `_decision_drawer.html` | merged without a git conflict: WP38's Observed-decision line on the v1 drawer and WP39's v2 delegation are both there. The v2 line now reads WP38's chain keys `mode`, `observed_decision` and `observe_approved` (`decisions_v2._observed`, `approvals` kept as a fallback); test added |
| WP39 vs WP38 | `gateway/detector_gate.py` | `agent_event.consumer_id` now records WP38's resolved `Decision.consumer_id` (`recorded_consumer_id`), never the raw context value; a plain id the policy does not know is recorded as NULL. The demo kit `demo.activity_seed` registers its three demo consumers in a copy of the policy folder. Test added |
| WP31 | `tests/transparency/*`, golden fixture | the WP31 tests expected the WP30 package to be absent (`not_built`); after the WP30 merge the controls section says `flag_off` (`CONTROLS_ENABLED`). Expectations updated, golden regenerated with its generator, baseline unchanged; the console test reads the PDF only when `fpdf2` is installed |
| WP25 | `pyproject.toml` | ruff per-file ignores: union |
| all | README, BACKLOG, CHANGELOG, `docs/index.md`, `docs/threat-model.md`, `docs/console.md`, `docs/INTEGRATION_GUIDE.md` | union, then cleaned once: one ADR row in the index, threat-model sections 3.10 to 3.18 (WP30 and WP25 had landed after section 5), one Agent row and one Integrations row in `docs/console.md`, one pattern C row in the integration guide, BACKLOG table without blank lines |

## 4. Regeneration and integration commits

| Step | What |
|---|---|
| a. Generated files | After each schema merge: `uv run python -m schema.generate`, `uv run python -m supervisor.databricks.notebook`, `policies/schema.json` from `policy_json_schema()`, the role matrix in `docs/console.md` from `rbac.matrix_markdown()`. Snapshot files: `UPDATE_SNAPSHOTS=1 UPDATE_ADVISORY_SNAPSHOTS=1` on the three snapshot tests. The final run of all of them gave **no diff**, so there is no separate regeneration commit (each merge commit carries its regenerated files) |
| b. Hot files | `config.py` blocks once each, in WP order; `app.py` routers once each (mcp_lock, risk, session, controls, tasks, transparency); `core/rbac.py` and the RBAC matrix test (`192 passed`); scheduler jobs `risk_evidence`, `control_status`, `task_due`, `transparency`, `decision_rollup`, `redteam_nightly` listed only under their flags, `session_monitor` as a JobSpec with its enable flag like the WP21 jobs; `config/alerts.yaml` 18 rules, old hashes unchanged; `NO_CLOCK_SOURCES` as above |
| c. ADRs | D23 to D32 exist once each with the titles of the status table; new `docs/adr/REGISTRY.md` lists D01 to D32 and the next free number D33 |
| d. Flaky test | `test_chain_feed_writes_schema_events_once`: besides case ids, the digit grep now ignores 64 / 32 hex digests, `act_` refs and hex tokens of 16+ characters that hold a letter a-f (a phone, CCCD or account never does); new test `test_pii_digit_grep_ignores_hashes_hex_ids_and_actor_refs_only`. 30 runs in a loop: 30 passed |
| e. WP26 F13 | kept as the security default (no flag); documented in CHANGELOG "Behaviour changes" and `docs/mcp-gateway.md` section 3. `policies/baseline.yaml` and the demo agents make no MCP data-method call (no MCP client in `src/supervisor_agents`), and the assurance run in mock mode gives the v0.3.0 result, so no `mcp.resources.read` was added to the baseline policy. The credit-memo benchmark code makes no `resources/read`, `prompts/get` or `completion/complete` call (search of its backend source: 0 hits) |
| f. WP25 scorer | `supervisor.gateway.mcp_scorer.install(settings)` registers `score_tool_description` with `mcp_lock.register_description_scorer` only when `DETECTORS_ENABLED=1` and `detectors.injection_classifier.enabled: true`; called by the `/v1/mcp/tools` routes and the review CLI. Report only (`scan.score_bp`). Refused weights (`ModelIntegrityError`) become `mcp_lock.ScorerRefused`: finding `scorer_refused`, the tool is never seeded by trust-on-first-use, the review case is high. 7 tests in `tests/gateway/test_mcp_scorer.py` |
| g. CHANGELOG | one section "v0.4.0-pre (phase 3 wave 2 and 3) - not released": feature table, flags table, behaviour changes, Delta migration note |
| h. BACKLOG | no duplicate rows found; blank lines inside the table removed; two rows closed by this integration removed (WP39 F18 resolved consumer id, WP25 scorer registration); three rows updated; all other "not done" rows kept |
| i. Files | 20 `HANDOFF_WP*` / `REVIEW_WP*` files moved with `git mv` to `docs/phase3/wave2/`. `WP25B_PROTOCOL.md` was never at the repo root: it lives in `data/eval/injection_vi_en/`, where the model card, the trainer, the CV tool and the validation report name it, so it stays there |
| Screens | `tools/console_screenshots.py --wave2` (new, dev only) seeds starter risks and controls, their evidence, the payments task list and one signed report; 23 wave-2 screens plus 19 WP39 screens in `docs/design/screens/wave2/` (viewport PNGs, 8.4 MB) |

## 5. Test counts

| Point | Passed | Skipped |
|---|---|---|
| main v0.3.0 (CHANGELOG) | 3684 | 29 |
| after WP31 merge (full run) | 4887 + 6 failed (fixed in `7ee4aa4`) | 30 |
| after WP25 merge (full run) | 5100 | 30 |
| `3e3cb08` (all code and tests) | 5108 | 30 |
| final, on `affe849` (this report committed) | **5108** | **30** |

Last line of the final full run: `5108 passed, 30 skipped, 1 warning in 951.82s (0:15:51)`.

## 6. Harness commands and their last line

All from the worktree, mock or synthetic paths, thresholds ILLUSTRATIVE.

| Harness | Command | Last line |
|---|---|---|
| Detectors (WP37) | `uv run python -m supervisor.detectors.harness --check` | `[OK] no drop below the baseline` (overall NO-GO only because the run includes the disabled WP25 classifier; `--detector dlp_vn --detector injection_regex --detector judge_advisory --check` gives `OVERALL: GO` and `[OK] no drop below the baseline`) |
| Injection classifier (WP25) | `uv run python -m supervisor.detectors.harness --detector injection_classifier --check` | `[OK] no drop below the baseline` (`OVERALL: NO-GO`, as recorded; held-out recall 8111 bp, false alarm 2522 bp) |
| MCP HTTP (WP26) | `uv run python -m supervisor.gateway.mcp_http_harness --no-latency` | `OVERALL: GO` |
| MCP HTTP probes on databricks_fake | `uv run python -m supervisor.gateway.mcp_http_harness --backend databricks_fake --split probe --no-latency` | `OVERALL: n/a` (probe-only split; same misses as SQLite, 12 documented known-gap probes) |
| Red team probes (WP28) | `uv run python -m supervisor.redteam.multiturn probes` | `[INFO] known limitation p-ben-07` (result line: `[OK] probes 40 counted 38 passed 38`) |
| Red team baseline | `uv run python -m supervisor.redteam.multiturn baseline` | `[OK] no regression against the recorded baseline` |
| Red team data | `uv run python -m supervisor.redteam.multiturn build-data --check` | `[OK] data files are current` |
| Session monitor (WP27) | `uv run python -m supervisor.monitors.session_harness --check` | `[OK] no drop below the baseline` (`OVERALL: GO`) |
| Collectors (WP38) | `uv run python -m supervisor.collectors.harness --check` | `[OK] no drop below the baseline` (`OVERALL: GO`) |
| Risk register (WP29) | `uv run python -m supervisor.risk.harness` | `[OK] all GO` (dev 30, held-out 20 at 10000 bp; adversarial 20/20; starters 19 risks, 86 links, 0 problems) |
| Controls (WP30) | `uv run python -m supervisor.controls.harness` | `[OK] all GO` (adversarial 24/24; starters 28 controls, 165 maps, 0 problems) |
| Transparency (WP31) | `uv run python -m supervisor.transparency.harness` | `[OK] all GO` (dev 36, held-out 18, leaks 0, adversarial 24/24) |
| Alerts (WP21 + WP39 drills) | `uv run python -m supervisor.alerts.harness` | `[OK] all GO` (8/8 alerts both splits; `[OK] drills GO`) |
| Activity (WP39) | `uv run python -m supervisor.console.activity_harness --check` | `[OK] no drop below the baseline` (`OVERALL: GO`) |

WP31 live report with `CONTROLS_ENABLED=1` (reviewer's note): on the smoke store,
`python -m supervisor.transparency generate payments` made v1 of the regulator, customer and
internal reports. The controls section is live: 16 controls in scope (13 product, 3 bank-owned),
compliance 0 bp (no control has working evidence on the demo store), and the `tasks` fields are
filled (stage initiation, level critical, 4 of 4 required tasks open). The regulator variant
lists controls without owners; the customer variant has no controls section (`not_for_variant`).

## 7. Console smoke (port 8143)

`SUPERVISOR_ENV_FILE=data/local/wave2-smoke.env` (in the worktree, git-ignored, not named
`.env`): laptop mode, SQLite store `data/local/wave2-smoke`, every `CONSOLE_*` flag on (placeholders
off), `DETECTORS_ENABLED`, `SESSION_MONITOR_ENABLED`, `RISK_REGISTER_ENABLED`, `CONTROLS_ENABLED`,
`TRANSPARENCY_ENABLED`, `COLLECTORS_ENABLED`, `MCP_HTTP_ENABLED`, `CONSOLE_DECISIONS_V2`,
`ALERTS_ENABLED`, `INVENTORY_ENABLED`, `TOOL_ANALYTICS_ENABLED` = 1, `JUDGE_ENABLED=0`. Seeded with
the app stopped: demo seed, inject 4, 2, 3, 1, starter risks and controls imported, `risk_evidence`,
`control_status`, tasks for payments, `decision_rollup --backfill`, transparency generate.
Started with `python -m uvicorn supervisor.app:app --host 127.0.0.1 --port 8143`, stopped with
`fuser -k 8143/tcp`.

* `/health` 200 (`version 0.3.0`), `/ready` 200 (scheduler running). One unsigned gate call (ingress auth off) with a
  `session_id` answered `allow` with `status` and `session_id`; `GET /v1/sessions/smoke-session-1` 200.
* 200 as `admin.chi` (every GET route of `rbac.ROUTES` with a known parameter, plus the new `/v1`
  routes): `/console/`, `/console/home`, `/console/agents`, `/console/agents/payments` and its twelve
  tabs (overview, policy, tools, inventory, traces, cases, assurance, compliance, risks, controls,
  tasks, transparency), `/console/alerts`, `/console/analytics` (gate, tools, metrics, latency,
  detectors), `/console/assurance`, `/console/audit`, `/console/cases`, a case page, its case file and
  sign-off, `/console/compliance`, `/console/compliance/payments` and an obligation,
  `/console/controls`, `/console/credentials`, `/console/decisions` (v2), `/console/evidence`,
  `/console/export`, `/console/health`, `/console/inbox`, `/console/integration`,
  `/console/integrations` (collector catalogue), `/console/inventory`, `/console/metrics`,
  `/console/onboard`, `/console/onboard/status`, `/console/playground`, `/console/policies`,
  `/console/risks`, `/console/search`, `/console/signoff`, `/console/tasks`, `/console/tools`,
  `/console/traces`, a trace and a span, `/console/transparency`, `/console/users`, every `/rows` and
  `/drawer` partial with a known id; `/v1/gate/detectors`, `/v1/mcp/tools`, `/v1/risks`,
  `/v1/risks/agents/payments`, `/v1/risks/<id>`, `/v1/risks/<id>/evidence`, `/v1/controls`,
  `/v1/controls/agents/payments`, `/v1/controls/<id>`, `/v1/tasks`, `/v1/tasks/agents/payments`,
  `/v1/tasks/<id>`, `/v1/tasks/export.csv`, `/v1/transparency`, `/v1/transparency/payments`
  (regulator JSON, customer HTML in Vietnamese, live preview), `/v1/sessions/<id>`,
  `/v1/analytics/tools`, `/v1/inventory/unmanaged`. Total 99 x 200.
* 4xx by design (user errors, not 500): made-up file names on the export and onboarding file routes
  (400), `/console/soon/policies` (400, placeholders off), a made-up static file (404),
  `/console/tools/payments/diff` (400 "nothing to change for this agent"), `/v1/inventory/payments`
  (404, the inventory job had not run), `/v1/mcp/tools/diff` without `server_id` and `tool` (400).
  A viewer POST to generate a transparency report: 403.
* App log: no ERROR, no traceback, no 500.
* Screens: section 4. Assurance in mock mode: section 1.

## 8. Behaviour changes (also in CHANGELOG)

1. WP26 F13 (no flag): the stdio and HTTP MCP proxies gate `resources/read`,
   `resources/templates/list`, `prompts/get` and `completion/complete` as the read-only tools
   `mcp.resources.read` and so on, and forward only `name`, `arguments` and
   `_meta.progressToken` of a `tools/call`. Kept as the security default.
2. WP37 F14: the policy loader refuses `skip_tools` that name a money, credit or pii_export tool
   (also for WP38 consumers).
3. WP38: the loader refuses consumer observe, agent observe on a money agent without SHADOW or two
   `observe_approvals`, and an agent `rules.disable` of a money / credit / pii_export block or
   pause rule without two `rule_approvals`. Old policy files load and hash as before.
4. WP28: 34 assurance packs (advisory `multiturn_redteam_vi`, also at Launch when
   assurance-at-launch is on).
5. Alerts: 18 rules; old rule hashes unchanged, the rule-set `config_hash` changes.
6. WP27: a completed agent resume also lifts that agent's session pauses.
7. Integration: `agent_event.consumer_id` holds only a consumer id the WP38 policy resolved.
8. `policies/schema.json`: new optional keys, none removed.

## 9. Commit trailers (stated, not rewritten)

* `8c651a3` (WP25b) has no `Co-Authored-By` or `Claude-Session` line.
* The first commit of three packages carries `Co-Authored-By: Claude Sonnet 5.5` instead of the
  brief's Fable line: `2cf9fd9` (WP37), `2e0548d` (WP26), `a496fc9` (WP31); the merge messages say so.
* `ea12550`, `44603ec` (WP27 review) and `5c0d887` (WP29 follow-ups) carry the Fable and session
  lines, but separated by a blank line, so git does not parse them as trailers.
* Every integration commit carries the Fable and session trailers.

## 10. Open owner questions, by package (reviewers' recommendations, from WAVE2_STATUS.md)

* **WP26 (7):** one-person TOFU (reviewer: no in production); suspicious tool needs an approver
  role (yes); hash the whole tool object (yes, minus volatile keys); refresh window by risk
  (re-list for money, credit and PII tools); auto-close the review case (comment only); listener
  port registry (a committed file); OAuth upstream (third-party servers only).
* **WP37 (7):** `verdict_status` on `agent_event` (keep); inline real judge (no, async);
  presets illustrative (accept); fail-closed classes (keep the three); correlation id from the SDK
  (yes); skip as a rule action (later; refuse on money now, done); finding retention (masked class).
* **WP28 (6):** pack stays advisory until thresholds are signed, then only `gate_catch`
  (rule-covered) and `unexpected_escape_count` required; holes: policy-only rules SVC-09, PII-03,
  CRD-08 first (bank checks limits), then an engine change for customer-keyed grouping (PAY-10,
  PAY-11, SVC-08), PAY-12 when a payee source exists; live model = the bank's serving model, one
  capped 60-conversation run per version; WP27: PII-shaped tokens are not a signal, memory poison
  via a stored-fact check; keep D25; traces as Delta only when WP27 reads from the store.
* **WP29 (7):** band thresholds (bank); who may accept risks (second approver?); is the two-state
  evidence rule enough; credit profile import; keep D26; window 7 days and 1 working control;
  store the gate state per verdict.
* **WP38 (7):** consumer observe refused (done); agent observe on money agents needs SHADOW or two
  `observe_approvals`; keep the action `log` plus status `report`; keep the engine order; key
  through the browser once accepted (no-store, htmx POST, first key only); operators issue the
  first key only, revisit with WP33; nightly real-framework run outside CI; no observed-decision
  column (the `observe_would_*` verdict rows carry it).
* **WP27 (5):** quiet point (K=3, 2500 bp) case only, re-tune on pilot traffic; memory may open a
  case alone (63/63 WP28 memory poison caught, cannot pause); pause off at go-live, then per agent
  (payments first), owner Payments Ops via policy YAML; consumer id is caller-asserted (WP20
  verifies the agent only): ask WP38 / WP20 for a hashed on-behalf-of user id; keep 30 min for the
  gate and add a daily per-consumer window in the batch job (case only, done). Blind WP28
  held-out: quiet 4099 bp catch / 0 of 108 false alarms; sensitive 7132 / 4 of 108.
* **WP25 (6) and WP25b (3):** ask the bank for masked labelled samples (held-out from another
  source); ship disabled, pilot report-only; pause off (`pause_tool_classes: []`) until
  validated; latency target p95 5 ms; MRM roles owner = product owner, validator = second-line
  model risk, approver = model risk committee naming `weights_sha256`, join the `judge.mrm`
  inventory; the integrator registers `score_tool_description` and refused weights hold the tool
  and open a case (done, section 4f). WP25b: do not recalibrate on the burnt held-out; choose
  presets by full-size cross-fitting; calibrate false alarm on masked benign traffic from a
  report-only shadow pilot, positives from the bank red team or WP28; a new sealed held-out from
  another author; pilot = lenient report-only on one agent, pause not in phase 1 (enable on money
  only after 0 false pauses on 800+ benign money calls). Plan with 5300 to 6400 bp recall on new
  attack families.
* **WP30 (7):** `tasks.yaml` stays ILLUSTRATIVE, second line signs it; waiver and high-level move
  at approver or admin, answerer not from the same stage; no task list = NO-GO (implemented: run
  `tasks generate` per agent before enabling the gate flag); pack window = cadence + margin, two
  independent sources for critical risks or high-risk agents; bank-owned controls in scope,
  apart, never working, attestation record later; draft starters need deterministic sources, not
  judged packs; CLI `--by` / `--role` acceptable on the laptop, authenticated routes on shared
  hosts; keep D30, add an ADR registry (done).
* **WP31 (6):** the customer version may name a bank-approved public name from a manifest field,
  never the agent id; every signed-in role reads it, handing it outside the bank = reviewer or
  admin after legal sign-off, audited; the regulator version shows the owner team (registration
  check: no person name or e-mail in the team field); omission plus cleaning for the pilot, the
  NER extra before the customer version leaves the bank; Fable trailers, mixed first commit stated
  (section 9); fpdf2 optional extra, `CASEFILE_PDF_FONT` to a Windows font with Vietnamese glyphs,
  HTML fallback.
* **WP39 (6):** Request tab from recorder events accepted (gate-only clients turn on masked
  capture); keep `CONSOLE_EXPORT_DIR` with one-time signed links, a UC volume only if exports
  must be kept; store route statuses for AL-ERROR-RATE (follow-up); the bank SOC sets the nine
  thresholds after two weeks inbox-only; SDK requires `consumer_id` for agents with registered
  consumers, the resolved id is recorded (done); coverage gap high for tool calls with no
  decision, a separate medium unknown-agent rule for inventory-only systems.
* Integration notes still open for the owner: `MCP_SERVER_AGENTS` should move into the policy file
  with WP40 (no per-agent MCP server list in the policy yet).

## 11. Known limits

* WP25 classifier: validation NO-GO (held-out recall 8111 bp against 8500, false alarm 2522 bp from
  miscalibrated presets); shipped disabled; its tool-lock score is off while it is disabled.
* WP28 / WP27 consistency: WP28's restatement of the WP27 quiet profile sees 2873 bp held-out of
  successful sessions; WP27's own adapter reports 3036 / 3796 bp; legacy counters see 8271 bp but
  flag 555 bp of benign sessions. The quiet point trades catch for zero false alarms (WP27 Q1).
* Nothing in waves 2 and 3 ran against a live Databricks workspace: the Delta path is tested with
  `databricks_fake` and recorded statements only (`bootstrap_schema` on Delta must run before the
  app; CHANGELOG deploy note).
* The full suite takes about 16 minutes on this shared host (load average 4 to 5 during the run).
* On the smoke store no control and no risk had working evidence (`working=0`): the demo events are
  outside the 7-day window or on paused agents; the figures prove the paths, not a compliance level.
* `AL-THREAT-NOT-ENFORCED` reads the WP38 `observe_would_*` rows, but no drill runs against a real
  observe-mode policy yet (BACKLOG).
* `tools/console_screenshots.py --wave2` needs `--reseed`; the WP29 page had not been captured
  before this integration.

No open defect: every failure met during the merges was fixed in this branch (section 3).

## 12. Branch and head

| | |
|---|---|
| Branch | `phase3-wave2` |
| Worktree | `/home/trung/supervisor/.claude/worktrees/agent-a28c62b5d9020b7a5` |
| Head | the commit after `affe849` that records the final run in this report (code and tests final at `affe849`) |
| Merged heads | WP37 `bfc6e09`, WP26 `0e5460f`, WP28 `1ec5936`, WP29 `5c0d887`, WP38 `71a79f8`, WP27 `a9907e0`, WP30 `2432f60`, WP31 `8bc25a1`, WP39 `21a4bec`, WP25 `ec535ee` |
