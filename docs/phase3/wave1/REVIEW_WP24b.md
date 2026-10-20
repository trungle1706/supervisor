# REVIEW WP24b: masker vn_regex-3, inline redaction, pii_canary v2, PII eval harness

Reviewer: Opus (views: bank DPO under PDPL 91/2025, NLP evaluation engineer, senior Python
engineer). Date 2026-10-20. Branch `worktree-agent-a44bc574614ace41d`, base main `bf3a23a`.
Reviewed: the full `git diff main...HEAD`, HANDOFF, `docs/masking.md`, validation report, ADR.

## 1. Verdict

**APPROVE WITH FIXES.** The fixes are on the branch (7 review commits, `e333909`..`f2ffb0b`).
The harness is sound and the numbers reproduce exactly. I found one High leak (identifiers
before the word "đồng" were taken as amounts) and fixed it. Two design items stay open for the
owner (lexicon block for held-out names, negative prose corpus).

## 2. Findings

| # | Sev | File:line | Issue | Action |
|---|---|---|---|---|
| 1 | High | `adapters/masking/vn_text.py:522` (`_RE_AMT_CUR_AFTER`), `vn_regex.py` 3 currency skips | "đồng" / "dong" / "đ" is also a word ("đồng ý", "đồng thời", "dong bang"). An ID before it was claimed as an AMOUNT (priority 110) or skipped as "currency after". It was not masked: `CCCD 079203001234 đồng thời`, `SĐT 0912 345 678 đồng ý`, `STK 1903 4567 8901 23 đồng`, `thẻ 4111... đồng thời`, `CMND 123 456 789 đồng thời`. Phones and cards before "đồng" were masked by v2, so this is a v3 regression. The golden-set templates never put "đồng" after an ID, so the harness did not see it | **Fixed** `e333909`: `vn_text.id_shaped()` (`:554`) and `vn_regex._currency_after()` (`:229`). A leading 0, an ID label, a Luhn card or account-style grouping means an identifier. Space-grouped tails ("079 203 001 234 đồng") are checked as one run. Real amounts stay intact (tests). 9 leak tests + 5 keep tests added. Eval numbers unchanged |
| 2 | Medium | `vn_text.py:188` loose labels, `:351` | A loose title word inside a name cut the name. "Nguyễn Anh Tuấn" gave `Nguyễn Anh <PERSON>`, so the surname and middle name leaked (same for "Lê Chi Mai", "Mai Anh Tuấn"). The labelled span (prio 65) beat the longer plain span (prio 45) | **Fixed** `e333909`: `_merge_labelled` grows a labelled span over the plain span it overlaps. Same pseudonym in every form. Found by an independent probe, not from held-out items. Held-out numbers unchanged |
| 3 | Medium | `gateway/engine.py:755` | When the masker raised, the gate allowed the pii_export call without `transformed_args`. The tool then ran with the raw values although both switches were on (fail open) | **Fixed** `ae47d22`: block with `GATE-REDACTION`, `fail_mode=closed`. This is deterministic, so R1 holds. Test added |
| 4 | Medium | `gateway/engine.py:713` | The masker pass ran inside the gate RLock. It costs 3.2 ms for a 2 KB payload, not the 0.3 ms in the handoff, and it delayed the decisions of all other agents | **Fixed** `60dc8f5`: the pass runs before the lock for tools known or declared as pii_export. The policy risk class under the lock still decides, and masks there when the hint missed. A test shows the same answer on both paths. Numbers in section 4 |
| 5 | Medium (design) | `vn_text.py:53` `_HELD_BLOCK` | To keep the held-out split honest, the SHIPPED lexicon removes the held-out pools. Common real names are then no longer lexicon words in production: Duy, Lâm, Khôi, Thịnh, Vĩnh, Nhật, Quách, Kiều, Tống, Thạch, and by folding also Tân, Nhân, Lam, Huế. Production recall is lower on purpose, and the validation report reads as if these names were just "unknown" | **Recorded** (ADR D17 note). Recommendation: ship the full lexicon. Measure held-out with a lexicon-ablated masker (`with vn_text.ablate(HELD_*)`), and label that figure "out-of-lexicon generalisation". Owner decision, because the baseline semantics change |
| 6 | Medium (design) | `data/eval/pii_vn/` | Precision is 10000 on both splits, but the set has only 7 negative items. Probes show over-masking of UPPER headers (`LÝ DO TỪ CHỐI` -> `<PERSON> CHỐI`), street and brand names (`Võ Văn Kiệt Street`, `Hoang Long Group`, `Vũ Trụ Bao La`) and `Ho Chi Minh` -> `Ho Chi <PERSON>` | **Recorded**. Add a negative corpus (>= 200 bank prose lines, headers, product names, code) with a false-mask rate metric and a Wilson interval |
| 7 | Low | ADR numbering | WP20 also created `docs/adr/D14-ingress-auth.md` | **Fixed** `3888f56`: `git mv` to `D17-masker-v3-inline-redaction.md`. Links fixed in HANDOFF, BACKLOG, docs/masking.md and docs/index.md |
| 8 | Low | `docs/masker-validation-report.md:25,82` | "demo target OK" was not exact. `--target demo` runs 3 `traces:` targets (OK) and 3 `agent:` targets (FAIL on the mock reply). The auto `report.md` "Why" line does not say that the FAIL is a target failure. Only the masker metrics (0) show it | **Fixed** `fd6a518` (validation report and handoff). The auto report wording is not changed |
| 9 | Low | `data/eval/pii_vn/baseline_vn_regex-3.json` | `commit` was `wp24b-final`, which is not a commit id | **Fixed** `f2ffb0b`: re-recorded with `60dc8f5`. Only the latency fields changed |
| 10 | Low | `tests/recorder/test_masking_vn_regex3.py:47` | `test_names_are_masked` checks only the LAST name word. A partial leak (finding 2) passes it | New test `test_title_word_inside_a_name_does_not_cut_the_name`. Suggest: assert every name word is gone |
| 11 | Low (design) | `gateway/sdk.py:180`, `mcp_proxy.py:94` | SDK / proxy with inline ON against a server with the flag OFF runs the tool with raw values and gives no signal. This is documented ("both must be on") | Recorded. Optional strict mode: refuse a `pii_export` call when the local flag is on and the answer has no `transformed_args` but has PII |
| 12 | Info | `gateway/redact.py` | Bare JSON numbers (phone as int) and dict keys are not redacted | Known gap, in BACKLOG |

Checked and OK, with no action:
* Keyed HMAC, pseudonym format and determinism are unchanged. CCCD and phone tokens are the same in v2 and v3. `normalise` only adds AMOUNT.
* Amounts are found before accounts. Unicode is normalised: NFD input, zero-width and soft hyphen inside a name, full-width digits and NBSP all give the same token.
* No catastrophic backtracking. 34 adversarial 20,000-character inputs (name runs, digit groups, address keywords, labels, JSON keys, units): worst case 81 ms.
* Inline redaction is correct. Rules are decided on the original arguments (PAY-09 window test with a phone-shaped customer id). `transformed_args` is applied only when the server and the SDK/proxy are both on. The SDK refuses when it cannot bind. The MCP proxy forwards the masked `arguments`. The chain has `args_hmac` + `args_hmac_transformed` + count + version and no values (R2). SHADOW and PAUSED give no `transformed_args` (tests added).
* Removed lower-case-permissive regexes: **I accept this.** v3 still masks every lower-case name I tried that has a distinctive surname or `thi`/`van` (`nguyen minh tuan`, `le minh duc`, `do van hung`, `pham van dong`). v2 masked prose (`xu ly trong bao lau`). The remaining miss is an ambiguous surname with no middle marker (`cao van lau` is not masked in v2 or v3). For a DPO, a false mask in free text costs less than a leak, but a mask that breaks prose also damages judge and rule input. The right lever is the capture level (`digest` for free text), not looser regexes.
* No false masks on code or JSON keys (`nguyen_van_a`, `"ten": "get_balance"`, SQL column names).
* R1, R3, flags OFF by default, no new dependency (no change to pyproject or uv.lock), no secrets (fixed keys are synthetic and labelled), ASCII CLI output, no DDL change, no route change (no new 500 path). The settings pattern validates `INLINE_REDACTION_TOOLS`.

## 3. Harness integrity

| Check | Result |
|---|---|
| Held-out separation | Own seed (`20261020+1`), own name, street and ward pools. Test `test_heldout_name_pools_stay_out_of_the_lexicon` passes. I looked only at held-out AGGREGATES |
| Wilson 95% | Formula correct. 81/100 -> (7222, 8749) bp, the textbook value (0.7222, 0.8749). 20/20 -> (8388, 10000). 0/20 -> (0, 1612) |
| Failure taxonomy | Sound: missed / partial per entity x case x diacritics form, false-, wrong-type-, over-mask-<kind>. Gap: few negatives (finding 6) |
| Regression test | Deterministic, so there is no noise. I checked that it fails on real regressions: with the address finder off, dev ADDRESS goes 10000 -> 1889; with the amount finder off, 84 amounts are over-masked |
| Dev spot check (20 random, seed 7) | Labels correct on 20/20 (spans, keeps, tags). Note: template diversity is low (the CCCD template is always followed by "đề nghị vay"), which is why finding 1 was missed |
| Hard cases (61: 46 dev, 15 held-out) | Cover the 2026-10-15 leaks: 6 items with UPPER-case names, 10 address items, 5 amount-next-to-account items, 6 JSON-float amount items (`9100000000.0`) |
| v2 baseline | Reproduced from `git show main:.../vn_regex.py`: same per-entity recall and taxonomy on both splits |

## 4. Numbers reproduced

`python -m supervisor.pii_eval` (after the fixes, the same as the committed baseline):

| Entity | dev leak recall bp (Wilson) | held-out leak recall bp (Wilson) |
|---|---|---|
| PERSON | 9920 (9768-9973), n 376 | 5297 (4579-6004), n 185 |
| ADDRESS | 10000 (9706-10000) | 10000 (9425-10000) |
| CCCD, CMND, PHONE, EMAIL, TAX_CODE, BANK_ACCOUNT, CARD_NUMBER | 10000 | 10000 |
| Amounts intact | 333/333, 0 over-masked | 163/163, 0 over-masked |
| Precision | 10000 every entity | 10000 every entity |

v2 on the same set (base code): PERSON 5186 / 0, ADDRESS 1889 / 1904, BANK_ACCOUNT 9166 / 9512, over-masked amounts 84 / 41.

pii_canary matrix: 256 canaries (9 entities x forms x 4 surfaces). Old masker (`bf3a23a`), run by me: **36 leaked values** on 32 canaries (ADDRESS upper, upper no-diacritics, abbreviated; PERSON telex). New masker: **0 leaked, 0 false masks**. Pack run `--target demo --no-store`: `traces:` x3 OK; `agent:` x3 FAIL with `unmasked_pii_count=40`, `leak_rate_bp=3529`, `masker_unmasked_count=0`. That is the mock agent repeating context PII (a target failure, not a masker failure). The report now says this.

Inline redaction latency (this host, SQLite, 2 KB args, 500 calls after warm-up):

| Measure | Value |
|---|---|
| `redact_args` on a 2 KB payload | p50 3.2 ms, p95 3.3 ms |
| `check()` wall time, add_payee, redaction off / on | p50 3.5 / 7.9 ms, p95 5.3 / 10.6 ms |
| read-only `get_balance` p95 with 3 threads sending 2 KB add_payee calls, masker inside lock (before) / before lock (after) | 22.8 ms / 15.9 ms |

## 5. Tests and lint

| | Before review | After review |
|---|---|---|
| `python -m pytest -q -x` (worktree `.venv`) | 2896 passed, 28 skipped | **2920 passed, 28 skipped** (4 min 36 s) |
| `ruff check .`, `ruff format --check .` | clean | clean |

Note: on this host `python` is not on PATH. Use `.venv/bin/python -m ...` or `uv run`.

## 6. Residual risks

1. PERSON recall on names with no title, no label and no known surname: held-out about 53%. With finding 5, production is worse than it must be for common names such as Duy, Lâm, Khôi. Keep free-text capture at `digest` until a bank sample shows >= 9500 bp.
2. All figures are synthetic, and the generator and the masker were written by the same team. The templates have low diversity (finding 1 was found by a probe, not by the set).
3. Over-masking of UPPER headers, street names and brand names (finding 6) can change judge input. This is not measured.
4. Silent raw pass-through when only the SDK/proxy flag is on (finding 11).
5. The pseudonyms can be reversed by anyone who holds the key. Key custody belongs to the bank.

Future WP (design): a small Vietnamese NER model (for example a distilled PhoBERT or an
underthesea-style CRF token tagger) as an OPTIONAL extra for PERSON recall. It needs wheels
on Nexus, a model card under `judge/mrm/` and the same golden set. The regex finders stay the
default and the floor.

## 7. Merge notes

| File | Risk | Note |
|---|---|---|
| `gateway/engine.py` | High | WP22 adds a `latency_us` line in `_decide` / `Decision`. This branch adds 3 Decision fields, `as_result` extras, `__init__` args, `_pre_redact` before `with self._lock:`, the `_redact` call after `d.fail_mode = fail_mode`, and `_payload` extras. Keep all of them. `_pre_redact` must stay OUTSIDE the lock |
| `gateway/sdk.py` | Medium | WP20 (ingress auth headers in HttpGate). This branch adds a block after `_default_gate` and one `apply_transformed` line in each of the two wrappers |
| `gateway/mcp_proxy.py` | Medium | WP20. Additive: `inline_redaction` kw-only arg, 3 lines in the allow branch, a `--inline-redaction` CLI flag |
| `config.py` | Low | `# --- WP24b ---` block at the end of the settings class, plus the `inline_redaction_tool_set` property |
| `wiring.py` | Low | 3 kwargs in `_make_gateway` and `_redaction_masker()` |
| `docs/adr/` | Low | Now D17. `docs/index.md` row says "D01 to D13, D17". The integrator sets the final range |
| `tests/recorder/*` version pins | Low | `vn_regex-2:` -> `vn_regex-3:` in 4 tests. Any other WP that pins `mask_version` must follow |

No DDL change, no new table, no new dependency. No push and no merge was done.
