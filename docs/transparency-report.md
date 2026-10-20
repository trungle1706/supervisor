# Transparency report (WP31)

One report per agent, built from facts the system already holds. It answers: what is this agent, how is it classed under Decision 33, which controls and checks exist, what is the state of the evidence, and what does the report not show. Off by default (`TRANSPARENCY_ENABLED=1`).

```
 facts (read only)                        report (JSON data model)          files
 agent row, inventory graph  ---+
 Decision 33 class + matrix     |
 agent card, judge card         +--> ReportBuilder --> allow-list --> JSON ---> HTML (vi, en)
 assurance, judge MRM, masking  |     (sections)       per variant     |        PDF  (vi, en)
 monitors, risk register        |                                      |
 evidence chain + offline check |                                      +--> chain record transparency_report
 open cases, BACKLOG            +                                           + rows in transparency_report
```

## Variants

| Variant | For | What it shows |
|---|---|---|
| `regulator` | SBV inspector, internal audit | Everything except people and internal notes: agent id, owner team, Decision 33 class and the obligation ids it relies on, matrix status counts, the Decision 33 rows, cards, assurance, judge status, monitors, risks (no owner, no actor), chain head hash and check, open cases (ids, severity; no text) |
| `customer` | Customers, handed on | Plain sentences only: what the assistant does, whether a person approves money transfers, the Decision 33 class in words, masking on or off, number of monitors on, the result of the chain check, the number of risks and the highest remaining level, the number of tests. No agent id, rule id, obligation id, hash, owner or flag name |
| `internal` | The bank | Everything: owner, business owner, model-risk role names, masked case titles, risk owners, and open BACKLOG rows that name the agent |

Each variant has an explicit allow-list (`src/supervisor/transparency/allowlist.py`). A field that is not listed is not copied. Every field the builder makes is also listed in `allowlist.REVIEWED`; a collector that adds a field fails `tests/transparency/test_review_leaks.py` until someone lists it and decides which variants may see it (some regulator sections are copied whole, so this list is the gate). After the projection every text value of the regulator and customer versions is scrubbed: the masker, then the patterns for e-mail, phone and a long run of digits (CCCD, account or card number); with no masker only a one-word code is kept and other text is dropped. This covers fields copied as they are (a matrix article, a limit pointer, the inventory node a risk comes through). A second check (`guard`) refuses a finished report if the customer version holds an agent id, rule or obligation id, hash, owner field or person name, or if either outer version holds an e-mail, a phone number or a long run of digits, whatever the allow-list says; the rendered text of both languages is checked again on every path (signed, preview, `live=1`, either `lang`). A package that adds a section (WP30 `controls`) must add its fields with `allowlist.set_spec`; until then the regulator and customer versions show nothing of it.

## Sections

| Id | Content | Source |
|---|---|---|
| `identity` | name, owner, host, model family, risk tier, gate state, purpose, oversight facts | agent registry, matrix product profile |
| `classification` | Decision 33 class and where it comes from (registry, onboarding proposal, matrix), the entries (transactions, credit) and the obligation ids `VN-QD33-2026-...` | registry, `profile.json`, compliance matrix |
| `inventory` | node risk, components with source and `file:line` evidence | `InventoryService.summary_for_agent` |
| `compliance` | counts by status and applicability, the Decision 33 rows, open items, ids cited but missing from the matrix | compliance matrix (advisory) |
| `cards` | agent card (purpose, classes, limits with `file:line`) and judge model card | matrix product, `judge/mrm/card.py` |
| `assurance` | newest result per pack for the agent, mock results counted | `eval_result` |
| `judge_mrm` | validation runs and the latest GO or NO-GO | `model_validation` |
| `masking` | masker, mask version, capture level | settings |
| `monitors` | which monitors are on, which are bound for this agent, newest oversight day | `BindingResolver`, settings |
| `risks` | register level (inherent, residual), risks by band, per risk the evidence state, the reason code and how many links are evidence and how many are references | `RiskService.agent_summary` |
| `controls` | hook for WP30; says "not built" until a collector is registered | none yet |
| `evidence` | agent lane entries and head hash, signing key kind, anchored, the offline check (`ok`, `failed`, `empty`, `not_run`) | chain tables, offline verifier |
| `cases` | open cases by severity and age | `cases` |
| `backlog` | internal only: open BACKLOG rows that name the agent or its model family | `BACKLOG.md` |
| `not_shown` | what this report does not show (below) | computed |

## What this report does not show

The last section lists every gap by a fixed code, so nothing is implied: a section with its feature switched off (with the flag name, except in the customer version), a section with no data, an agent not in the inventory, no matrix, a source that failed, a section not built (WP30), thresholds that are ILLUSTRATIVE, a mock judge or mock assurance results, a chain that was not checked, is empty, or failed its check, monitors that are switched off (count; names except in the customer version), masking switched off, a judge with no validation run, a Decision 33 obligation id that the classification cites but the matrix lacks, lists cut at 40 rows, a retired agent. It always states that the matrix is advisory, that AI judge findings are advice, and that the report holds no customer data or raw prompts.

A chain that fails the offline check is stated in all three variants (the customer version says in plain words that a check did not pass).

## Risk evidence wording

The risk section follows the register's evidence rule (ADR D26 and its review amendment): rule links, packs not scored by a judge model and the monitors `fairness`, `drift`, `multiagent` count as evidence; judge-scored packs (unless `RISK_EVIDENCE_JUDGED_PACKS=1`), other monitor links, matrix links and case links are references and never lower a score. Each risk shows the two counts. The reason code `changed_since_evidence` is shown with its label when a risk changed after its last evidence.

## Versions, hashes and the chain

* `report_version` is a whole number per agent and variant. A new version is made only when the facts changed (the content hash covers the facts, not the time, the version or the chain head, which moves with every record). `--force` makes a version with equal content.
* Files are written under `TRANSPARENCY_DIR/<agent>/<variant>/v<N>/` (`report.json`, `report.<lang>.html`, `report.<lang>.pdf`) and are never overwritten. On the Databricks App the folder is ephemeral; the rows and the chain record keep the hashes.
* Table `transparency_report` (append-only): one row per variant, language and version, with the sha256 of the JSON and of the HTML and PDF, the section hashes (for the diff to the next version), the chain check result, the chain entry hash and `generated_by` (the same ref as the chain record).
* Chain record `transparency_report` (agent lane): ids, version, `content_hash`, `json_sha256`, `html_sha256_<lang>`, `pdf_sha256_<lang>`, section counts, `diff_*` counts and the list of changed section ids (fixed words), `generated_by` (a product role such as `system:transparency` or `cli:transparency` as it is, a person as a keyed hash `act_...`; the readable person is in the `console_action` audit row only), the time. Integers, hashes and fixed codes only; no text.
* Reading: `GET /v1/transparency/<agent>` serves the latest signed file and checks it against the hash in its row; a file that was changed answers HTTP 400, a file that is gone 404. With no signed version it builds a PREVIEW from the current facts and says so (`x-report-status: preview`).

## Use

```
set TRANSPARENCY_ENABLED=1
python -m supervisor.transparency build payments --variant regulator --format html --lang vi --out out\tr
python -m supervisor.transparency generate payments        (signs; run with the app stopped)
python -m supervisor.transparency list
python -m supervisor.jobs.transparency                       (all running agents)
```

| Route | Permission | Does |
|---|---|---|
| `GET /v1/transparency` | `transparency.view` (every role) | agents with latest version per variant |
| `GET /v1/transparency/{agent}?variant=&format=json\|html\|pdf&lang=vi\|en&live=0\|1` | `transparency.view` | the report |
| `POST /v1/transparency/{agent}/generate` | `transparency.generate` (reviewer, admin) | build and sign; two audit rows |
| `/console/transparency` | needs `CONSOLE_TRANSPARENCY_ENABLED=1` too | list, drawer, generate button; Agent tab "Transparency" |

The customer version sits behind the same sign-in as every other read route; it is made to be handed on, not to be public. `transparency.view` always needs a signed-in person, whatever `API_RBAC_ENABLED` says: with no identity (and no `default_user` in the laptop users file) the answer is HTTP 400, and a service principal gets HTTP 403 (`transparency.view` is not in the read-only set of non-person callers). In laptop dev mode the users file's `default_user` signs every unsigned call in, as for every console route.

| Setting | Default | Effect |
|---|---|---|
| `TRANSPARENCY_ENABLED` | `0` | routes (HTTP 400 when off), job, CLI |
| `CONSOLE_TRANSPARENCY_ENABLED` | `0` | page and tab (needs the first flag) |
| `SCHED_TRANSPARENCY_S` | `86400` | job interval (listed only when the first flag is on) |
| `TRANSPARENCY_DIR` | `<data_dir>/transparency` | report files |
| `TRANSPARENCY_BACKLOG_FILE` | `BACKLOG.md` | read for the internal variant |

On Delta run `python -m supervisor.jobs.bootstrap_schema` first (one new table).

## Hooks (WP30)

The `controls` section is filled by `transparency/controls_adapter.py`. It looks for `supervisor.controls` without importing it; only with `CONTROLS_ENABLED` on it imports `supervisor.controls.service` and `supervisor.tasks.service` (WP30 exports the services there, not from the packages) and reads `ControlService.agent_compliance`, `obligation_coverage`, `uncovered_risks` and `TaskService.agent_summary` (shapes checked on branch `wp30-controls` at 9ba1f4f). Package absent (or no service module): "not built". Package present and `CONTROLS_ENABLED` off: "flag off", nothing imported. On: compliance in integer bp with the product-versus-bank split, controls in scope with status, obligation coverage, the count of active risks this agent reaches that no control covers (`uncovered_risks` lists the whole register; the adapter keeps the agent's own), and the task fields `stage`, `generated`, `level`, `required_open`, `required_total`, `stage_done_bp`, `overdue`, `next_stage` and `counts_<status>` (no task rows, no owners). Controls the bank owns never read "working"; when any are in scope the report says so. Owners are shown in the internal version only. After the merge of WP30 nothing but `CONTROLS_ENABLED=1` is needed. Another package can replace it with `ReportBuilder.register("controls", fn)` where `fn(ctx) -> {"available": ..., "data": {...}}` (helpers `ok` and `na`); then `allowlist.set_spec(variant, "controls", spec)` for each variant that may show it. Nothing else changes.

## PDF

The PDF uses the case-file path: optional extra `fpdf2`, a local Unicode font (`CASEFILE_PDF_FONT` or a system font), no download, no network. With either missing the PDF is not made, the HTML is, and the notice says so. The HTML page carries the case-file page's own style block (read from its template).

## Harness

`python -m supervisor.transparency.harness` (TEAM_BRIEF section 3). Golden set: 54 scenarios (36 dev on payments and customer_service, 18 held-out on credit_prequal) from (agent, variant, profile) over the manifests plus `tests/fixtures/inventory/workspace_7.json`; expected values from an independent reference (`tests/fixtures/transparency/generate.py`); 24 adversarial probes in a separate row; determinism (same facts, same content hash; same bytes under a fixed clock); baseline in `tests/fixtures/transparency/baseline.json`. Rubrics: "regulator inspector (SBV)" (class and obligation ids cited, every gap stated, hash to check) and "data protection officer" (nothing identifying reaches the customer version, planted personal data is masked, names are not copied outward). A report has no AI part, so there is no model card; thresholds are ILLUSTRATIVE.

## Limits

* The matrix is advisory; Vietnamese wording of regulator text needs legal review.
* Names are not reliably masked (BACKLOG, masker `vn_regex-3`): the allow-lists keep names out of the regulator and customer versions by omission, not by masking. The internal variant shows masked text and may still show a name.
* The customer version uses generic wording per agent class, not the agent's name, so that no id leaks; whether to name the product is an owner decision.
* Facts are those of this installation at the time of the build; there is no live Databricks check.
* No electronic signature of the file itself: the hash is in the signed chain.
