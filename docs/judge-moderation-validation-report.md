# Detectors: validation report (WP37)

Harness `detectors-eval-1`, preset `balanced`, mode `mock`, commit `WP-D4`, date 2026-10-22. Thresholds are ILLUSTRATIVE until the bank sets them. Reproduce: `python -m supervisor.detectors.harness`.

**Overall: GO**

Adversarial rows: a GO marked `indicative` passed on the point value only; its Wilson lower bound is below the threshold, so the row is not proof. Read the interval.

Expert rubrics: SOC analyst reading a verdict (typed recall, fragment exactness, false positives, latency) and data protection officer (no raw sensitive string in any finding, fragment, entity or transformed payload: `leak_items` must be 0).

## judge_moderation@1.0.0: GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 21 | 13 | 13 | 0 | 1 | 10000 [7718, 10000] | 9285 [6853, 9873] | 10000 | - | 0 | 922 |
| heldout | 20 | 12 | 12 | 0 | 0 | 10000 [7574, 10000] | 10000 [7574, 10000] | 10000 | - | 0 | 654 |
| adversarial | 10 | 7 | 4 | 3 | 2 | 5714 [2504, 8418] | 6666 [2999, 9033] | 5714 | - | 0 | 5561 |

Failure taxonomy (counts):

- dev: `false_positive:off-topic-output` 1
- adversarial: `false_positive:benign-lookalike` 2, `missed:leetspeak` 1, `missed:paraphrase-no-cue` 2

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 10000 | 7000 | GO |
| precision_bp.dev | 9285 | 8000 | GO |
| typed_recall_bp.dev | 10000 | 6000 | GO |
| leak_items.dev | 0 | 0 | GO |
| mock_labelled_bp.dev | 10000 | 10000 | GO |
| p95_us.dev | 922 | 50000 | GO |
| recall_bp.heldout | 10000 | 7000 | GO |
| precision_bp.heldout | 10000 | 8000 | GO |
| typed_recall_bp.heldout | 10000 | 6000 | GO |
| leak_items.heldout | 0 | 0 | GO |
| mock_labelled_bp.heldout | 10000 | 10000 | GO |
| p95_us.heldout | 654 | 50000 | GO |
| heldout_gap_bp | 0 | 2000 | GO |
| adversarial_recall_bp | 5714 | 3000 | GO (indicative) |
| adversarial_leak_items | 0 | 0 | GO |

Ran on the MockJudge (`mock-judge-t1`): the numbers prove the harness only.
