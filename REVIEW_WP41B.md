# REVIEW WP41b: triage fixes D31, D32, D26 (bank security review)

Reviewer: Opus. Branch `wp41b-triage`, delta `phase3-wave2...HEAD` (dc8fde0, 95b9bf5, c044419).
Review commits on the branch: 533f212 (D31 guard), 1dd7e6d (D32 gap, docs), plus this file and a
BACKLOG line in the last commit.

## Verdict

**APPROVED WITH FOLLOW-UPS.** Two High findings were found and fixed on the branch (F1, F2). The
follow-ups are Low and are in BACKLOG.

## 1. D31: a cut argument fails closed

| Check | Result |
|---|---|
| Default set (dlp_vn + injection_regex), money / credit / pii_export | block `GATE-DETECTOR-FAILED` (author tests) |
| Only `injection_regex` enabled (dlp_vn off), credit and pii_export | block (new probe) |
| dlp_vn `fail_closed: false`, injection_regex `fail_closed: true`, pii_export | **was ALLOWED** (F1); block after fix |
| Every detector disabled for the agent, `DETECTORS_ENABLED=1` | no detector runs, so no budget cut; allowed, `detectors: []` (same as detectors off for that agent) |
| Classifier only | the cut is listed in `coverage` and `not_executed`; no block (R1: the classifier may not fail closed) - Low L1 |
| read_only, cut tool result | coverage only (author tests) |
| Output direction | not affected (new probe) |
| Flag off | `tests/detectors/test_flag_off_fingerprint.py` passes unchanged |

**F1 (High, fixed 533f212).** The new rule skipped its `*:payload_too_large` row when ANY
`payload_too_large` row was already present. dlp_vn adds such a row when its transform is cut, but
with `fail_closed: false` that row does not block. Result: a 99 KB pii_export argument was allowed
with status `report` while injection_regex was `fail_closed: true`. Fix: the guard counts only rows
that close; the closing test is one helper `DetectorRegistry._closes` (also used by the final loop,
no change of behaviour there).

## 2. D32: masker budget

| Check | Result |
|---|---|
| `over_budget` on str, nested dict, list, tuple, bytes, bytearray, lone surrogate, 3-byte UTF-8 | correct (10 parametrised cases); bytes are not counted (the masker does not read them either) |
| Stops at the limit | yes, across leaves (spy test: stops at the 3rd of 10,000 leaves). Inside one leaf it encoded the whole string; now a string longer than the budget answers at once (UTF-8 >= 1 byte per char) |
| Masker below the budget | still runs (author test) |
| Gate off / dlp_vn off | code path unchanged: `redact_budget_bytes()` is None; masker output equals `redact_args` byte for byte (new test) |
| `args_masked` holds names and key hashes only | true for the gate row: `engine.py` writes `canonical_json({"keys": keys})`. The OTLP recorder (`recorder/normalise.py`) masks span text separately, without a budget - Low L4 |
| Handoff "D32 gap" | **not acceptable** (F2) |

**F2 (High, fixed 1dd7e6d).** Above the dlp_vn budget the masker was skipped in every
configuration, but the call is refused only when a fail-closed detector closes it. In these
configurations the loader accepts, a 99 KB pii_export argument reached the tool **unmasked** (WP24b
masked it before): dlp_vn `fail_closed: false` (with or without injection_regex closed),
`fail_closed_risk_classes: [money]`, every detector disabled for the agent while dlp_vn is on
globally. Refusing these configurations is wrong (they are valid for small arguments), so the fix
is on the call: the masker is skipped only when the detector pre-pass already fails the call
closed and observe will not lift it (`_detector_fails_closed` in `engine.py`; the pre-pass now runs
before `_pre_redact` so the skip is decided outside the lock too). Otherwise the masker masks the
full text as in WP24b. Tests: `test_big_pii_export_argument_is_never_sent_unmasked[*]`,
`..._with_detectors_disabled_for_the_agent`, `test_observe_mode_never_lets_...` (4 of them failed
before the fix).

## 3. D26: status pause

| Source | answer | event row / `status_of` | chain | SIEM attrs |
|---|---|---|---|---|
| rule pause | pause | pause | pause | pause |
| classifier pause | pause | pause | pause | pause |
| state `GATE-PAUSED` | pause (`action` stays block) | pause | pause | pause |
| session `GATE-SESSION-PAUSE` | pause (`action` stays block) | pause | pause | pause |
| quarantined | block | block | block | block |

All from author tests `tests/detectors/test_wp41b.py`; drawer and rollup read `status_of` /
`verdict_status` (checked `jobs/decision_rollup.py`, `analytics/decisions.py`). The alert signal
`_enforcement` treats block and pause both as `enforced`, so AL-THREAT-NOT-ENFORCED is unchanged;
`tests/console` and `tests/alerts` pass. Precedence block > pause holds for rules (`derive_status`
with `matched_actions`). A built-in pause is decided before the rules run, so a block rule that
would also match is not seen and the status is `pause` (the call is refused either way) - Low L2.

## 4. Performance (99 KB pii_export, fail closed, inline redaction on)

`RUN_PERF=1 uv run python -m pytest -q -s tests/detectors/test_wp41b.py -k perf`, after the fixes:

| Run | p50 | Load average (1 min) |
|---|---|---|
| 1 | 14 ms | 1.93 |
| 2 | 15 ms | 1.93 |
| 3 | 16 ms | 1.93 |

The test is marked `perf` (marker registered in `pyproject.toml`) and skipped without `RUN_PERF=1`.
Where nothing refuses the call (F2 configurations) the full masker runs again: WP24b cost, about
800 ms for 99 KB - Low L3, an operator choice.

## 5. Docs

`docs/detectors.md` 3b, ADR D33 addendum, CHANGELOG and BACKLOG now state the F1/F2 rules. The
author's handoff line "D32 gap ... operator choice, as before" is superseded by this review.

## Tests run

| Scope | Result |
|---|---|
| tests/detectors, gateway, console, alerts, monitors, collectors | 2031 passed, 3 skipped |
| tests/detectors/test_wp41b_review.py (new, 24 tests) | 24 passed |
| ruff check, ruff format --check | clean |
| Full suite `uv run python -m pytest -q -p no:cacheprovider` | `5232 passed, 32 skipped in 951.84s (0:15:51)` (author: 5208 + 24 new) |

## Triage

| Id | Finding | Severity | Decision | Re-run |
|---|---|---|---|---|
| F1 | dlp_vn `fail_closed: false` cut row hid the D31 `*` row: cut pii_export argument allowed | High | fixed 533f212 | `tests/detectors/test_wp41b_review.py`, `test_wp41b.py`, `test_wp41_review.py`; bench probe_big_pii_export |
| F2 | over-budget pii_export argument sent unmasked when nothing fails the call closed | High | fixed 1dd7e6d | `tests/detectors/test_wp41b_review.py`, `tests/gateway`; bench probe_big_pii_export with `fail_closed: false` |
| F3 | `over_budget` encoded a whole long non-ASCII leaf | Low (trivial) | fixed 1dd7e6d | `tests/detectors/test_wp41b_review.py -k over_budget` |
| L1 | classifier-only set: a cut argument stays coverage | Low | BACKLOG (owner decision, R1) | `test_cut_argument_with_a_classifier_only_set` |
| L2 | built-in pause hides a block rule that would also match (status pause) | Low | BACKLOG | `tests/detectors/test_wp41b.py -k pause` |
| L3 | full masking cost (about 800 ms / 99 KB) where nothing refuses the call | Low | BACKLOG | perf probe with `fail_closed: false` |
| L4 | OTLP recorder masks span text with no budget | Low | BACKLOG | `tests/collectors` |
