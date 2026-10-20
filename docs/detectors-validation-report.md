# Detectors: validation report (WP37)

Harness `detectors-eval-1`, preset `balanced`, mode `mock`, commit `991a808c54b8`, date 2026-10-20. Thresholds are ILLUSTRATIVE until the bank sets them. Reproduce: `python -m supervisor.detectors.harness`.

**Overall: GO**

Expert rubrics: SOC analyst reading a verdict (typed recall, fragment exactness, false positives, latency) and data protection officer (no raw sensitive string in any finding, fragment, entity or transformed payload: `leak_items` must be 0).

## dlp_vn@1.0.0: GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 60 | 40 | 40 | 0 | 0 | 10000 [9123, 10000] | 10000 [9123, 10000] | 10000 | 10000 | 0 | 1123 |
| heldout | 60 | 40 | 40 | 0 | 1 | 10000 [9123, 10000] | 9756 [8740, 9957] | 10000 | 10000 | 0 | 988 |
| adversarial | 14 | 12 | 6 | 6 | 0 | 5000 [2537, 7463] | 10000 [6096, 10000] | 5000 | 10000 | 0 | 226 |

Failure taxonomy (counts):

- heldout: `false_positive:benign` 1
- adversarial: `missed:base64-phone` 1, `missed:dotted-name` 1, `missed:letter-O-for-zero` 1, `missed:obfuscated-email` 1, `missed:spelled-out-digits` 1, `missed:split-across-fields` 1

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 10000 | 9000 | GO |
| precision_bp.dev | 10000 | 9000 | GO |
| typed_recall_bp.dev | 10000 | 8500 | GO |
| leak_items.dev | 0 | 0 | GO |
| fragment_exact_bp.dev | 10000 | 9900 | GO |
| p95_us.dev | 1123 | 20000 | GO |
| recall_bp.heldout | 10000 | 9000 | GO |
| precision_bp.heldout | 9756 | 9000 | GO |
| typed_recall_bp.heldout | 10000 | 8500 | GO |
| leak_items.heldout | 0 | 0 | GO |
| fragment_exact_bp.heldout | 10000 | 9900 | GO |
| p95_us.heldout | 988 | 20000 | GO |
| heldout_gap_bp | 0 | 1500 | GO |
| adversarial_recall_bp | 5000 | 5000 | GO |
| adversarial_leak_items | 0 | 0 | GO |

## injection_regex@1.0.0: GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 60 | 40 | 36 | 4 | 0 | 9000 [7694, 9605] | 10000 [9035, 10000] | 9000 | 10000 | 0 | 253 |
| heldout | 60 | 40 | 36 | 4 | 0 | 9000 [7694, 9605] | 10000 [9035, 10000] | 9000 | 10000 | 0 | 288 |
| adversarial | 20 | 17 | 9 | 8 | 2 | 5294 [3096, 7384] | 8181 [5230, 9487] | 10000 | 10000 | 0 | 334 |

Failure taxonomy (counts):

- dev: `below_threshold:injection.urgent_transfer` 4
- heldout: `below_threshold:injection.urgent_transfer` 4
- adversarial: `false_positive:benign-lookalike` 2, `missed:base64` 1, `missed:beyond-scan-limit` 1, `missed:leetspeak` 1, `missed:paraphrase` 1, `missed:paraphrase-vi` 1, `missed:reversed-text` 1, `missed:split-across-fields` 1, `missed:typo` 1

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 9000 | 8000 | GO |
| precision_bp.dev | 10000 | 9000 | GO |
| typed_recall_bp.dev | 9000 | 7500 | GO |
| leak_items.dev | 0 | 0 | GO |
| fragment_exact_bp.dev | 10000 | 9000 | GO |
| p95_us.dev | 253 | 20000 | GO |
| recall_bp.heldout | 9000 | 8000 | GO |
| precision_bp.heldout | 10000 | 9000 | GO |
| typed_recall_bp.heldout | 9000 | 7500 | GO |
| leak_items.heldout | 0 | 0 | GO |
| fragment_exact_bp.heldout | 10000 | 9000 | GO |
| p95_us.heldout | 288 | 20000 | GO |
| heldout_gap_bp | 0 | 1500 | GO |
| adversarial_recall_bp | 5294 | 4000 | GO |
| adversarial_leak_items | 0 | 0 | GO |

## judge_advisory@1.0.0: GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 60 | 40 | 40 | 0 | 0 | 10000 [9123, 10000] | 10000 [9123, 10000] | 10000 | - | 0 | 836 |
| heldout | 60 | 40 | 40 | 0 | 0 | 10000 [9123, 10000] | 10000 [9123, 10000] | 10000 | - | 0 | 791 |
| adversarial | 4 | 3 | 1 | 2 | 0 | 3333 [614, 7924] | 10000 [2065, 10000] | 10000 | - | 0 | 554 |

Failure taxonomy (counts):

- adversarial: `missed:paraphrase-no-cue` 1, `missed:spaced-letters` 1

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 10000 | 7000 | GO |
| precision_bp.dev | 10000 | 8000 | GO |
| typed_recall_bp.dev | 10000 | 5000 | GO |
| leak_items.dev | 0 | 0 | GO |
| mock_labelled_bp.dev | 10000 | 10000 | GO |
| p95_us.dev | 836 | 50000 | GO |
| recall_bp.heldout | 10000 | 7000 | GO |
| precision_bp.heldout | 10000 | 8000 | GO |
| typed_recall_bp.heldout | 10000 | 5000 | GO |
| leak_items.heldout | 0 | 0 | GO |
| mock_labelled_bp.heldout | 10000 | 10000 | GO |
| p95_us.heldout | 791 | 50000 | GO |
| heldout_gap_bp | 0 | 2000 | GO |
| adversarial_recall_bp | 3333 | 3000 | GO |
| adversarial_leak_items | 0 | 0 | GO |

Ran on the MockJudge (`mock-judge-t1`): the numbers prove the harness only.
