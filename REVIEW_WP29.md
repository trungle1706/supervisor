# REVIEW WP29: Risk register

Reviewer: Opus (internal auditor and bank security reviewer view). Date: 2026-10-20.
Branch `wp29-risk-register` in worktree `agent-a61f8e42f76d2b4d6`. Author head `316a039`; review head is the commit that adds this file.
No push, no merge, no history rewrite. Six review commits, all additive.

## Verdict

**APPROVED WITH FOLLOW-UPS.** I found one High and five Medium findings. I fixed all six on the branch, with tests. The open items are Low, or they need an owner decision (four-eyes, actor identity in the chain, starter links to monitors that write no status).

## API changes (for WP30 and WP31, which branch from this head)

| Change | Who it hits |
|---|---|
| **Monitor evidence:** a `monitor` link counts only for `fairness`, `drift` and `multiagent`. `quality` (an LLM scorer) and `oversight` and `sweeps` (they write no `monitor_status`) are always `idle`. | WP30: a catalogue control that maps to `oversight`, `sweeps` or `quality` never lowers a score. |
| **Pack and monitor evidence needs every supervised agent:** for a risk that applies to many agents, the result must be `ok` for each of them. Rule hits of any agent still count. | WP30, WP31 (the evidence state can change for shared risks) |
| **Rule hits must be enforced:** verdicts labelled `shadow_*`, `rule_error`, `fail_open` or `fail_closed`, checker `gate:fail_mode`, and mock verdicts are not hits. | WP30 |
| **New reason code `changed_since_evidence`:** after a material edit (anchor, treatment, inherent or declared values, control links), the old evidence row does not count until the next pass. The next pass can write a new row in the same window. | WP31: show the code (EN and VI labels added) |
| `RiskService.effective(row, latest, now, controls=None)` (new optional argument), `evidence.evidence_id(risk_id, w, basis="")` (new optional argument), new `evidence.evidence_basis(row, controls)` and `evidence.enforced_hit(v)` | Additive |
| **Stricter validation:** `avoid` or `transfer` with a residual below the inherent value needs `treatment_note` (HTTP 400 and import error without it). | API clients, bank import files |
| Harness `_Env`: verdict rows now use the gate's real values (`checker_id gate:tier0a`, `label matched`); its catalogue has the monitors `oversight`, `drift`, `quality` | Tests that reuse `_Env` |

## Findings

| Id | Sev | File:line (author head) | What | Fix |
|---|---|---|---|---|
| H1 | High | `src/supervisor/risk/evidence.py:235` | `rule_hits` counted every tier-0 row with action log/alert/block/pause. A SHADOW agent's "would block" row (action `log`, label `shadow_would_block`) counted as a hit when the agent is RUNNING now. A rule that raised an error (`rule_error`, fail mode decided), a gate fail-mode row and a mock verdict also counted. So a broken rule or a rule that never enforced anything lowered the residual. The gate writes the label at the time of the call, so the data to tell them apart was already there. | `57fe324` (`enforced_hit`), tests `test_shadow_error_fail_and_mock_rows_are_not_rule_hits` (5 cases), scenario S5 |
| M1 | Medium | `evidence.py:242`, `evidence.py:266` | Cross-agent evidence: for a shared-component risk, one `ok` pack result or one `ok` monitor day on agent A made the control "working" and lowered the risk for agent B, which had no result. | `57fe324`: pack and monitor must be `ok` for every supervised agent (partial coverage = `warn`/idle). Tests `test_a_pack_run_on_one_agent...`, `test_a_monitor_ok_on_one_agent...`, `test_a_shadow_agent_on_a_shared_risk_is_excluded_not_required` |
| M2 | Medium | `evidence.py:266` (and `monitors/status.py` `MONITORS`) | Monitor evidence was not what the docs said. (a) `quality` is the advisory LLM groundedness/guideline scorer; a status `ok` from it lowered a score, but ADR D26 #6 and threat model 3.10 say "no judge is an input" (R1). (b) Only `quality`, `fairness`, `drift`, `multiagent` write `monitor_status`. `oversight` and `sweeps` never do, so the 12 starter links to them can never be evidence, but the starter check still reports `problems=[]`. (c) `ok` means "the monitor ran and produced values", not "it found nothing". | Code: `57fe324` (`EVIDENCE_MONITORS`), test `test_judge_and_statusless_monitors_never_lower_a_score`, docs say what `ok` means (`f96d25e`). **Open:** the starter links (BACKLOG row updated) |
| M3 | Medium | `src/supervisor/risk/service.py:277`, `:497` | The evidence row was not bound to the risk as it is now. After a pass showed `working`, a person could remove the working link, move the risk to another agent, change the treatment or lower the declared residual. The old row still applied until the next window, which is up to 6 h with the default scheduler. The row id (risk, window end) also blocked a re-run in the same window. | `57fe324`: evidence basis hash in the row id and a check in `effective()`, so these edits give `changed_since_evidence` and the inherent score. Text edits keep the evidence. Tests: unlink, lower declared, re-anchor, text edit, list/agent-level agreement |
| M4 | Medium | `src/supervisor/risk/model.py:270` | `avoid` and `transfer` showed any declared residual, with no evidence and no written justification. A person could set `transfer` and 1 x 1 and the score went down at once (the Saidot weakness for 2 of 4 treatments). | `65232ed`: a residual below the inherent value needs `treatment_note`. Four-eyes is still open (owner question 2). Test `test_avoid_or_transfer_below_inherent_needs_a_note` |
| M5 | Medium | `tests/integrations/test_integrations.py:85` | Flaky test (see the investigation below). | `8260b86` |
| L1 | Low | `evidence.py:121` | `window_for` with a naive datetime used the host's local time zone (`astimezone`), so the window changed with the host TZ. | `57fe324` (naive = UTC), test `test_window_is_the_same_instant_in_every_time_zone` (UTC, +07:00, naive give the same end) |
| L2 | Low | `src/supervisor/risk/harness.py:321` | The harness verdict rows used values the gate never writes (`checker_id gate`, `label hit`), so the harness could not see H1. | `57fe324` |
| L3 | Low | `service.py:174` | The `risk_change` chain payload has `actor` (a user id; on the App this can be an email). The brief says "integers, codes and hashes only". This follows the existing `gate_state_change.principal` convention, so it is not a new class of data. | Open: owner decision (keep the identity, as other chain records do, or hash it) |
| L4 | Low | `service.py:268` | `_latest_evidence()` reads the newest 20,000 rows of all risks. With many risks and windows, the latest row of an older risk can fall outside the read. The risk then shows `no_evidence_yet` (fails safe, the score stays high). | Open (for example, read per risk or keep a latest-row index) |
| L5 | Low | `src/supervisor/risk/__main__.py:105` | The CLI `import` has no RBAC (actor `cli`). Shell plus store access means write access, the same as every other CLI in the repo. Chain records are still written. | Open / info (document it in the deploy guide) |
| L6 | Low | `evidence.py:242` | Packs that are scored by a judge (for example `groundedness_monitor`, `halueval_vi`) can lower a score. They go through the assurance judge-MRM gate, so this is less strong than M2a, but it is the same question. | Open: owner decision with M2 |
| I1 | Info | `tests/monitors/test_scheduler.py::test_start_and_stop_apscheduler` | One `PytestUnhandledThreadExceptionWarning` (`JobLookupError: supervisor-startup`). This test existed before WP29; the author's run shows the same warning. | Not WP29 |

What I checked and found sound:

* **Append-only:** `risk_evidence` has no update or delete path in service, API or CLI (only `tables.append`). SQLite has the two ABORT triggers and Delta has `delta.appendOnly` plus 1825-day retention. Import and update touch only `risk` and `risk_link`. An unlink sets `active=false`.
* **Chain coverage:** there are records for create, update, retire, link, unlink, import (`_rewrite` gives `import`; new risks give `create`) and evidence. All payload values are int or str (test).
* **CSV export:** `csv_cell` prefixes `= + - @ TAB CR`.
* **RBAC:** `risks.edit` is held by reviewer, owner and admin only (generated matrix, `test_docs_table_equals_matrix_markdown`). A viewer gets 403 on create, update and link, and each denied write writes a `denied` row. Both `console_action` rows have before and after hashes (also on the link route, new test).
* **No 500:** 20 more bad bodies (types, ids, bools, floats, dates, unknown fields, bad link shapes) all give 400. An oversized body gives 400/413.
* **Inheritance:** it reuses `Graph.effective_risk`. The 3,000-deep chain probe passes. Cycles, gone nodes and draft/retired risks are handled. A shared endpoint reaches all agents (author test, plus my scenario S3).
* **Both modes:** the DDLs, `model.yaml` and the notebook are generated and current. The Delta path passes on the mirror fake. `bootstrap_schema` on an existing v0.3.0 SQLite file adds the 3 tables and 2 triggers, is idempotent and keeps rows. I checked this by hand on a v0.3.0 DDL file and added a test.
* **Flag off:** the tests exist (400 naming the flag, no nav item, no tab, CLI and job `[SKIP]`, scheduler job only when on). The full suite, including the all-pages probe, UX fingerprints and the i18n duplicate-key test, is green.
* **Shared files:** the edits are minimal and additive, as the handoff lists. `docs/console.md` role matrix equals `rbac.matrix_markdown()` (enforced by a test).

## Harness honesty (item 8)

* I wrote 5 independent scenarios (`tests/risk/test_review_scenarios.py`) as an operational risk manager. I computed every expected band and link by hand:
  * S1: an enforced rule lowers 20 critical to the declared 10 high.
  * S2: a failing pack beats a working rule, so the score stays 12 high.
  * S3: a shared endpoint reaches two agents. The band edges 9 (medium) and 10 (high) are checked, the agent level is the max, and the shared risk lowers to 3 low only when drift is `ok` on both agents.
  * S4: draft (16) and retired (25) risks do not count. With no link, the risk keeps its inherent score of 4.
  * S5: a SHADOW agent gives `no_supervised_agent` (12 high stays). A transfer with a note shows its declared 4 low.
* Before the fixes, S3 and S5 and 15 of the other new tests failed: 16 of 50 new tests in the first pass. The log is `wp29_review_newtests_before_fix.txt` in the scratchpad.
* Mutation check of the baseline and the regression test (mutate, run, revert; log `wp29_review_mutation.txt`):

| Mutation | `tests/risk/test_harness.py` |
|---|---|
| band edge `score <= medium_max` changed to `<` | 3 failed, including `test_no_regression_against_the_recorded_baseline` |
| SHADOW counted as supervised | 2 failed, including the regression test |
| failing control ignored | failures in the harness and scenario tests (4 failed together) |

The tree was clean after each revert.

## Flake investigation (item 9)

* I ran `test_chain_feed_writes_schema_events_once` 20 times in a loop, each with a new demo seed. All 20 passed (log `wp29_review_flake_loop.txt`). The failure is rare, so 20 passes do not prove it is gone.
* **Cause (confirmed):** case ids are `CASE-` plus 10 upper-case hex characters of a hash (`cases/service.py:133`). The demo makes new ids on every seed. The grep `(?<![0-9a-f])\d{9,12}(?![0-9a-f])` treats upper-case `A-F` and `-` as boundaries, so an id that is all digits or has a 9-digit run looks like a phone or account number. That is about 2% per id, and the demo has 2 cases. I reproduced it directly: a script seeded the demo 3 times, and the third seed gave `CASE-5607640249` with 2 matches (`wp29_review_tools/siem_digits.py`). The author's guess (a digit-run grep on the SIEM stream) was right.
* **Fix (`8260b86`):** the test removes case ids (`CASE-[0-9A-F]{10}`) before the digit grep. A new unit test, `test_pii_digit_grep_ignores_case_ids_only`, pins this: `CASE-5607640249` passes, and a phone `0912345678` or a CCCD-like `079123456789` still fails. Product code is not changed.

## Commands (last lines)

```
uv run python -m pytest -q -x            (before review)  3829 passed, 29 skipped in 505.07s
uv run python -m pytest -q -x            (after review)   3881 passed, 29 skipped, 1 warning in 534.78s
uv run python -m ruff check              All checks passed!
uv run python -m ruff format --check     687 files already formatted
uv run python -m supervisor.risk.harness [dev] n=30 10000bp [8864, 10000]  [held_out] n=20 10000bp [8388, 10000]
                                         [adversarial] 20/20  [starters] risks=19 links=85 problems=[]
                                         [determinism] 10000bp  [OK] all GO
uv run python tests/fixtures/risk/generate.py --check   exit 0
```

Final test count: **3,881 passed, 29 skipped** (+52 from review: 20 evidence-hole tests, 5 scenarios, 26 route probes, 1 SIEM grep unit test). Logs are in the scratchpad: `wp29_review_pytest_initial.txt`, `wp29_review_pytest_final.txt`, `wp29_review_ruff.txt`, `wp29_review_harness_final.txt`.

## Review commits

| Commit | What |
|---|---|
| `65232ed` | avoid or transfer below inherent needs `treatment_note` |
| `57fe324` | evidence-rule holes: enforced hits, every-agent packs and monitors, deterministic monitors only, evidence basis, naive TZ |
| `fedf92a` | 5 independent scenarios, route probes |
| `8260b86` | deterministic SIEM PII grep (flake) |
| `f96d25e` | docs, ADR D26 amendment, BACKLOG, bootstrap upgrade test |
| (this file) | REVIEW_WP29.md |

## Recommendations on the author's seven owner questions

1. **Band thresholds and step meanings.** Keep ILLUSTRATIVE. Ask the bank's operational risk function (second line) to give its existing 5 x 5 matrix, with each step defined in VND loss (integer minor units), customers affected and regulatory consequence. Store it as a signed risk-appetite object (signer, date, version) and not only as YAML numbers. This closes the Saidot gap "thresholds not stated". Later, per-category thresholds can follow.
2. **Who may create, edit and accept.** Add four-eyes before production. A second person with a different role must approve `accept`, `avoid` or `transfer` with a lowered residual, any lowering of a declared residual, and `retire`. The creator cannot approve their own change (SoD). Today's single-person rule is acceptable only while the flag is off or in a pilot.
3. **Is the two-state rule enough?** Yes for v1: it is auditable and does not depend on traffic volume. Do not grade by hit count. First fix the evidence sources: the 12 starter links to `oversight`/`sweeps` should point to `drift`/`fairness`/`multiagent` or to a pack replay. Then add the canary probe through the gate for rarely firing rules, labelled synthetic and excluded from business metrics.
4. **`credit_prequal` as the credit profile.** Agree. The bank imports its own credit-memo register in the same YAML format; nothing from the testbed agent goes into the repo.
5. **ADR number D26.** Keep it and let the integrator check for a clash at merge (D23 to D25 are on other branches). I suggest a small ADR number registry in `docs/adr/README` so that parallel WPs reserve numbers.
6. **Window 7 days and 1 working control.** Keep 7 days for rules and monitors. Packs usually run less often, so either use a pack window as long as the assurance cadence (for example 30 days) or schedule the pack weekly. Make `min_working_controls` risk-based: 1 for low to high, 2 for an inherent critical risk. All values stay ILLUSTRATIVE until the bank signs them.
7. **Store the gate state with each verdict.** The review fix (H1) mostly answers this: the gate already writes `shadow_*` labels at the time of the call, and those rows no longer count. A new `gate_state` column on `verdict` is not needed for WP29. Add it only if the bank wants it to be explicit for audit; it would be an additive column on an append-only table, through the schema generator.
