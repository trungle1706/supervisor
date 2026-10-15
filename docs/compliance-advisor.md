# Compliance advisor (WP14)

> **Advisory only. Not legal advice. Bank counsel must confirm.** / Khong phai tu van phap ly.
> The advisor does not decide compliance. It lists duties, shows which Supervisor controls
> support them, and asks questions about facts it cannot know.

## Purpose

The advisor takes one AI product and the regulation knowledge base (RegKB, WP13). It builds an
**obligations matrix**: one row for every obligation in RegKB. Each row says:

- does the duty apply to this product (`applies`: `yes`, `no`, `needs_answer`);
- how well the product's controls cover it (`status`);
- which controls and facts support that status (control ids and file pointers);
- which dates matter;
- which open questions block a firm answer.

Two more results come with the matrix:

- a **Decision 33 suggestion** (is the product high risk under Decision 33 and Circular 53 Art. 4);
- a **threshold check** (does the money limit stay under the Circular 53 Art. 5(1)(g)(ii) cap).

Rule of the advisor: **an unknown fact becomes a question. It never becomes a guess.** A status
that does not trace to a control id and a product fact is a defect.

## Inputs

| Input | How it gets in |
|---|---|
| Onboard profile | `profile.json` from `python -m supervisor.onboard`. The files `inventory.json`, `plan.json` and `policy.yaml` next to it are read when present. |
| Questionnaire | `product.yaml`. Use this when the code is not available or when you know more than the code shows. |
| Answers | A second `product.yaml` (`--answers`). Its values override or fill any fact. A list you give in answers counts as complete. |
| Policy files | `--policy FILE` (repeatable). The advisor reads rule ids and money limits from the gate rules. |
| Internal rules | `REGKB_INTERNAL_DIR` or `--internal DIR`. See "Internal rules". |

Create a blank questionnaire:

```
python -m supervisor.advisory.compliance --write-template product.yaml
```

Run the advisor on an onboarded product:

```
python -m supervisor.advisory.compliance --profile out\payments\profile.json --out out\payments-compliance --mock-llm
```

Run it on a questionnaire:

```
python -m supervisor.advisory.compliance --profile product.yaml --out out\product-compliance
```

It writes `compliance_matrix.json`, `compliance_matrix.md` and `compliance_matrix.html`.
The Markdown and HTML files use English and Vietnamese headings. The HTML file has no external
script, style or font.

### Questionnaire fields

All fields are optional except `product_id` and `name`. A blank field means "unknown". The
file `src\supervisor\advisory\compliance\product.schema.json` is the machine form;
`product.example.yaml` is a filled example.

| Field | Meaning | Maps to |
|---|---|---|
| `product_id` | Short stable id (required) | matrix header, row of the console tab |
| `name` | Product name (required) | matrix header |
| `version` | Product version | matrix header |
| `owner_team` | Team that owns it | matrix header |
| `purpose` | What it does, in one or two sentences | matrix header |
| `agent_classes` | `payment`, `credit_decision`, `customer_facing`, `internal_tool` | `applies_to.agent_class` of each obligation |
| `data_classes` | `personal`, `sensitive_personal`, `financial`, `biometric`, `core_data`, `important_data` | `applies_to.data_classes` |
| `autonomy` | `advisory`, `acts_with_approval`, `acts_autonomously` | `applies_to.autonomy` |
| `cross_border` | Data or model call leaves Vietnam | `applies_to.cross_border` |
| `model_hosting` | `on_prem`, `domestic_cloud`, `foreign_cloud` | `applies_to.model_hosting` |
| `roles` | `deployer`, `provider` | `applies_to.role` |
| `customer_facing` | Customers use it directly | adds or removes class `customer_facing` |
| `decisions_affecting_customers` | It makes or shapes customer decisions | question only (no rule uses it yet) |
| `customer_types` | `individual`, `organisation` | Decision 33 value lines, Art. 5(1)(g)(ii) cap |
| `executes_payments` | It creates and executes payments itself | Decision 33 entry "transactions" (condition 1) |
| `human_approval_before_execution` | A human inspects or approves each payment first | Decision 33 entry "transactions" (condition 3) |
| `credit_decisions` | It decides or records credit decisions | Decision 33 entry "credit" (condition 1) |
| `independent_credit_approval` | A credit officer approves independently | Decision 33 entry "credit" (condition 2) |
| `max_transaction_vnd` | Largest single payment, whole VND | Decision 33 condition 2, threshold check |
| `max_daily_vnd` | Largest total per customer per day, whole VND | Decision 33 condition 2, threshold check |
| `max_credit_vnd` | Largest credit amount, whole VND | Decision 33 credit condition 3 |
| `in_operation_since` | Go-live date (`YYYY-MM-DD`) | which transition date applies (deadlines) |
| `controls` | `supervised`, `catalogue`, `rules`, `policy_files`, `monitors`, `evidence` | control presence (status) |

Money values are whole VND. Floats and booleans are rejected. The file is checked before use and
all problems are listed together.

## Applicability and `needs_answer`

The advisor reuses the RegKB rule `supervisor.regkb.evaluate`. It does not make a second one.

Facts found in code are a **lower bound**. A payment tool proves class `payment`. The absence of
a credit tool does not prove "no credit". So the advisor treats such a set as **incomplete**:

| Found values vs. what the obligation wants | Result |
|---|---|
| Set is incomplete and the values overlap what the obligation wants | `yes` (positive evidence is enough) |
| Set is incomplete and the values do not overlap | `needs_answer` (the advisor asks) |
| Set is complete (questionnaire or answers) and the values do not overlap | `no` |
| The fact is `None` | `needs_answer` |

Each missing fact becomes one question (`Q-<fact>`, English and Vietnamese). The question lists
the obligations it would decide. Payments example: `Q-agent_classes` decides 76 obligations,
`Q-in_operation_since` decides 85.

The summary counts statuses for `applies = yes` rows only. Rows with `needs_answer` keep the
status they would have if the duty applies, and are counted apart.

## Status derivation

The first rule that fits wins. A present control with coverage `none` does not count as present.

| # | Condition (checked in this order) | Status | Example from the payments matrix |
|---|---|---|---|
| 1 | `applies` is `no` | `not_applicable` | None in the demo products (their sets are incomplete). With a complete questionnaire, a product with no payment class gets `no` on payment-only duties. |
| 2 | A threshold finding with verdict `exceeds` is tied to the obligation | `gap` | `VN-TT53-2026-A5.01G2-01`: PAY-03 allows 150,000,000 VND per day, cap 100,000,000. |
| 3 | The control mapping has no Supervisor control (only `process`) | `bank_process` | `INTL-ATLAS-T0056-01`: process id `security_assessment`. |
| 4 | Supervisor controls are mapped, none is present (or controls unknown) | `gap` | `INTL-ATLAS-T0070-01`: missing `groundedness` (catalogue not on). |
| 5 | A present control has coverage `full` | `met` | No payments row. RegKB maps no `full` coverage to a Supervisor control today, so `met` is 0. An internal rule can reach it (see "Internal rules"). |
| 6 | Otherwise (at least one present Supervisor control, all partial) | `partial` | `INTL-ATLAS-T0010-01`: present `agent_version`. |

`status_reason` names the control ids and the facts, for example
`present: single_limit (plan.json), PAY-02 (policies/baseline.yaml:139); missing: drift (monitor not on)`.

How the advisor finds a control in the product:

| Control kind | Present when |
|---|---|
| `catalogue` | the id is in the plan's `on_ids` |
| `rule` | the rule id is in the product's policy |
| `monitor` | the monitor name is on |
| `evidence` | the evidence id is in the product's evidence list |
| `console` | the console screen name is in the product's list |
| `process` | never checked (the bank owns it; the row says `bank_process`) |

Demo results (2026-10-15, RegKB as of that day):

| Product | Applies yes | Needs answer | Gap | Partial | Bank process | Decision 33 |
|---|---|---|---|---|---|---|
| payments | 406 | 122 | 31 | 314 | 61 | high risk |
| credit_prequal | 403 | 125 | 20 | 327 | 56 | high risk |
| customer_service | 423 | 105 | 27 | 323 | 73 | needs answer (Onboard proposes not high risk) |
| fastapi_toolserver_remit (planned) | 406 | 122 | 41 | 304 | 61 | needs answer |

The snapshot files in `tests\advisory\compliance\snapshots` hold the full rows.
`UPDATE_SNAPSHOTS=1` rewrites them after a deliberate change.

## Decision 33 and Circular 53 Art. 4

The suggestion has two entries. Each entry has **three conditions**. The entry is triggered when
all three are true.

| Entry | Condition 1 | Condition 2 (value) | Condition 3 |
|---|---|---|---|
| `transactions` (QD33 PL4.1; TT53 Art. 4(2)(a)) | The product executes payments by itself | High value (below) | No human inspection or approval before execution |
| `credit` (QD33 PL4.2; TT53 Art. 4(2)(b)) | The product decides credit by itself | No independent approval by a credit officer | Credit of 50,000,000 VND or more |

**Value lines for payments (Art. 4(2)(a)):**

| Customer type | Per transaction | Per day |
|---|---|---|
| Individual | more than 10,000,000 VND | more than 20,000,000 VND |
| Organisation | more than 50,000,000 VND | more than 100,000,000 VND |

Rules:

- Any one condition false: the entry is **not triggered**.
- All three true: the entry is **triggered**.
- Otherwise: `needs_answer`, with a question.
- Customer type unknown: a limit above the organisation line is above both lines (true). A limit
  at or below the individual line is below both (false). A limit in between needs `customer_types`.
- No value limit known: condition 2 is unknown and the advisor asks for `max_transaction_vnd`
  and `max_daily_vnd`. It does not assume "unbounded". The `fastapi_toolserver_remit` repo shows
  this: payments with no approval step in code, but no value limit, so the class is
  `needs_answer`. (The Art. 5 daily-cap check below has its own rule for a missing daily limit.)
- Not found in code is not "no". If Onboard finds no payment tool (or no credit tool), the fact
  `executes_payments` (or `credit_decisions`) stays unknown and becomes a question. So the
  `customer_service` demo agent, which Onboard proposes as not high risk, is `needs_answer` here
  until the owner answers. An approval step counts only when Onboard finds it in code, in the
  same file as the tool; a bank step outside the code must be stated in `product.yaml`.
- Classification: `high_risk` if any entry is triggered; `not_high_risk` if every entry is false;
  otherwise `needs_answer`.

Each reasoning line cites an obligation id or a fact pointer. The onboard caveat text is kept.
Both the Onboard profile and the advisor give a **suggestion**. The bank decides the class.

## Threshold check: Circular 53 Art. 5(1)(g)(ii)

The cap is per customer per day: **100,000,000 VND** for an individual, **500,000,000 VND** for an
organisation. The check runs on the obligation `VN-TT53-2026-A5.01G2-01` when the product
executes payments (or may). Every daily limit and every per-transaction limit gets a verdict:

| Verdict | Meaning |
|---|---|
| `exceeds` | limit above the cap |
| `at_cap` | limit equal to the cap (one transfer may use the whole day) |
| `within` | limit below the cap |
| `needs_answer` | the customer type or the limit is unknown |

Only rules with action `block` or `pause` count as limits (a `log` or `alert` rule limits
nothing); a rule with `ge N` allows at most N - 1. The **effective** finding uses the smallest
daily per-customer limit. If there is no daily limit
and the controls are known, the verdict is `exceeds` with the reason "the day total is unbounded".

**Payments result** (policy `policies\baseline.yaml`, customer type individual):

| Limit | Value (VND) | Cap (VND) | Verdict |
|---|---|---|---|
| PAY-03 (daily per customer) | 150,000,000 | 100,000,000 | exceeds |
| manifest `daily_transfer_max_minor` (daily) | 300,000,000 | 100,000,000 | exceeds |
| PAY-02 (per transfer) | 100,000,000 | 100,000,000 | at cap |
| manifest `transfer_max_minor` (per transfer) | 100,000,000 | 100,000,000 | at cap |
| Effective daily ceiling (PAY-03) | 150,000,000 | 100,000,000 | exceeds |

So the row `VN-TT53-2026-A5.01G2-01` is `gap`. The summary shows 1 threshold gap (the effective
finding). `threshold_exceeds` is 3: the two daily limits above the cap (PAY-03 and the manifest
daily limit) plus the effective finding.

**The advisor does not change the baseline policy.** The owner of the payments agent decides:
lower PAY-03 to 100,000,000 or less, or show why a higher limit is allowed (for example only
organisation customers). The advisor only shows the numbers.

## Deadlines

Dates come from the RegKB data. The advisor shows them and invents none. For each row:

| Item | Source in the data |
|---|---|
| Effective | `dates.effective` of the instrument (obligation can override) |
| Compliance deadline | `dates.compliance_deadline` |
| Transitions | `dates.milestones` |
| Article effective | a milestone whose label starts with the article of the row (for example "Art. 14" for `Art. 14(2)`) |

Dates that matter in the data today:

| Instrument | Date | Rule |
|---|---|---|
| Circular 53/2026 | 2026-11-15 | Art. 23(1): effective; Art. 14 on 2027-01-01; Art. 6(1)(b) and Art. 21 on 2027-09-01 |
| Circular 53/2026 | 2027-03-01 | Art. 24: systems in official operation before 2026-11-15 comply with Chapters II-IV |
| AI Law | 2027-03-01 | Art. 35(1)(b): 12 months for systems running before 2026-03-01 (other sectors) |
| AI Law | 2027-09-01 | Art. 35(1)(a): 18 months for health, education and finance |

Whether banking counts as "finance" under AI Law Art. 35 is not settled. The data uses the
earlier date for planning (tag `ASSUMED`). Which transition date applies depends on the date the
product went live. If `in_operation_since` is blank, the question `Q-in_operation_since` is
raised on every Circular 53 and AI Law row (85 rows for payments).

## Internal rules

A bank can add its own rules. Put YAML files in a folder and set:

```
set REGKB_INTERNAL_DIR=C:\supervisor\internal-rules
```

or pass `--internal DIR` to the CLI (`--internal ""` turns it off). The format is in
`regulations\internal\README.md`. A copy of `regulations\internal\example-ai-use-policy.yaml.example`
renamed to `.yaml` is a working sample.

Effect on the matrix (payments with the sample):

- New rows with ids `INT-<instrument>-...` appear, 3 rows for the sample (528 to 531 rows).
- The header shows `internal_rules: true` and the instrument ids.
- Internal rows follow the same applicability and status rules. The sample gives two `partial`
  rows and one `met` row (`pii_masking` is mapped with coverage `full`), so the summary changes
  from `partial 314` to `316` and shows the first `met`.
- RegKB rows are unchanged. With the folder off, the matrix is the same as before.
- Internal text is untrusted: the HTML report escapes it.

## Launch pack (Onboard)

Setting `ONBOARD_COMPLIANCE_ENABLED` (default `0`):

```
set ONBOARD_COMPLIANCE_ENABLED=1
python -m supervisor.onboard --target src\supervisor_agents\payments --out out\payments --mock-llm
```

After the Instrument stage the run builds the product from the inventory, profile, plan and the
generated `policy.yaml` (basis `planned`: the controls exist after the pull request merges). It
writes `compliance_matrix.json`, `.md` and `.html` next to the other artefacts and prints
`[OK] compliance: ...` with counts. The narrative is marked `mock` when the model is the mock.
With the setting off, the run writes the same 14 files as before. The three compliance files are
named in `COMPLIANCE_ARTEFACTS`, not in `ARTEFACTS`.

## Console tab

Setting `CONSOLE_COMPLIANCE_ENABLED` (default `0`). When it is on, the nav shows **Compliance**:

| Page | Content |
|---|---|
| `/console/compliance` | One card per agent: counts by status, Decision 33 class, open questions, threshold gaps |
| `/console/compliance/<agent>` | Counts, Decision 33 lines, threshold findings, open questions, rows with filters `status`, `applies`, `instrument`, `duty` (query parameters) |
| `/console/compliance/<agent>/obligation/<id>` | Vietnamese text, English summary, article, sources, mapped controls, the status of this product |

The pages are read-only (GET only). Permission: `compliance.view`, held by every role. Every page
shows "Advisory only" and the disclaimer. The three demo agents are built in memory. A product
onboarded with the launch pack shows when `<DATA_DIR>\onboard\<agent>\compliance_matrix.json`
exists. A narrative stored in that file is not shown. When the setting is off, each compliance URL
answers HTTP 400 with a short note on how to turn the tab on (the Onboard Start and Integration
pattern; the nav link is hidden). An unknown agent, obligation or filter
value answers 400.

## Assurance packs as evidence (WP17)

Each row lists `assurance_packs`: the assurance eval packs whose `maps_to.regkb_duties`
(in `src\supervisor\assurance\packs\*.yaml`) meet the row's duties. The md and html files show
them in the evidence column as `eval_result pack <id> (test evidence, not read)`. This tells an
auditor where test evidence lives (table `eval_result`). The advisor does not read the results,
so a pack never changes a status. Future work: read the latest `eval_result` per agent and pack,
and show pass, warn or fail next to the pack id.

## Incident clock and judge MRM as evidence (WP19)

Each row also lists `evidence_hints`, chosen by duty id:

| Duty | Hint |
|---|---|
| incident_report, incident_report_24h, incident_report_72h, incident_response | case incident clock fields (Decree 142/2026 Art. 19: preliminary report in 72 h if urgent, else 5 working days; formal report 15 days later) |
| independent_validation | table `model_validation`, `python -m supervisor.judge.mrm validate` |
| change_control | `python -m supervisor.judge.mrm triggers` |
| technical_documentation | `python -m supervisor.judge.mrm card` |

The MRM hints cover **Supervisor's own judge model only**, not the product's model. Hints never
change a status: the RegKB control vocabulary does not name these sources yet. When it does, they
can become real controls.

## AI risk register (enterprise-readiness row A-6.1)

`docs\enterprise-readiness.md` row A-6.1 ("Planning: AI risk assessment") says Onboard gives
only a proposal per agent and lists "no risk register, no likelihood/impact scale, no review
date". The matrix is **the input** for the bank's register. It is not the register.

| Register need | Where the matrix helps |
|---|---|
| List of risks and duties per AI system | One row per obligation with `applies`, article and duties |
| Current control state | `status`, `status_reason` and control ids with pointers |
| Gaps to treat | Rows with `gap`, threshold findings, open questions |
| Risk class | Decision 33 suggestion with reasoning lines |
| Review date | `as_of`, `generated_at`, RegKB `version`. Run again on a change or when RegKB changes. |
| Likelihood and impact | Not in the matrix. The bank adds them with its own method. |

The bank copies the rows it accepts into its risk register, adds the scale and the owner, and
keeps the matrix JSON as the evidence of the state on that date.

## Limits: what the advisor cannot know

- **The legal reading.** RegKB is a structured reading of public texts. Counsel decides scope
  and meaning (for example, whether banking is "finance" in AI Law Art. 35).
- **Deployment switches.** The plan says which monitors the Onboard PR turns on. It does not say
  whether the bank turned them on, or in which mode (shadow or enforce). Basis `planned` vs
  `deployed` is shown in the controls.
- **Process evidence.** Policies, committees, training and contracts (`bank_process` rows) are
  outside the advisor.
- **Code it cannot read.** Private repos, binaries, runtime config, and anything the scrubber
  removed. Code facts are a lower bound.
- **Data classes it cannot see.** It never adds `sensitive_personal`, `biometric`, `core_data` or
  `important_data` from code. Those are legal classes.
- **Customer base.** Customer types, cross-border flow, model hosting, go-live date and approval
  steps outside the code come from the questionnaire only.
- **Limits outside the policy.** Limits set in a core banking system or a payment hub are not
  visible unless you enter them.
- **Control quality.** "Present" means "configured", not "effective". Coverage values come from
  RegKB and are honest but coarse (`partial` for almost every Supervisor control).
- **The narrative.** The short narrative never changes a row. With the mock model it is a
  template, labelled `mock`.

## Disclaimer

Not legal advice. Bank counsel must confirm. / Khong phai tu van phap ly.
This document, the matrix, the Decision 33 suggestion and the threshold check are working aids.
They do not certify compliance and do not replace the bank's legal, risk and compliance functions.
