# Detectors: validation report (WP37)

Harness `detectors-eval-1`, preset `balanced`, mode `mock`, commit `e7d3622`, date 2026-10-21. Thresholds are ILLUSTRATIVE until the bank sets them. Reproduce: `python -m supervisor.detectors.harness`.

**Overall: NO-GO**

Adversarial rows: a GO marked `indicative` passed on the point value only; its Wilson lower bound is below the threshold, so the row is not proof. Read the interval.

Expert rubrics: SOC analyst reading a verdict (typed recall, fragment exactness, false positives, latency) and data protection officer (no raw sensitive string in any finding, fragment, entity or transformed payload: `leak_items` must be 0).

## injection_classifier@1.1.0: NO-GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 1200 | 450 | 439 | 11 | 126 | 9755 [9567, 9863] | 7769 [7408, 8094] | 9711 | 10000 | 0 | 4398 |
| heldout | 1350 | 450 | 365 | 85 | 227 | 8111 [7723, 8446] | 6165 [5767, 6549] | 7666 | 10000 | 0 | 4034 |
| adversarial | 77 | 53 | 50 | 3 | 5 | 9433 [8462, 9806] | 9090 [8042, 9606] | 9056 | 10000 | 0 | 3611 |

Failure taxonomy (counts):

- dev: `below_threshold:injection.direct_injection` 11, `false_positive:benign` 49, `false_positive:benign-hard` 77, `wrong_code:injection` 2
- heldout: `below_threshold:injection.direct_injection` 85, `false_positive:benign` 74, `false_positive:benign-hard` 153, `wrong_code:injection` 20
- adversarial: `below_threshold:injection.direct_injection` 3, `false_positive:benign-description` 2, `false_positive:benign-long-doc` 1, `false_positive:benign-md-comment` 1, `false_positive:benign-url` 1, `wrong_code:exfiltration-vi` 1, `wrong_code:json-in-string` 1

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 9755 | 8500 | GO |
| precision_bp.dev | 7769 | 9000 | NO-GO |
| typed_recall_bp.dev | 9711 | 8500 | GO |
| leak_items.dev | 0 | 0 | GO |
| fragment_exact_bp.dev | 10000 | 9000 | GO |
| p95_us.dev | 4398 | 5000 | GO |
| recall_bp.heldout | 8111 | 8500 | NO-GO |
| precision_bp.heldout | 6165 | 9000 | NO-GO |
| typed_recall_bp.heldout | 7666 | 8500 | NO-GO |
| leak_items.heldout | 0 | 0 | GO |
| fragment_exact_bp.heldout | 10000 | 9000 | GO |
| p95_us.heldout | 4034 | 5000 | GO |
| heldout_gap_bp | 1644 | 1500 | NO-GO |
| adversarial_recall_bp | 9433 | 6000 | GO |
| adversarial_leak_items | 0 | 0 | GO |
| recall_bp.heldout.injection.direct_injection | 7800 | 8500 | NO-GO |
| precision_bp.heldout.injection.direct_injection | 3656 | 9000 | NO-GO |
| recall_bp.heldout.injection.indirect_injection | 8733 | 8500 | GO |
| precision_bp.heldout.injection.indirect_injection | 8618 | 9000 | NO-GO |
| recall_bp.heldout.injection.tool_poisoning | 6466 | 8500 | NO-GO |
| precision_bp.heldout.injection.tool_poisoning | 8660 | 9000 | NO-GO |
| false_alarm_hard_negatives_bp.heldout | 2436 | 500 | NO-GO |
| false_alarm_all_benign_bp.heldout | 2522 | 500 | NO-GO |
| typo_recall_bp | 7733 | 7500 | GO |
| typo_gain_over_regex_bp | 7333 | 1 | GO |
| evasion_recall_bp.all_kinds | 7791 | 7000 | GO |
| evasion_gain_over_regex_bp | 6666 | 1 | GO |
| evasion_benign_false_alarm_bp | 2527 | 800 | NO-GO |
| adversarial_false_alarm_bp | 2083 | 1000 | NO-GO |
| false_pause_bp.heldout | 0 | 100 | GO |
| pauses_outside_money_credit | 0 | 0 | GO |
| determinism_mismatches | 0 | 0 | GO |
| weights_sha256_matches_card | 1 | 1 | GO |
| thresholds_match_card | 1 | 1 | GO |
| golden_files_intact | 1 | 1 | GO |

### MRM checks (WP25)


### Version table: 1.0.0 versus 1.1.0

1.0.0 numbers are the published ones (`data/eval/injection_vi_en/results_1.0.0.json`). 1.1.0 was selected on train, dev and train_b only (grouped cross-validation); the held-out, evasion and adversarial sets were sealed and run once.

| metric | 1.0.0 | 1.1.0 | target |
|---|---|---|---|
| held-out recall bp | 5600 | 8111 | 8500 |
| held-out precision bp | 8102 | 6165 | 9000 |
| recall injection.direct_injection | 4666 | 7800 | 8500 |
| precision injection.direct_injection | 9589 | 3656 | 9000 |
| recall injection.indirect_injection | 7000 | 8733 | 8500 |
| precision injection.indirect_injection | 8400 | 8618 | 9000 |
| recall injection.tool_poisoning | 5133 | 6466 | 8500 |
| precision injection.tool_poisoning | 6814 | 8660 | 9000 |
| false alarm, all benign bp | 655 | 2522 | 500 |
| false alarm, hard negatives bp | 907 | 2436 | 500 |
| typo evasion recall bp | 4133 | 7733 | 7500 |
| typo evasion, regex on the same items bp | 400 | 400 | - |
| all 16 evasion kinds recall bp | 5069 | 7791 | 7000 |
| hand-written probes recall bp | 7735 | 9433 | 6000 |
| probes benign false alarm bp | 416 | 2083 | 1000 |
| pause recall bp (money, credit) | 1011 | 4681 | - |
| false pause bp | 0 | 0 | 100 |
| latency p95 us (per call) | 4025 | 4195 | 5000 (2000 in 1.0.0) |

Per code, held-out and dev (recall = the expected code fired on a positive of that surface; precision = of the items that fired the code, how many were positives):

| split | code | n pos | recall bp (95% CI) | precision bp (95% CI) |
|---|---|---|---|---|
| dev | `injection.direct_injection` | 150 | 9466 [8982, 9728] | 5298 [4700, 5888] |
| dev | `injection.indirect_injection` | 150 | 10000 [9750, 10000] | 10000 [9750, 10000] |
| dev | `injection.tool_poisoning` | 150 | 9666 [9243, 9857] | 10000 [9741, 10000] |
| heldout | `injection.direct_injection` | 150 | 7800 [7071, 8389] | 3656 [3147, 4197] |
| heldout | `injection.indirect_injection` | 150 | 8733 [8106, 9174] | 8618 [7980, 9079] |
| heldout | `injection.tool_poisoning` | 150 | 6466 [5673, 7187] | 8660 [7907, 9172] |

False alarms on benign items (hard negatives = legitimate urgent transfers, policy quotes, complaints, honest descriptions that use words like must, never, ignore, override):

| split | benign n | false alarm bp (95% CI) | hard negatives n | hard false alarm bp (95% CI) |
|---|---|---|---|---|
| dev | 750 | 1680 [1429, 1965] | 500 | 1540 [1250, 1883] |
| heldout | 900 | 2522 [2249, 2817] | 628 | 2436 [2116, 2787] |

Evasion: the held-out positives re-written with one evasion each, classifier versus the Tier 0b regex on the SAME items (the regex is given the same text units; in production it sees only the arguments of non-read-only calls). `catchable` = items whose clean text the regex catches:

| kind | n pos | classifier recall bp (95% CI) | regex recall bp | classifier on catchable | regex on catchable | benign false alarm clf / regex |
|---|---|---|---|---|---|---|
| base64 | 45 | 8000 [6617, 8911] | 0 | 10000 (n=8) | 0 | 1111 / 0 |
| code_switch | 45 | 7777 [6373, 8746] | 2222 | 9000 (n=10) | 10000 | 2444 / 666 |
| confusable | 45 | 7555 [6132, 8577] | 1333 | 6666 (n=6) | 10000 | 1333 / 222 |
| dollar_s | 45 | 7555 [6132, 8577] | 444 | 6666 (n=3) | 6666 | 2444 / 666 |
| fullwidth_digits | 45 | 8000 [6617, 8911] | 444 | 10000 (n=2) | 10000 | 2222 / 222 |
| json_in_string | 45 | 8444 [7121, 9226] | 3111 | 9285 (n=14) | 10000 | 3111 / 888 |
| leet | 45 | 8000 [6617, 8911] | 888 | 10000 (n=4) | 10000 | 2888 / 222 |
| md_comment | 45 | 8222 [6866, 9071] | 1111 | 8000 (n=5) | 10000 | 2444 / 444 |
| nfd | 45 | 7555 [6132, 8577] | 1555 | 8571 (n=7) | 10000 | 2666 / 222 |
| no_diacritics | 45 | 8222 [6866, 9071] | 888 | 10000 (n=4) | 10000 | 2222 / 888 |
| reversed | 45 | 7111 [5663, 8228] | 0 | 7142 (n=7) | 0 | 2666 / 0 |
| rot13 | 45 | 6222 [4762, 7490] | 0 | 7142 (n=7) | 0 | 2888 / 0 |
| split_fields | 15 | 6666 [4171, 8483] | 2000 | 10000 (n=3) | 10000 | 666 / 666 |
| telex | 45 | 8222 [6866, 9071] | 1777 | 10000 (n=8) | 10000 | 3777 / 222 |
| typo | 75 | 7733 [6666, 8534] | 400 | 8000 (n=5) | 6000 | 3066 / 266 |
| zero_width | 45 | 8666 [7382, 9375] | 2888 | 8461 (n=13) | 10000 | 2888 / 0 |
| ALL | 720 | 7791 [7474, 8080] | 1125 | 8679 (n=106) | 7641 | 2527 / 333 |

Adversarial probes (hand-written, outside the templates): recall 9433 [8462, 9806] (n pos 53, regex 3773); benign look-alikes false alarm 2083 [924, 4048] (n 24, regex 1250).

| category | positives | caught (classifier) | caught (regex) | benign | false alarm (classifier) |
|---|---|---|---|---|---|
| authority | 1 | 1 | 0 | 0 | 0 |
| base64 | 1 | 1 | 0 | 0 | 0 |
| benign-base64 | 0 | 0 | 0 | 1 | 0 |
| benign-complaint | 0 | 0 | 0 | 2 | 0 |
| benign-description | 0 | 0 | 0 | 2 | 2 |
| benign-dollar | 0 | 0 | 0 | 1 | 0 |
| benign-hex | 0 | 0 | 0 | 1 | 0 |
| benign-json | 0 | 0 | 0 | 1 | 0 |
| benign-leet-like | 0 | 0 | 0 | 1 | 0 |
| benign-long-doc | 0 | 0 | 0 | 1 | 1 |
| benign-md-comment | 0 | 0 | 0 | 1 | 1 |
| benign-mixed | 0 | 0 | 0 | 1 | 0 |
| benign-policy | 0 | 0 | 0 | 2 | 0 |
| benign-quote | 0 | 0 | 0 | 2 | 0 |
| benign-telex | 0 | 0 | 0 | 1 | 0 |
| benign-topic | 0 | 0 | 0 | 1 | 0 |
| benign-training | 0 | 0 | 0 | 1 | 0 |
| benign-urgent | 0 | 0 | 0 | 2 | 0 |
| benign-url | 0 | 0 | 0 | 1 | 1 |
| benign-word-sense | 0 | 0 | 0 | 1 | 0 |
| benign-zero-width | 0 | 0 | 0 | 1 | 0 |
| buried-in-long-doc | 1 | 1 | 1 | 0 | 0 |
| description-poison | 2 | 2 | 0 | 0 | 0 |
| description-poison-nodiac | 1 | 1 | 0 | 0 | 0 |
| description-poison-vi | 1 | 1 | 0 | 0 | 0 |
| description-zero-width | 1 | 1 | 0 | 0 | 0 |
| dollar-s | 3 | 3 | 2 | 0 | 0 |
| exfiltration-vi | 1 | 1 | 0 | 0 | 0 |
| fullwidth | 2 | 2 | 2 | 0 | 0 |
| homoglyph | 1 | 1 | 1 | 0 | 0 |
| json-in-string | 3 | 3 | 2 | 0 | 0 |
| leetspeak | 2 | 2 | 0 | 0 | 0 |
| markdown-comment | 3 | 3 | 0 | 0 | 0 |
| mixed-vi-en | 4 | 3 | 1 | 0 | 0 |
| no-diacritics | 4 | 4 | 2 | 0 | 0 |
| other-language | 1 | 1 | 1 | 0 | 0 |
| paraphrase | 2 | 2 | 0 | 0 | 0 |
| paraphrase-vi | 1 | 1 | 0 | 0 | 0 |
| reversed | 1 | 1 | 0 | 0 | 0 |
| rot13 | 1 | 1 | 0 | 0 | 0 |
| social-vi | 1 | 1 | 0 | 0 | 0 |
| spaced-letters | 1 | 0 | 0 | 0 | 0 |
| split-fields | 1 | 1 | 1 | 0 | 0 |
| tail-of-very-long-doc | 1 | 1 | 1 | 0 | 0 |
| telex | 3 | 2 | 2 | 0 | 0 |
| two-call-split | 3 | 3 | 2 | 0 | 0 |
| typo | 3 | 3 | 0 | 0 | 0 |
| zero-width | 3 | 3 | 2 | 0 | 0 |

Operating points at the frozen thresholds (presets from out-of-fold scores; dev is in the final training data; threshold bp = the highest surface threshold of the preset):

| split | point | threshold bp | recall bp (95% CI) | false alarm bp (95% CI) | hard negatives false alarm bp |
|---|---|---|---|---|---|
| dev | strict | 4000 | 9844 [9682, 9925] | 1680 [1429, 1965] | 1540 |
| dev | balanced | 4750 | 9755 [9567, 9863] | 1680 [1429, 1965] | 1540 |
| dev | lenient | 5500 | 9555 [9323, 9711] | 0 [0, 51] | 0 |
| dev | pause | 7250 | 8111 [7723, 8446] | 0 [0, 51] | 0 |
| heldout | strict | 4000 | 8688 [8345, 8970] | 2788 [2505, 3091] | 2722 |
| heldout | balanced | 4750 | 8111 [7723, 8446] | 2522 [2249, 2817] | 2436 |
| heldout | lenient | 5500 | 7155 [6721, 7553] | 288 [197, 420] | 286 |
| heldout | pause | 7250 | 4777 [4320, 5240] | 11 [1, 63] | 15 |

Pause (held-out, money and credit tools): pause recall 4681 [4091, 5281] (n 267); false pauses 0 of 539 benign calls = 0 bp [0, 71]; pauses on other tool classes: 0.

Failure taxonomy (counts only, no item text):

- dev missed by template id: `desc_inj.vi` 2, `args_inj.vi.38` 1, `args_inj.vi.37` 1, `args_inj.vi.39` 1, `args_inj.vi.7` 1, `args_inj.en.42` 1, `args_inj.en.7` 1, `args_inj.vi.1` 1, `args_inj.vi.40` 1, `desc_inj.en` 1
- dev false alarm by template id: `desc_ben.en` 34, `desc_ben.vi` 31, `res_ben.en.10` 2, `res_ben.en.12` 2, `res_ben.en.0` 2, `res_ben.vi.10` 2, `res_ben.vi.14` 1, `res_ben.en.5` 1, `res_carrier_ben.vi.23.14` 1, `res_carrier_ben.en.16.5` 1, `res_ben.en.11` 1, `res_ben.vi.40` 1
- heldout missed by template id: `desc_inj.en` 25, `desc_inj.vi` 14, `args_inj.en.28` 3, `args_inj.en.25` 3, `res_inj.vi.1` 3, `args_inj.mx.8` 2, `args_inj.en.5` 2, `res_inj.en.18` 2, `args_inj.vi.2` 1, `args_inj.vi.28` 1, `args_inj.en.49` 1, `args_inj.en.56` 1
- heldout false alarm by template id: `desc_ben.vi` 55, `desc_ben.en` 47, `args_ben.en.14` 4, `args_ben.mx.2` 3, `res_ben.en.1` 3, `args_ben.vi.52` 2, `res_ben.vi.14` 2, `res_ben.vi.7` 2, `res_carrier_ben.en.4.40` 2, `res_ben.en.15` 2, `args_ben.vi.33` 1, `args_ben.en.53` 1
- evasion missed by kind: `base64` 9, `code_switch` 10, `confusable` 11, `dollar_s` 11, `fullwidth_digits` 9, `json_in_string` 7, `leet` 9, `md_comment` 8, `nfd` 11, `no_diacritics` 8, `reversed` 13, `rot13` 17, `split_fields` 5, `telex` 8, `typo` 17, `zero_width` 6
- adversarial categories missed: `mixed-vi-en`, `spaced-letters`, `telex`
- adversarial categories with a false alarm: `benign-description`, `benign-long-doc`, `benign-md-comment`, `benign-url`

Latency per call (whole registry run, microseconds, n 2627): p50 1708, p95 4195, p99 5500, max 33000; calls with no finding p95 2678, calls with a finding p95 4770 (includes the masker for fragments).

Determinism: 0 score mismatches over 2550 items between two independent model loads.

Data: synthetic, this repo; independent template strings per pool {'dev': 99, 'heldout': 108, 'train': 201, 'train_b': 198}. n counts items; items share templates, so a Wilson interval understates template-level variance. See the miss list by template id.

### Caveats (read before using any number above)

- **Targets declared first.** `THRESHOLDS` in `validation.py` were committed in 87ada25, before the first model (0e8410d) and before any held-out run. The only later change is the latency target (p95 2 ms to 5 ms), declared in `WP25B_PROTOCOL.md` (efce71e) before the 1.1.0 run.
- **Calibration (1.1.0).** The presets come from out-of-fold scores (each fold model saw two of the three pools); the final weights saw all three pools, so their scores run higher and `strict` and `balanced` fire far more often on unseen benign text than the rule intended. The operating points of other presets read from this report are descriptive (read after the run), not tuned; the shipped presets were not changed after the run.
- **Dev is in-sample (1.1.0).** dev.jsonl is one of the three training pools of the final weights, so the dev rows and `heldout_gap_bp` compare in-sample with held-out numbers; they are not a validation split.
- **Burnt held-out.** The 1.0.0 held-out failure taxonomy shaped the 1.1.0 design (pool train_b targets its false-alarm clusters and missed families). The sealed sets were run once for 1.1.0, but they are no longer a clean test of a design: heldout-v1 is now dev. The next held-out set must come from another author or from bank red-team traffic.
- **Late probes.** 15 adversarial positives were added after the first run (to reach n >= 50); nothing was tuned on them, but the adversarial row is one author's probes and is indicative only.
- **Template variance.** n counts items; items share about 100 template strings per pool, so the Wilson intervals understate the variance between templates. Recall under a new template family is the real risk.
- **Latency.** p95 per call is judged against the 5 ms target of WP25b (2 ms in 1.0.0); calls with a finding cost more (fragments).
- **Same items, two detectors.** The classifier beats the regex on every evasion kind on the same items, but on the regex-catchable subset the regex is often better; run both (they are separate detectors).
