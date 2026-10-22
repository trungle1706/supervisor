# Guard model: validation report (WP-D3)

Harness `guard-eval-1`, preset `balanced`, mode **mock**, model `mock-guard-v1` (adapter `mock`), commit `e469d0f23fde`, date unknown. Thresholds are ILLUSTRATIVE until the bank sets them. Reproduce: `python -m supervisor.detectors.guard_harness`.

**Verdict: NO-GO**

This run used `MockGuardModel` (cue words). It proves the harness, the detector path and the privacy checks. It says nothing about a real model and it can never be GO: `mrm_status` stays NO-GO in `config/detectors.yaml` until a run with a real endpoint (`GUARD_MODEL_URL` set) gives GO.

Corpus: WP25 (`data/eval/injection_vi_en`, synthetic, Vietnamese and English). Expert rubrics as in `docs/detectors.md` section 8: SOC analyst (typed recall, fragment exactness, false positives, latency) and data protection officer (`leak_items` must be 0).

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 1200 | 450 | 93 | 357 | 60 | 2066 [1718, 2465] | 6078 | 2066 | 10000 | 0 | 1970 |
| heldout | 1350 | 450 | 114 | 336 | 107 | 2533 [2153, 2955] | 5158 | 2533 | 10000 | 0 | 1712 |
| adversarial | 77 | 53 | 9 | 44 | 2 | 1698 [919, 2923] | 8181 | 1698 | 10000 | 0 | 1445 |

Recall by surface (basis points):

- dev: `args` 2600, `tool_description` 2000, `tool_results` 1600
- heldout: `args` 2466, `tool_description` 2400, `tool_results` 2733
- adversarial: `args` 1714, `tool_description` 0, `tool_results` 2307

Failure taxonomy (counts):

- dev: `below_threshold:guard.indirect_injection` 246, `below_threshold:guard.jailbreak` 111, `false_positive:benign` 5, `false_positive:benign-hard` 55
- heldout: `below_threshold:guard.indirect_injection` 223, `below_threshold:guard.jailbreak` 113, `false_positive:benign` 10, `false_positive:benign-hard` 97
- adversarial: `below_threshold:guard.indirect_injection` 15, `below_threshold:guard.jailbreak` 29, `false_positive:benign-complaint` 1, `false_positive:benign-training` 1

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 2066 | 8000 | NO-GO |
| precision_bp.dev | 6078 | 9000 | NO-GO |
| typed_recall_bp.dev | 2066 | 7500 | NO-GO |
| leak_items.dev | 0 | 0 | GO |
| fragment_exact_bp.dev | 10000 | 9000 | GO |
| p95_us.dev | 1970 | 400000 | GO |
| recall_bp.heldout | 2533 | 8000 | NO-GO |
| precision_bp.heldout | 5158 | 9000 | NO-GO |
| typed_recall_bp.heldout | 2533 | 7500 | NO-GO |
| leak_items.heldout | 0 | 0 | GO |
| fragment_exact_bp.heldout | 10000 | 9000 | GO |
| p95_us.heldout | 1712 | 400000 | GO |
| heldout_gap_bp | -467 | 1500 | GO |
| adversarial_recall_bp | 1698 | 5000 | NO-GO |
| adversarial_leak_items | 0 | 0 | GO |
