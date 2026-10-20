# HANDOFF WP24b: masker fixes and inline redaction

Branch: `worktree-agent-a44bc574614ace41d` (7 commits on top of main bf3a23a). Not pushed, not merged.
Tests: main 2791 passed; this branch **2896 passed, 28 skipped** (`python -m pytest -q`, 4.5 min).
Lint: `ruff check` and `ruff format --check` clean.

## 1. What was built

| Part | What | Where |
|---|---|---|
| Masker `vn_regex-3` | Names in UPPER / lower / mixed case, with and without diacritics, telex-typed; titles (Ong, Ba, Anh, Chi, Khach hang, Giam doc, ...), labels, JSON keys. Street addresses (number, street, ward, district, province, `P.6, Q.3, TPHCM`, `To 4, Khu pho 2`). Amounts found BEFORE account rules; typed `<AMOUNT:hex>` only with `MASK_AMOUNTS=1`, else left intact. Glued `sdt0912...`. Grouped account may end in one digit. Same keyed-HMAC `<TYPE:hex>` format, deterministic, no new dependency | `src/supervisor/adapters/masking/vn_text.py` (new), `vn_regex.py` |
| Inline redaction | Gate answer carries `transformed_args`, `args_hmac_transformed`, `redaction_count` for `pii_export` tools and for `INLINE_REDACTION_TOOLS`; SDK and MCP proxy apply it. Chain `gate_decision` keeps `args_hmac` (original) + `args_hmac_transformed`; no values | `gateway/redact.py` (new), `engine.py`, `sdk.py`, `mcp_proxy.py`, `wiring.py`, `config.py` |
| Harness | Golden set `data/eval/pii_vn/` (721 items: dev 486, held-out 235; 61 hand-written hard cases; seed 20261020; MANIFEST), per-entity leak recall, typed recall, precision, Wilson 95% (bp), failure taxonomy, latency; baselines `baseline_vn_regex-2.json` (before, bf3a23a code) and `baseline_vn_regex-3.json` (after) | `src/supervisor/pii_eval/` |
| Regression test | Fails on any per-entity recall drop vs the v3 baseline, any over-masked amount, a precision drop over 100 bp; also checks set shape, generator determinism, held-out pools out of the lexicon | `tests/pii_eval/test_regression.py` |
| `pii_canary` v2 | Canary matrix: 9 entities x forms (upper, no diacritics, telex, grouped, intl, abbreviated) x 4 surfaces (prompt, context, JSON tool args, JSON tool result) = 256 canaries through the masker; agent target also asks the agent to repeat them; traces target also scans with masker finders (names, addresses) and runs the matrix. Fails on any survivor | `assurance/pii_matrix.py` (new), `runners/security.py`, `packs/pii_canary.yaml` |
| Docs | `docs/masking.md`, `docs/masker-model-card.md` (version `vn_regex-3`), `docs/masker-validation-report.md` (GO / NO-GO), `docs/adr/D17-masker-v3-inline-redaction.md`, README rows, `docs/index.md`, BACKLOG, threat-model gap row, `.env.example` | |

## 2. Flags (all default OFF)

`MASK_AMOUNTS`, `INLINE_REDACTION_ENABLED`, `INLINE_REDACTION_TOOLS` (settings block `# --- WP24b ---`).
SDK: env `INLINE_REDACTION_ENABLED` or `sdk.set_inline_redaction(True)`. MCP proxy: `--inline-redaction` or the same env.
Server flag and SDK / proxy flag must both be on for a tool to see masked arguments. Off path is tested (no `transformed_args`, tool gets the original arguments).

## 3. Commands

```
python -m supervisor.pii_eval                  # table, both splits
python -m supervisor.pii_eval --show-failures  # DEV failing ids by class (never look at held-out items)
python -m supervisor.pii_eval --record --commit <id>   # new baseline, then commit it
python -m supervisor.pii_eval --generate       # rewrite golden set from the seed
python -m supervisor.assurance run pii_canary --target demo --out DIR --no-store
python -m pytest -q tests/pii_eval tests/recorder/test_masking_vn_regex3.py tests/gateway/test_inline_redaction.py tests/assurance/test_security.py
```

## 4. Results (synthetic, ILLUSTRATIVE thresholds; not bank numbers)

Leak recall in bp, v2 -> v3 (dev / held-out):

| Entity | dev | held-out |
|---|---|---|
| PERSON | 5186 -> 9920 | 0 -> 5297 (Wilson 4579-6004) |
| ADDRESS | 1889 -> 10000 | 1904 -> 10000 |
| CCCD, CMND, EMAIL, TAX_CODE, CARD_NUMBER | 10000 -> 10000 | 10000 -> 10000 |
| PHONE | 9919 -> 10000 | 10000 -> 10000 |
| BANK_ACCOUNT | 9166 -> 10000 (precision 5350 -> 10000) | 9512 -> 10000 |
| Amounts intact | 7477 -> 10000 (84 over-masked -> 0) | 7484 -> 10000 (41 -> 0) |

Verdict (validation report): **GO** for structured identifiers, addresses, labelled names, amounts, and to merge. **NO-GO** to rely on the masker alone for names written without a title, label or known surname (held-out PERSON about 53%). Latency about 0.25 ms median per call.

`pii_canary` on sample agents (`--no-store`): `--target demo`: the three `traces:` targets OK, 0 of 256 canaries leaked, 0 false masks (old pack: 102 items, no masker metrics). The three `agent:<id>` sandbox targets FAIL in the old pack and the new pack alike: 40 leaked values on 12 of 34 file probes, because the mock responder repeats PII from retrieved context. Masker metrics for those targets: 0 and 0. Old masker on the matrix: 36 leaks (addresses, telex names); new: 0.

## 5. Existing tests changed

* Version pins `vn_regex-2:` -> `vn_regex-3:` in `tests/recorder/test_capture.py`, `test_masking.py`, `test_masking_vn_regex2.py`, `test_normalise.py` (and `factory.py` docstring).
* `tests/assurance/test_security.py::test_pii_canary_traces_good_vs_bad`: masker metrics on traces are now `0, 0` (active matrix) instead of `None`. New pii_canary tests added. No test removed or skipped.

## 6. Not done (also in BACKLOG)

* No real bank text: every recall figure is synthetic; dev was used to fix the masker (optimistic); held-out is the honest figure.
* Unlabelled names with surnames outside the lexicon; lower-case names with ambiguous surnames (`do`, `ho`, `mai`, `cao`) without label; addresses with no number and no street word.
* Bare JSON numbers are not redacted inline. No per-tool policy-schema flag (a setting is used, to keep `policy_hash` stable).
* Redaction cost about 0.3 ms for short arguments, 3.2 ms for 2 KB; after review it runs before the gate lock (see REVIEW_WP24b.md).
* `INLINE_REDACTION` for HTTP MCP gateway (WP26) must reuse `McpGateProxy`.
* The chain schema is unchanged; the new payload keys are additive.

## 7. Open questions for the owner

1. PERSON recall threshold (illustrative 9500 bp) and whether to accept more false masks for more recall (D17 Open 4).
2. Should `MASK_AMOUNTS` be on for some agents' `masked` capture level?
3. Bank labelled sample: who supplies it, and when?
4. Should the `agent:<id>` sandbox mock stop echoing context PII, or should the pack keep failing it on purpose?

## 8. Neighbour findings (not fixed)

* The shared scratchpad directory is used by other sessions (file name collisions such as `dbg.py`); I used `wp24b_*` names.
* `docs/assurance.md` pack table row for `pii_canary` was not regenerated (it lists two metrics; the pack has four).

## 9. Files touched

New: `src/supervisor/adapters/masking/vn_text.py`, `src/supervisor/gateway/redact.py`, `src/supervisor/assurance/pii_matrix.py`, `src/supervisor/pii_eval/{__init__,__main__,generate,harness}.py`, `data/eval/pii_vn/*`, `tests/pii_eval/*`, `tests/gateway/test_inline_redaction.py`, `tests/recorder/test_masking_vn_regex3.py`, `docs/masking.md`, `docs/masker-model-card.md`, `docs/masker-validation-report.md`, `docs/adr/D17-masker-v3-inline-redaction.md`, `HANDOFF_WP24b.md`.
Edited (shared files, minimal additive edits): `config.py` (WP24b block at the end of the settings class, plus one property), `wiring.py` (gateway masker args + `_redaction_masker`), `adapters/factory.py` (`mask_amounts`), `gateway/engine.py`, `gateway/sdk.py`, `gateway/mcp_proxy.py`, `adapters/masking/vn_regex.py`, `assurance/runners/security.py`, `assurance/packs/pii_canary.yaml` (version 2), `README.md`, `BACKLOG.md`, `.env.example`, `docs/index.md`, `docs/recorder.md`, `docs/threat-model.md`, and the four test files named in section 5.
No schema / DDL change, no new dependency, no subprocess, no network.

## 10. Review follow-up (REVIEW_WP24b.md findings 5, 6, 10, 11)

Code commit `d4e8015`; baselines re-recorded with that id. Suite: **2926 passed, 28 skipped**
(was 2896 before the review fixes and this follow-up). Ruff check and format clean.

| Finding | Done |
|---|---|
| 5 full lexicon | Production ships the full lexicon (Duy, Lâm, Khôi, Thịnh, Quách, Kiều, Tân, Nhân, Thạch, Tống, ... added; `_HELD_BLOCK` removed). `python -m supervisor.pii_eval --ablate-heldout-lexicon` removes the held-out pools at evaluation time only (`vn_text.ablate`, restores on exit). Baseline holds dev (production lexicon), held-out (ablated) and `heldout_production_lexicon` (information only). The lexicon test checks the ablation path and that the shipped lexicon has the common names |
| 6 negatives | `src/supervisor/pii_eval/negatives.py`: 310 negative prose items (UPPER headers with and without diacritics, street and brand names, places, products, amounts, dates, code, English) plus the hand-written negatives. Metric `false_mask` per entity with Wilson interval; ILLUSTRATIVE limit 500 bp; regression test fails on a rise over 100 bp or above the limit. Fixes (dev recall unchanged): `LÝ DO TỪ CHỐI`, `Ho Chi Minh City` and other 3-word provinces, `Võ Văn Kiệt Street` (brand/street suffix within 3 words; `kiệt` no longer a street keyword), product names after `Gói`/`Sản phẩm`, `DO TU` two-word case |
| 10, 11 | SDK (`supervised_tool` on a `pii_export` tool) and `McpGateProxy` log ONE warning per process when the local inline flag is on: it only works if the server flag is on too. Test added |

Numbers (bp; Wilson 95%). Dev (production lexicon): PERSON recall 9920 (9768-9973), ADDRESS 10000, all IDs 10000, amounts intact 10000, false-mask 0 for every entity over 190 negatives (dev was used to fix them). Held-out (lexicon ablated): PERSON 5297 (4579-6004), ADDRESS 10000, IDs 10000, false-mask PERSON 373 (160-844; 5 of 134), others 0. Held-out with production lexicon: PERSON 9891 (contaminated, information only). v2 for contrast: false-mask PERSON 210 dev / 223 held-out, BANK_ACCOUNT 105 / 74.

Not done: `Vũ Trụ Bao La`-style brand names (surname + two unknown words) are still masked; `DO TU` as a 2-word pair is now skipped but `Do Tu` as a real name is lost; the held-out negative failures were not inspected item by item.
