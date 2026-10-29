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

## Internal documents (WP-W3)

Flag `REGKB_INTERNAL=1` (default `0`; needs `LAWAGENT_ENABLED=1`). `REGKB_INTERNAL_MAX_MB` (default
`10`, 1 to 50). A person uploads a bank policy, standard or procedure; the law agent drafts one duty
per section from the **masked** text; a person with `regkb.confirm` accepts rows; the accepted rows
become the instrument `VN-INT-<doc id>` that the compliance matrix, the Duties step and the factory
`policy_refs` (WP-F2) can reference like an external instrument. Not legal advice.

```
upload (.txt .md .pdf) -> text -> personal-data masker -> DATA_DIR/regkb/internal/<doc id>/
   -> [Draft duties] sections -> gateway model (masked text only) -> rules -> regkb_draft
   -> person: Confirm / Drop on /console/regkb/VN-INT-<doc id>/drafts
   -> instrument.yaml (rebuilt from all confirmed rows) -> validator -> loader at startup
```

| Part | What it does |
|---|---|
| Upload | `POST /v1/regkb/internal` or the form on `/console/regkb/internal`. Multipart field `file` plus text fields `title`, `owner_group` (required), `version_label`. Accepted: `.txt`, `.md`, `.pdf` with a text layer (read with `read_pdf` of `detectors/intake.py`; it needs the optional extra `documents`, else code `pdf_reader_missing`). Size limit `REGKB_INTERNAL_MAX_MB`. Refusal codes (HTTP 400): `regkb_internal_off`, `bad_type`, `empty_file`, `too_large`, `unreadable`, `pdf_no_text_layer`, `pdf_reader_missing`, `too_short`, `owner_group_required`, `field_too_long`, `masker_off`, `no_sections`, `actor_required`, `cross_site`, `bad_body`. |
| Files | `DATA_DIR/regkb/internal/<doc id>/`: `text.txt` (raw text, for the person), `text.masked.txt` (the only text a model sees), `.meta.json` (title, owner group, version label, `uploaded_by`, `uploaded_at`, `sha256` of `text.txt`, `masked_sha256`, mask version), `drafts.json` (risk dimensions and the section label of each draft), `instrument.yaml` (after the first confirmation). The doc id is 12 characters of `0-9A-F`. |
| Table | `regkb_internal_doc` (state): `doc_id`, `title`, `owner_group`, `version_label`, `sha256`, `status` (`uploaded`, `drafted`, `confirmed`, `retired`), `uploaded_by`, `uploaded_at`, `row_version`. Title, owner group and version label are masked before they are stored. |
| Masker | The configured masker (`MASKER_KIND`) runs on the text at upload. With `MASKER_KIND=none` the upload is refused (`masker_off`). A model call reads the masked file only, and the file is checked against `masked_sha256` first (`files_changed`). The raw text never goes to a model. A drafted quote is a quote of the masked text, so no personal data enters `regkb_draft` or the instrument. |
| Draft | `python -m supervisor.regkb.lawagent --internal <doc id>` or the button **Draft duties** (`POST /console/regkb/internal/<doc id>/draft`, `POST /v1/regkb/internal/<doc id>/draft`; permission `regkb.upload`). One call per section. The model says if the section imposes a duty; if so it gives 1 to 3 duty ids, subject, trigger, evidence, a verbatim quote, a one-line English summary and the risk dimension ids it touches. Rules (a reply that fails is dropped and counted): the duty ids are in `duties.yaml`; the four text fields are not empty; the quote has 12 to 2000 characters and is a substring of the section text (white space folded); dimension ids outside the eight of `config/risk_dimensions.yaml` are removed. A mock model is refused (`model_is_mock`). A draft already in the table, or one a person dropped, is not written again. |
| Rows | `regkb_draft` with `instrument_id = VN-INT-<doc id>`, `article` = the section pointer `S<n>` (the n-th section of the masked text), `duty_id` = the duty ids joined by a comma. The drafts page `/console/regkb/VN-INT-<doc id>/drafts` shows them grouped by section with the quote marked, the dimension ids and the section pointer. |
| Instrument | After each **Confirm**, `regkb/internal.py` rebuilds `instrument.yaml` from all confirmed rows, checks it with the RegKB schema validator and loader rules in a scratch folder, writes it, drops the RegKB caches and writes the chain record. With no confirmed row left the file is removed. A document can be retired (`InternalDocs.retire`): the file is removed and the loader no longer sees it. |
| Loader | With the flag on, `load_kb()` reads `DATA_DIR/regkb/internal/*/instrument.yaml` next to `regulations/vn` (ids must start with `VN-INT-`). It accepts `kind: internal`, `binding: internal` and `verification: VERIFIED_INTERNAL` there and refuses them in every other folder. `sources[].local_path` of such a file is `regkb/internal/<doc id>/text.txt`, relative to `DATA_DIR`; its sha256 is checked at load. |
| Version hash | The RegKB version hash covers an internal instrument **only while the flag is on** (the loader does not read the files otherwise). Turning the flag on or off, or confirming a row, changes the version hash that the compliance matrix and the evidence records show. |
| Chain | One `regkb_internal` record on upload (`action: upload`, doc id, sha256, masked sha256, section count, byte count) and one on each confirm (`action: confirm`, doc id, sha256, counts of confirmed, dropped and open drafts, sha256 of the instrument file). No title, no user id, no text, no floats. |
| Permissions | `regkb.upload` (reviewer, owner, approver, admin): upload and Draft duties. `regkb.view` (every role): the page and the reader API. `regkb.confirm` (approver, admin): Confirm and Drop, on the existing drafts routes. |
| Audit | Every POST writes two `console_action` rows (`attempted`, then `ok` or the failure). |

Reader API for the factory editor (WP-F2). The editor links to `/console/regkb/internal` and keeps
an internal document id as a `policy_refs` value (`VN-INT-<doc id>` or one of its obligation ids).
All reads answer HTTP 400 `regkb_internal_off` while the flag is off.

| Call | Answer |
|---|---|
| `GET /v1/regkb/internal` | `{"documents": [...]}` : `doc_id`, `instrument_id`, `title`, `owner_group`, `version_label`, `sha256`, `status`, `uploaded_by`, `uploaded_at`, `drafts` (counts), `has_instrument` |
| `GET /v1/regkb/internal/{doc_id}` | the same fields plus `sections`: `n`, `ref` (`S<n>`), `label`, `heading`, `chars` |
| `GET /v1/regkb/internal/{doc_id}/sections/{n}` | `n`, `ref`, `label`, `heading`, `text` (masked), `masked: true` |

Section splitter (`regkb/internal_text.py`, pure, tested on three synthetic policies). A line starts
a section when it is `Điều N`, `Chương X`, `Phần X`, `Mục X`, `N.` or `N)` followed by text (1 or 2
digits), or a dotted number `N.N`, `N.N.N` (up to four levels). A bare number ("15 tháng") does not.
Text before the first heading is a `Preamble` section when it has 120 characters or more. A
`Chương`, `Phần` or `Mục` with fewer than 60 characters of text under it is dropped. A section over
8000 characters is cut at line boundaries (`(part 2)`, ...). With fewer than two headings the text
is cut at blank lines into blocks `P1`, `P2`, ... (a block under 80 characters joins the next).
Sections are numbered from 1 after these steps; at most 300 sections.

Instrument file written for a document (`regkb/internal.py`; the row fields are those of
`regulations/vn/*.yaml`):

```yaml
schema_version: 1
instrument:
  id: VN-INT-3F9A0C21B7D4          # 'VN-INT-' + doc id
  jurisdiction: VN
  kind: internal
  issuer: <owner group>
  number: <version label>
  title_vi: <title>
  title_en: <title>
  status: in_force
  binding: internal                 # new value; true/false stay for external instruments
  dates: {issued: {date: <upload day>, source: https://regkb.internal.invalid/VN-INT-..., verification: VERIFIED_INTERNAL}}
  sources: [{url: https://regkb.internal.invalid/VN-INT-..., title: ..., fetched_at: <upload day>, kind: primary, sha256: <text.txt sha>, local_path: regkb/internal/3F9A0C21B7D4/text.txt}]
  verification: VERIFIED_INTERNAL   # new value
  primary_text_fetched: true
  last_checked: <day>
obligations:
- id: VN-INT-3F9A0C21B7D4-S3-01     # S<section n>, then a two-digit suffix
  article_ref: Sec. 3 (Điều 3)
  text_vi: <the verbatim masked quote>
  summary_en: ...
  duties: [risk_classification, internal_policy]
  applies_to: {}
  addressee: bank
  control_mapping: []
  evidence_needed: [<evidence asked>]
  verification: VERIFIED_INTERNAL
  confirmed_by: <person>
  sources: [<as above>]
  confidence: medium
  notes: <section, risk dimensions, subject, trigger, model, run, who confirmed and when>
```

Limits and open points. (1) `DATA_DIR` is wiped on a Databricks App restart; the uploaded files
and `drafts.json` are on that disk, so on Databricks `DATA_DIR` must be a persistent volume before
this feature is used there. (2) The risk dimension ids of a row are kept in `drafts.json` and in
the `notes` of the obligation; the obligation schema has no field for them. (3) The "Draft duties"
button runs in the request (one model call per section, up to 300 sections); a long document should
be drafted with the CLI. (4) The compliance matrix, the Duties step and the register caches are
refreshed on a confirm; other long-lived caches (assignment rules, risk references) refresh after a
restart.

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

## Watcher and update package (WP-W1)

The watcher asks vbpl.vn whether a stored Vietnamese instrument changed. It runs on a developer
host or a laptop, never in the Databricks App (the App has no internet). It only finds and
stores: **nothing is applied to RegKB**. Not legal advice. Bank counsel must confirm.

```
dev host / laptop                                       the App (offline)
  python -m supervisor.regkb watch                        POST /v1/regkb/import (admin)
    -> vbpl.vn (tools/regkb_fetch.py)                       check signature + every sha
    -> sources/<id>/incoming/<date>/*.txt + sidecar         store regkb/incoming/<sha>/
    -> watch-<date>.json / .md                              list on /console/regkb/watch
    -> update-package-<date>.zip (signed)  --copy-->        "pending review (WP-W2)"
```

### Run it

```
python -m supervisor.regkb watch --dry-run --instrument VN-TT53-2026   (query, print, write nothing)
python -m supervisor.regkb watch --out C:\bank\regwatch                  (all instruments)
```

`--out` defaults to `DATA_DIR/regwatch`. New texts go to
`regulations/sources/<id>/incoming/<YYYY-MM-DD>/` (git-ignored; `--sources-root` changes the
base folder). The stored text of record is never changed. All network calls use the functions of
`tools/regkb_fetch.py` (search action id rediscovery included). Downloaded content is data: it
is written as bytes and never imported or executed.

### What it detects

| Kind | Rule |
|---|---|
| `amendment`, `replacement`, `repeal` | Another document whose title names the full number with "sửa đổi", "thay thế" or "bãi bỏ" (the first word found wins: repeal, then replacement, then amendment). A longer number (199/2026 for 99/2026) does not match. A number named in the instrument file or in the last report is known, not new. |
| `effect_status_change` | vbpl effect status code differs from the last report. In the first run: not compatible with the `status` in the file. |
| `updated_date_newer` | `updatedDate` is later than the last report, or than `last_checked` in the first run. |
| `text_changed` | A primary vbpl source now gives a text whose sha256 and word sequence differ from the stored one. The word sequence leaves out line breaks, page-number lines (`12`, `- 12 -`, `Trang 12`, `12/40`) and part headings (`Chương`, `Mục`, `Phần`, `Tiểu mục` with a number, and the capitals title line after it). Article headings stay: an added or renamed article is a change. A layout-only difference is counted (`layout_only`), not reported. |

Also once per full run: the keywords "trí tuệ nhân tạo" and "AI" for the SBV, the Government,
the MST and the MPS (new instrument candidates), the Decree 142 Art. 46 interim channel
("cổng thông tin một cửa trí tuệ nhân tạo", "cơ chế tạm thời") on the Government and MST (a
note with the hits), and the open items M-01 to M-10 of `REGULATOR_MAP.md` (numbers are
searched exactly; items without a number list candidates).

### Files

`watch-<date>.json` (format `regwatch-report-1`: per instrument `record`, `observed`, `changes`;
`new_candidates`, `interim_channel`, `open_items`, `errors`) and `watch-<date>.md` for people.
The update package is `update-package-<date>.zip` (50 MB at most):

| Member | Content |
|---|---|
| `manifest.json` | `format regwatch-package-1`, `run_id`, `created_at`, every other member with `sha256` and `size` |
| `signature` | JSON: `key_id`, `key_kind`, `signed` (sha256 of `manifest.json`), base64 Ed25519 `signature` over `supervisor-regwatch-package/v1 ` + that sha, `public_key` |
| `watch-<date>.json`, `watch-<date>.md` | the report |
| `proposed_changes.yaml` | empty placeholder (`proposed: []`) for WP-W2 |
| `incoming/<id>/<date>/<name>.txt` and `<name>.meta.json` | new texts; sidecar has url, fetched_at, sha256, vbpl record fields |

### Import (App, admin)

`POST /v1/regkb/import` with multipart field `file`. The signature is checked against
`REGKB_IMPORT_PUBKEY` (a PEM file) or, when empty, the public key of this install's evidence
signer; the key id in the package must match. Then every member is checked against the manifest.
Stored under `DATA_DIR/regkb/incoming/<package sha256>/`; the same package twice answers 200
`already_imported`. Refusals are HTTP 400 with a code at the start of the message:

| Code | Meaning |
|---|---|
| `regwatch_off` | `REGWATCH_ENABLED` is off (every route) |
| `nothing_to_import` | no file in the form |
| `too_large` | over 50 MB, over 600 members or over 200 MB unpacked |
| `bad_zip` | not a zip, or a member cannot be read |
| `path_traversal` | a member path with `..`, a leading `/`, a backslash or a colon |
| `unknown_member` | a member name outside the allowed set, or listed twice |
| `bad_manifest` | manifest or signature missing or not valid; not exactly one report |
| `bad_signature` | the signature does not cover the manifest or does not verify |
| `untrusted_key` | the key id is not the trusted key |
| `sha_mismatch` | a member differs from the manifest, or members and manifest differ |

Read: `GET /v1/regkb/watch/runs` (runs and reports), `GET /v1/regkb/watch/packages`, page
`/console/regkb/watch` (Risks and controls, admin). Each change shows "pending review (WP-W2)".
Permissions `regkb.import` and `regkb.watch` are admin only. Each import writes two
`console_action` rows and one `regkb_import` chain record (hashes and counts).

### Scheduler job

`REGWATCH_ENABLED=1` and `REGWATCH_INTERVAL_S` (default 86400, minimum 3600) add the job
`regwatch` in laptop mode (`python -m supervisor.jobs.regwatch` runs it once). In
`databricks_app` mode the job is refused with a log line. Output goes to `DATA_DIR/regwatch/`
(new texts under `sources/<id>/incoming/`). One `regwatch_run` row per run and one
`regwatch_run` chain record (counts and the two sha256 values). A laptop carries the zip to the
App by a file transfer approved by the bank.

## Change to re-evaluation (WP-W2)

Flag `REGKB_CHANGE_LOOP=1` (default off; needs `LAWAGENT_ENABLED=1` and `GOVERNANCE_ENABLED=1`; the
input is a package imported by WP-W1, or a text file on the command line). With the flag off every
route answers HTTP 400 `change_loop_off`, the loader reads no override and no event is made.
Not legal advice. Bank counsel must confirm.

```
imported package (WP-W1)  ->  diff  ->  person: accept or drop drafts  ->  Apply change
                                                                              |
   override under DATA_DIR/regkb/overrides  ->  new RegKB version hash  ->  event regkb_changed
        ->  duty rows open again + gap tasks + owner notice + re-evaluation (classification only)
```

Only the draft is made by a model. The diff, the override, the validator, the quote check and every
rule of the event are deterministic.

Navigation (WP-B1): with `CONSOLE_NAV_V3=1` the tab **Law changes** (`/console/regkb/changes`,
`regkb.view`) sits under Risks & controls while the flag is on. On the system **Duties** tab a row
whose note reads "article changed on <date> (package <sha8>)" shows a link "Law change that
re-opened this duty" to `/console/regkb/changes/<sha>/<instrument>`; the sha8 is matched to an applied
change that lists the obligation. No link with the flag off.

### Diff mode of the law agent

```
python -m supervisor.regkb.lawagent --diff VN-DEC142-2026 --incoming <package sha | text file>
    [--incoming-name VN-DEC142-2026/2026-10-28/x.txt] [--out report.json]
```

The console button is "Diff against the text of record" on the watch page (per package and
instrument) and on `/console/regkb/changes`. `POST /v1/regkb/changes/{sha}/{instrument}/diff` does the
same (permission `regkb.confirm`, so approver and admin).

1. The text of record is the newest override text of the instrument, else the stored text under
   `regulations/sources`. The incoming text is a `text_changed` file of the package (or the file you
   name).
2. `split_articles` cuts both at the `Dieu N.` headings. The diff compares the white-space-folded
   text per article: `unchanged`, `changed`, `added`, `removed`, with the number of changed
   characters (words that differ, whole numbers). A text that differs outside the articles (annex,
   title, signature block) is flagged `outside_articles_changed`.
3. The model reads the changed and the added articles only, with the guards of the external mode
   (duty id from `duties.yaml`, verbatim quote inside the article of the incoming text, 12 to 2000
   characters). Rows go to `regkb_draft` with status `draft`; table `regkb_change_draft` links each
   draft to its change (`change_ref` = `<package sha>:<article>`). **No model call** when no article
   changed or was added.
4. The obligations whose `article_ref` names a changed or removed article are listed as
   `affected_obligations` (`article_changed`, or `article_removed` when all their articles are gone).
   `lawagent.article_numbers` reads the article numbers: `Art. 5(3)` is 5; `Art. 5(1), 6(2)` is 5
   and 6; `Art. 5-7` is 5, 6, 7; an annex reference has none and is not listed.

Files under `DATA_DIR/regkb/changes/<package sha>/<instrument>/`: `diff.json`, `diff.md`,
`diff.meta.json` (sha256 of both, of the incoming text and of the old text), `old.txt`,
`incoming.txt`, `incoming.meta.json`. Report shape (`regkb-diff-1`):

```
{ "format", "change_id", "package_sha256", "instrument_id", "generated_at",
  "old": {"sha256","where"}, "new": {"sha256","name"}, "outside_articles_changed": bool,
  "model": {"id","prompt_version","calls"},
  "summary": {"unchanged","changed","added","removed","articles_old","articles_new",
              "changed_chars","classification_hit","drafts_made","affected_obligations_n",
              "dropped_by_rules"},
  "articles": [{"number","label","status","old_heading","new_heading","old_sha256",
                "new_sha256","changed_chars"}],
  "affected_obligations": [{"id","article_ref","articles","reason","coverage"}],
  "drafts": [{"draft_id","article","duty_id"}] }
```

### Confirm and apply

Page `/console/regkb/changes/{package sha}/{instrument}` (permission `regkb.view` to read): the old and
the new folded text side by side for each article that is not unchanged, the drafted duties with
Confirm and Drop (the same buttons and routes as the drafts page), the affected obligations, and
**Apply change** behind a confirmation tick (`confirm=yes`). A person with `regkb.confirm` presses it;
a second person is not required; the actor is logged on the row, in the audit rows and (as a hash)
in the chain record. `POST /v1/regkb/changes/{sha}/{instrument}/apply` does the same.

Apply refuses with HTTP 400 and a code: `no_diff`, `already_applied`, `nothing_to_apply`,
`stale_diff` (the text of record changed after the diff), `override_invalid` (the validator or a quote
check failed; nothing is written), `confirm_required` (console).

### The override and the version hash

The committed `regulations/vn/*.yaml` files are never written at run time. Apply writes
`DATA_DIR/regkb/overrides/<instrument>/override.yaml` (format `regkb-override-1`) and the new text
under `text/<sha12>.txt` with its sidecar (content addressed, never deleted):

```
format: regkb-override-1
instrument_id: VN-DEC142-2026
text: {path: regkb/overrides/VN-DEC142-2026/text/<sha12>.txt, sha256, url, title, fetched_at}
removed: [obligation ids dropped because their article was removed]
obligations: [obligation rows in the file shape of regulations/vn: a row with an existing id
              replaces it, a row with a new id is added]
applied: [{package_sha256, change_id, applied_at, applied_by, text_sha256}]
```

* A confirmed draft whose article and duty match an existing obligation **updates** it (same id,
  its `control_mapping` and `applies_to` are kept, `text_vi`, `summary_en`, `evidence_needed`, sources
  and `confirmed_by` are new). Any other confirmed draft is a **new** obligation with a free id. An
  affected obligation with no confirmed draft stays as it is: counsel decides.
* With the flag on, `load_kb()` applies the overrides after the committed files: the instrument's
  primary source becomes the incoming text (path relative to `DATA_DIR`, sha256 checked), each
  override row passes the same schema validator and semantic rules, and its `text_vi` must be a quote
  of the incoming article (`override_invalid` / "text_vi is not a quote of the incoming text").
  `load_kb(overrides_dir=...)` names the folder (tests, Apply). With the flag off the loader ignores
  the folder.
* **Hash.** There is no separate term for the override. The version hash is computed over the merged
  instruments and obligations, so it changes because the instrument's primary source (url, sha256,
  `local_path`) and the added, updated and removed obligations are different. The row
  `regkb_change` keeps `version_before` and `version_after`.
* Chain record `regkb_change`: package sha, instrument, articles changed (changed + added +
  removed), obligations added, updated and removed, `actor_ref` (first 16 hex of the sha256 of the user
  id). Integers and ids only.

### Governance event `regkb_changed`

New source `regkb_changes` in `governance/event_sources.py` reads `regkb_change` rows with status
`applied`. One event per system (not archived): the systems that have an `obligation_status` row on an
affected obligation, and, when a classification article changed, every system. Payload (in the row
`regkb_change`): instrument, article numbers, `obligations_affected`, package sha. Severity: `high`
when a classification article changed or a **full or partial** duty of the system on the
classification path (articles cited by `config/classification.yaml`) is affected; else `medium`.

| Rule (config/governance_actions.yaml) | Min severity | Actions |
|---|---|---|
| `GA-REGKB-CHANGED` | medium | `reopen_obligations`, `notify_owner`, `fire_webhook` |
| `GA-REGKB-CHANGED-CLASSIFICATION` | high | `move_to_re_evaluation` |

* `reopen_obligations` (new action, `governance/regkb_reopen.py`): every duty row of the system on an
  affected obligation gets the note "article changed on <date> (package <sha8>)"; a closed or waived
  row that applies goes back to `open`. One task per re-opened group (instrument and coverage) with the
  WP-L3 text ("Close N duties of <number> (coverage partial)"; "Re-check ..." for full coverage),
  template `DUTY-CHG-<sha8>-<instrument>-<coverage>`. One chain record `regkb_reopen` per system.
* Classification articles (trigger list of WP-C1): Law 134/2025 Art. 7, 9, 10; Decree 142 Art. 6, 8,
  9, 11; Circular 53 Art. 4; Decision 33 (any change, because Appendix IV is an annex the article
  splitter does not read). `move_to_re_evaluation` only moves a system in `deployment` or `operation`.
* Banner on My overview: "Law change pending review: N" while an imported package has a changed text
  that is not applied, and "Law change applied on <date>: N systems re-opened" for 7 days after the
  apply. Nothing shows while the flag is off.

Limits: the diff reads articles; a change only in an annex is flagged but not drafted. Amending texts
(a new decree that amends this one) are not diffed against the old text; counsel reads them and a new
text of the instrument is imported when the consolidated text exists. The risk register line of
WP-L3 is not refreshed by the event; use Re-evaluate on the Duties tab.

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
