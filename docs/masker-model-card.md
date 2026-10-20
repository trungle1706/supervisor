# Model card: `vn_regex` PII masker, version `vn_regex-3`

Follows the conventions of `docs/judge-mrm.md` (identity, intended use, data, metrics, failure
modes, change log). The masker is rules and lexicons, not a trained model, but it takes the same
model-risk treatment because a miss is a personal-data incident. Not legal advice.

## Identity

| Field | Value |
|---|---|
| Component | `supervisor.adapters.masking.vn_regex.VnRegexMasker` (+ `vn_text.py`) |
| Version id | `vn_regex-3` (written as `vn_regex-3:<key id>` in `mask_version`; `+amt` when `MASK_AMOUNTS=1`) |
| Previous | `vn_regex-2` (2026-10-15 baseline, commit bf3a23a) |
| Type | Deterministic regular expressions, token rules, name and place lexicons. Standard library only. No network, no model weights |
| Owner / developer / validator / approver | FILL-ME (bank names them; see `docs/judge-mrm.md` section 2) |
| Risk level, approval document | FILL-ME (bank) |
| Pseudonym | HMAC-SHA256 of `TYPE:normalised value` under `MASK_HMAC_KEY`, first 6 hex characters. Names and addresses are folded to lower case without diacritics first, so `NGUYỄN VĂN THỬ` and `Nguyen Van Thu` get one token |

## Intended use

Mask personal data in text before it is stored as `args_masked` / `result_masked`, shown to a
judge, or (optionally) passed to a `pii_export` tool by inline redaction. Vietnamese banking text
(tickets, tool arguments, tool results, credit memo fields), also English mixed in.

Not intended for: legal anonymisation (the pseudonym is reversible by whoever holds the key and
the raw value), free-text names with no title, label or known surname, languages other than
Vietnamese and English, images and scans.

## Data

* Lexicons: `src/supervisor/data/wordlists.py` (own lists) plus additions in `vn_text.py`
  (surnames, middle and given names, 63 province names, ward / district words). Own data, no
  third-party lists.
* Evaluation: `data/eval/pii_vn/` synthetic golden set, 1031 items (666 dev, 365 held-out), seed
  `20261020`, including 61 hand-written hard cases and 310 negative prose items. No real customer data.
* The shipped lexicon is FULL (common names such as Duy, Lâm, Khôi, Thịnh, Quách, Kiều included).
  The held-out split is scored with its name pools removed at evaluation time only
  (`python -m supervisor.pii_eval --ablate-heldout-lexicon`, `vn_text.ablate`), so it measures
  generalisation to unseen names.

## Metrics (integer basis points; Wilson 95% interval)

Source: `data/eval/pii_vn/baseline_vn_regex-3.json`, compared with `baseline_vn_regex-2.json`.
Leak recall = no character of the gold value survives.

| Entity | v2 dev | v3 dev | v2 held-out | v3 held-out | v3 held-out interval |
|---|---|---|---|---|---|
| PERSON | 5186 | 9920 | 0 | 5297 | 4579 - 6004 |
| ADDRESS | 1889 | 10000 | 1904 | 10000 | 9425 - 10000 |
| CCCD | 10000 | 10000 | 10000 | 10000 | 9143 - 10000 |
| CMND | 10000 | 10000 | 10000 | 10000 | 8388 - 10000 |
| PHONE | 9919 | 10000 | 10000 | 10000 | 9398 - 10000 |
| EMAIL | 10000 | 10000 | 10000 | 10000 | 9143 - 10000 |
| TAX_CODE | 10000 | 10000 | 10000 | 10000 | 8388 - 10000 |
| BANK_ACCOUNT | 9166 | 10000 | 9512 | 10000 | 9143 - 10000 |
| CARD_NUMBER | 10000 | 10000 | 10000 | 10000 | 8388 - 10000 |
| Amounts intact (hard rule) | 7477 | 10000 | 7484 | 10000 | - |

The full per-entity table with precision and the failure taxonomy is in the validation report.
Latency: about 0.26 ms median, 0.4 ms p95 per call on this host (`latency_us_p50/p95` in the baseline).

## Known failure modes

1. Personal name with no title, label or JSON key and a surname outside the lexicon: missed.
2. Lower-case or no-diacritics name with an ambiguous surname (`do`, `ho`, `mai`, `cao`) and no label: missed.
3. A weak label (`khach hang`, `toi la`, `ky boi`) before a name made only of out-of-lexicon words: needs three words.
4. English capitalised word pairs after a strong label can be masked (`Do Anything Now` is guarded; others may not be).
5. Address with no number and no street keyword (`Quan 1, TP.HCM` alone) is not an address here.
6. A PII value sent as a bare JSON number is not masked by inline redaction.
7. Recall on real bank text is unmeasured. Synthetic recall is not a bank figure.

## Change log

| Version | Date | Change |
|---|---|---|
| `vn_regex-3` | 2026-10-20 | Name finder rewritten (case-insensitive, no-diacritics, telex, titles, labels, JSON keys, exact spelling for words with diacritics). Address finder (number, street, ward, district, province, abbreviations). Amount finder runs before account rules; amounts left intact unless `MASK_AMOUNTS=1`. Glued phone prefix. Grouped account may end in one digit. Old lowercase-permissive name regexes removed (they masked `xu ly trong bao`) |
| `vn_regex-2` | 2026-10-15 | Normalisation (NFKC, invisible characters), grouped separators |
| `vn_regex-1` | 2026-10-14 | First regex masker |

## Change control

Any change to `vn_regex.py`, `vn_text.py` or the lexicons: re-run `python -m supervisor.pii_eval`,
commit a new baseline only if no per-entity recall dropped (the regression test enforces it), bump
the version id when the output for the same input changes, and add a row above.
