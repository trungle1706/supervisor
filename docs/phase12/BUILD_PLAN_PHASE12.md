# Phase 12 (and 11): compliance-first onboarding, the agent factory, the guardian factory

Owner: the hub session. Workers: one Sonnet worker per WP in its own worktree, targeted tests
only, one hub review per WP. Rules of `CLAUDE.md` apply to every WP: flag off by default with an
off-path test; HTTP 400 never 500; only deterministic rules block or pause, a model drafts or
advises; evidence chain without personal data or floats; synthetic Vietnamese data only; schema
changes by appending to `schema/model.yaml` and regenerating (`python -m schema.generate`,
`python -m supervisor.databricks.notebook`), never by hand-editing DDL.

Written 2026-10-28 from the owner's five ideas, two research notes (`research/`), and v0.8.0.

## 0. Owner decisions (2026-10-28)

| # | Question | Decision |
|---|---|---|
| 1 | Workflow order | Nine steps; classification (step 4) before the risk assessment (step 5); duties (6) pre-filled from 4 and 5; guardian fit test (7) after the assessment. |
| 2 | Risk types | Exactly the eight of Circular 53 Art. 14(3) as fixed platform ids. More can be added later by configuration; none now. |
| 3 | Factory schemas | The platform locks the agent definition schema, the output schema, the tool registry and the mandatory guardians. Teams edit the listed fields only. **Supporting agents exist from the start**: the factory ships helper agents (policy-to-checklist drafter, golden-set generator, result explainer) so that a risk team is helped, not left alone (WP-F2, WP-F3). |
| 4 | Where judges run | Open. Proposal: the test gate's judge model is the bank's own gateway model (`LLM_BASE_URL`), golden sets are synthetic Vietnamese cases we write, calibration uses a human-labelled subset. The owner decides before WP-F3 starts. |
| 5 | Start | 12A (C1, C2) and F1 now, in parallel. |
| 6 | Phase 11 | Elaborated in section 4; the owner decides whether it runs beside 12A. |

Earlier decisions stay: real LLM gateway for key features, no mock run in a key feature; the
person can change, re-upload, retry; English first with verbatim Vietnamese quotes.

## 0.1 What exists (v0.8.0) and the gap

| Part | Module | Gap this phase closes |
|---|---|---|
| Register v2, seven steps (identify, ai, check, duties, class, guardians, review) | `governance/register_v2/` | compliance shown late; classification is the Decision 33 high-list test only |
| Decision 33 flow: 4 questions, outcomes high_risk / not_high_risk / unclassified | `governance/decision33.py`, `config/decision33.yaml` | no medium / low / prohibited; no SBV thresholds; no drawn tree |
| Risk register: 8 categories, lines link to rules, packs, monitors | `risk/` | not the eight risk types of Art. 14(3); no status per type per system |
| Facts card: 10 fact kinds with file and line | `onboard/facts.py` | no frozen schema other agents can read |
| Pre-deploy: rules + 34 packs + red team | `onboard/predeploy.py`, `assurance/` | fixed sequence; no per-team agents; no test gate for new agents |
| Detectors: fixed contract, config file, custom regex rules | `detectors/`, `config/detectors.yaml` | no authoring UI, no benchmark gate, no shadow mode for a new detector |
| My overview v4: pipeline, completion, risk by autonomy | `console/overview_v4.py` | no classification tiers, no risk-type status at portfolio level |
| RegKB: 79 obligations in the two instruments | `regulations/vn/` | the classification articles (Law 7, 9, 10; Decree 6, 8, 9, 11, 12(2)) and Art. 14(3)-(4) are not rows |

## 1. Phase 12A: compliance-first onboarding (4 WPs)

### WP-C1: classification tree (Law 134/2025 Art. 7, 9, 10, 13; Decree 142 Art. 6, 8, 9, 11, 12; QĐ 33; TT 53 Art. 4)

Flag `CLASSIFICATION_V2=1` (needs `GOVERNANCE_ENABLED=1`). Read `research/regulation-structure.md`
section 1 first; it has the levels, the criteria, the thresholds and the step order with quotes.

* `config/classification.yaml` (`illustrative: true` like `decision33.yaml`): the tree as ordered
  nodes. Each node: `id`, `question_en`, `question_vi`, `article` (instrument id + article ref),
  `answers` (`yes` / `no` / `excluded` → next node id or outcome), `prefill` (optional rule on the
  facts card or the system record, never a model), `evidence_hint`. Outcomes: `not_system`,
  `prohibited`, `high_certify`, `high_self`, `medium`, `low`. The "in the PM list" node reuses
  the Decision 33 questions and outcome as a sub-flow (do not duplicate them). SBV thresholds as
  integers (VND) in the file: personal 10,000,000 per transaction and 20,000,000 per day;
  organisation 50,000,000 and 100,000,000; credit 50,000,000. Re-classification triggers
  (Decree Art. 11(1)(a)-(d), 11(2), 11(4) not a trigger) as a list with articles.
* Loader with strict keys like `decision33.py` (unknown key → `ConfigError` naming the field).
  A test walks every path and checks that every node ends in an outcome and every node has an
  article that exists in RegKB.
* New table `classification_v2` (append to `schema/model.yaml`): `classification_id`,
  `system_id`, `outcome`, `path_json` (node id, answer, evidence pointer per step; no free text
  longer than 300 chars), `decided_by`, `approved_by` (bank approval, TT 53 Art. 4(3); a
  different person from `decided_by`; HTTP 400 `same_person`), `inherited_from_provider`
  (Art. 4(4)), `valid_until` (yearly review, Art. 4(5)), `created_at`. Chain record
  `classification_v2` with the outcome and the path hash.
* Level mapping: `prohibited` → risk level `prohibited`; `high_*` → `high`; `medium` → `medium`;
  `low` → `low`; `not_system` → no change. Reuse the classifier-floor rule of Decision 33 (never
  lowers a stored level). Decision 33 `apply` stays and is called by the sub-flow.
* Console: page `/console/systems/{id}/classify` and a panel in Register v2 step `class`. The
  tree is drawn server-side (HTML/CSS boxes and arrows, or inline SVG from a template; no inline
  script, CSP `script-src 'self'`). Each node shows the article, the answer, the evidence
  pointer, the prefill source when a rule answered. The chosen path is highlighted; the outcome
  card names the duties that follow (impact assessment TT 53 Art. 13, conformity Law Art. 13,
  board approval Art. 12(3), dossier and notification Decree Art. 12(2), Law Art. 10(3)).
  Separation of duties as in WP-P2: the system owner cannot approve the own classification.
* API: `GET/POST /v1/systems/{id}/classification`, `POST .../classification/approve`,
  `GET /v1/classification/summary` (counts per outcome for WP-C4). Roles: `systems.edit` to
  decide, `systems.approve` (or the existing approver role) to approve, `systems.view` to read.
* RegKB: add obligations with verbatim `text_vi` from the stored texts for Law Art. 7(2), 9(1),
  9(2), 10(1), 10(2), 10(3), 10(4); Decree Art. 6(2), 6(3), 8(1), 8(2), 9(1), 9(3), 11(4),
  12(2). `control_mapping` to a new console control `classification_v2` and evidence
  `classification_record`; the quote tests must pass. Keep `verification: VERIFIED_PRIMARY`.
* Off path: the Decision 33 flow and the `class` step are unchanged; the routes answer 400
  `classification_v2_off`.
* Docs: `docs/classification.md` (new) and a note in `docs/decision33.md`.

### WP-C2: eight risk types as records (TT 53 Art. 14(3)-(4), 16, 17, 18, 19, 6, 7)

Flag `RISK_DIMENSIONS=1` (needs `GOVERNANCE_ENABLED=1`). Read `research/regulation-structure.md`
section 2 first.

* `config/risk_dimensions.yaml`: the eight ids `model`, `data_governance`, `cybersecurity`,
  `legal_compliance`, `ethics`, `third_party`, `supply_chain`, `reputation`; each with
  `label_en`, `label_vi`, `articles`, `definition_en` (Art. 14(4) "nội hàm"), `criteria`
  (identification criteria), `measure` (what is measured), `threshold` (a placeholder the bank
  sets; integers or enums, no floats), `controls` (ids from `regulations/schema/controls.yaml`
  and pack ids), `measured_by` (packs, monitors, rules that already produce a result),
  `applies_to` (`reputation`: banks only), `agent_slot` (the factory agent id that will assess it,
  empty now). No ninth row in this WP (owner decision 2); leave a documented `extra_dimensions`
  list that is empty.
* New table `risk_dimension_status` (append): `status_id`, `system_id`, `dimension_id`, `status`
  (`not_started`, `in_progress`, `pass`, `fail`, `waived`, `not_applicable`), `owner_team`,
  `assessed_by` (agent id and version, or a person ref), `report_ref` (assessment report id,
  WP-F1; nullable now), `evidence_json` (pointers: pack result ids, fact ids, document ids),
  `threshold_json`, `note` (≤ 300 chars, masked), `updated_by`, `updated_at`, `valid_until`.
  One row per system and dimension; the service creates the eight rows the first time a
  system is read with the flag on.
* Rules: `waived` needs a reason and a person who is not the system owner; `pass` needs at least
  one evidence pointer; a change writes a chain record `risk_dimension_status` (dimension id,
  from, to, actor ref, evidence hash) and an audit row with before and after.
* Initial fill by rules only (no model): a mapping in the YAML from pack results and monitors to
  a proposed status (`pass` when every mapped required pack passed at the current version,
  `fail` when one failed, else `not_started`); the proposal is shown, a person confirms.
* Console: tab **Risk assessment** on the system page: eight rows with status pill, owner team,
  assessed by, evidence pointers, threshold, actions (set status with evidence, waive, request
  re-assessment placeholder for WP-F4). Link each row to the risk register lines of the matching
  category (`money_movement`, `credit_decision` → model; `pii` → data_governance and
  legal_compliance; `injection` → cybersecurity; `model_behaviour` → model; `availability` →
  supply_chain; `third_party` → third_party; `duties_gap` → legal_compliance).
* API: `GET/POST /v1/systems/{id}/risk-dimensions`, `POST .../risk-dimensions/{dim}/waive`,
  `GET /v1/risk-dimensions/summary` (portfolio counts per dimension and status, for WP-C4).
* RegKB: add rows for TT 53 Art. 14(3) and 14(4) (one per paragraph, verbatim quotes) with a
  note that Art. 14 applies from 2027-01-01; map to a new evidence control `risk_dimension_status`.
* Off path: no table read, routes answer 400 `risk_dimensions_off`, system page unchanged.
* Docs: `docs/risk-dimensions.md`.

### WP-C3: the nine-step workflow with a compliance strip (after C1, C2, F1)

Flag `REGISTER_V3=1` (needs `CONSOLE_REGISTER_V2=1`, `CLASSIFICATION_V2=1`, `RISK_DIMENSIONS=1`).

* Steps: 1 Source (intake, WP-O1), 2 Facts (WP-O2, shown, not editable), 3 Identify and AI type
  (pre-filled from facts v1: model, endpoint, tools, autonomy, data; AI type taxonomy from the
  facts: assistant, decision, automation, platform, feature plus generative / agentic flags),
  4 Classify (WP-C1 panel), 5 Risk assessment (WP-C2 rows; the orchestrator fills them when
  WP-F4 exists, else rules), 6 Duties (WP-L2, pre-filled: the classification outcome and the
  eight statuses answer the matrix questions they can), 7 Guardian fit (pre-deploy WP-O3 with
  the proposed guardian set), 8 Review and submit (stage approval request, WP-P1), 9 Done
  (links to the agent page tabs).
* Compliance strip on every step: the articles that apply at that step (from the RegKB rows and
  the step's duties), status met / open / not applicable, the evidence pointer, and the attempt
  number. The strip is one template used by every step.
* Go back, change, re-run any step; attempts are numbered as in WP-O1.
* Off path: the seven-step workflow as before.

### WP-C4: portfolio dashboard blocks (after C1, C2)

Flag `OVERVIEW_PORTFOLIO=1` (needs `CONSOLE_OVERVIEW_V4=1`).

* Block **Classification**: one bar per outcome (prohibited, high certify, high self-assess,
  medium, low, not classified) with counts; click → the systems list filtered.
* Block **Risk assessment**: eight columns (the dimensions) × systems rows as a status grid,
  with the portfolio total per column (pass, open, fail, waived) and the count of systems past
  `valid_until`. Click a cell → the system's Risk assessment tab.
* Both blocks read the summary APIs of C1 and C2, so the numbers equal the system pages.
* Off path: My overview unchanged.

## 2. Phase 12B: the assessment-agent factory (6 WPs)

Read `research/agent-factory-research.md` first (comparison, ten principles, schema, test gate,
promotion, licences, anti-patterns).

### WP-F1: the schemas (no flag; pure modules, one export route)

* `src/supervisor/factory/schemas/facts_v1.py`: a frozen JSON schema and pydantic model for the
  facts card export: version `1`, the ten fact kinds of `onboard/facts.py` as typed records with
  `kind`, `name`, `detail`, `file`, `line`, `source` (`rule` / `model`), `confidence`
  (`low` / `medium` / `high`), plus the summary. Field names are frozen; a test fails when the
  facts card gains a field that the export does not carry (the export must be updated on
  purpose). Route `GET /v1/facts/{node_id}/export` (flag `ONBOARD_FACTS`, `systems.view`).
* `assessment_report_v1.py`: `report_id`, `agent_id`, `agent_version`, `system_id`,
  `dimension_id` (one of the eight), `findings[]` with `finding_id`, `checklist_id`, `verdict`
  (`pass` / `fail` / `not_applicable` / `question`), `evidence[]` (`kind`: `fact` / `document` /
  `regkb` / `pack` / `system_record`; `ref`; `file`; `line`), `rationale` (≤ 600 chars),
  `confidence` (enum, no floats); `summary` with integer counts; `model_id`; `created_at`.
  A finding with verdict `pass` or `fail` and no evidence is invalid.
* `agent_definition_v1.py`: the schema of the research note section (c): `schema_version`,
  `id`, `name` (≤ 64), `description` (≤ 1024), `owner_group`, `dimension_id`, `policy_refs[]`,
  `checklist[]` (`id`, `question`, `evidence` kinds, `severity`, `pass_rule`), `evidence_rules`,
  `tools[]` (by `tool_id` only; inline tools are refused), `instructions` (≤ 5000 tokens by a
  simple count), `output_schema` (must be `assessment_report_v1`), `guardians[]` (the mandatory
  set must be present), `eval_pack`, `lifecycle` (`state` in `draft` / `tested` / `approved` /
  `live` / `retired`, `version`, `approvals[]`).
* `config/factory_tools.yaml`: the tool registry: `tool_id`, `label`, `kind` (`read_facts`,
  `read_regkb`, `read_pack_results`, `read_system_record`, `search_documents`), `scope` kinds,
  `data_class`, `allowed_groups`, `mode: read`. Loader with strict keys.
* `config/factory_groups.yaml`: the user groups (model_risk, data, cyber, legal, third_party,
  ethics, platform) mapped to roles of `users.yaml`; a group owns dimensions and sees tools.
* CLI `python -m supervisor.factory validate <file>` for the three schemas; tests with example
  files under `tests/factory/data/`; `docs/factory.md` section "Schemas".

### WP-F2: the factory UI and catalogue (after F1)

Flag `AGENT_FACTORY=1`. Table `factory_agent` (append): id, version, owner_group, dimension_id,
definition_json, state, created_by, updated_at; `factory_agent_event` (append only) for every
state change and approval. Pages: catalogue `/console/factory` (cards per agent: dimension,
owner group, state, version, last test result), editor with the eight authoring steps of the
research note (template → policy refs → checklist table editor → tools from the group's
allow-list → instructions with linter → guardians (mandatory pre-checked, not removable) →
preview on three past onboardings with a plan tracer → golden set and thresholds). **Helper
agents in the editor (owner decision 3)**: *checklist drafter* (reads the attached policy
sections and proposes checklist rows with the section pointer), *golden-set generator* (proposes
synthetic cases from the checklist, Vietnamese, no real data), *result explainer* (turns a
report into plain sentences with the pointers). All three draft only; a person accepts each row.
Model calls through the gateway only; off when `LLM_BASE_URL` is empty with a clear message.

### WP-F3: test gate and promotion (after F1, F2) — the test-eval-improve loop

Flag `AGENT_FACTORY_GATE=1`. Golden sets stored per agent (≥ 50 cases, stratified by checklist
item; synthetic Vietnamese). Layers: deterministic checks first (schema valid, every pass or fail
verdict cites evidence that exists in an allowed source, no tool outside scope, no personal data
in the output, token budget); then guideline judges (yes/no with reason) with a human-labelled
calibration subset and Cohen's kappa reported (an agreement number alone is not enough); then a
shadow run on past onboardings (the agent runs, the result is stored, not shown). Gate: the
deterministic layer at 100 %; the judge layer with no regression against the live version (paired
comparison) and a floor per tier; the shadow report attached. States draft → tested → approved →
live with two approvals for a high-tier agent (owner group lead + second line); a change of
tools, guardians, output schema or tier re-opens approval; immutable versions; one-click rollback;
`retired`. Reuse: promptfoo (MIT) or DeepEval (Apache-2.0) only as vendored pure-Python where
offline rules allow, else own runner; Inspect AI (MIT) as reference. Owner decision 4 applies
(where the judge runs). Reports as integers; chain record per state change.

### WP-F4: the orchestrator (after F1, C1, C2)

Flag `ONBOARD_ORCHESTRATOR=1`. Deterministic, no model call of its own. Input: the system, its
classification outcome, AI type flags, facts v1. Plan: which of the eight dimensions apply and
which live agent assesses each (from `factory_agent` by dimension and `live` state; a dimension
without a live agent gets the rule proposal of WP-C2). Runs the agents with a time and token
budget, in order, writes `assessment_report_v1` rows and the `risk_dimension_status` proposals,
resolves conflicts by rule (the worst verdict wins; a `fail` needs a person), writes the Duties
pre-fill and `onboard_log` rows (WP-O5) for each step. Re-run after a fix is a new attempt.

### WP-F5: six starter agents (after F2, F3)

One live-able agent per dimension model, data_governance, cybersecurity, legal_compliance,
third_party, ethics, each with a checklist from the articles in `research/regulation-structure.md`
section 2, a golden set, and the mapping to the packs that already measure the dimension.
`supply_chain` and `reputation` ship as templates with an empty golden set. Each agent passes the
WP-F3 gate on synthetic data before merge.

## 3. Phase 12C: the guardian factory (4 WPs)

### WP-G1: detector definition and registry

Flag `GUARDIAN_FACTORY=1`. Schema: `id`, `name`, `owner_group`, `type` (`regex`, `keyword_list`,
`classifier`, `judge_prompt`, `policy`), `stage` (`preflight`, `input`, `tool_call`, `output`),
`scope` (agents, tools, data classes), `action_on_fail` (`block`, `redact`, `require_approval`,
`log`; only `regex`, `keyword_list` and `policy` may block), `sensitivity` (1-4), `benchmark_pack`,
`thresholds` (integers: min true positive rate in percent, max false positive rate, max p95 ms),
`lifecycle`. Plain-words authoring: the person writes the rule in words; the platform makes the
artifact (regex through the existing safety checks of `custom_rules`, policy, judge prompt) and
validates it; the person sees and edits the artifact. Table `guardian_def` (append). Registry page
and editor.

### WP-G2: benchmark harness (after G1)

Attack set (true positives) and benign set drawn from stored traces (synthetic) per detector;
true positive rate, false positive rate, p95 latency, cost at each sensitivity level, next to the
live detector of the same stage. Report as integers. Gate from the thresholds of the definition.

### WP-G3: shadow mode and promotion (after G2)

A `benchmarked` detector runs in log-only mode on live gate traffic for N days (`shadow_days`),
findings stored, nothing blocked; flagged items reviewed; states draft → benchmarked → shadow →
approved (owner group + platform security) → live as an immutable version attached to agents by
id and version through guardian bindings; allow-lists with an expiry date.

### WP-G4: the smart guardian (after F4, C2)

From the assessment reports and the facts, propose the guardian set, the thresholds and the
autonomy limits for one agent, with the pointer that justifies each line; a person accepts; the
pre-deploy test (WP-O3) proves the fit. Proposals only; never attaches by itself.

## 4. Phase 11: regulation watch loop (2 WPs, elaborated)

The App has no internet. The watcher runs on a dev host or as a scheduled job with internet and
produces an **update package** that the App imports offline.

### WP-W1: watcher and update package

Flag `REGWATCH_ENABLED=1` (laptop mode scheduler job, default off) and CLI
`python -m supervisor.regkb watch`. For every instrument in RegKB: query the vbpl.vn search
action (`tools/regkb_fetch.py vbpl-search`; the action id rediscovery and the sitemap fallback
exist) by document number and by keywords ("trí tuệ nhân tạo", "AI") for the issuing agencies
(SBV, Government, MST); detect a new amendment, replacement, effect-status change or a newer
`updatedDate`; fetch the new text into `regulations/sources/<id>/incoming/<date>/` with sha and
sidecar; write a watch report (JSON and markdown: instrument, what changed, dates, sha) and a
signed update package zip (texts, report, proposed YAML changes empty at this step). The App
imports a package with `POST /v1/regkb/import` (admin, signature and sha checked, stored, not
applied). Nothing is applied automatically. Also watches the Decree 142 Art. 46 interim channel
announcement (MST) by keyword.

### WP-W2: change to re-evaluation

The law agent (WP-L1) gets a diff mode: article-by-article diff of the stored text against the
incoming text, drafts the changed or new duties with quotes, marks the obligations whose article
changed. A person with `regkb.confirm` confirms; the RegKB version hash changes; a governance
event `regkb_changed` (WP-G5 rules) with the instrument and the article list: re-opens the
`obligation_status` rows mapped to those articles (status open, note "article changed on
<date>"), creates the gap tasks (WP-L3), moves a system to `re_evaluation` when a classification
input changed (Decree Art. 11(1)(c) list change; the C1 trigger list), notifies the owners, and
shows a banner "law change pending review" on My overview. Chain record and audit rows.

## 5. Order and merge

```
 wave 1  WP-C1 | WP-C2 | WP-F1                (parallel, now)           + WP-W1 if the owner says so
 wave 2  WP-F2 -> WP-F3 | WP-F4 | WP-G1 -> WP-G2 -> WP-G3   (after wave 1)  + WP-W2
 wave 3  WP-C3 | WP-C4 | WP-F5 | WP-G4         (close-out)             -> v0.9.0
```

Each WP: worker in a worktree, targeted tests, hub review and merge, full suite once per
release, live check on the laptop demo and on the Databricks App.
