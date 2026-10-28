# Risk dimensions: the eight risk types of Circular 53 Art. 14(3) (WP-C2)

> **Not legal advice. Bank counsel must confirm.** The definitions, criteria and thresholds in `config/risk_dimensions.yaml` are placeholders (`illustrative: true`). The bank sets its own (Art. 14(4)).

Flag `RISK_DIMENSIONS=1` (default `0`; needs `GOVERNANCE_ENABLED`; the tab also needs `CONSOLE_SYSTEMS_ENABLED`; Windows cmd: `set RISK_DIMENSIONS=1`). Art. 14 of Circular 53/2026/TT-NHNN applies from **2027-01-01** (Art. 23(2)).

Art. 14(3) lists the risk types a bank manages "tối thiểu" (at least). Art. 14(4) says the bank sets, for each type, the meaning, the identification criteria, the measurement method, the acceptance threshold and the control measures. This module keeps one status row per AI system and per type, so a person can see which types are assessed, with what evidence.

## The eight types

Exactly eight fixed ids (owner decision 2, 2026-10-28). There is no ninth row. The loader refuses any other id, any other count, and a non-empty `extra_dimensions` list.

| Id | Art. 14(3) | Detail articles | Measured by (required packs) |
|---|---|---|---|
| `model` | (a) | 16(3), 16(5) | `truthfulqa_vi`, `perturbation_vi` |
| `data_governance` | (b) | 7(2), 7(3), 7(4) | `pii_canary` |
| `cybersecurity` | (c) | 6(1)(a), 6(1)(b) | `owasp_agentic_redteam`, `indirect_injection_vi`, `finance_harm_refusal`, `prefilter_evasion` |
| `legal_compliance` | (d) | 3(1), 5(1)(a), 7(1), 13(1)(c) | none (a person decides; see the Duties tab) |
| `ethics` | (đ) | 17(1), 17(2), 13(1)(b) | `fairness_metrics`, `four_fifths_rule`, `counterfactual_vi` |
| `third_party` | (e) | 18(2)(a), 18(3), 18(4)(đ) | none required (`model_dependency_inventory` is advisory) |
| `supply_chain` | (g) | 19(1), 19(2), 19(3), 19(5) | `licence_allowlist`, `pin_hash_check`, `mcp_tool_manifest_drift` |
| `reputation` | (h) banks only | none | none (bank defined) |

## Config file

`config/risk_dimensions.yaml`, strict keys (an unknown key is a `ConfigError` that names the field). Each type has:

| Key | Meaning |
|---|---|
| `label_en`, `label_vi`, `articles` | Name and the articles |
| `definition_en` | The meaning (Art. 14(4) "nội hàm") |
| `criteria` | Identification criteria |
| `measure` | What is measured |
| `threshold` | A placeholder mapping of ids to integers, booleans or short enums. No float |
| `review_days` | A pass is valid this many days (`valid_until`); `0` = no expiry |
| `controls` | Ids from `regulations/schema/controls.yaml` and assurance pack ids (a test checks they exist) |
| `measured_by` | `{kind: pack or monitor, id, required}`. Monitors: `fairness` (rows in `fairness_slice`), `oversight` (rows in `oversight_metric`) |
| `risk_categories` | Categories of the risk register shown on the row |
| `applies_to` | `any`, or `bank` (reputation) |
| `agent_slot` | The factory agent that will assess the type (WP-F4). Empty now |

## Status rows

Table `risk_dimension_status` (appended at the end of `schema/model.yaml`): `status_id`, `system_id`, `dimension_id`, `status`, `owner_team`, `assessed_by`, `report_ref`, `evidence_json`, `threshold_json`, `note`, `updated_by`, `valid_until`, plus `row_version` and `updated_at`. One row per system and type; the service creates the eight rows the first time the system is read with the flag on (a repeat changes nothing).

Statuses: `not_started`, `in_progress`, `pass`, `fail`, `waived`, `not_applicable`.

| Rule | Refusal (HTTP 400, message starts with the code) |
|---|---|
| `pass` needs at least one evidence pointer: `pack:<pack>:<run>:<agent>`, `fact:<id>`, `doc:<id>`, `monitor:`, `case:`, `report:`, `task:`, `control:`, `risk:` | `evidence_required`, `bad_evidence` |
| `waived` has its own action: a reason of 20 characters or more and a person who is not the owner of the system (`owner_user`, or a team member with role `system_owner`) | `reason_too_short`, `owner_cannot_waive`, `use_waive` |
| `not_applicable` needs a note of 20 characters or more | `reason_too_short` |
| Note at most 300 characters, URLs and long numbers masked | `note_too_long`, `bad_text` |
| Threshold: integers, booleans and short enums only | `bad_threshold` |
| An archived system cannot change | `archived` |
| Two people change a row at once | `changed` (reload) |

The flag off: every route answers `risk_dimensions_off`.

## The rule proposal

For each type with `measured_by`, the rules read the newest `eval_result` of every required pack for every agent linked to the system, and the monitor rows:

| Proposal | When |
|---|---|
| `pass` | The system has an agent, and every required item is `ok` at the **current pack version** for every agent. The pointers of those results are the evidence |
| `fail` | A required item failed (`fail` or `error`) at the current version |
| `not_started` | Anything else: no result, a result of an old pack version, a warning, no agent, or a type that nothing measures |

A proposal is only shown. A person presses **Confirm proposal**; the status and the pointers are then stored with the person as `assessed_by`. No model sets a status.

## Console: tab Risk assessment

`/console/systems/<id>?tab=riskdim`. Eight rows: status pill, owner team, assessed by, evidence pointers, threshold, valid until, the rule proposal with its checks, the risk register lines of the matching categories, and actions **Confirm proposal**, **Set status** (with evidence and a note), **Request re-assessment** (disabled until WP-F4) and **Waive**. The category links:

| Register category | Type |
|---|---|
| `money_movement`, `credit_decision`, `model_behaviour` | model |
| `pii` | data_governance, legal_compliance |
| `injection` | cybersecurity |
| `availability` | supply_chain |
| `third_party` | third_party |
| `duties_gap` | legal_compliance |

Ethics and reputation have no register category. The answer to a button is the refreshed tab (htmx) with the result in `#flash`, or a 303 for a plain form post.

## API

| Route | Permission | Does |
|---|---|---|
| `GET /v1/systems/{id}/risk-dimensions` | `systems.view` | The eight rows with definitions and proposals; creates the rows on the first read |
| `POST /v1/systems/{id}/risk-dimensions` | `systems.edit` | Body `dimension_id` and `status` (+ `evidence`, `note`, `threshold`, `valid_until`, `report_ref`), or `confirm_proposal: true` |
| `POST /v1/systems/{id}/risk-dimensions/{dim}/waive` | `systems.approve` | Body `reason` |
| `GET /v1/risk-dimensions/summary` | `systems.view` | Counts per type and status over the systems in scope (read-only; for the portfolio views) |

Console routes: `POST /console/systems/<id>/risk-dimensions/<dim>/set|confirm|waive`.

## Evidence

* **Chain record** `risk_dimension_status` on the root lane for each change: `system_id`, `dimension_id`, `from`, `to`, `actor_ref` (a hash of the person, not the id), `evidence_hash` (SHA-256 of the sorted pointers), `evidence_n`, `ts`. Strings and integers only; no float, no personal data, no typed text.
* **Audit rows**: two `console_action` rows per write. The `detail` holds `risk_dim <type> <before>><after> n=<pointers>` and, for typed text, `text_sha=<12 hex>`.
* **Control** `risk_dimension_status` in `regulations/schema/controls.yaml`, mapped from RegKB rows `VN-TT53-2026-A14.03-01` (Art. 14(3)) and `VN-TT53-2026-A14.04-01` (Art. 14(4)); both carry the verbatim `text_vi` and the date override 2027-01-01.

## Not done here

Assessment reports and assessing agents (WP-F1, WP-F4: `report_ref`, `agent_slot`, **Request re-assessment**), the nine-step workflow strip (WP-C3) and the portfolio view (WP-C4) come later. A ninth row ("customer harm / operations", Art. 13(1)(b)) is not added; it needs an owner decision.
