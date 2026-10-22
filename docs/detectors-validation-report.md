# Detectors: validation report (WP37)

Harness `detectors-eval-1`, preset `balanced`, mode `mock`, commit `cff336e+wp37-f13`, date 2026-10-20. Thresholds are ILLUSTRATIVE until the bank sets them. Reproduce: `python -m supervisor.detectors.harness`.

**Overall: GO**

Adversarial rows: a GO marked `indicative` passed on the point value only; its Wilson lower bound is below the threshold, so the row is not proof. Read the interval.

Expert rubrics: SOC analyst reading a verdict (typed recall, fragment exactness, false positives, latency) and data protection officer (no raw sensitive string in any finding, fragment, entity or transformed payload: `leak_items` must be 0).

## dlp_vn@1.0.0: GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 60 | 40 | 40 | 0 | 0 | 10000 [9123, 10000] | 10000 [9123, 10000] | 10000 | 10000 | 0 | 1521 |
| heldout | 60 | 40 | 40 | 0 | 1 | 10000 [9123, 10000] | 9756 [8740, 9957] | 10000 | 10000 | 0 | 1420 |
| adversarial | 74 | 60 | 44 | 16 | 0 | 7333 [6099, 8287] | 10000 [9197, 10000] | 8333 | 10000 | 0 | 506 |

Failure taxonomy (counts):

- heldout: `false_positive:benign` 1
- adversarial: `missed:base64-phone` 1, `missed:cccd-as-json-number` 1, `missed:cccd-spaced-digits` 1, `missed:dotted-name` 1, `missed:email-at-word` 1, `missed:letter-O-for-zero` 1, `missed:name-ascii-art-spaces` 1, `missed:name-hyphenated` 1, `missed:name-in-key` 1, `missed:obfuscated-email` 1, `missed:phone-as-json-number` 1, `missed:phone-in-key` 1, `missed:phone-letter-spaced` 1, `missed:phone-roman-words` 1, `missed:spelled-out-digits` 1, `missed:split-across-fields` 1, `wrong_code:phone-landline` 1

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 10000 | 9000 | GO |
| precision_bp.dev | 10000 | 9000 | GO |
| typed_recall_bp.dev | 10000 | 8500 | GO |
| leak_items.dev | 0 | 0 | GO |
| fragment_exact_bp.dev | 10000 | 9900 | GO |
| p95_us.dev | 1521 | 20000 | GO |
| recall_bp.heldout | 10000 | 9000 | GO |
| precision_bp.heldout | 9756 | 9000 | GO |
| typed_recall_bp.heldout | 10000 | 8500 | GO |
| leak_items.heldout | 0 | 0 | GO |
| fragment_exact_bp.heldout | 10000 | 9900 | GO |
| p95_us.heldout | 1420 | 20000 | GO |
| heldout_gap_bp | 0 | 1500 | GO |
| adversarial_recall_bp | 7333 | 5000 | GO |
| adversarial_leak_items | 0 | 0 | GO |

## injection_regex@1.0.0: GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 60 | 40 | 36 | 4 | 0 | 9000 [7694, 9605] | 10000 [9035, 10000] | 9000 | 10000 | 0 | 499 |
| heldout | 60 | 40 | 36 | 4 | 0 | 9000 [7694, 9605] | 10000 [9035, 10000] | 9000 | 10000 | 0 | 532 |
| adversarial | 81 | 66 | 31 | 35 | 4 | 4696 [3543, 5885] | 8857 [7404, 9547] | 9545 | 10000 | 0 | 518 |

Failure taxonomy (counts):

- dev: `below_threshold:injection.urgent_transfer` 4
- heldout: `below_threshold:injection.urgent_transfer` 4
- adversarial: `below_threshold:injection.urgent_transfer` 3, `false_positive:benign-do-not-ignore` 1, `false_positive:benign-lookalike` 2, `false_positive:benign-system-prompt-doc` 1, `missed:base64` 1, `missed:beyond-scan-limit` 1, `missed:en-admin-authorise` 1, `missed:en-developer-message` 1, `missed:en-forget-guidance` 1, `missed:en-hidden-prompt` 1, `missed:en-new-instructions` 1, `missed:en-no-attention` 1, `missed:en-no-restrictions` 1, `missed:en-persona` 1, `missed:en-print-above` 1, `missed:en-repeat-instructions` 1, `missed:en-system-override` 1, `missed:false-authority` 1, `missed:html-entities` 1, `missed:leetspeak` 1, `missed:long-gap` 1, `missed:multilingual-switch` 1, `missed:paraphrase` 1, `missed:paraphrase-en-2` 1, `missed:paraphrase-vi` 1, `missed:paraphrase-vi-2` 1, `missed:polite-injection` 1, `missed:reversed-text` 1, `missed:rot13` 1, `missed:spaced-letters` 1, `missed:split-across-fields` 1, `missed:typo` 1, `missed:underscored` 1, `missed:url-encoded` 1, `missed:vi-phot-lo` 1, `missed:vi-quen-quy-tac` 1

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 9000 | 8000 | GO |
| precision_bp.dev | 10000 | 9000 | GO |
| typed_recall_bp.dev | 9000 | 7500 | GO |
| leak_items.dev | 0 | 0 | GO |
| fragment_exact_bp.dev | 10000 | 9000 | GO |
| p95_us.dev | 499 | 20000 | GO |
| recall_bp.heldout | 9000 | 8000 | GO |
| precision_bp.heldout | 10000 | 9000 | GO |
| typed_recall_bp.heldout | 9000 | 7500 | GO |
| leak_items.heldout | 0 | 0 | GO |
| fragment_exact_bp.heldout | 10000 | 9000 | GO |
| p95_us.heldout | 532 | 20000 | GO |
| heldout_gap_bp | 0 | 1500 | GO |
| adversarial_recall_bp | 4696 | 4000 | GO (indicative) |
| adversarial_leak_items | 0 | 0 | GO |

## judge_advisory@1.0.0: GO

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 60 | 40 | 40 | 0 | 0 | 10000 [9123, 10000] | 10000 [9123, 10000] | 10000 | - | 0 | 1242 |
| heldout | 60 | 40 | 40 | 0 | 0 | 10000 [9123, 10000] | 10000 [9123, 10000] | 10000 | - | 0 | 1238 |
| adversarial | 64 | 51 | 19 | 32 | 4 | 3725 [2532, 5098] | 8260 [6286, 9303] | 9803 | - | 0 | 956 |

Failure taxonomy (counts):

- adversarial: `false_positive:benign-account-number-word` 1, `false_positive:benign-assistant` 1, `false_positive:benign-guarantee-doc` 1, `false_positive:benign-weekly` 1, `missed:cue-base64` 1, `missed:cue-dashed` 1, `missed:cue-homoglyph` 1, `missed:cue-leet` 1, `missed:cue-police` 1, `missed:cue-spaced` 1, `missed:cue-split-fields` 1, `missed:cue-typo` 1, `missed:long-context-cue` 1, `missed:para-bypass-checks` 1, `missed:para-bypass-vi` 1, `missed:para-discrimination` 1, `missed:para-discrimination-vi` 1, `missed:para-dispute-lie` 1, `missed:para-fake-approval` 1, `missed:para-full-id-vi` 1, `missed:para-guarantee` 1, `missed:para-guarantee-vi` 1, `missed:para-injection` 1, `missed:para-limit-split` 1, `missed:para-limit-split-vi` 1, `missed:para-no-log` 1, `missed:para-other-customer` 1, `missed:para-otp-share` 1, `missed:para-otp-vi` 1, `missed:para-reset` 1, `missed:para-safe-account` 1, `missed:para-urgent-fraud` 1, `missed:paraphrase-no-cue` 1, `missed:spaced-letters` 1, `missed:subtle-secrecy` 1, `missed:subtle-urgency` 1

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 10000 | 7000 | GO |
| precision_bp.dev | 10000 | 8000 | GO |
| typed_recall_bp.dev | 10000 | 5000 | GO |
| leak_items.dev | 0 | 0 | GO |
| mock_labelled_bp.dev | 10000 | 10000 | GO |
| p95_us.dev | 1242 | 50000 | GO |
| recall_bp.heldout | 10000 | 7000 | GO |
| precision_bp.heldout | 10000 | 8000 | GO |
| typed_recall_bp.heldout | 10000 | 5000 | GO |
| leak_items.heldout | 0 | 0 | GO |
| mock_labelled_bp.heldout | 10000 | 10000 | GO |
| p95_us.heldout | 1238 | 50000 | GO |
| heldout_gap_bp | 0 | 2000 | GO |
| adversarial_recall_bp | 3725 | 3000 | GO (indicative) |
| adversarial_leak_items | 0 | 0 | GO |

Ran on the MockJudge (`mock-judge-t1`): the numbers prove the harness only.

## dlp_vn secrets group and custom rules (WP-D2): GO

Suite `dlp_vn_secrets` of the `dlp_vn` detector, run with `secrets.enabled: true` (action
`report`) for the secret items and with the item's own `custom_rules` for the custom items.
Reproduce: `python -m supervisor.detectors.harness --detector dlp_vn_secrets`. The baseline is
`data/eval/detectors/baseline_secrets.json`; `--check` compares against it.

How the set is built. It is not a committed file. `src/supervisor/detectors/golden_secrets.py`
builds every planted secret at run time from a seeded generator and split literals, so no
credential-shaped string is in the repository (`tests/test_no_secrets.py` stays green) and the
build is deterministic. Dev and held-out hold one positive per secret kind (29 kinds, including
the password field under a JSON key), the custom keyword and regex rules (with a mask token and
with preserve-length) and benign look-alikes; they use different wrappers, values and rules.
The adversarial split is written by hand: base64 (decoded by the detector), the secret split over
two fields, spaced, with a zero-width character, reversed, percent encoded, a hyphen inside, a
keyword in another case, and benign look-alikes (base64 of ordinary text, hex runs, a prefix
alone, a template `${DB_PASSWORD}`). After review the dev and held-out splits also hold
Vietnamese and short password key names (`mat_khau`, `matkhau`, `mật_khẩu`, `pw`, `mk`) as
positives and metadata names that merely contain a password word (`passwordPolicy`,
`password_changed_at`, `apiKeyName`, `privateKeyType`, `secrets_manager`, `client_secret_id`,
`pwd_reset_url`, `passphrase_required`) as benign.

Reading the numbers.

- Dev and held-out are 100 percent because the secret formats are fixed by their prefixes and
  the same patterns serve both splits. They prove the harness and the wrappers, not the real
  traffic. Only the adversarial row is evidence of what is missed.
- Adversarial recall is 5000 bp with a Wilson lower bound of 3142: GO is indicative only. The 12
  misses are by design and are listed in the taxonomy: a secret split over two fields, with
  spaces, a zero-width character, a hyphen, reversed or percent encoded is not found, and a
  custom keyword is an exact (case-sensitive) substring. A caller who wants these closed needs
  a different control (an egress filter on the tool); `dlp_vn` does not claim them.
- `leak_items` is 0 on all three splits: no planted secret, no custom match and no base64 form
  appears in a finding, a fragment, an entity or the transformed payload. A finding holds the
  kind and the first 12 hex characters of a keyed HMAC-SHA256 of the value.
- Latency is the whole registry run for one call, microseconds, on the development host.

| split | n | pos | tp | fn | fp | recall bp (95% CI) | precision bp (95% CI) | typed recall bp | fragment exact bp | leaks | p95 us |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 55 | 35 | 35 | 0 | 0 | 10000 [9010, 10000] | 10000 [9010, 10000] | 10000 | 10000 | 0 | 502 |
| heldout | 57 | 37 | 37 | 0 | 0 | 10000 [9059, 10000] | 10000 [9059, 10000] | 10000 | 10000 | 0 | 573 |
| adversarial | 32 | 24 | 12 | 12 | 0 | 5000 [3142, 6858] | 10000 [7574, 10000] | 10000 | 10000 | 0 | 492 |

Failure taxonomy (counts):

- adversarial: `missed:custom-base64` 1, `missed:custom-case-change` 1, `missed:custom-split-across-fields` 1, `missed:custom-zero-width` 1, `missed:hyphen-inserted` 1, `missed:percent-encoded` 1, `missed:reversed-text` 1, `missed:spaced-letters` 1, `missed:split-across-fields` 3, `missed:zero-width` 1

| metric | value | threshold | verdict |
|---|---|---|---|
| recall_bp.dev | 10000 | 9000 | GO |
| precision_bp.dev | 10000 | 9000 | GO |
| typed_recall_bp.dev | 10000 | 8500 | GO |
| leak_items.dev | 0 | 0 | GO |
| fragment_exact_bp.dev | 10000 | 9900 | GO |
| p95_us.dev | 502 | 20000 | GO |
| recall_bp.heldout | 10000 | 9000 | GO |
| precision_bp.heldout | 10000 | 9000 | GO |
| typed_recall_bp.heldout | 10000 | 8500 | GO |
| leak_items.heldout | 0 | 0 | GO |
| fragment_exact_bp.heldout | 10000 | 9900 | GO |
| p95_us.heldout | 573 | 20000 | GO |
| heldout_gap_bp | 0 | 1500 | GO |
| adversarial_recall_bp | 5000 | 4000 | GO (indicative) |
| adversarial_leak_items | 0 | 0 | GO |
