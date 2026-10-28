# Duty evidence and the regulator pack (WP-L4)

> **Not legal advice. Bank counsel must confirm.** Evidence counts show that a Supervisor control produced rows. They do not show that a duty is met in law.

Flag `REGULATOR_PACK=1` (default `0`; needs `GOVERNANCE_ENABLED` and `RISK_DUTIES`, so also `CONSOLE_SYSTEMS_ENABLED`; Windows cmd: `set REGULATOR_PACK=1`). It builds on the `obligation_status` rows of the Duties step (WP-L2) and the Duties tab (WP-L3, `docs/risk-register.md` "Duties (WP-L3)"). No new table.

| Variable | Default | Meaning |
|---|---|---|
| `REGULATOR_PACK` | `0` | Evidence marks on the Duties tab, auto-close, group task closing, Refresh button, the pack |
| `DUTY_EVIDENCE_WINDOW_DAYS` | `30` | Window of the counts (1 to 365). It ends at the last full hour |
| `DUTY_EVIDENCE_MIN_ROWS` | `1` | Rows a control needs in the window to count as working |
| `DUTY_EVIDENCE_SWEEP_S` | `0` | Scheduler sweep over every system; `0` = off, else 300 or more |

## Evidence per control

A duty maps to Supervisor controls in the `control_mapping` of its RegKB obligation. The controls of a duty are the entries of kind catalogue, rule, monitor, evidence and console whose coverage is not `none`. A bank process (kind `process`) is never a Supervisor control. For one system, the counts are read for its supervised agents (gate state RUNNING, PAUSED or QUARANTINED; a SHADOW, RETIRED or unknown agent is not evidence, the same rule as the risk register). The numbers are integers.

| Counter | Used for | Rows counted in the window |
|---|---|---|
| `rule` | kind rule (for example `PII-02`) | Tier-0 verdict hits that the gate enforced (`risk.evidence.Collector.rule_hits`: not a shadow, mock, error or fail-mode row) |
| `gate` | `approved_tools`, `pii_masking`, `single_limit`, `daily_aggregate`, `split_payment`, `pii_bulk_read`, `prior_read`, `amount_valid`, `system_of_record` | Gate decisions (`agent_event`, `gate_decision`) |
| `findings` | `injection_prefilter` | Detector findings that ran (`finding`) |
| `verdicts` | `verdict_log` | Non-mock `verdict` rows |
| `judge` | `groundedness`, `tier1_monitor`, `tier2_judge` | Non-mock tier 1 and 2 verdicts. **Advisory**: shown, never working (rule R1: a judge never changes a control decision) |
| chain | `evidence_chain` (agent lanes), `chain_verify_report` and `audit_pack` (root lane), `anchor` | `chain_entry` rows, `anchor` rows |
| `packs` | `launch_report` | Non-mock `eval_result` rows on the agent or its traces |
| monitor | monitors `drift`, `fairness`, `multiagent`, `oversight`; `drift_band`, `fairness_slices`, `oversight_metric` | Daily `oversight_metric` rows; for drift, fairness and multiagent only rows whose monitor status is `ok` |
| others | `case_file`, `case_files`, `signoff_record`, `coverage_rows`, `agent_version`, `policy_baseline`, `fairness_slice`, `agent_event_log`, `otlp_ingest`, `proxy_log`, `agent_registry` | The table named in the pack pointer |

A control **works** when it has at least `DUTY_EVIDENCE_MIN_ROWS` rows and is not advisory. A control without a counter is **unmeasured** and never works: console screens (`cases`, `agents`, `case_signoff`, ...), onboarding artefacts (`onboard_plan`, `onboard_profile`, `handover`) and the `quality` and `sweeps` monitors (an advisory LLM scorer, and a job that writes no status). A system with no supervised agent has no evidence at all.

## Rules (hub notes after WP-L3)

| Rule | What happens |
|---|---|
| (a) Close by evidence | An open row with `applies = yes` and coverage `full` that has mapped Supervisor controls, all working, becomes `closed`. `closing_control` is the control ids joined by `,`. The note is the banner and `closed by evidence <window> <id=count,...>` (the earlier note follows after ` \| before: `). One chain record `duty_evidence_close` (system id, window, count, obligation ids). Rows with coverage partial, none or unknown, waived rows and closed rows are never touched; a repeat closes nothing. A closed row is not reopened when its evidence later stops |
| (b) Group task | When the last open applying row of a WP-L2 gap group (instrument x coverage partial or none) is closed by a person (Close button, one row or the group), the task `DUTY-<instrument id>-<coverage>` is marked done through the task service with actor `system:duty_evidence`. Its evidence reference becomes the banner and "all duties of the group closed". A group that has no closed row (all waived) keeps its task. Needs `REGULATOR_PACK`; with the flag off nothing changes |
| (c) Where the text is | The close evidence and the waive reason are in `note` after the banner; the control is in `closing_control`. The Duties tab shows them this way (and says "closed by evidence" for rule (a)); the pack stores only a hash of the note |

## Sweep and button

* `python -m supervisor.jobs.duty_evidence_sweep` and the scheduler job `duty_evidence_sweep` (every `DUTY_EVIDENCE_SWEEP_S` seconds) run rule (a) for every system that is not archived and has an open `full` row. For each system where rows closed, one `console_action` row is written with actor `system`, actor kind `system`, path `/jobs/duty_evidence_sweep`, and the row hash before and after. The standalone command writes to the evidence chain: run it with the app stopped, or let the app's scheduler run it.
* **Refresh evidence** on the Duties tab: `POST /console/systems/<id>/duties/refresh-evidence`, permission `systems.edit`, two `console_action` rows (`attempted`, then `ok` with `duty_evidence_refresh checked=N closed=M`). The answer is the refreshed tab. With the flag off: HTTP 400 `regulator_pack_off`.
* The Duties tab shows for each row the rows per control (integers) and a mark: works, no evidence, or "no Supervisor control" for a duty that only a bank process covers.

## Regulator pack

One pack per system, as signed JSON and as HTML. Offline (no script, no link, no font download), no personal data, no floats.

| Part | Content |
|---|---|
| Header | System name and id, Decision 33 class, risk level, lifecycle stage, autonomy level, owner roles by role name and head count (no person id), generated at, RegKB version hash, pack version, the evidence window and threshold |
| One section per instrument | For each duty: article, obligation id, duty, the verbatim `text_vi` quote from RegKB, applies, coverage, status, closing control, how it ended (evidence, person, waived), a hash of the typed note, due date, works mark, the evidence table (control, kind, coverage, rows in window, source table, state), pointers (the `status_id`, the gap task id, source tables), confirmed by and date |
| Confirmed by | A duty that came from a law-agent draft (RegKB `confirmed_by`, or a confirmed `regkb_draft` with the same quote) names the confirmer as a keyed reference (`act_...`, never the id) and the confirmation date. Any other duty: `RegKB data 2026-10-15` |
| Summary | Counts by status, by coverage, by applies, coverage x status, gap closure score (integer percent, `null` when no applying row is open or closed), rows closed by evidence, controls working / no evidence / no Supervisor control |
| Banner | "Not legal advice. Bank counsel must confirm." in the JSON, at the top (fixed, so it prints on every page) and at the end of the HTML |

Routes (permission `systems.view`, so the auditor role too; a system outside the caller's scope answers 404; flag off answers 400 `regulator_pack_off`):

* `GET /v1/systems/<id>/regulator-pack.json` (a download)
* `GET /v1/systems/<id>/regulator-pack.html`
* CLI: `python -m supervisor.governance.regulator_pack --system <id> --out <dir>` writes `regulator-pack.json`, `regulator-pack.html` and `public_key.pem` (`[SKIP]` while the flag is off).

Buttons **Regulator pack** are on the Duties tab (HTML and JSON) and in the header of the system page.

### Signature and offline check

The JSON has `content_sha256` (SHA-256 of the canonical JSON without `content_sha256` and `signature`) and a `signature` block: Ed25519 by the evidence signer over `supervisor-regulator-pack/v1 ` plus the hash, with `key_id`, `key_kind` and the public key. Each pack also writes a chain record `regulator_pack` (system id, hash, row count, RegKB version, key id; no text), so the hash is committed by the signed roots.

```
python -m supervisor.evidence.verify regulator-pack.json
python -m supervisor.evidence.verify regulator-pack.json --pubkey notary_public_key.pem
```

The first form trusts the key inside the file (it proves the file was not changed after signing); the second pins the notary key and is the check an auditor should use. Exit code 0 = OK, 1 = a check failed, 2 = not readable. A directory is still verified as an evidence export (`docs/assurance.md`, audit pack), unchanged. The verifier imports only the standard library and `cryptography`.

## Limits

* Counts show that a control produced rows, not that it is configured well. A quiet period gives 0 and the duty stays open.
* Console screens and onboarding artefacts are not measured, so a `full` duty that maps to one of them is never closed by evidence.
* The pack is a snapshot: `generated_at` and the window are in the header; sign again for a later state.
