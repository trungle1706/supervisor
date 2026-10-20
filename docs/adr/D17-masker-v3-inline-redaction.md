# D17 - Masker `vn_regex-3` and inline redaction at the gate

Status: Accepted (WP24b, 2026-10-20). Bank decisions listed under "Open".

## Context

A real credit agent run under Supervisor (2026-10-15) found: upper-case Vietnamese person names and
street addresses stored unmasked in 101 trace rows; VND amounts typed as bank accounts, which
destroyed the value the rules read; the `pii_canary` pack reporting zero leaks on the same store;
and a masker recall of 1.000 that was synthetic by construction. Gap rows 8 and 9 of the
assessment ask for a masker that handles these forms and for masking before a PII-export tool runs.

## Decision

1. **New name, address and amount finders** in `adapters/masking/vn_text.py`, called from
   `VnRegexMasker`. Version id `vn_regex-3`. The keyed-HMAC pseudonym format (`<TYPE:hex>`),
   the key handling and determinism stay. No new dependency.
   * Names: token rules over a surname / middle / given lexicon (extended), any case, with or
     without diacritics, telex-typed. A lexicon word that has diacritics must be spelled exactly
     (`nguyên` is not `Nguyễn`). Lower-case text needs surname + middle + given, and a distinctive
     surname or `thi`/`van`. After a title, label or JSON key, any written name is accepted.
   * Addresses: number + street + ward / district / province parts, in any case.
   * Amounts: a currency and scale grammar run BEFORE the account rules. An amount span is claimed
     first; it is typed `<AMOUNT:hex>` only when `MASK_AMOUNTS=1`, otherwise it is left intact.
2. **The old lower-case-permissive name regexes are removed.** They masked prose such as
   `xu ly trong bao lau`. The cost is lower recall for lower-case names with an ambiguous surname
   and no label. A DPO may prefer recall; the trade is recorded in the validation report.
3. **Inline redaction.** For tools classed `pii_export` (plus `INLINE_REDACTION_TOOLS`), an allowed
   non-shadow gate answer carries `transformed_args`. The SDK (`supervised_tool`) and the MCP proxy
   apply it when their own switch is on. Rules are decided on the original arguments. Amounts stay
   intact. The chain records `args_hmac` (original) and `args_hmac_transformed`, never values.
   A per-tool policy flag was not added to the policy schema: it would change every
   `policy_hash`; a setting does the same job and is reversible without a policy deploy.
4. **Evaluation harness first.** `data/eval/pii_vn/` golden set with dev and held-out splits,
   `python -m supervisor.pii_eval`, per-entity recall and precision with Wilson intervals, a
   failure taxonomy, baselines for v2 and v3, and a regression test that fails on any recall drop.
5. **`pii_canary` v2** plants every entity in every surface form on four surfaces and scans traces
   with the masker finders too (`assurance/pii_matrix.py`).

## Alternatives rejected

* Presidio / spaCy NER: needs model wheels (no runtime downloads, bank guide); stays an optional
  extra.
* Always mask amounts: breaks the credit rules (PAY, CRD limits read amounts).
* Policy-schema flag per tool: see item 3.
* One merged recall number: hides that names are the weak entity.

## Consequences

* `mask_version` changes to `vn_regex-3:<key id>`; existing rows keep `vn_regex-2` and stay valid.
* Pseudonyms of names and addresses can differ from v2 for the same value (they did not match
  across cases before, so rows were not joinable on them anyway).
* Cost: one masker pass per `pii_export` gate call when the server flag is on (about 0.3 ms
  for short arguments, about 3.2 ms for a 2 KB payload). Review: the pass runs before the gate
  lock; a masker error blocks the call (`GATE-REDACTION`, fail closed).
* Review follow-up (findings 5, 6): the shipped lexicon is now FULL. The held-out split is
  measured with `--ablate-heldout-lexicon` (`vn_text.ablate`, evaluation only), and a negative
  prose corpus gives a false-mask rate per entity. See `docs/masker-validation-report.md`.
* Trust boundary: the gate answer now may carry masked arguments. See `docs/threat-model.md` 3.1.

## Open

1. Bank supplies a labelled real sample; until then every recall figure is synthetic.
2. Threshold for PERSON recall (illustrative 9500 bp) and for ADDRESS.
3. Whether `MASK_AMOUNTS` should be on for the `masked` capture level of some agents.
4. Whether to mask unlabelled names more aggressively (higher recall, more false masks).
