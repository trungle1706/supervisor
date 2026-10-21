# REVIEW WP30: Control catalogue and task list

Reviewer: Opus (internal auditor under the Three Lines model, and bank security reviewer). Date: 2026-10-20.
Branch `wp30-controls` in worktree `agent-ac6d50fb68d95276d`. Author head `bc58454` (contains the final WP29 head `5c0d887`).
The review delta is `git diff wp29-risk-register...HEAD`. No push, no merge, no history rewrite. Six review commits, all additive.

## Verdict

**APPROVED WITH FOLLOW-UPS.** I found 3 High, 3 Medium and 6 Low findings. I fixed all High and Medium findings and 2 Low findings on the branch, with tests. The open items are Low, or they need an owner decision.

```
 before review                                  after review
 Launch gate on  -> NO-GO at every stage        -> NO-GO only for a real reason:
   (the stage's own move is "open")                no task list | stage < deployment |
                                                   required task open | list unreadable |
                                                   gate flag on, CONTROLS_ENABLED off
 owner closes the second-line review            -> needs role approver (or admin)
 approver cannot reach /done (403)              -> POST /v1/tasks/{id}/approve
 class or band down -> move loses approval,     -> sizing keeps the highest level and
   validation stage skipped                        every class the agent had
 bank control + rule hit -> "working"           -> no_data / bank_owned
```

## Findings

| Id | Sev | File:line (author head `bc58454`) | What | Fix |
|---|---|---|---|---|
| H1 | High | `src/supervisor/tasks/service.py:300` (`open_required`), `:911` (`launch_tasks_for`), `src/supervisor/onboard/launch.py:220` | With `TASKS_LAUNCH_GATE_ENABLED=1` the launch gate was NO-GO at every stage except retirement. `open_required` includes the stage's own move task (always required and open), so the gate always had a blocker. Also, DEP-LAUNCH ("Obtain a GO from the launch report") is required in the deployment stage, so the GO that closes it could never be given. The harness and the author tests passed rows in by hand (`given`), so the read path was not tested. Probe log: `wp30_review_tools/probe2.py`. | `aeda3a6`, `7c9979e`: `TaskService.launch_blockers` (no move, no template with `blocks_launch: false`), DEP-LAUNCH `blocks_launch: false`. Test `test_s5_launch_hook_follows_the_lifecycle` |
| H2 | High | `src/supervisor/tasks/service.py:640` (`done`), `src/supervisor/tasks/api.py:141` | Segregation of duties. `done()` did not check the template role. An agent owner could close VAL-SECOND ("Independent review of the validation report by the second line", role approver), VAL-FAIR (reviewer) and REV-APPROVE (approver). Also the reverse: the `/done` route needs `tasks.edit`, which the approver role does not hold, so an approver got 403 on a high-level move and on approver tasks. Only an admin could do them. | `7c9979e`: `tm.done_refusal` (a reviewer, approver, auditor or admin task needs that role or admin); new route `POST /v1/tasks/{id}/approve` (`tasks.approve`) for moves and approver tasks only. Tests `test_s5_template_role_decides_who_may_mark_done`, `test_approver_closes_the_move_and_the_first_line_cannot` |
| H3 | High | `src/supervisor/tasks/service.py:570`, `:578`, `:484` | A class or band downgrade in the middle of the lifecycle relaxed the list. `_resize` wrote the new (lower) level on open rows: the move lost its stage approval, so the owner moved a high-risk agent alone. It also retargeted the move from `validation` to `deployment` (the validation stage was skipped). Later stages were released with the light set. The ADR and the docstring say "never silently looser". The harness probe `class_change_mid_lifecycle_is_additive_never_relaxes` tested only an upgrade. | `7c9979e`: `TaskService.sizing` (highest level and every class in the agent's rows, plus the current ones), `plan_at`, `next_stage_at`. The level only goes up, and a move is retargeted only to an earlier stage. Test `test_s4_a_downgrade_in_the_middle_never_relaxes` |
| M1 | Medium | `src/supervisor/controls/evidence.py:99`, `src/supervisor/controls/refs.py:137`, `:164` | A bank-owned control with a rule, pack or monitor source read `working` and counted in the figure (probe: `bp 10000`). Docs section 4, owner question 4 and the brief say that bank controls never show working (the product cannot observe a bank process). `implemented_by` was not in the map fingerprint, so a status of `working` survived a change from product to bank. | `eb02c1b`: `evaluate(..., bank=True)` gives `no_data` / `bank_owned`; `runtime_sources` gives a risk nothing from a bank control; `implemented_by` is in `map_fingerprint`; EN and VI label. Tests `test_s1_...`, `test_s3_...` |
| M2 | Medium | `src/supervisor/onboard/launch.py:202`, `:235` | Launch passed on unknowns. (a) An agent with no task list got a note and GO, which is a bypass (owner question 2). (b) With `TASKS_LAUNCH_GATE_ENABLED=1` and `CONTROLS_ENABLED=0`, the hook was silently off. (c) An agent at initiation or design with a clean stage got GO, although Launch leads to Operate. | `aeda3a6`: each case is NO-GO with a clear reason (`LAUNCH_STAGE = "deployment"`). Tests `test_s5_launch_hook_follows_the_lifecycle`, `test_launch_gate_flag_without_the_catalogue_is_no_go` |
| M3 | Medium | `src/supervisor/controls/service.py:477` | `ControlService.collector()` did not pass `RISK_EVIDENCE_JUDGED_PACKS`. With the switch on, a risk that looks through a control counted a judge-scored pack, but the control itself read `no_data`. The two views disagreed, and the docs promise the switch. | `eb02c1b`. Test `test_judged_pack_switch_reaches_the_control_status` |
| L1 | Low | `src/supervisor/tasks/model.py:217` | The "different person" check compared user ids with letter case: `Binh@Bank.vn` could answer the waiver of `binh@bank.vn`. | `7c9979e`: `tm.same_person` (casefold), also in `integrity_problems`. Test `test_same_person_with_another_letter_case_is_the_same_person` |
| L2 | Low | `src/supervisor/controls/service.py:590` | A map changed and changed back in one window: the control read `changed_since_evidence` until the next window (fails safe). | Control side fixed in `eb02c1b` (`_latest_for_agent` picks the newest row of the current basis), test `test_a_map_changed_and_changed_back_finds_its_first_row`. **Open** on the WP29 risk side (BACKLOG) |
| L3 | Low | `src/supervisor/risk/evidence.py` (`Collector.count`, `control` links) | A risk that looks through a control ignores the control's agent scope, and it uses the risk window (7 days) for packs, not the control pack window (30). This is stricter for packs, and rule scope is checked when the control is saved. | Open (BACKLOG) |
| L4 | Low | `src/supervisor/tasks/service.py:614` | A `pack` task closes on the newest real `ok` result of any age, and it does not apply the judge-scored list. The starter templates name only deterministic packs. | Open: owner to set a pack age for tasks if a bank config names other packs |
| L5 | Low | `src/supervisor/tasks/__main__.py:93` | The CLI takes `--role` as given (`--role admin` passes the stage approval). This is the documented CLI posture (shell access to the store is write access). | Info; documented in `docs/controls.md` (owner question 6) |
| L6 | Low | `src/supervisor/tasks/service.py:53` | `TASK_CSV` is declared but not used. Tasks have no CSV export (JSON only). The control CSV is formula-safe (`csv_cell`; harness probe `csv_formula_injection_neutralised`). | Open (BACKLOG) |

What I checked and found sound:

* **Evidence integrity:** status uses the WP29 `Collector` (it calls `enforced_hit` and uses `EVIDENCE_MONITORS`; there is no own filter). A document or a detector never counts; mutation M1 below proves the regression test catches it. The pack window is 30 days and the rule window 7 days (scenario S2). A change to status, scope, map (and now `implemented_by`) invalidates the control status and the evidence basis of linked risks (scenario S3).
* **Append-only:** `control_status` and `task_event` have no update or delete path in the service, the API or the CLI (only `tables.append`). SQLite has ABORT triggers and Delta has `delta.appendOnly` with 1825-day retention. I also checked them after `bootstrap_schema` on a WP29-head store (new test).
* **Chain payloads:** they carry `actor_ref` (keyed HMAC), integers, codes and hashes. Reason text is only in the row, and only `reason_sha256` goes to the chain (author test plus `test_chain_payloads_carry_a_keyed_actor_ref_never_the_actor`).
* **Overdue cases:** one case per overdue required task, and none on a second run. I checked this with the real `CaseService` (`case_link` dedupe) as well as the fake.
* **RBAC and audit:** `controls.edit` and `tasks.edit` are reviewer, owner and admin (the same holders as `risks.edit`). `tasks.approve` is approver and admin. A viewer gets 403 on 9 write routes and each denial writes a `denied` `console_action` row. CLI writes need `--by` and write a `console_action` row. 26 bad bodies give 400 (none gave 500 before or after the fixes).
* **Both modes:** 5 tables in both DDLs and in `model.yaml`. I regenerated the notebook and it is identical (`--check` OK). Delta fake tests pass. `bootstrap_schema` on a store with the WP29 tables and without the WP30 tables adds them, runs twice without error, and keeps rows (new test).
* **Flag off:** no routes (400 with the flag name), no nav, no tab, CLI and jobs `[SKIP]`, scheduler jobs only when on. The launch report of the three demo agents is the same on the WP29 head and on the review head (sha256 of the report JSON: `payments ccfb013f1e0d2cb1`, `credit_prequal dbee7e3667581009`, `customer_service 387fd058f07d49fe`; logs `wp30_review_launch_fp_wp29.txt`, `wp30_review_launch_fp_wp30.txt`). The all-pages probe, the UX fingerprints and the i18n duplicate-key test are green in the full suite.
* **Shared files:** the author's edits are minimal and additive. The WP29 tests pass unchanged. The review edits to shared files: `core/rbac.py` (one route, one description), `onboard/launch.py` (`_with_tasks`), `console/i18n.py` (one label), `docs/console.md` (matrix row and page row), `README.md` (one flag line). One author test was changed: `tests/tasks/test_tasks.py::test_a_task_becomes_required_when_the_size_grows` closes INI-D33 (a reviewer task) as a reviewer and not as the owner. ADR D30 is kept, with an amendment.

## Harness honesty: my five scenarios (compliance officer)

I computed every expected value by hand from `config/tasks.yaml` and `docs/controls.md`. I did not use the author's generator. The tests are in `tests/controls/test_review_wp30.py`.

| # | Scenario | Hand-computed expectation |
|---|---|---|
| S1 | 4 controls in scope: product with an enforced hit; product with a hit and a failing pack; product with a document only; bank with a hit | working, failing, no_data/reference_only, no_data/bank_owned; compliance 1x10000//4 = **2500 bp**; product 1x10000//3 = **3333 bp**; bank_in_scope 1 |
| S2 | pack ok 20 days ago; rule hit 10 days ago; pack ok 40 days ago | working; no_data/no_working_source; no_data; **3333 bp** |
| S3 | risk 4x5 linked by a control map; remove the rule; add another rule; turn the control into a bank control | residual 10 -> changed_since_evidence and 20 at once -> reference_only, 20 -> 10 -> changed_since_evidence -> bank_owned, 20 |
| S4 | task sets; a high_risk/high agent that is downgraded to not_high_risk/low at design | high_risk+low: level high, **26** tasks, all required, 7 stages. not_high_risk+low: **8** named tasks, 5 stages. unclassified+low: medium, **20** tasks, **18** required (optional: DES-CONTROLS, VAL-INJECT). After the downgrade, the move stays MOVE-VALIDATION at level high with role approver; the owner is refused; validation is released with VAL-FAIR, VAL-SECOND and VAL-INJECT, all required |
| S5 | SoD and launch on a high_risk agent | the owner and the reviewer are refused on VAL-SECOND; the owner is refused on VAL-FAIR; reviewer and approver succeed. Launch: no list = NO-GO; initiation or design with a clean stage = NO-GO ("deployment stage"); deployment with DEP-OVERSIGHT open = NO-GO; only DEP-LAUNCH and the move open = **GO** |

Before the fixes, 9 of the 11 new tests in this file failed (log `wp30_review_newtests_before_fix.txt`: S1 bank control `working`, S3, S4 `KeyError MOVE-VALIDATION` because the move was retargeted, S5 twice, gate flag, letter case, judged switch, and bootstrap).

**Mutation check** (mutate, run `tests/controls/test_harness.py` and the review tests, revert; log `wp30_review_mutation.txt`; the tree was clean after each revert):

| Mutation | `tests/controls/test_harness.py` | review and task tests |
|---|---|---|
| a document-only control counted as working (`decide`) | 3 failed, including `test_no_regression_against_the_recorded_baseline` | 2 failed |
| same-person waiver allowed (`waive_refusal`) | 3 failed, including the regression test | 2 failed |
| move gate off (`move_refusal` ignores open required tasks) | 3 failed, including the regression test | 1 failed |

The starter check fails an active product control that has only reference sources (`test_harness_starter_check_fails_a_product_control_with_only_references`, green). Golden set: `generate.py --check` exit 0. The golden file did not change; the baseline changed only in `tasks_config_sha256`, because `config/tasks.yaml` gained `blocks_launch` and comments.

## Commands (last lines)

```
uv run python -m pytest -q -x            (author head, first clean run)   4027 passed, 29 skipped, 1 warning in 574.45s
uv run python -m pytest -q -x            (review head)                    4045 passed, 29 skipped, 1 warning in 564.70s
uv run python -m ruff check              All checks passed!
uv run python -m ruff format --check     724 files already formatted
uv run python -m supervisor.controls.harness
  [dev] n=30 accuracy=10000bp [8864, 10000]   [held_out] n=20 accuracy=10000bp [8388, 10000]
  [adversarial] 24/24 [8620, 10000] failed=[]   [starters] controls=28 maps=165 risks_covered=19 obligations_covered=26 problems=[]
  [determinism] 10000bp   [OK] all GO
uv run python tests/fixtures/controls/generate.py --check      exit 0
uv run python -m supervisor.databricks.notebook --check         [OK] ... DDL is current (regenerated copy identical)
```

Final test count: **4,045 passed, 29 skipped** (+18: 12 tests in `tests/controls/test_review_wp30.py`, 5 in `tests/console/test_controls_review.py` (these run 26 bad bodies and 9 viewer writes), and 1 more case in the route-parametrised RBAC matrix test for the new `/approve` route). The warning is the existing scheduler `JobLookupError` from before WP29. Logs in the scratchpad: `wp30_review_pytest1.txt`, `wp30_review_pytest_final.txt`, `wp30_review_harness_initial.txt`, `wp30_review_harness_final.txt`, `wp30_review_mutation.txt`, `wp30_review_newtests_before_fix.txt`.

## Review commits

| Commit | What |
|---|---|
| `eb02c1b` | bank-owned controls never work, `implemented_by` in the fingerprint, judged-pack switch, current-basis row |
| `7c9979e` | template role for done, `/approve` route, sizing never relaxes, case-insensitive same person, `launch_blockers` |
| `aeda3a6` | launch gate: stage move ignored, NO-GO on no list, before deployment, catalogue off; `blocks_launch` |
| `fa722cd` | five scenarios, route probes, bootstrap upgrade test |
| `9ba1f4f` | docs, ADR D30 amendment, BACKLOG, CHANGELOG, threat model |
| (this file) | REVIEW_WP30.md |

## Recommendations on the seven owner questions

1. **Real task sets, levels, floors, due times; who answers a waiver and a high-level move.** Keep `config/tasks.yaml` ILLUSTRATIVE. Ask the second line (operational risk, model risk) to own the file, signed and versioned like the risk appetite (WP29 Q1). Keep the waiver answer and the high-level move at approver or admin. Add one rule: the person who answers a waiver must not have done or asked for another task of the same stage of the same agent (stricter maker-checker). This is a follow-up.
2. **No task list = NO-GO at launch?** Yes. It is now implemented: with the gate flag on, no list, a stage before deployment, an unreadable list, or `CONTROLS_ENABLED` off are each NO-GO with a clear reason. Before the bank turns the flag on, run `python -m supervisor.tasks generate --agent <id> --by <you>` for every registered agent (BACKLOG row).
3. **Pack window 30 days, one working source is enough?** Keep 30 days for packs if the assurance cadence is monthly; set it to the real cadence plus a margin. "One working source" is enough for v1, but for a control that covers a critical risk or a Decision 33 high-risk agent, require two independent sources (for example a rule and a pack), as in WP29 Q6.
4. **Bank-owned controls in the figure.** Keep them in scope and report them apart. They are now never working (`bank_owned`). Add an attestation record (who, when, expiry, second person) as a separate "attested" count, never added to `working`.
5. **Draft starters (oversight, chain, quality, groundedness).** Build deterministic sources: an oversight status in `monitor_status` (pause/resume latency, two-person rate), and a chain-verify job result as a pack-like row. Do not turn on `RISK_EVIDENCE_JUDGED_PACKS` for these. A judged pack stays a reference (rule R1) until judge MRM validation is signed for that pack.
6. **CLI trusts `--by` (and `--role`).** This is acceptable on the laptop, with the posture now documented. For the Databricks App, CLI writes do not apply. If the bank runs the CLI on a shared host, require the OS user to match `--by`, or disable `--role approver|admin` from the CLI and keep approvals on the authenticated route only.
7. **ADR number D30.** Keep it. The integrator checks for clashes at merge (D23 to D29 belong to other packages). I repeat the WP29 suggestion: add an ADR number registry in `docs/adr/README`.
