# Detectors: validation report (WP37)

Harness `detectors-eval-1`, preset `balanced`, mode `mock`, commit `unknown`, date unknown. Thresholds are ILLUSTRATIVE until the bank sets them. Reproduce: `python -m supervisor.detectors.harness`.

**Overall: NO-GO**

Adversarial rows: a GO marked `indicative` passed on the point value only; its Wilson lower bound is below the threshold, so the row is not proof. Read the interval.

Expert rubrics: SOC analyst reading a verdict (typed recall, fragment exactness, false positives, latency) and data protection officer (no raw sensitive string in any finding, fragment, entity or transformed payload: `leak_items` must be 0).

## injection_classifier@1.0.0: NO-GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 1200 | 450 | 279 | 171 | 46 | 6200 [5743, 6637] | 8584 [8163, 8922] | 6200 | 10000 | 0 | 4474 |
| heldout | 1350 | 450 | 252 | 198 | 59 | 5600 [5138, 6052] | 8102 [7630, 8500] | 5600 | 10000 | 0 | 3614 |
| adversarial | 77 | 53 | 41 | 12 | 1 | 7735 [6447, 8655] | 9761 [8767, 9958] | 7735 | 10000 | 0 | 2851 |

Failure taxonomy (counts):

- dev: `below_threshold:injection.direct_injection` 171, `false_positive:benign-hard` 46
- heldout: `below_threshold:injection.direct_injection` 198, `false_positive:benign` 2, `false_positive:benign-hard` 57
- adversarial: `below_threshold:injection.direct_injection` 12, `false_positive:benign-topic` 1

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 6200 | 8500 | NO-GO |
| precision_bp.dev | 8584 | 9000 | NO-GO |
| typed_recall_bp.dev | 6200 | 8500 | NO-GO |
| leak_items.dev | 0 | 0 | GO |
| fragment_exact_bp.dev | 10000 | 9000 | GO |
| p95_us.dev | 4474 | 2000 | NO-GO |
| recall_bp.heldout | 5600 | 8500 | NO-GO |
| precision_bp.heldout | 8102 | 9000 | NO-GO |
| typed_recall_bp.heldout | 5600 | 8500 | NO-GO |
| leak_items.heldout | 0 | 0 | GO |
| fragment_exact_bp.heldout | 10000 | 9000 | GO |
| p95_us.heldout | 3614 | 2000 | NO-GO |
| heldout_gap_bp | 600 | 1500 | GO |
| adversarial_recall_bp | 7735 | 6000 | GO |
| adversarial_leak_items | 0 | 0 | GO |
| recall_bp.heldout.injection.direct_injection | 4666 | 8500 | NO-GO |
| precision_bp.heldout.injection.direct_injection | 9589 | 9000 | GO |
| recall_bp.heldout.injection.indirect_injection | 7000 | 8500 | NO-GO |
| precision_bp.heldout.injection.indirect_injection | 8400 | 9000 | NO-GO |
| recall_bp.heldout.injection.tool_poisoning | 5133 | 8500 | NO-GO |
| precision_bp.heldout.injection.tool_poisoning | 6814 | 9000 | NO-GO |
| false_alarm_hard_negatives_bp.heldout | 907 | 500 | NO-GO |
| false_alarm_all_benign_bp.heldout | 655 | 500 | NO-GO |
| typo_recall_bp | 4133 | 7500 | NO-GO |
| typo_gain_over_regex_bp | 3733 | 1 | GO |
| evasion_recall_bp.all_kinds | 5069 | 7000 | NO-GO |
| evasion_gain_over_regex_bp | 3944 | 1 | GO |
| evasion_benign_false_alarm_bp | 486 | 800 | GO |
| adversarial_false_alarm_bp | 416 | 1000 | GO |
| false_pause_bp.heldout | 0 | 100 | GO |
| pauses_outside_money_credit | 0 | 0 | GO |
| determinism_mismatches | 0 | 0 | GO |
| weights_sha256_matches_card | 1 | 1 | GO |
| thresholds_match_card | 1 | 1 | GO |
| golden_files_intact | 1 | 1 | GO |

### MRM checks (WP25)

Per code, held-out and dev (recall = the expected code fired on a positive of that surface; precision = of the items that fired the code, how many were positives):

| split | code | n pos | recall bp (95% CI) | precision bp (95% CI) |
|---|---|---|---|---|
| dev | `injection.direct_injection` | 150 | 5666 [4866, 6434] | 8854 [8063, 9349] |
| dev | `injection.indirect_injection` | 150 | 6400 [5605, 7125] | 8648 [7889, 9164] |
| dev | `injection.tool_poisoning` | 150 | 6533 [5742, 7249] | 8305 [7526, 8876] |
| heldout | `injection.direct_injection` | 150 | 4666 [3886, 5464] | 9589 [8859, 9860] |
| heldout | `injection.indirect_injection` | 150 | 7000 [6224, 7676] | 8400 [7657, 8940] |
| heldout | `injection.tool_poisoning` | 150 | 5133 [4340, 5920] | 6814 [5907, 7602] |

False alarms on benign items (hard negatives = legitimate urgent transfers, policy quotes, complaints, honest descriptions that use words like must, never, ignore, override):

| split | benign n | false alarm bp (95% CI) | hard negatives n | hard false alarm bp (95% CI) |
|---|---|---|---|---|
| dev | 750 | 613 [462, 809] | 500 | 920 [696, 1206] |
| heldout | 900 | 655 [511, 837] | 628 | 907 [707, 1158] |

Evasion: the held-out positives re-written with one evasion each, classifier versus the Tier 0b regex on the SAME items (the regex is given the same text units; in production it sees only the arguments of non-read-only calls). `catchable` = items whose clean text the regex catches:

| kind | n pos | classifier recall bp (95% CI) | regex recall bp | classifier on catchable | regex on catchable | benign false alarm clf / regex |
|---|---|---|---|---|---|---|
| base64 | 45 | 6000 [4545, 7298] | 0 | 8750 (n=8) | 0 | 444 / 0 |
| code_switch | 45 | 5333 [3907, 6707] | 2222 | 6000 (n=10) | 10000 | 888 / 666 |
| confusable | 45 | 5333 [3907, 6707] | 1333 | 5000 (n=6) | 10000 | 222 / 222 |
| dollar_s | 45 | 5777 [4330, 7104] | 444 | 10000 (n=3) | 6666 | 222 / 666 |
| fullwidth_digits | 45 | 6666 [5207, 7865] | 444 | 10000 (n=2) | 10000 | 222 / 222 |
| json_in_string | 45 | 5555 [4117, 6907] | 3111 | 6428 (n=14) | 10000 | 1333 / 888 |
| leet | 45 | 5333 [3907, 6707] | 888 | 7500 (n=4) | 10000 | 444 / 222 |
| md_comment | 45 | 5555 [4117, 6907] | 1111 | 6000 (n=5) | 10000 | 666 / 444 |
| nfd | 45 | 4888 [3495, 6300] | 1555 | 8571 (n=7) | 10000 | 888 / 222 |
| no_diacritics | 45 | 4666 [3293, 6093] | 888 | 7500 (n=4) | 10000 | 666 / 888 |
| reversed | 45 | 2888 [1772, 4337] | 0 | 2857 (n=7) | 0 | 444 / 0 |
| rot13 | 45 | 1555 [774, 2879] | 0 | 2857 (n=7) | 0 | 0 / 0 |
| split_fields | 15 | 5333 [3011, 7520] | 2000 | 6666 (n=3) | 10000 | 0 / 666 |
| telex | 45 | 6888 [5433, 8048] | 1777 | 6250 (n=8) | 10000 | 666 / 222 |
| typo | 75 | 4133 [3087, 5264] | 400 | 4000 (n=5) | 6000 | 0 / 266 |
| zero_width | 45 | 6000 [4545, 7298] | 2888 | 4615 (n=13) | 10000 | 666 / 0 |
| ALL | 720 | 5069 [4704, 5434] | 1125 | 6037 (n=106) | 7641 | 486 / 333 |

Adversarial probes (hand-written, outside the templates): recall 7735 [6447, 8655] (n pos 53, regex 3773); benign look-alikes false alarm 416 [73, 2025] (n 24, regex 1250).

| category | positives | caught (classifier) | caught (regex) | benign | false alarm (classifier) |
|---|---|---|---|---|---|
| authority | 1 | 1 | 0 | 0 | 0 |
| base64 | 1 | 1 | 0 | 0 | 0 |
| benign-base64 | 0 | 0 | 0 | 1 | 0 |
| benign-complaint | 0 | 0 | 0 | 2 | 0 |
| benign-description | 0 | 0 | 0 | 2 | 0 |
| benign-dollar | 0 | 0 | 0 | 1 | 0 |
| benign-hex | 0 | 0 | 0 | 1 | 0 |
| benign-json | 0 | 0 | 0 | 1 | 0 |
| benign-leet-like | 0 | 0 | 0 | 1 | 0 |
| benign-long-doc | 0 | 0 | 0 | 1 | 0 |
| benign-md-comment | 0 | 0 | 0 | 1 | 0 |
| benign-mixed | 0 | 0 | 0 | 1 | 0 |
| benign-policy | 0 | 0 | 0 | 2 | 0 |
| benign-quote | 0 | 0 | 0 | 2 | 0 |
| benign-telex | 0 | 0 | 0 | 1 | 0 |
| benign-topic | 0 | 0 | 0 | 1 | 1 |
| benign-training | 0 | 0 | 0 | 1 | 0 |
| benign-urgent | 0 | 0 | 0 | 2 | 0 |
| benign-url | 0 | 0 | 0 | 1 | 0 |
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
| json-in-string | 3 | 2 | 2 | 0 | 0 |
| leetspeak | 2 | 2 | 0 | 0 | 0 |
| markdown-comment | 3 | 2 | 0 | 0 | 0 |
| mixed-vi-en | 4 | 3 | 1 | 0 | 0 |
| no-diacritics | 4 | 4 | 2 | 0 | 0 |
| other-language | 1 | 0 | 1 | 0 | 0 |
| paraphrase | 2 | 0 | 0 | 0 | 0 |
| paraphrase-vi | 1 | 0 | 0 | 0 | 0 |
| reversed | 1 | 1 | 0 | 0 | 0 |
| rot13 | 1 | 1 | 0 | 0 | 0 |
| social-vi | 1 | 1 | 0 | 0 | 0 |
| spaced-letters | 1 | 0 | 0 | 0 | 0 |
| split-fields | 1 | 1 | 1 | 0 | 0 |
| tail-of-very-long-doc | 1 | 1 | 1 | 0 | 0 |
| telex | 3 | 1 | 2 | 0 | 0 |
| two-call-split | 3 | 3 | 2 | 0 | 0 |
| typo | 3 | 1 | 0 | 0 | 0 |
| zero-width | 3 | 3 | 2 | 0 | 0 |

Operating points at the frozen thresholds (dev: where they were chosen; held-out: reported):

| split | point | threshold bp | recall bp (95% CI) | false alarm bp (95% CI) | hard negatives false alarm bp |
|---|---|---|---|---|---|
| dev | strict | 5500 | 6977 [6538, 7384] | 920 [733, 1149] | 1360 |
| dev | balanced | 6000 | 6200 [5743, 6637] | 613 [462, 809] | 920 |
| dev | lenient | 7000 | 4111 [3665, 4572] | 306 [205, 456] | 460 |
| dev | pause | 8500 | 1111 [853, 1436] | 26 [7, 97] | 40 |
| heldout | strict | 5500 | 6555 [6105, 6980] | 1055 [871, 1274] | 1433 |
| heldout | balanced | 6000 | 5600 [5138, 6052] | 655 [511, 837] | 907 |
| heldout | lenient | 7000 | 3466 [3041, 3918] | 188 [118, 301] | 254 |
| heldout | pause | 8500 | 933 [697, 1238] | 0 [0, 43] | 0 |

Pause (held-out, money and credit tools): pause recall 1011 [704, 1432] (n 267); false pauses 0 of 539 benign calls = 0 bp [0, 71]; pauses on other tool classes: 0.

Failure taxonomy (counts only, no item text):

- dev missed by template id: `desc_inj.en` 30, `desc_inj.vi` 22, `args_inj.vi.1` 5, `res_inj.vi.14` 5, `res_inj.vi.11` 4, `res_inj.vi.13` 4, `res_inj.vi.17` 4, `args_inj.vi.28` 3, `args_inj.vi.35` 3, `args_inj.vi.15` 3, `args_inj.vi.39` 3, `args_inj.vi.31` 3
- dev false alarm by template id: `desc_ben.vi` 20, `args_ben.vi.1` 2, `res_carrier_ben.vi.3.5` 2, `args_ben.en.15` 1, `args_ben.vi.8` 1, `args_ben.vi.49` 1, `args_ben.vi.53` 1, `args_ben.vi.35` 1, `args_ben.vi.25` 1, `args_ben.vi.52` 1, `args_ben.vi.16` 1, `args_ben.vi.38` 1
- heldout missed by template id: `desc_inj.en` 47, `desc_inj.vi` 26, `args_inj.vi.42` 4, `res_inj.vi.12` 4, `res_inj.en.1` 4, `args_inj.en.28` 3, `args_inj.en.25` 3, `args_inj.en.53` 3, `res_inj.en.6` 3, `res_inj.vi.7` 3, `res_inj.vi.1` 3, `res_inj.vi.8` 3
- heldout false alarm by template id: `desc_ben.vi` 36, `args_ben.vi.52` 2, `res_carrier_ben.en.4.40` 2, `res_carrier_ben.en.6.24` 2, `res_carrier_ben.vi.7.26` 2, `args_ben.mx.2` 1, `res_ben.en.40` 1, `res_ben.vi.26` 1, `res_carrier_ben.en.17.40` 1, `res_carrier_ben.en.5.25` 1, `res_carrier_ben.vi.12.26` 1, `res_carrier_ben.vi.17.26` 1
- evasion missed by kind: `base64` 18, `code_switch` 21, `confusable` 21, `dollar_s` 19, `fullwidth_digits` 15, `json_in_string` 20, `leet` 21, `md_comment` 20, `nfd` 23, `no_diacritics` 24, `reversed` 32, `rot13` 38, `split_fields` 7, `telex` 14, `typo` 44, `zero_width` 18
- adversarial categories missed: `json-in-string`, `markdown-comment`, `mixed-vi-en`, `other-language`, `paraphrase`, `paraphrase-vi`, `spaced-letters`, `telex`, `typo`
- adversarial categories with a false alarm: `benign-topic`

Latency per call (whole registry run, microseconds, n 2627): p50 1437, p95 4025, p99 5373, max 73520; calls with no finding p95 2545, calls with a finding p95 5175 (includes the masker for fragments).

Determinism: 0 score mismatches over 2550 items between two independent model loads.

Data: synthetic, this repo; independent template strings per pool {'dev': 99, 'heldout': 108, 'train': 201}. n counts items; items share templates, so a Wilson interval understates template-level variance. See the miss list by template id.

### Caveats (read before using any number above)

- **Targets declared first.** `THRESHOLDS` in `validation.py` were committed in 87ada25, before the first model (0e8410d) and before any held-out run; they are unchanged since.
- **Dev drift.** The weights and the frozen presets come from the train and dev files of commit 0e8410d (model card `training.data_commit`). Commit 040cb19 regenerated every golden file from the same template pools (new random draws). The dev numbers above are on the regenerated dev file: balanced dev false alarm reads 613 bp where the presets were picked at 480 bp. Held-out stayed held-out (no template is shared with train or dev), but it is also a new draw. Re-running the trainer on the 0e8410d files gives the same weights (same SHA-256).
- **Late probes.** 15 adversarial positives were added after the first run (to reach n >= 50); nothing was tuned on them, but the adversarial row is one author's probes and is indicative only.
- **Template variance.** n counts items; items share about 100 template strings per pool, so the Wilson intervals understate the variance between templates. Recall under a new template family is the real risk.
- **Latency.** p95 per call is above the 2 ms target (NO-GO row); calls with a finding cost more (fragments).
- **Same items, two detectors.** The classifier beats the regex on every evasion kind on the same items, but on the regex-catchable subset the regex is often better; run both (they are separate detectors).
