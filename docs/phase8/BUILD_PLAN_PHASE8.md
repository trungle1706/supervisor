# Phases 8 to 11: law agent, visible onboarding agent, workflow close-out, regulation watch

Owner: the hub session. Workers: one Sonnet worker per WP in its own worktree, one independent
reviewer per WP. Rules of `CLAUDE.md` and `docs/BANK_DEPLOY_GUIDE.md` apply. Every switch below
is OFF by default; the off path behaves as before and has a test.

Written 2026-10-28 after the first live run on Databricks (v0.6.1, Supervisor App
`aichampion-mrm-app` + candidate App `aichampion-kb-chatbot`).

## 0. Owner decisions (2026-10-28)

| # | Question | Decision |
|---|---|---|
| 1 | Deadline | None. Build the most functional product. |
| 2 | Models and data | Key features run on the real LLM gateway (Databricks AI Gateway, `LLM_BASE_URL`). Data is synthetic and made by us. **No mock run in a key feature.** The mock adapters stay for unit tests only. |
| 3 | Law agent | Agent + deterministic rules give the most insightful draft. The person who registers can change answers, re-upload the source, or retry the assessment after a fix. |
| 4 | Candidate source | Synthetic data and proxy candidate agents made by us first (the three testbed candidates and new ones). Workspace read of a bank App is a later step. |
| 5 | Language | English first. Vietnamese quotes (`text_vi`) stay verbatim; the Vietnamese UI follows later. |
| 6 | Decree 142 text | The stored text (`regulations/sources/VN-DEC142-2026/`, Official Gazette no. 278, signed PDF, sha `b8e0be6b...`) is the authority. thuvienphapluat needs a login. The chinhphu.vn link the owner gave is the signed Circular 53 PDF; it is stored as `VN-TT53-2026/53-2026-tt-nhnn-signed.pdf` (sha `f0661470...`, same as the owner's upload). |

Rule for every WP: "insightful" means a finding with a pointer (file:line, article, table row). A
sentence with no pointer is not a finding. The model drafts; a rule or a person confirms.

## 0.1 What exists (v0.6.1) and the gap each phase closes

| Part | Module | State | Gap |
|---|---|---|---|
| RegKB: Law 134/2025 (32), Decree 142/2026 (26), QĐ 33 (12), TT 53 (53), all VERIFIED_PRIMARY | `regkb/`, `regulations/` | built | static YAML from 2026-10-15; no agent reads the text |
| Compliance advisor: obligations matrix, questions | `advisory/compliance/` | built | own page; not inside Register or the risk register |
| Decree 142 coverage | `regulations/vn/decree-142-2026.yaml` | 0 full / 50 partial / 28 none | no effectiveness claim possible |
| Onboard agent: Discover, Understand, Decision 33, autonomy, PR | `onboard/` | built | CLI on a local folder; nothing visible in the console |
| Inventory scan + candidate row | `inventory/` | built | shows the name, not what was learned |
| Packs, red team, judges, monitors | `assurance/`, `redteam/`, `judge/`, `monitors/` | built | not shown as one pre/post-deploy assessment |
| Guardian bindings + floor | `governance/guardians.py` | built | no picture of the attachment |
| Register v2, six steps | `governance/register_v2/` | built | after Submit: approvals, stage, RUNNING are API only |

## 1. Phase 10 first: close the workflow, harden the live run (3 WPs, parallel)

Sources: the UX test (`office-build/ux.json`, H1 to H8) and the live-run errors of 2026-10-27.

### WP-P1: tasks and stage approvals in the console

Flag `CONSOLE_WORKFLOW_ACTIONS=1` (needs `GOVERNANCE_ENABLED=1`, `CONSOLE_SYSTEMS_ENABLED=1`).

* System > Tasks: buttons **Done** and **Waive** (reason required, min 10 chars). Role check:
  the task's `role` or `systems.edit`; the waiver needs a different person from the task creator
  when `created_by` is set. Audit row with action name, before, after, reason (fixes M10 for this
  action).
* System > Stage: **Request move** (target stage, reason) → **Approve** / **Reject** by a second
  person (not the requester; HTTP 400 `same_person`) → **Move**. Reuse the resume pattern of
  cases. Backed by the existing `POST /v1/systems/{id}/approvals`, `.../decide`, `.../stage`.
* Next action (`governance/next_action.py`) points to these buttons, never to an API path.
* Tests: off path unchanged; role and same-person rules; HTMX fragments (`HX-Request: true`).

### WP-P2: agent state and separation of duties

Flag `CONSOLE_STATE_ACTIONS=1`.

* Agent page: **Request RUNNING** (from SHADOW; reason) and **Approve RUNNING** by a second
  person who is the agent owner or in `reviewers:` of the policy. Backed by
  `POST /v1/gate/agents/{id}/state`. Shadow would-block count of the last 7 days is shown next to
  the button (M8: reuse the Activity query).
* Decision 33 apply: the system owner cannot apply the class on the own system (H3); a
  justification (min 20 chars) is required for every answer. HTTP 400 `owner_cannot_apply`.
* Guardian switch-off (H4): reason required; on a system in production or high risk a second
  person approves (same request/approve rows as WP-P1, kind `guardian_off`).
* Tests: each rule on and off; the two-person rule with the synthetic identities.

### WP-P3: live-run hardening

* `SCHEMA_SELFCHECK=1`: at start the app compares the tables and columns of `schema/model.yaml`
  with the warehouse (one `information_schema` query per table). A missing table or column shows
  a console page `/console/admin/schema` with the exact SQL plan (CREATE or ALTER ADD COLUMNS)
  for copy and paste, and a banner on every admin page. The app does not run DDL by itself.
* Candidate SDK: `HttpGate` default `timeout_s` stays 2.0 for the library; the kb-chatbot and the
  other testbed candidates set `SUPERVISOR_TIMEOUT_S=25` in `app.yaml`; the gate's own budget
  (`GATE_DECISION_TIMEOUT_S`) is returned in `/healthz` so a candidate can read it.
* `/healthz` adds `schema_ok`, `judge_sweep`, `model_resource` (the gateway call probe, cached
  60 s) so the Re-check page of a candidate can show them.
* Deploy docs: the Model resource reset on `bundle deploy`; the `databricks sync` + `apps deploy`
  path; the local `.databricks` snapshot trap; the Umbrella DNS block; all in
  `LAUNCH_DATABRICKS.md` section "Failure map".
* `python -m supervisor.demo seed --databricks`: writes the synthetic systems, agents, cases and
  evidence of the local demo into the warehouse tables (idempotent, tagged `demo=1`).

## 2. Phase 9: the visible onboarding agent (5 WPs)

Goal: a person sees the Supervisor agent work: scan, read the source, state facts with pointers,
assess before deploy, attach the guardians, assess after deploy. Every step is re-runnable after
the candidate owner fixes something (decision 3).

### WP-O1: candidate source intake

Flag `ONBOARD_INTAKE=1`.

* Sources of code, in this order: (a) upload a zip in the console (max 20 MB, Python and config
  files only, scrubbed by `onboard/scrub.py`, stored under `DATA_DIR/intake/<node_id>/<n>/`);
  (b) a git URL the Supervisor can clone offline-safe (allowlist `ONBOARD_GIT_HOSTS`);
  (c) a Databricks Workspace folder or Git folder (`ONBOARD_WORKSPACE_ROOTS`; the Supervisor
  service principal needs CAN READ). (a) and (b) first; (c) behind its own flag.
* Each intake is a numbered attempt on the candidate (`intake_attempt` table: node_id, n, source
  kind, ref, sha256, size, files, by, at, status). Re-upload makes attempt n+1; old attempts stay.
* Secrets never reach the model: the WP16 scrub and the planted-secret test run on every attempt.

### WP-O2: facts card ("what we know about this agent")

Flag `ONBOARD_FACTS=1`.

* Server-side run of `onboard.discover` + `onboard.understand` on the attempt. Output stored as
  `onboard_facts` rows: tools (name, side effect, reversibility), models and endpoints, data
  (UC tables, files, vector indexes), secrets use (kind only), external URLs, MCP servers, human
  approval points, autonomy level, Decision 33 pre-fill, weak spots. Every row has `file`, `line`,
  `quote` (max 200 chars).
* Model claims (decision 2: the real gateway model) go through `validate_llm_claims`; a claim
  without a file:line is dropped and counted.
* Console: candidate page tab **Facts**: the card, grouped; a line "n claims dropped (no
  evidence)". Button **Re-read** after a new attempt.
* The inventory graph gets the edges from the facts (`uses`, `reads`, `writes`), source
  `onboard_facts`, so the register prefill and the risk inheritance use them.

### WP-O3: pre-deploy assessment

Flag `ONBOARD_PREDEPLOY=1`.

* One report per attempt: facts (O2) + readiness (`systems_wizard.readiness`) + the required
  assurance packs in the launch sandbox (gate in SHADOW, synthetic world) + the multi-turn red
  team pack + the duties matrix (Phase 8, when on; else "duties: not run").
* Verdict: `GO`, `NO-GO` (a required pack failed or a deterministic rule blocks), or `QUESTIONS`
  (facts the person must answer). The verdict is deterministic from the rows; the model never
  sets it.
* Console: tab **Pre-deploy**: the verdict, the items, each with its pointer, and **Run again**.
  Register v2 step 3 links to the latest report instead of the folder scan.

### WP-O3b: packs against the running candidate (follow-up found in WP-O3)

The launch sandbox runs demo agents only. A real candidate tree has no harness, so every pack that
needs a running agent fails and the verdict is NO-GO. Build an `HttpAgentTarget`: the required
packs and the multi-turn red team run against the candidate App URL (the candidate in SHADOW,
ingress credential of the Supervisor service principal, synthetic data only), the same way the
kb-chatbot Re-check page calls the gate. The pre-deploy report says which target ran. Also fix
`assurance.gates._row`, which drops `is_mock` from a `PackResult` object (found in WP-O3).

### WP-O4: guardian attachment view

Flag `ONBOARD_ATTACH_VIEW=1`.

* Per candidate or agent: a wiring picture (inline SVG, both themes) of the plug point in use
  (SDK `HttpGate`, HTTP proxy, MCP gateway, Databricks App env) and the guardians on it: gate
  rules, detectors, judges, monitors, packs, with the floor marked. Each item shows its last
  evidence time (verdict, finding, eval_result, monitor row) and lights up when evidence arrives.
  Data: `GateStates`, `RulesService.guardian_floor`, the detector catalogue, `readmodels`.
* The kb-chatbot Re-check page is the model: the view is the same check from the Supervisor side.
* A **How to attach** panel with the exact env lines for the plug point (copied from the policy
  and `agent_identities.yaml`), no secrets.

### WP-O5: post-deploy assessment and the agent log

Flag `ONBOARD_POSTDEPLOY=1`.

* Tab **Post-deploy**: the SHADOW statistics (calls, would-block by rule), judge verdicts by
  tier, drift (the session monitor), incidents, pack re-runs on traces, on one timeline next to
  the pre-deploy verdict. The RUNNING request (WP-P2) reads this tab.
* **Agent log**: every onboarding action is a row (`onboard_log`: attempt, step, what, pointer,
  by model or by rule, at). The console shows it as a timeline "plan, read, found, suggest". This
  is the visible agentic part. Rows are append-only; no PII; no floats.

## 3. Phase 8: the law agent (5 WPs)

### WP-L1: law breakdown agent

Flag `LAWAGENT_ENABLED=1`. CLI `python -m supervisor.regkb.lawagent --instrument VN-DEC142-2026`.

* Input: the stored primary text of one instrument. The agent (gateway model, decision 2) reads
  article by article and drafts: duty (from `duties.yaml`), subject (who), trigger (when), the
  evidence an auditor asks for, the verbatim `text_vi` quote, a one-line English summary.
* Rules check every draft: the quote must be a substring of the stored text (else dropped), the
  duty id must exist, the article must exist. A draft becomes an obligation only after a person
  confirms it in the console (`/console/regkb/<instrument>/drafts`, two buttons: confirm, drop).
  Confirmed rows get `verification: VERIFIED_PRIMARY` and `confirmed_by`.
* Diff mode: on a new text version the agent lists added, changed and removed articles (Phase 11
  uses it).
* Not legal advice: the banner on every page and in every output stays.

### WP-L2: duties step in Register v2

Flag `CONSOLE_REGISTER_DUTIES=1`.

* New step **Duties** after readiness and before Decision 33. The matrix (`advisory/compliance`)
  runs on the draft answers and the facts (WP-O2). The rows: applies yes / no / needs answer;
  coverage full / partial / none; the open questions are form fields in the step.
* On submit: one `obligation_status` row per applying duty on the AI system, and one task per
  duty with coverage partial or none (WP-L3 owns the task text).
* The person can go back, change answers, and re-run the step.

### WP-L3: duties in the risk register and gap tasks

Flag `RISK_DUTIES=1`.

* One risk line per applying duty with coverage partial or none: owner, due date (from the
  instrument's effective date and the staged dates of TT 53), the closing control: a Supervisor
  control id or a bank manual control (`regulations/internal/`), status open, closed, waived.
* Gap closure score per system: closed / (open + closed), integer percent, shown on the system
  page and on My overview (assessment completion gets a "duties" dimension).
* Deadlines from `advisory/compliance/deadlines.py` become tasks with due dates.

### WP-L4: effectiveness evidence and the regulator pack

Flag `REGULATOR_PACK=1`.

* For every duty mapped to a Supervisor control, live counts in the window (gate decisions,
  findings, verdicts, chain verifications, pack results) prove the control works. The same
  rows as the risk register evidence (`risk/evidence.py`).
* One pack per system (HTML and JSON, offline, no PII, no floats): instrument, article, duty,
  applies, coverage, status, evidence counts, pointers, confirmed by, date. Signed with the
  evidence signer; the audit pack verifier reads it.


Hub notes after WP-L3 (2026-10-28): WP-L4 must (a) close a `full` coverage row by itself with the
mapped Supervisor control id once live evidence for that control exists, so the score reflects the
controls that work; (b) close the WP-L2 gap task of a group when its last row closes; (c) read the
close evidence and the waive reason from `obligation_status.note` (after the banner) and the
control from `closing_control`.

### WP-L5: Decree 142 and TT 53 coverage raise

No flag; data and controls.

* Every `partial` duty of Decree 142 and TT 53 gets: the missing control named, built when it is
  a runtime or console control, or marked `manual` with the bank procedure field. Target: 0
  `none` left without a named manual control; `partial` only where the gap is named.
* The OCR of the signed TT 53 PDF (tesseract vie) stored as a second text with its sha; a test
  checks every TT 53 `text_vi` quote against both texts.

## 4. Phase 11: regulation watch loop (2 WPs)

### WP-W1: watcher

Flag `REGWATCH_ENABLED=1`. Reuse the vbpl.vn search action of the reggraph POC (memory
`reference-vbpl-search-action`). A scheduler job (default off) lists new or changed texts of the
instruments in RegKB and stores them under `regulations/sources/<id>/incoming/` with sha. No
auto-apply.

### WP-W2: change to re-evaluation

WP-L1 diff mode runs on the incoming text. A person confirms. The RegKB version hash changes. A
governance event `regkb_changed` (WP-G5 rules) reopens the duties of every system the instrument
touches: tasks, re-evaluation stage, owner notice.

## 5. Order and merge

```
 week 1      WP-P1 | WP-P2 | WP-P3            (parallel)  -> v0.7.0
 weeks 2-4   WP-O1 -> WP-O2 -> WP-O3, WP-O4 | WP-L1 -> WP-L2 -> WP-L3   (two lanes)
 week 5      WP-O5 | WP-L4 | WP-L5                        -> v0.8.0
 week 6-7    WP-W1 -> WP-W2                               -> v0.9.0
```

Each WP: worker in a worktree, targeted tests, independent review, hub merge, full suite once
per release. Each release adds a live-run check on the two Databricks Apps.
