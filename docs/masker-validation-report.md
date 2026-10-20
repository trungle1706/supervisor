# Validation report: `vn_regex-3` PII masker (WP24b)

Validator view: a bank data protection officer under PDPL 91/2025 and Decree 13-style sensitive
data rules, plus an NLP evaluation engineer. Primary metric: recall on direct identifiers (name,
CCCD, phone, account, e-mail, address), per entity, never one average. Over-masking an amount is a
hard fail because the credit rules read the amount. Thresholds are ILLUSTRATIVE until the bank
sets them. Not legal advice.

Date 2026-10-20. Reproduce: `python -m supervisor.pii_eval` (data `data/eval/pii_vn/`, seed
`20261020`, 721 synthetic items, 61 of them hand-written hard cases; dev 486, held-out 235).
Baselines: `baseline_vn_regex-2.json` (before, commit bf3a23a), `baseline_vn_regex-3.json` (after).
Everything is synthetic: **these numbers are not bank numbers** (BACKLOG: measure on a bank sample).

## 1. Verdict

| Check (ILLUSTRATIVE threshold) | Result | Verdict |
|---|---|---|
| Structured identifiers (CCCD, CMND, phone, e-mail, tax code, account, card): leak recall 10000 bp on both splits | 10000 on dev and held-out; Wilson lower bounds 8388 to 9699 | GO |
| ADDRESS leak recall: point >= 9500 bp on held-out | 10000 (interval 9425 - 10000) | GO |
| PERSON, dev: point >= 9500 bp | 9920 (9768 - 9973) | GO |
| PERSON, held-out (unseen surnames, mostly no title): point >= 9000 bp | 5297 (4579 - 6004) | **NO-GO** |
| Amounts left intact: 10000 bp, 0 over-masked | 10000, 0 of 496 amounts touched | GO (hard rule met) |
| Precision per entity: >= 9500 bp | 10000 for every entity on both splits | GO |
| No recall drop per entity vs baseline (regression test) | Test passes | GO |
| `pii_canary` masker metrics (`--target demo`: 3 `traces:` and 3 `agent:` targets) | `masker_unmasked_count` 0 of 256 canaries, 0 false masks on all six; the three `traces:` targets OK | GO (masker); the `agent:` targets FAIL on the agent reply, see section 4 |

**Overall: NO-GO for relying on the masker as the only control for personal names written without
a title, label or known surname. GO to merge and to use for structured identifiers, addresses,
labelled names and amounts.** Mitigation until a bank sample is measured: keep the capture level
`digest` for free-text fields that carry unlabelled names, and keep raw capture off.

## 2. Before and after (leak recall in bp; precision in brackets)

| Entity | v2 dev | v3 dev | v2 held-out | v3 held-out |
|---|---|---|---|---|
| PERSON (n 376 / 185) | 5186 (10000) | 9920 (10000) | 0 (10000) | 5297 (10000) |
| ADDRESS (127 / 63) | 1889 (10000) | 10000 (10000) | 1904 (10000) | 10000 (10000) |
| CCCD (83 / 41) | 10000 (10000) | 10000 (10000) | 10000 (10000) | 10000 (10000) |
| CMND (41 / 20) | 10000 (8913) | 10000 (10000) | 10000 (9090) | 10000 (10000) |
| PHONE (124 / 60) | 9919 (10000) | 10000 (10000) | 10000 (10000) | 10000 (10000) |
| EMAIL (83 / 41) | 10000 (10000) | 10000 (10000) | 10000 (10000) | 10000 (10000) |
| TAX_CODE (41 / 20) | 10000 (8723) | 10000 (10000) | 10000 (10000) | 10000 (10000) |
| BANK_ACCOUNT (84 / 41) | 9166 (5350) | 10000 (10000) | 9512 (5125) | 10000 (10000) |
| CARD_NUMBER (41 / 20) | 10000 (10000) | 10000 (10000) | 10000 (10000) | 10000 (10000) |
| Amounts intact (333 / 163) | 7477 | 10000 | 7484 | 10000 |

The BANK_ACCOUNT precision of about 5300 bp in v2 is the amount defect: about half of the
"accounts" it found were VND amounts.

## 3. Failure taxonomy (counts of gold values or hits)

| Class | v2 dev | v3 dev | v2 held-out | v3 held-out |
|---|---|---|---|---|
| over-mask-amount | 84 | 0 | 41 | 0 |
| missed-address (all case and diacritic forms) | 103 | 0 | 51 | 0 |
| missed-person-uppercase (with or without diacritics) | 41 | 0 | 66 | 18 |
| missed-person-mixed case (with or without diacritics, telex) | 87 | 0 | 89 | 30 |
| missed-person-lowercase-nodiac | 11 | 3 | 19 | 20 |
| partial-person (tail of the name left) | 42 | 0 | 11 | 19 |
| missed-phone-glued | 1 | 0 | 0 | 0 |
| partial-bank_account (last group of one digit) | 7 | 0 | 2 | 0 |

Read exact counts in the two baseline files (`taxonomy`). The 3 dev misses are lower-case table
cells with an ambiguous surname (`do`, `ho`, `cao`) and no label. The held-out misses are names
with a surname outside the lexicon (`Thach`, `Quach`, `Tong`, ...) written without a title.

## 4. Method and limits

* Golden set: seeded generator plus hand-written hard cases (upper-case, no diacritics, telex,
  names inside addresses, amounts next to account numbers, CCCD against phone collisions, e-mail
  with Vietnamese names, glued prefixes, company names, prose that uses lexicon words). Labeller
  `synthetic` or `expert rubric`; licence own. The generator and the masker were written by the
  same team, so recall on dev is optimistic by construction. The held-out split uses name pools
  kept out of the lexicon, and only its aggregate numbers were looked at.
* Dev was used to fix the masker (the dev failures guided the rules). A false-positive scan on the
  repo's non-PII text (assurance probes, tickets) guided the guards that stop prose from being
  masked; after the guards no prose span remains in that corpus except true names.
* Leak recall counts a value as caught only if every letter and digit of it is covered by a
  detected span (a half-masked name is a miss and is listed as `partial-...`).
* Intervals are Wilson 95%. With n = 20 an observed 10000 bp still has a lower bound near 8400 bp.
* Latency: median about 0.26 ms, p95 about 0.4 ms per call (this host, Python 3.11).
* `pii_canary` v2 on sample agents (mock responder, `--no-store`): `--target demo` runs
  three `traces:` targets (OK: 0 of 256 canaries leaked, 0 false masks; old pack: 102 items, no
  masker metrics) and three `agent:` targets. The three
  `agent:<id>` sandbox targets FAIL in both the old and the new pack, with the same 40 leaked
  values on 12 of 34 file probes: the mock responder repeats PII from the retrieved context. This
  is the agent target behaving as a naive agent, not a masker miss; the masker metrics for those
  targets are 0 and 0. **A FAIL there is a target (agent) failure, not a masker failure.**
* Review (2026-10-20): the 256-canary matrix and the dev split use the same name pools the
  masker was tuned on, so "0 of 256" is a dev figure. Old masker (`bf3a23a`) on the same
  matrix: 36 leaked values (addresses upper / no diacritics / abbreviated, telex names);
  reproduced by the reviewer.

## 5. Residual risk and conditions

1. Names without a title, label or known surname leak (held-out 53%). Condition: do not store
   free-text with unlabelled names at capture level `masked` until a bank sample shows >= 9500 bp.
2. No measurement on real text. Condition: the bank supplies a labelled sample (BACKLOG).
3. Lower-case names with an ambiguous surname and no label leak.
4. Inline redaction ignores bare JSON numbers.
5. The pseudonym is reversible by a key holder; key custody is the bank's.

## 6. Sign-off fields

| Role | Name | Date | Decision |
|---|---|---|---|
| Independent validator | FILL-ME | | |
| Data protection officer | FILL-ME | | |
| Model owner | FILL-ME | | |
