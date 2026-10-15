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
| International reference frameworks (`binding: false`) | `regulations/intl/*.yaml` |
| Official texts as fetched, with sha256 sidecars | `regulations/sources/<instrument_id>/` |
| Bank internal rules (off by default) | folder named by `REGKB_INTERNAL_DIR`; guide in `regulations/internal/README.md` |
| Loader, validator, applicability, version hash, CLI | `src/supervisor/regkb/` |
| Dev-host fetcher (never imported by the app) | `tools/regkb_fetch.py` |

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

## Coverage (2026-10-15)

`python -m supervisor.regkb coverage` prints this table from the data. P/S/A = obligations
tagged VERIFIED_PRIMARY / VERIFIED_SECONDARY / ASSUMED.

### Vietnam (binding)

| Instrument | Number | Status | Effective | Obligations | P/S/A | Primary text stored |
|---|---|---|---|---|---|---|
| Law on Artificial Intelligence | 134/2025/QH15 | in_force | 2026-03-01 | 32 | 32/0/0 | yes |
| Decree guiding the AI Law | 142/2026/NĐ-CP | in_force | 2026-05-01 | 26 | 26/0/0 | yes |
| High-risk AI system list | 33/2026/QĐ-TTg | in_force | 2026-08-15 | 12 | 12/0/0 | yes |
| SBV circular on AI in banking | 53/2026/TT-NHNN | **issued** | 2026-11-15 (staged to 2027-09-01) | 53 | 53/0/0 | yes |
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

Total: 31 instruments, 528 obligations. Control coverage: no obligation is fully met by a
Supervisor control alone; 433 have partial Supervisor controls; 95 rely only on a bank process.
That is by design: Supervisor produces evidence; it does not make a product compliant.

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
