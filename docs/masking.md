# PII masking (WP24b, `vn_regex-3`)

> Not legal advice. The reading of PDPL 91/2025 and Decree 13-style sensitive-data rules is an
> engineering reading. The bank data protection officer (DPO) must confirm.

Supervisor never lets personal data into the evidence chain or into a judge prompt (design rule
R2). The masker is the part that makes this true. This page says what it masks, what it leaves
alone on purpose, how it is measured, and how the gate can mask tool arguments before a tool runs.

Related files: model card `docs/masker-model-card.md`, validation report
`docs/masker-validation-report.md`, decision `docs/adr/D14-masker-v3-inline-redaction.md`,
recorder side `docs/recorder.md`.

## 1. What the masker does

`VnRegexMasker` (`src/supervisor/adapters/masking/vn_regex.py`, finders in `vn_text.py`) replaces
each personal value with `<TYPE:hex>`. The hex is a keyed HMAC-SHA256 pseudonym of the normalised
value, so the same person gets the same token in every form, and another key gives other tokens.
Pure Python, standard library only, deterministic.

| Entity | What is found | Notes |
|---|---|---|
| PERSON | Surname lexicon + middle + given name, in Title, UPPER or lower case, with or without diacritics, telex-typed (`Nguyeenx Vawn Thuwr`). A written (Title or UPPER case) unknown final word is accepted. After a title, label or JSON key (`Ong`, `Ba`, `Anh`, `Chi`, `Khach hang:`, `Giam doc:`, `"full_name":`) any written name is accepted | `vn_text.py`, lexicon extends `data/wordlists.py` |
| ADDRESS | House number + street (+ `duong`, `ngo`, `pho`) + ward / district / province, also `P.6, Q.3, TPHCM`, `To 4, Khu pho 2`, in any case and with or without diacritics | Whole address is one span |
| CCCD, CMND | 12 and 9 digits, with label or valid province prefix, grouped by space, dot, dash, `/`, `_` | unchanged from `vn_regex-2` |
| PHONE | `0xx`, `+84`, `84`, dotted, spaced, glued to `sdt`/`tel` | |
| EMAIL | any case, Vietnamese names in the local part | |
| TAX_CODE, BANK_ACCOUNT, CARD_NUMBER | label, check digit, Luhn, grouped runs | a grouped account may end in a single digit |
| AMOUNT | `1.500.000.000 VND`, `1,5 tỷ`, `2 tỷ rưỡi`, `500tr`, `VND 250,000,000`, JSON floats (`9100000000.0`), bare digits after an amount key (`"total_assets": 12500000000`) | **found first, left intact by default** |

### Amounts (the credit-memo defect)

Before `vn_regex-3` a VND amount such as `9100000000.0` was typed `BANK_ACCOUNT`, which destroyed
the value the credit rules read. Now amount detection runs BEFORE any account rule and claims its
span. Then:

| Setting | Effect |
|---|---|
| `MASK_AMOUNTS=0` (default) | The amount stays in the text. Hard rule: an over-masked amount is a correctness defect |
| `MASK_AMOUNTS=1` | The amount becomes `<AMOUNT:hex>` (the capture level asks for it). `mask_version` gets the suffix `+amt` |

A labelled account number (`STK 190 3456 7890 12`) still wins over an amount shape.

### What is deliberately not masked

Dates, times, loan terms, percentages, reference numbers (`HD-2026-00123`), hotline numbers,
company names (a two-word brand inside `Cong ty TNHH ...` is not a person), single first names
after a lower-case `anh` (`chuyen den anh Nam`), and ordinary prose that uses lexicon words
(`khach hang co the khieu nai`, `xu ly trong bao lau`). Numbers sent as bare JSON numbers
(a phone as an integer) keep their value and type in inline redaction (see BACKLOG).

## 2. Inline redaction at the gate

For tools classed `pii_export` (and the tools named in `INLINE_REDACTION_TOOLS`), the gate answer
carries `transformed_args`: a masked copy of the arguments. The SDK or the MCP proxy swaps it in
before the tool runs. Two switches, both off by default:

| Where | Setting | Effect |
|---|---|---|
| Gateway (server) | `INLINE_REDACTION_ENABLED=1`, optional `INLINE_REDACTION_TOOLS=a,b` | An allowed, non-shadow call to a `pii_export` tool gets `transformed_args`, `args_hmac_transformed`, `redaction_count` in the answer |
| SDK (`supervised_tool`) | env `INLINE_REDACTION_ENABLED=1` or `sdk.set_inline_redaction(True)` | The tool runs with the masked values |
| MCP proxy | `--inline-redaction` or env `INLINE_REDACTION_ENABLED=1` | The upstream server receives the masked `arguments` |

Rules the code keeps:

* Rules are evaluated on the original arguments (amounts, limits, payees) before masking.
* Never in SHADOW state and never on a blocked call.
* Amounts stay intact in the masked copy (the gate masker has `mask_amounts` off).
* Numbers, booleans and null keep value and type; only string leaves change.
* If the SDK cannot map the answer onto the tool signature, it refuses the call (fail closed).
* The chain record `gate_decision` keeps `args_hmac` (original arguments) and adds
  `args_hmac_transformed`, `redaction_count`, `masker_version`. Values never enter the chain.
* If only one side is on, nothing changes for the tool: server on and SDK off means the tool
  still sees the original arguments. The server flag costs one masker pass per `pii_export` call.

## 3. Measuring it

Golden set: `data/eval/pii_vn/` (`dev.jsonl`, `heldout.jsonl`, `MANIFEST.json`), over 700 items.
Every item has id, source, licence, labeller (`synthetic` or `expert rubric`), tags, text, gold
spans and `keep` strings. The held-out split uses its own name pools that the masker lexicon must
not contain (a test checks it); never tune on it.

```
python -m supervisor.pii_eval                 # per-entity table, both splits
python -m supervisor.pii_eval --show-failures # failing DEV item ids per failure class
python -m supervisor.pii_eval --json          # machine-readable report
python -m supervisor.pii_eval --record        # write baseline_<masker>.json (commit it)
python -m supervisor.pii_eval --generate      # rewrite the golden set from the seed
```

Metrics (integers, basis points): per entity leak recall (no character of the value survives),
typed recall, precision, each with a Wilson 95% interval; amount-intact rate; failure taxonomy
(`missed-person-uppercase-nodiac`, `partial-address-...`, `over-mask-amount`, ...). Thresholds are
ILLUSTRATIVE until the bank sets them.

Regression gate: `tests/pii_eval/test_regression.py` fails on any per-entity recall drop below
`baseline_vn_regex-3.json`, on any over-masked amount, and on a precision drop above 100 bp.
Baselines: `baseline_vn_regex-2.json` (before the fix) and `baseline_vn_regex-3.json` (after).

## 4. The `pii_canary` assurance pack

Version 2 plants canaries of every entity type in every surface form (upper-case, no diacritics,
telex, grouped, international, abbreviated) on four surfaces: prompt, retrieved context, JSON tool
arguments and JSON tool result (`src/supervisor/assurance/pii_matrix.py`, 256 canaries). The
default masker must remove every value (case and diacritics ignored) and keep the amounts. The
agent target also asks the agent to repeat the data and checks the reply. The traces target scans
stored `args_masked` and `result_masked` with the tier0b patterns and with the masker finders
(names, addresses), and runs the same canary matrix. Any survivor fails the pack.

```
python -m supervisor.assurance run pii_canary --target demo --out C:\supervisor\assurance\pii --no-store
python -m supervisor.assurance run pii_canary --target agent:payments --out C:\supervisor\assurance\pii --no-store
```

Honest limit: the detector for traces is the masker itself plus the tier0b patterns. A name the
masker cannot recognise is not found by either, which is why the planted matrix exists.

## 5. Flags

| Flag | Default | Effect |
|---|---|---|
| `MASK_AMOUNTS` | off | Type amounts `<AMOUNT:...>` in masked text |
| `INLINE_REDACTION_ENABLED` | off | Gate answer carries `transformed_args` for `pii_export` tools; SDK / MCP proxy apply them when their own flag is on |
| `INLINE_REDACTION_TOOLS` | empty | Extra tool names (comma separated) that get inline redaction |
| `MASKER_KIND`, `MASK_HMAC_KEY`, `MASK_KEY_ID` | `vn_regex`, dev key | unchanged, see `docs/recorder.md` |

## 6. Known gaps

See `BACKLOG.md` and the validation report. Short list: names written without a title or label,
with a surname outside the lexicon, are missed (held-out PERSON recall is about 53%); lower-case
names with an ambiguous surname (`do`, `ho`, `mai`, `cao`) are missed unless a title or label
helps; no measurement on real bank text yet; addresses with no number and no street word are not
found.
