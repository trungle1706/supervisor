# Register workflow v3: nine steps with a compliance strip (WP-C3)

> **Not legal advice. Bank counsel must confirm.** The articles in `config/register_v3_strip.yaml` are illustrative.

Flag `REGISTER_V3=1` (default `0`). It needs `CONSOLE_REGISTER_V2`, `CLASSIFICATION_V2`, `RISK_DIMENSIONS` and `GOVERNANCE_ENABLED`. With the flag on and one of those off, every register URL answers HTTP 400 and names what is missing. With the flag off the six-step (or seven-step, `CONSOLE_REGISTER_DUTIES`) workflow of `docs/register-v2.md` runs exactly as before.

## The steps

| # | Key | What it shows | Live with |
|---|---|---|---|
| 1 | `source` | The Source panel (upload a zip or a git URL) bound to the draft's source key, or "skip, no source" with a reason of 10 or more characters | `ONBOARD_INTAKE` |
| 2 | `facts` | The Facts card, read only, with the Re-read (rebuild) button. Continue takes the facts into step 3 | `ONBOARD_FACTS` |
| 3 | `identify` | Identify and AI type on one page. Fields filled from facts v1 carry a "from facts" mark. The AI type flags. Continue saves the system record | none (facts add the prefill) |
| 4 | `classify` | The WP-C1 panel (tree, prefill, save). The second-person approval stays on the system page | `CLASSIFICATION_V2` (needed) |
| 5 | `assess` | The eight rows of WP-C2 with the proposal, and the Run assessment button of WP-F4 | rows: `RISK_DIMENSIONS` (needed); Run assessment: `ONBOARD_ORCHESTRATOR` |
| 6 | `duties` | The Duties step, pre-filled and marked | none (the assessment prefill needs `ONBOARD_ORCHESTRATOR`) |
| 7 | `guardians` | The pre-deploy panel (WP-O3) and the guardian table | pre-deploy panel: `ONBOARD_PREDEPLOY` |
| 8 | `review` | The summary and the submit action: a stage approval request | none |
| 9 | `done` | The result page with links to the agent and system pages and tabs | none |

A step whose flag is off shows a "turn on FLAG" note and lets the person continue. The source key of a draft is the scanned node id, the policy agent id, or (blank draft) the draft id. The intake attempts, the facts card and the pre-deploy report are stored under that key.

## The system record is made at step 3

Register v2 made the system record at submit. The assessment panel, the classification panel and the orchestrator need a system id, so in v3 the first Continue of step 3 calls `SystemService.register` (status `draft`, stage `initiation`) and keeps the id in the draft (`data.sys`). A later Continue of step 3 updates the same record (`update_fields`); no second record is made. Submit does not register again: it does the rest (agent row, links, Decision 33 draft, guardian rows, duties rows and tasks, intake tasks) and the stage approval request. Abandon archives the record. Save for later never makes the record.

## AI type (step 3)

`system_type` is one of `assistant`, `decision`, `automation`, `platform`, `feature`. Four boolean flags go with it:

| Flag | Rule |
|---|---|
| `generative` | a `model` or `endpoint` fact exists, or the model family is filled |
| `agentic` | a `tool` or `mcp_server` fact exists, or the autonomy level is L2 or higher |
| `customer_facing` | the user segment is `customer` |
| `decides` | the credit decision box, or system type `decision`, or an agentic system with no human control |

The page proposes the type (`decision` if it decides; `automation` if agentic, internal and not deciding; else `assistant`). The person can change the type and every flag; a flag that differs from the rule is marked "set by a person". The flags are stored on the draft (`ai_flags`, `ai_flag_src`) and on the system record as the tags `ai_generative`, `ai_agentic`, `ai_customer_facing`, `ai_decides` (`1` or `0`). No new column.

## Prefill from facts

The prefill uses the facts v1 export (`GET /v1/facts/{id}/export`) of the source key. It fills purpose, data sources, personal data, model family, autonomy level, money movement, credit decision and human control, and the type. A field filled this way is listed in `ai_from` with the fact pointer (`kind:name @ file:line`) and shows "from facts". A field the person changed is never overwritten and loses the mark. A second Continue of step 2 takes a newer attempt in.

## Duties prefill (step 6)

* **From the classification** (level of the newest record, approved or waiting): the entries of `steps.duties` in the strip file whose `when` fits the level are shown with the mark "from classification". High: TT53 Art. 13 (impact assessment), Law Art. 13 (conformity), TT53 Art. 12(3) (board approval). Medium and high: Decree Art. 12(2) (dossier), Law Art. 10(3) and Decree Art. 14(1) (notification). The rows come from the matrix, so their "applies" and "coverage" are the matrix's.
* **From the assessment** (`ONBOARD_ORCHESTRATOR`): `read_duties_prefill` gives the articles whose type has a passing report. Each TT53 matrix row for such an article is shown with "from assessment" and "confirmed" (a person set the status to pass) or "proposal".
* **Answers**: the two questions the AI type settles, `Q-customer_facing` and `Q-decisions_affecting_customers`, are filled on the Continue of step 5 and marked "from AI type". A changed answer is the person's and is never taken back. The button "Re-apply the pre-fill" fills the unanswered ones again.

## Compliance strip

One template, `_compliance_strip.html`, on every step. Mapping: `config/register_v3_strip.yaml` (step to RegKB obligation ids; a test checks that each id exists).

| Step | Articles (Law = 134/2025/QH15, Decree = 142/2026/ND-CP, TT53 = Circular 53/2026) |
|---|---|
| source | TT53 19(2), 8(2) |
| facts | TT53 19(2), 4(5) |
| identify | TT53 4(5), 4(1) |
| classify | Law 9(1), 9(2), 10(1); Decree 6(2), 6(3), 8(1), 9(1); TT53 4(1), 4(3) |
| assess | TT53 14(3), 14(4), 13(1) |
| duties | TT53 13(1), 12(3); Law 13(1), 10(3); Decree 12(2), 14(1) |
| guardians | TT53 5(1), 5(2), 6(1), 6(2), 7(4) |
| review | TT53 12(3), 4(3) |
| done | TT53 22(1)-(2), 4(5) |

Each row shows the status, the evidence pointer and the attempt number of the step. The status is set by one rule from a closed list; no model sets it.

| Rule | Met when | Evidence |
|---|---|---|
| `source_taken` | a stored intake attempt exists (not applicable: the person skipped, with a reason) | `intake_attempt:<key>#<n>` |
| `facts_built` | a facts card was built | `facts:<key>#<n>` |
| `system_saved` | step 3 made the system record | `ai_system:<id>` |
| `class_recorded` | a classification record exists (approved or waiting) | `classification_v2:<id>` |
| `class_approved` | an approved record exists (TT53 Art. 4(3)) | `classification_v2:<id>` |
| `dims_started` | at least one of the eight rows left `not_started` | `risk_dimension_status:<system>` |
| `dims_closed` | all eight rows are `pass`, `waived` or `not_applicable` (Art. 14(3)) | `risk_dimension_status:<system>` |
| `matrix_row` | the duties matrix row for the article applies and has full coverage (not applicable when it does not apply) | `obligation:<id>` |
| `guardians_saved` | step 7 was saved at least once | `registration_draft:<id>#guardians` |
| `predeploy_go` | the newest pre-deploy report of the source has the verdict `go` | `predeploy_report:<id>` |
| `stage_requested` | a stage approval is pending or approved | `stage_approval:<id>` |
| `submitted` | the draft is submitted | `ai_system:<id>` |

An entry with `when: high` (or `medium_high`) is "not applicable" when the classification level is lower, "open" when there is no record yet.

**Attempts.** Source and facts reuse the intake attempt number and the facts attempt number. Every other step has a counter in the draft (`step_attempts`) that goes up by one on each save of that step. A person can go back to any step, change it and save it again.

## Submit

Step 8 shows what will be written and the stage the request goes to (the first later stage whose move needs an approval; `deployment` with the default `config/tasks.yaml`). The button "Submit and ask for approval" runs the register submit and then `LifecycleService.request` (the call behind the WP-P1 button; `CONSOLE_WORKFLOW_ACTIONS` is not needed for it). The result page lists the step `Stage approval request`. A second person answers it on the system page. Nothing is applied: the classification stays a record that waits for its approver.

## Routes

No new route. The step, save, submit, abandon and result routes of `docs/register-v2.md` answer for the nine steps. Permission `systems.edit`; a viewer gets 403. Step 9 is the result page. The embedded panels use their own routes (`/console/intake/{key}`, `/console/facts/{key}`, `/console/predeploy/{key}`, `/console/systems/{id}/classify`, `/console/systems/{id}/risk-dimensions/...`, `/console/systems/{id}/orchestrate`) with their own audit rows. A bad value is HTTP 400 with the field name.

## Files

`governance/register_v3/` (`flags.py`, `strip.py`, `service.py`), `config/register_v3_strip.yaml`, `console/templates/_compliance_strip.html`, branches with `v3` in `register_step.html` and `register_result.html`, `console/i18n_register3.py`, tests `tests/governance/test_c3_register_v3.py` and `tests/console/test_c3_register_v3_routes.py`.
