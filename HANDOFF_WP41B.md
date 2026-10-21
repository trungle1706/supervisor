# HANDOFF WP41b: triage of the second benchmark (D31, D32, D26)

Branch `wp41b-triage` (from `phase3-wave2` c30484a). Two commits. No new flag, no new dependency.
All three changes act only with `DETECTORS_ENABLED` on; flag-off fingerprint test unchanged.

## What changed
| Id | Cause | Fix | Files |
|---|---|---|---|
| D31 | Only a transforming detector (`dlp_vn`) failed closed on a cut argument. A cut argument on a credit or money tool was only coverage. | In `DetectorRegistry.run`: a cut `args` part on a money, credit or pii_export call adds a `*:payload_too_large` not_executed row, which fails closed -> `GATE-DETECTOR-FAILED`. read_only and cut tool results stay coverage only. | `core/detectors.py` |
| D32 | The inline masker (`INLINE_REDACTION_ENABLED`, `_pre_redact`) read all 99 KB before the gate refused the call. Detectors, record (`args_masked` = key hashes, no text) and SIEM were cheap. | With the detector gate on and `dlp_vn` enabled, the masker does not run on arguments above the `dlp_vn` `max_scan_bytes` (new `over_budget`, stops reading at the limit; `DetectorGate.redact_budget_bytes`). `args_hmac` still covers the whole argument. No gate or `dlp_vn` off: WP24b behaviour as before (tested). | `gateway/redact.py`, `gateway/detector_gate.py`, `gateway/engine.py` |
| D26 | The built-in pauses (`GATE-PAUSED`, `GATE-SESSION-PAUSE`) have `action: block`, so `derive_status` said `block`. Rule pause and classifier pause were already `pause`. | `Decision.pause_status`; v2 status `pause`. Old `action` stays `block`. Precedence block > pause unchanged. The answer, event row, chain record, SIEM `attrs.status`, `status_of` (drawer, rollup) all read the one value. | `gateway/engine.py`, `gateway/detector_gate.py` |

Note on the D32 brief: "mask only the first max_scan_bytes for the record, store a hash of the rest" does not apply. The record never holds masked argument text. I skipped the masker above the budget instead.

## D32 numbers (99 KB PII-dense pii_export argument, inline redaction on, in-process gateway, SQLite)
| Run | Before fix | After fix (p50 of 9 calls) | Load average |
|---|---|---|---|
| 1 | 817 ms (one call, profiled) | 17 ms | 4.0 |
| 2 | - | 15 ms | 4.0 |
| 3 | - | 15 ms | 4.0 |
Target under 100 ms: met. Bench host figure before the fix was 879 ms. Perf test: `RUN_PERF=1 uv run python -m pytest -q -s tests/detectors/test_wp41b.py -k perf` (marker `perf`).

## Tests
`tests/detectors/test_wp41b.py` (19 tests, 1 perf): four risk classes with a cut argument (block `GATE-DETECTOR-FAILED` for money, credit, pii_export; read_only allowed), small argument still allowed, chain record carries the reason, cut tool result stays coverage only, detectors off unchanged, `over_budget`, masker never reads beyond the budget, no-gate masking unchanged, and every pause source (rule, classifier, state, session) checked in answer, event row, `status_of`, chain record and SIEM event, plus quarantine stays `block`.
Affected modules (detectors, gateway, rbac matrix, monitors, collectors): 1330 passed, 3 skipped. Harness checks (detectors, session, collectors): no drop below baseline. Ruff check and format clean.
Full suite last line: `5208 passed, 32 skipped in 962.09s (0:16:02)`

## Docs
`docs/detectors.md` (section 3b, new "Cut arguments fail closed on every risky tool"; status table), `CHANGELOG.md` (v0.4.0-pre, WP41b), `BACKLOG.md` (D26, D31, D32 closed), `docs/adr/D33-benchmark-defects-m2.md` (addendum).

## Not done / notes
- D32: if `dlp_vn` is disabled or its `fail_closed` is false for an agent, a big pii_export argument is not blocked and not masked (operator choice, as before).
- The bench host figure (879 ms) was not re-measured on the bank host; re-run the probes below.
- Backlog from the triage (not in this WP): D04 design, D30 pilot profile measure, AL-COVERAGE-CUT alert.

## Triage table
| Id | Severity | Decision | Re-run |
|---|---|---|---|
| D31 | High | fixed | `tests/detectors/test_wp41b.py`, `tests/detectors/test_wp41_defects.py`, `tests/detectors/test_wp41_review.py`; bench probe_big_pii_export (credit tool must now block) |
| D32 | Medium | fixed | `RUN_PERF=1 pytest tests/detectors/test_wp41b.py -k perf`; bench probe_big_pii_export, probe_detectors latency |
| D26 | Medium | fixed | `tests/detectors/test_wp41b.py` (pause sources), `tests/gateway`, `tests/monitors/test_session*.py`, `tests/detectors/test_injection_classifier_gate.py`; bench probe_detectors |
