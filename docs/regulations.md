# Regulation knowledge base (RegKB, WP13)

> **Not legal advice. Bank counsel must confirm.** The data below is a structured reading of
> public texts made by engineers and AI research agents on 2026-10-15. It helps a bank find the
> duties that may apply to an AI product and the Supervisor controls that support them. It does
> not decide what the law requires. Every CLI output repeats this line.

## What it is

| Part | Path |
|---|---|
| Schema (JSON Schema 2020-12) | `regulations/schema/obligation.schema.json` |
| Duty vocabulary | `regulations/schema/duties.yaml` |
| Control vocabulary (monitor, console, evidence, process ids) | `regulations/schema/controls.yaml` |
| Vietnamese instruments (one file each) | `regulations/vn/*.yaml` |
| Regulator map: every regulator, every instrument that binds or guides a bank AI system, stored or missing (WP-W0) | `regulations/REGULATOR_MAP.md` |
| International reference frameworks (`binding: false`) | `regulations/intl/*.yaml` |
| Official texts as fetched, with sha256 sidecars | `regulations/sources/<instrument_id>/` |
| Bank internal rules (off by default) | folder named by `REGKB_INTERNAL_DIR`; guide in `regulations/internal/README.md` |
| Loader, validator, applicability, version hash, CLI | `src/supervisor/regkb/` |
| Dev-host fetcher (never imported by the app) | `tools/regkb_fetch.py` |
| Dev-host OCR of a signed scan (tesseract `-l vie` through `subprocess`; never imported by the app) | `tools/regkb_ocr.py` |
| OCR text of the signed Circular 53 PDF, with sidecar (WP-L5) | `regulations/sources/VN-TT53-2026/53-2026-tt-nhnn-signed.ocr.txt` and `.ocr.meta.json` |

Each obligation has an id (`VN-QD33-2026-PL4.1-01`), an article reference, a verbatim Vietnamese
quote when the official text was read (`text_vi`), an English summary, duty ids, an `applies_to`
predicate over a product profile, a mapping to Supervisor controls with honest coverage
(`full` / `partial` / `none`), the evidence an auditor would ask for, sources (URL + fetch date),
and a verification tag:

| Tag | Meaning |
|---|---|
| `VERIFIED_PRIMARY` | The official text of that article was read. For Vietnamese texts the quote is in `text_vi`, and a test checks it against the stored text. |
| `VERIFIED_SECONDARY` | Only a law-firm, press or reproduction source was read. |
| `ASSUMED` | Judgement; the reason is in `notes`. |

Status values: `in_force`, `issued` (signed, not yet effective), `draft`, `superseded`,
`repealed`, `reference` (international frameworks). A draft is never `in_force`; the loader refuses it.

## Coverage (2026-10-28)

`python -m supervisor.regkb coverage` prints this table from the data. P/S/A = obligations
tagged VERIFIED_PRIMARY / VERIFIED_SECONDARY / ASSUMED. The first 18 Vietnamese rows were read on
2026-10-15 and checked again on 2026-10-28 (WP-W0); the last 8 were added on 2026-10-28.
`regulations/REGULATOR_MAP.md` lists every regulator and every instrument, stored or missing, with the
articles that are not yet rows.

### Vietnam (binding)

| Instrument | Number | Status | Effective | Obligations | P/S/A | Primary text stored |
|---|---|---|---|---|---|---|
| Law on Artificial Intelligence | 134/2025/QH15 | in_force | 2026-03-01 | 32 | 32/0/0 | yes |
| Decree guiding the AI Law | 142/2026/NĐ-CP | in_force | 2026-05-01 | 26 | 26/0/0 | yes |
| High-risk AI system list | 33/2026/QĐ-TTg | in_force | 2026-08-15 | 12 | 12/0/0 | yes |
| SBV circular on AI in banking | 53/2026/TT-NHNN | **issued** | 2026-11-15 (staged to 2027-09-01) | 53 | 53/0/0 | yes (vbpl text, plus OCR of the signed scan) |
| Personal Data Protection Law | 91/2025/QH15 | in_force | 2026-01-01 | 35 | 35/0/0 | yes |
| Decree guiding the PDPL | 356/2025/NĐ-CP | in_force | 2026-01-01 | 29 | 29/0/0 | yes |
| Law on Data | 60/2024/QH15 | in_force | 2025-07-01 | 17 | 17/0/0 | yes |
| Decree guiding the Data Law | 165/2025/NĐ-CP | in_force | 2025-07-01 | 19 | 19/0/0 | yes |
| Law on Cybersecurity | 116/2025/QH15 | in_force | 2026-07-01 | 26 | 26/0/0 | yes (+ Decrees 331/2026, 333/2026) |
| Decree 53/2022 (2018 Cybersecurity Law) | 53/2022/NĐ-CP | superseded (status ASSUMED) | 2022-10-01 | 9 | 9/0/0 | yes |
| Law on Credit Institutions | 32/2024/QH15 | in_force (amended by 96/2025/QH15) | 2024-07-01 | 16 | 16/0/0 | yes |
| Customer information confidentiality | 117/2018/NĐ-CP | in_force | 2018-11-01 | 7 | 7/0/0 | yes |
| IS security in banking | 09/2020/TT-NHNN | in_force (Art. 25 repealed) | 2021-01-01 | 24 | 24/0/0 | yes |
| Online banking safety | 50/2024/TT-NHNN | in_force (amended by 77/2025/TT-NHNN) | 2025-01-01 | 25 | 25/0/0 | yes |
| Online payment safety (biometrics) | 2345/QĐ-NHNN | superseded in substance by 50/2024 (secondary) | 2024-07-01 | 5 | 0/5/0 | no (reproduction only) |
| E-Transactions Law | 20/2023/QH15 | in_force | 2024-07-01 | 19 | 19/0/0 | yes |
| E-signatures and trust services | 23/2025/NĐ-CP | in_force | 2025-04-10 | 10 | 10/0/0 | yes |
| Consumer Rights Protection Law (+ Decree 55/2024) | 19/2023/QH15 | in_force | 2024-07-01 | 28 | 28/0/0 | yes |
| SBV internal control and risk management, incl. model risk (WP-W0) | 83/2025/TT-NHNN | in_force | 2026-07-01 (model risk by 2028-01-01) | 22 | 22/0/0 | yes |
| SBV credit information, CIC (WP-W0) | 15/2023/TT-NHNN (+46/2026) | in_force | 2024-01-01 (46/2026: 2026-11-01) | 8 | 8/0/0 | yes (+ Circular 46/2026) |
| SBV non-cash payment services (WP-W0) | 15/2024/TT-NHNN (+30/2025, 21/2026) | in_force | 2024-07-01 | 11 | 11/0/0 | yes (+ 30/2025, 21/2026) |
| Anti-Money Laundering Law (WP-W0) | 14/2022/QH15 | in_force | 2023-03-01 | 10 | 10/0/0 | yes |
| Law amending the SBV, AML and Credit Institutions laws (WP-W0) | 23/2026/QH16 | **issued** | 2026-12-01 | 3 | 3/0/0 | yes |
| Penalties: cybersecurity and personal data, incl. AI (Art. 67) (WP-W0) | 330/2026/NĐ-CP | in_force | 2026-08-19 | 12 | 12/0/0 | yes |
| Non-cash payments decree (WP-W0) | 52/2024/NĐ-CP | in_force | 2024-07-01 | 6 | 6/0/0 | yes |
| E-identification and authentication (WP-W0) | 69/2024/NĐ-CP (+320/2026) | in_force | 2024-07-01 (320/2026: 2026-09-28) | 4 | 4/0/0 | yes (+ Decree 320/2026) |

### International reference frameworks (`binding: false`)

| Framework | Status | Obligations | P/S/A | Text stored |
|---|---|---|---|---|
| EU AI Act 2024/1689 (+ omnibus 2026/1744) | reference | 19 | 19/0/0 | yes (OJ text) |
| NIST AI RMF 1.0 | reference | 15 | 15/0/0 | no |
| NIST AI 600-1 GenAI profile | reference | 11 | 11/0/0 | no |
| ISO/IEC 42001:2023 | reference | 10 | 0/1/9 | no (paywalled) |
| ISO/IEC 23894:2023 | reference | 6 | 0/3/3 | no (paywalled) |
| MAS FEAT principles | reference | 9 | 9/0/0 | no |
| MAS AI Risk Management Guidelines (final 2026-10-07, effective 2027-10-07) | reference | 15 | 15/0/0 | no |
| HKMA GenAI consumer protection (2024) | reference | 7 | 7/0/0 | no |
| Fed SR 11-7 (replaced by SR 26-2 on 2026-04-17) | superseded | 8 | 0/0/8 | SR 26-2 attachment |
| OWASP Top 10 for LLM Applications 2025 | reference | 10 | 10/0/0 | no (CC BY-SA: URL only) |
| OWASP Top 10 for Agentic Applications 2026 | reference | 10 | 10/0/0 | no |
| MITRE ATLAS 2026.09 | reference | 11 | 11/0/0 | no |
| OECD AI Principles (2019, updated 2024) | reference | 5 | 1/4/0 | no |

Total: 39 instruments (26 Vietnamese, 13 international), 618 obligations. Control coverage by Supervisor controls
(bank process steps do not count; `python -m supervisor.regkb coverage --levels` prints it per instrument): 1 obligation
has a `full` control, 507 have only `partial` controls, 96 rely only on a bank process or have no control. Before WP-W0 these
were 1 / 435 / 92 (528 obligations); WP-W0 added 76 obligations, 72 partial and 4 with no Supervisor control. Supervisor produces
evidence; it does not make a product compliant. Detail for Decree 142 and Circular 53: "Coverage raise (WP-L5)" below.

### Coverage of the instruments added by WP-W0

Same rules as WP-L5 for the notes (`Missing: ...`, `Manual step: ...`, `No Supervisor control: ...`); the tests of
WP-L5 still check only Decree 142 and Circular 53. The level is the best coverage of the entries of an obligation.

| Instrument | Obligations | Supervisor f / p / n | With process f / p / n | Rows with `No Supervisor control` |
|---|---|---|---|---|
| VN-TT83-2025 (internal control, model risk) | 22 | 0 / 21 / 1 | 0 / 22 / 0 | 1 |
| VN-TT15-2023 (credit information) | 8 | 0 / 7 / 1 | 0 / 8 / 0 | 1 |
| VN-TT15-2024 (non-cash payment services) | 11 | 0 / 9 / 2 | 0 / 11 / 0 | 2 |
| VN-AML-2022 (AML Law) | 10 | 0 / 10 / 0 | 0 / 10 / 0 | 0 |
| VN-LAW23-2026 (amends the AML Law) | 3 | 0 / 3 / 0 | 0 / 3 / 0 | 0 |
| VN-DEC330-2026 (penalties) | 12 | 0 / 12 / 0 | 0 / 12 / 0 | 0 |
| VN-DEC52-2024 (non-cash payments) | 6 | 0 / 6 / 0 | 0 / 6 / 0 | 0 |
| VN-DEC69-2024 (e-identification) | 4 | 0 / 4 / 0 | 0 / 4 / 0 | 0 |

No row is `full`: a gateway rule, the evidence chain or the pause switch supports the duty, but a bank step (policy, record, report, contract) is always needed. New duty id: `pd_compliance_assessment` (yearly personal data compliance assessment; Decree 330/2026 Art. 64(1) and 67(1); no existing tag fitted).

### Facts that changed during the research (read before you use older notes)

- The SBV AI circular is **signed**: Circular 53/2026/TT-NHNN of 2026-09-30, effective
  2026-11-15. Art. 14 applies from 2027-01-01, Art. 6(1)(b) and Art. 21 from 2027-09-01. Systems
  in operation before 2026-11-15 must meet Chapters II-IV from 2027-03-01 (Art. 24). The
  consultation draft's "24-hour incident report" is **not** in the signed text; incident reports
  follow Decree 142/2026 Art. 19 (preliminary report within 72 h if urgent, else 5 working days).
- Circular 53 Art. 4(2) sets the "high value" lines that Decision 33 leaves to the SBV
  (individual: > 10 million VND per transaction or > 20 million per day; organisation: > 50
  million / > 100 million; credit: >= 50 million). Art. 5(1)(g) caps AI-autonomous payments
  at 100 million VND per day per individual customer. The demo policy limits (PAY-02 100
  million per transfer, PAY-03 150 million per day) are above that cap: the bank sets real limits.
- Decision 33/2026/QĐ-TTg banking entries are cumulative tests. A Supervisor pause is a safety
  control after the agent acts; it is not human approval before execution
  (see `docs/onboard.md`, "Decision 33").
- Decree 356/2025 makes bank credentials, card data, transaction history and credit information
  **sensitive** personal data, and requires breach notice to the authority and the data subject
  within 72 h in banking. A judge model hosted outside Vietnam is a cross-border transfer
  (PDPL Art. 20(1)(c)).
- Cybersecurity Law 116/2025 replaced the 2018 and 2015 laws on 2026-07-01; Decree 333/2026
  (local storage, 24-month minimum after a storage request; 12-month system logs) and Decree
  331/2026 (system security levels; 24 h initial notice of serious incidents) guide it.

- Circular 83/2025/TT-NHNN (internal control, in force 2026-07-01) replaces Circular 13/2018 and 40/2018 and adds
  **model risk management** (Art. 56-58: model list rated high, medium or low, validation before use, after a material
  change and yearly, override control, model file, three lines, yearly report). It does not name AI; "model" is
  defined in Art. 3(23) as any quantitative method or system that turns inputs into outputs. Duties from 2028-01-01 at the latest.
- Decree 330/2026/NĐ-CP (penalties, in force 2026-08-19) is the first text that puts a fine on AI-specific personal data
  duties: Art. 67 (notice and explanation of the algorithm, opt-out of automated processing, risk classes, human
  re-assessment, yearly assessment), Art. 64 (banking and credit scoring without consent), Art. 70 (biometric data), Art. 56
  (cross-border transfer, up to 5 percent of revenue). Suspension of an AI system for 3 to 6 months is an added penalty.
- Circular 30/2025/TT-NHNN (in force 2025-11-18) added to Circular 15/2024: a payment service outage over 30 minutes is
  reported to SBV within **4 hours**; availability limits of 4 hours a year; identity matching against police-issued data or
  the e-identification account. The incident clock of Supervisor (Decree 142: 72 h or 5 working days) has no 4-hour clock.
- Law 23/2026/QH16 (signed 2026-08-24, effective 2026-12-01) changes the AML Law: risk assessment of products that use new
  technology must be carried out in full, identification applies when a transaction is suspected even if not completed, and
  suspicious reports rest on the bank own analysis and signs.
- Decree 320/2026/NĐ-CP (in force 2026-09-28) requires bank electronic transaction accounts to be linked to electronic
  identity accounts (Decree 69/2024 Art. 40(9)).
- Decree 13/2023/NĐ-CP is repealed by Decree 356/2025 (Art. 40(2) of that Decree). Chapter IV (AI) of the Digital Technology
  Industry Law 71/2025/QH15 is repealed by the AI Law Art. 33, so it is not stored.
- Texts checked again on 2026-10-28 (WP-W0): 16 vbpl.vn texts are unchanged; Decree 142/2026 and Decision 33/2026 come from
  the Official Gazette PDFs and were not re-fetched (see the re-check log in the regulator map).

## Regulator map (WP-W0)

`regulations/REGULATOR_MAP.md` has one table per group: the 26 stored Vietnamese instruments, the 13 international references, and
17 rows of missing, open or checked-and-closed instruments (M-01 to M-17). Each row has regulator, status, issued and effective
dates, scope for a bank AI system, stored (`yes` or `yaml-only`), verified tag, obligation count, and the gap or action. The gap
column lists the articles of the stored text that are not rows yet. A test (`tests/regkb/test_regulator_map.py`) keeps the map and
the files in step: every instrument file is listed, a row marked `yes` has a sources folder with sidecars, and the counts match.
When you add an instrument, add its row to the map (the test fails until you do).

Where the map stands on 2026-10-28:

| Regulator | Stored | Missing or open |
|---|---|---|
| National Assembly | AI Law, PDPL, Data Law, Cybersecurity Law, E-Transactions Law, Consumer Law, Credit Institutions Law, AML Law, Law 23/2026 | Laws 96/2025, 142/2025, 43/2024 (amend the credit law); Law on Identification 26/2023 |
| Government | Decrees 142, 356, 165, 330, 117, 23, 52, 69, 53 (superseded) | Decree 85/2016 (security levels); AML guiding decree; banking penalty decree |
| Prime Minister | Decision 33/2026 | none found |
| SBV | Circulars 53/2026, 09/2020, 50/2024, 83/2025, 15/2023, 15/2024; Decision 2345 (reproduction) | payment intermediary (40/2024), bank card, e-KYC, outsourcing, AML circular |
| MST (with former MIC functions) | none own | no AI circular or decree found besides Decree 142 and Decision 33 |
| MPS | none own (authority under PDPL and Cybersecurity Law) | biometric technical regulations 169/2026 and 170/2026 (effective 2027-04-15); Decree 70/2024 |
| MOF | none | none found that binds a bank AI system |

## Use it (Windows cmd)

```
python -m supervisor.regkb validate
python -m supervisor.regkb coverage
python -m supervisor.regkb list --jurisdiction VN
python -m supervisor.regkb list --instrument VN-TT53-2026
python -m supervisor.regkb show VN-QD33-2026-PL4.1-01
python -m supervisor.regkb export C:\temp\regkb-2026-10-15.json
python -m supervisor.regkb diff C:\temp\regkb-2026-10-15.json regulations
```

`validate` checks every file against the schema and the RegKB rules (sources present, duties
known, controls resolve, drafts never in force, quotes need a primary source) and prints
`[OK] <n> instruments, <m> obligations, version <hash>`. The version hash is a SHA-256 over the
canonical JSON of all instruments and obligations; it changes when any content changes and
does not depend on file names, order or YAML style. `diff` compares two roots or exports and
lists added, removed and changed obligation ids with the changed fields.

## Add an internal rule

1. Copy `regulations\internal\example-ai-use-policy.yaml.example` to a folder outside the
   repository, for example `C:\bank\regkb-internal\ai-use-policy.yaml`.
2. Set the instrument id to `INT-<BANK>-<DOC>`, `kind: internal`, the owning unit as `issuer`,
   and one `primary` source with the intranet URL. Use duty ids from
   `regulations/schema/duties.yaml` and control ids from the catalogue, `policies/baseline.yaml`
   and `regulations/schema/controls.yaml`.
3. `set REGKB_INTERNAL_DIR=C:\bank\regkb-internal` (or put it in `.env`), then
   `python -m supervisor.regkb validate`. Leave the setting empty to turn internal rules off.

Details: `regulations/internal/README.md`. Do not commit confidential internal text to the
public repository.

## Refresh the sources (dev host only, internet needed)

The app never fetches. On a developer machine:

```
uv run python tools/regkb_fetch.py vbpl-search --keyword "53/2026/TT-NHNN"
uv run python tools/regkb_fetch.py vbpl-doc <vbpl uuid> --instrument VN-TT53-2026
uv run python tools/regkb_fetch.py url https://vbpl.vn/... --instrument VN-XXX --slug name
uv run python tools/regkb_fetch.py verify
uv run python -m supervisor.regkb validate
uv run python -m pytest tests/regkb -q
```

- `vbpl-search` uses the vbpl.vn search server action. Its action id changes when the site is
  redeployed; the tool rediscovers it and checks the response shape. Check that the result table
  looks right. `vbpl-sitemap` is the fallback.
- thuvienphapluat.vn article pages return HTTP 403 to scripts; use the vbpl gateway or the
  Công báo PDF and extract the text.
- Each stored file has a `<slug>.meta.json` sidecar with URL, `fetched_at` and sha256. A test
  checks every sidecar, and another test checks every `VERIFIED_PRIMARY` Vietnamese quote
  against the stored text.
- Vietnamese legal texts are outside copyright (IP Law Art. 15) and are stored in full.
  Copyrighted or share-alike texts (ISO, OWASP, regulator letters, law-firm notes) are kept as
  URL + own summary only.
- A signed scan without a text layer (the signed Circular 53 PDF) is read by
  `uv run python tools/regkb_ocr.py` (needs `tesseract` with the `vie` language data and
  `pdftoppm` on the PATH; dev host only). It writes `<pdf stem>.ocr.txt` and
  `<pdf stem>.ocr.meta.json` next to the PDF (sha256 of the PDF and of the text, tool versions,
  language, dpi, date). OCR text is a second check, not the text of record.
- After a refresh, update `last_checked`, re-run `validate`, and `diff` against the previous
  export to see what changed.

## How WP14 (compliance advisory agent) uses it

```
from supervisor.regkb import load_kb, applicable, ProductProfile
kb = load_kb(internal_dir=...)            # None = internal rules off
profile = ProductProfile(agent_classes=("payment", "customer_facing"),
                         data_classes=("personal", "financial"),
                         autonomy="acts_autonomously", cross_border=None,
                         model_hosting="domestic_cloud", roles=("deployer",))
for obligation, result in applicable(kb, profile):
    result.status        # applies | not_applicable | unknown
    result.missing_facts # unknown facts become questions, never guesses
```

WP14 builds the obligations matrix from these results: one row per applicable obligation,
citing the obligation id, its status and dates (an `issued` instrument shows its effective
date), the `control_mapping` (met / partial / gap / bank process), `evidence_needed`, and a
question for every `unknown`. It records `kb.version` in the matrix so a reviewer can tell which
data version produced it.

## Law agent (WP-L1)

> **Not legal advice. Bank counsel must confirm.** The agent drafts. It never makes an
> obligation. The banner is on the page and in every CLI output.

The agent reads the stored official text of one instrument (`regulations/sources/<id>/*.txt`)
article by article and drafts the duties in it. A person decides what becomes an obligation.

```
stored text -> split at "Dieu N." (46 articles for Decree 142)
            -> gateway model, temperature 0, one call per article
            -> rules (drop + count) -> table regkb_draft (status draft)
            -> person: Confirm / Drop on /console/regkb/<id>/drafts
            -> CLI --export-confirmed -> YAML -> pull request -> python -m supervisor.regkb validate
```

| Part | What it does |
|---|---|
| Switch | `LAWAGENT_ENABLED=1` (default `0`). `LAWAGENT_MODEL` names another model; empty = `LLM_MODEL`, the bank chat model. |
| Draft | `duty_id` (from `duties.yaml`), `subject` (who), `trigger` (when), `evidence_asked` (what an auditor asks), `text_vi` (verbatim quote, max 2000 chars), `summary_en`, optional clause. |
| Rules | The quote must be a substring of the stored article text (white space folded, nothing else). The duty id must be in `duties.yaml`. The article must exist. A draft that fails is dropped and counted by reason in the run summary. A draft already in the table (same article, duty and quote) is not written again; one a person dropped is not proposed again. |
| Table | `regkb_draft` (state): `draft_id`, `instrument_id`, `article` (`Điều 12` or `12.3`), `duty_id`, `subject`, `trigger`, `evidence_asked`, `text_vi`, `summary_en`, `source` (`model` or `rule`), `model_id`, `prompt_version`, `status` (`draft`, `confirmed`, `dropped`), `confirmed_by`, `confirmed_at`, `run_id`, `created_at`. The Databricks App cannot edit repo files, so drafts and decisions live in the table. |
| Page | `/console/regkb/<instrument>/drafts`: drafts grouped by article with the quote marked in the article text; **Confirm** and **Drop** (HTMX; two audit rows per POST; the person is written on the row). `regkb.view`: every role. `regkb.confirm`: approver and admin. There is no run button. |
| Diff mode | `compare(old_text, new_text)` lists added, changed and removed articles by heading and body hash (Phase 11 uses it). CLI: `--compare old.txt new.txt`. |

Run it (Windows cmd; the model settings are those of the other LLM features, see
`docs/llm-features.md`):

```
set LAWAGENT_ENABLED=1
python -m supervisor.regkb.lawagent --instrument VN-DEC142-2026 --articles 1-5 --out drafts.json
python -m supervisor.regkb.lawagent --instrument VN-DEC142-2026
python -m supervisor.regkb.lawagent --instrument VN-DEC142-2026 --export-confirmed confirmed.yaml
python -m supervisor.regkb.lawagent --compare old.txt new.txt
```

Output is ASCII (`[OK]`, `[FAIL]`, `[SKIP]`). The run prints the model id and the prompt
version, the number of drafts the model gave, the number kept and the number the rules dropped
with the reasons (`quote_not_in_article`, `unknown_duty`, `bad_quote_length`, `missing_field`,
`bad_clause`). The same ids are stored on every row, so a reviewer sees which model wrote it. If
the configured model is a mock (empty `LLM_BASE_URL` or `LLM_MOCK=1`) the CLI stops with
`[FAIL]`; `--allow-mock` is for tests, and then every output and the page say MOCK MODEL.

`--export-confirmed` writes the confirmed rows as obligations in the shape of
`regulations/vn/*.yaml`: `verification: VERIFIED_PRIMARY`, `confirmed_by`, the primary source of
the instrument with its stored sha256, `evidence_needed`, an empty `control_mapping`, and the
subject, trigger and run in `notes`. An engineer pastes the items under `obligations:` of the
instrument file, adds the control mapping, runs `python -m supervisor.regkb validate` and opens a
pull request. The obligation schema accepts the optional field `confirmed_by`; it is part of the
version hash only when present.

## Coverage raise (WP-L5)

> **Not legal advice. Bank counsel must confirm.** A mapping says which Supervisor control or
> bank process supports a duty. It does not say the duty is met.

Every obligation of Decree 142/2026 (26) and Circular 53/2026 (53) was read again against the
stored article, and its `control_mapping` was written again by hand with a pointer to the control
and the missing part. `text_vi`, `verification`, article references and dates were not changed
(a script compared them with the earlier data; the quote tests check the text).

### Counts

The level of an obligation is the best coverage of its entries. "Supervisor" counts the entries
that are not a bank process. "With process" counts every entry; a bank process step is `partial`
at most. `python -m supervisor.regkb coverage --levels` prints both.

| Instrument | Obligations | Before (full / partial / none) | After, Supervisor | After, with process |
|---|---|---|---|---|
| Decree 142/2026 | 26 | 0 / 19 / 7 | 1 / 19 / 6 | 1 / 24 / 1 |
| Circular 53/2026 | 53 | 0 / 47 / 6 | 0 / 49 / 4 | 0 / 53 / 0 |

The level is coarse: one `partial` control makes a row `partial`. The raise is mostly inside the
rows. Supervisor entries went from 50 to 87 (Decree 142) and from 129 to 202 (Circular 53). Before,
every bank process entry was `none` (78 entries); now 94 of 95 process entries are `partial` with a
named manual step, and one is `none` with its reason. Rows that moved by level: Decree 142 Art. 5(4)
and Circular 53 Art. 16(4) and Art. 20(2) from none to partial; Decree 142 Art. 19(6) from
partial to full.

### Rules for the two instruments (tests enforce them)

| Entry | Rule |
|---|---|
| Supervisor control, `partial` | At least one note of the obligation says `Missing: ...`, the part that Supervisor does not cover. |
| Bank process | Coverage `partial`; the note starts `Manual step: ...` and names the step the bank does. |
| Duty with no Supervisor control | The note says `No Supervisor control: <reason>` (or `No control:` for coverage `none`). |
| `full` | Only when the control alone meets the evidence need of the duty. One row: Decree 142 Art. 19(6); the ability to stop an agent on the authority's order is the pause and quarantine switch. The order itself and the person who triggers the switch are a manual step. |

Rows that stay without a Supervisor control, each with its reason in the note:

| Obligation | Reason |
|---|---|
| Decree 142 Art. 13(6) publish the conformity result | Act of the provider on the national portal; Supervisor is offline. |
| Decree 142 Art. 16(6) agreement with the model vendor | A contract term. |
| Decree 142 Art. 17(1) machine-readable mark | Text agents need no mark. Process `media_marking`, coverage `none`. |
| Decree 142 Art. 18(1) and 18(2) notice and label of public AI content | Supervisor does not see what the bank publishes; its agents make text only. |
| Decree 142 Art. 46(1) interim filing channel | Outside knowledge; a watcher is planned in Phase 11. |
| Circular 53 Art. 5(1)(h) credit by electronic means | The e-lending rules were not analysed and the product has no check for them. |
| Circular 53 Art. 18(1)(b) outsourcing responsibility | The vendor register and the contracts are outside Supervisor. |
| Circular 53 Art. 21(3) and 21(4) training and yearly capability review | Records of the bank's training and HR functions. |

### New controls in `controls.yaml`

Entries added for the features of phases 8 to 10 carry `doc: "<file> | <heading>"` (a test checks
that the file and the heading exist). Console entries are assumed present for every supervised
product (`advisory.compliance.facts.standard_controls`); a label that names a flag is live only
when the deployment sets that flag. Evidence entries are present only when the product says so.
The schema of `controls.yaml` is unchanged (the section names `monitors`, `console`, `evidence`,
`process`); the dotted names of the plan map to a section and a key, for example
`console.workflow_actions`, `evidence.guardian_off_approval`.

| Id | Section | Feature | Doc section |
|---|---|---|---|
| `workflow_actions` | console | Task and stage buttons with a second person (WP-P1) | `docs/console.md`, "Tasks and stage approvals as buttons" |
| `state_actions` | console | Request and approve RUNNING; owner cannot apply the class (WP-P2) | `docs/decision33.md`, "Separation of duties" |
| `guardian_off_approval` | evidence, table `guardian_off_request` | Reason and second person to switch a guardian off (WP-P2) | `docs/guardian-bindings.md`, "Reason and second person for a switch-off" |
| `schema_selfcheck` | console | Start-up schema check, `/healthz` fields (WP-P3) | `docs/console.md`, "Schema check" |
| `intake_scrub` | evidence, table `intake_attempt` | Source intake with secret scrub (WP-O1) | `docs/onboard.md`, "Intake" |
| `facts_card` | evidence, table `onboard_facts` | Facts card with file and line (WP-O2) | `docs/onboard.md`, "Facts card" |
| `predeploy_report` | evidence, table `predeploy_report` | Pre-deploy GO, NO-GO or QUESTIONS (WP-O3) | `docs/onboard.md`, "Pre-deploy assessment" |
| `attach_view` | console | Guardian attach view (WP-O4) | `docs/guardian-bindings.md`, "Attach view" |
| `law_agent_drafts` | console | Law agent drafts confirmed by a person (WP-L1) | `docs/regulations.md`, "Law agent" |
| `duties_step` | evidence, table `obligation_status` | Duties step and rows (WP-L2) | `docs/register-v2.md`, "Duties step" |
| `duties_actions` | console | Close, waive, re-evaluate (WP-L3) | `docs/console.md`, "Duties tab" |
| `duties_gap` | evidence, module `supervisor.governance.duties_gap` | Gap score, risk line, sweep (WP-L3) | `docs/risk-register.md`, "Duties" |

`law_agent_drafts` is not mapped to a duty on purpose: it keeps this knowledge base current; it is
not a control of a bank product.

Also added, because the mapping needed them and they already exist in the product: console
`systems`, `incidents`, `transparency`, `assurance`; evidence `incident_record`, `incident_clock`,
`transparency_report`, `assurance_results`, `risk_register`, `control_catalogue`, `task_record`,
`lifecycle_approval`, `classification_record`, `ai_system_record`, `threshold_check`. New bank
process ids (one line each in the file): `change_management`, `ai_inventory_review`,
`risk_classification_approval`, `ai_bom_management`, `customer_control_tool`,
`impact_assessment_file`, `go_live_decision`, `board_reporting`, `three_lines_model`,
`elending_compliance`, `media_marking`, `emergency_stop_drill`, `retirement_procedure`,
`user_guidance`, `customer_explanation`.

Effect on the compliance matrix (advisory): the status table is unchanged. For the four test
products (`tests/advisory/compliance/snapshots/`): Decree 142 Art. 19(6) goes from `partial` to
`met`; Circular 53 Art. 16(4) and Art. 20(2) go from `bank_process` to `partial`; Decree 142
Art. 5(4) goes from `bank_process` to `gap` (Supervisor evidence is mapped but not on for a product
that has not launched; the matrix reads that as "Supervisor controls mapped, none present"). The
snapshots and the generated `product.schema.json` (the evidence ids a questionnaire may list) were
regenerated. The version hash moved from `74cb5bb09c73` to the value that
`python -m supervisor.regkb validate` prints.

### OCR of the signed Circular 53 (second text)

`tools/regkb_ocr.py` renders `53-2026-tt-nhnn-signed.pdf` page by page (`pdftoppm -r 300`) and
reads each page with `tesseract -l vie --psm 6`. It writes `53-2026-tt-nhnn-signed.ocr.txt` (23
pages, a line `=== page N ===` before each page) and `53-2026-tt-nhnn-signed.ocr.meta.json`
(sha256 of the PDF and of the text, tesseract 5.5.3, pdftoppm 24.02.0, language `vie`, 300 dpi,
date). The sidecar has the keys of the other sidecars, so `tests/regkb/test_sources.py` checks the
text too. The vbpl text stays the text of record: `tests/regkb/test_quotes.py` ignores
`*.ocr.txt`.

`tests/regkb/test_quotes_ocr.py` checks every Circular 53 `text_vi` quote against both texts:

1. vbpl text: the quote must match as in `test_quotes.py` (white space folded, nothing else).
2. OCR text: both sides are folded (page numbers and page markers removed, no diacritics, the
   Vietnamese d with stroke as `d`, only `0-9a-z`, the look-alikes `1 l j` as `i` and `0` as `o`).
   A quote matches when it is a substring (EXACT) or when at least 90 percent of its 12-character
   chunks lie in one stretch of the OCR text of about the quote's length plus 10 percent
   (NOISE-TOLERANT).

**Threshold: the test fails when more than 10 percent of the quotes match in neither way.** The
test id (`ocr-match exact=... noise-tolerant=... fail=...`) and a printed line carry the counts.
Result on 2026-10-28: exact 46 of 53, noise-tolerant 53 of 53, fail 0 of 53. The seven quotes that
are not exact have OCR noise (a letter read as a digit, a dropped or added letter); none has a
different wording. A made-up sentence does not match, so the fold is not a blank check.

## Open points for counsel

- Whether the Decision 33 transition date for banks is 2027-09-01 ("finance", AI Law Art. 35)
  or 2027-03-01 (Circular 53 Art. 24; Decision 33 Art. 4(3) for new systems). The data uses
  2027-03-01 as an ASSUMED planning date.
- Whether Decree 53/2022 and Decree 85/2016 are formally replaced (no repeal clause found).
- Whether Decision 2345/QĐ-NHNN was formally repealed (only a secondary source says it is
  folded into Circular 50/2024).
- ISO/IEC 42001 and 23894 clause numbers were not checked against a licensed copy.
- Whether the bank is a large digital platform under the Consumer Protection Law (Art. 39(4)(c)).
- Whether a monitoring or judge call falls under the Decree 356 payment exemption (assumed not).
- Whether an AI or LLM agent is a "model" under Circular 83/2025 Art. 3(23) and so falls under the model risk section
  (Art. 56-58, from 2028-01-01 at the latest). The KB reads it that way.
- Whether an AI credit memo agent is "approval of credit by electronic means" (Circular 83/2025 Art. 15(3)), and whether the
  "new technology" in the AML Law Art. 19 covers AI agents.
- Which form of authorisation satisfies Decree 52/2024 Art. 10(2) ("in writing") when an AI agent acts on a customer account.
- Whether the 5-year limit on negative credit information (Circular 15/2023 Art. 13(1)) also limits the bank own use of the data.
- Whether "big data" in Decree 330/2026 Art. 66 covers an AI agent platform, and how the fines of Art. 67 relate to Circular 53 (both ask for human re-assessment of automated decisions).
- Whether Decree 53/2022 is superseded: vbpl.vn still shows it in force on 2026-10-28 (existing point, new evidence).
- Circular 15/2024 and Decree 52/2024: vbpl.vn shows "partly expired" for Circular 15/2024; the expired parts were not identified. Later amendments of Decree 52/2024 were not checked.
- Decree 320/2026 Art. 20 (transition for the e-identification link) was not read in full.
- Instruments the map lists as open (M-01 to M-10): amending laws of the credit law, identification law and decree, biometric
  technical regulations, security levels decree, payment intermediary and card circulars, e-KYC, outsourcing, AML guides, and the
  banking penalty decree. Counsel should confirm which of them apply to the bank.
- Whether an SBV AI instrument besides Circular 53/2026 exists. The search on 2026-10-28 found none; the keyword search is weak.
