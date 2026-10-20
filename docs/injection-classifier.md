# Injection classifier, Vietnamese and English (WP25)

Detector slug `injection_classifier`. Decision record: `docs/adr/D27-injection-classifier.md`.
Model card: `data/models/injection_vi_en/1.0.0/model_card.json`. Validation report (GO / NO-GO):
`docs/injection-classifier-validation-report.md`. Contract and precedence: `docs/detectors.md`.

**Switch.** The detector is listed in `config/detectors.yaml` with `enabled: false`. That `enabled` key
is the only switch (and `DETECTORS_ENABLED=1` must be on for any detector to run). A per-agent policy
override can enable it for one agent (`agents.<id>.detectors.enable: [injection_classifier]`).
With the flag off, or the entry off, the gate behaves as before (the WP37 fingerprint test still holds).

## 1. What it does

It reads text and gives a score from 0 to 10000 bp for "this text tries to give instructions to the
agent". It looks at three places:

| Surface | Source | Code of the finding |
|---|---|---|
| tool arguments | `args` (all string leaves, joined; `context.prior_calls` placed in front) | `injection.direct_injection` |
| tool results | `context.tool_results` (each result) and, on the output side, `context.output` | `injection.indirect_injection` |
| tool description | `context.tool_description` (the description of the tool being called) | `injection.tool_poisoning` |

A finding fires when the score is at or above the threshold of the preset (`strict` / `balanced` /
`lenient`, see section 4). Fragments point into the MASKED text (best clause of the best leaf;
`precision: leaf` when the evidence is spread over the leaf). Raw text never leaves the detector (R2).

Read-only tools are scanned too (Tier 0b skips them; credit benchmark finding D04). The detector
keeps no state: for an attack split across two calls, the caller passes the earlier text in
`context.prior_calls` (a per-trace buffer is WP27).

## 2. Method

```
 text --> prepare --> variants --> windows (240 chars) --> features --> logit --> score_bp
          |
          +- JSON-in-string flattened, <!-- --> and invisible characters marked
          +- NFKC, zero-width dropped, case fold, look-alike letters folded (Tier 0b normaliser)
          +- diacritics removed ("no-diacritic form"), leetspeak and $-for-s folded inside words
          +- base64 tokens decoded; ROT13 and reversed text only when a trigger lexicon fires
          +- Telex-decoded second variant
```

* **Features.** Per window: character 3-, 4- and 5-grams (digit runs become `#`), word unigrams and
  bigrams, hashed with CRC-32 into 65,536 buckets; plus concept features (4,096 buckets): a small
  bilingual lexicon (`concepts.py`) maps words to classes such as override verb, rule noun, negation,
  quote or training marker, authority claim, secrecy, exfiltration, address to the assistant, and the
  model sees how classes combine in a clause (for example negation before an override verb is
  policy text; an override verb at the start of a clause followed by a rule noun is an instruction).
* **Model.** Logistic regression, integer weights (scale 10,000) in `weights.json`. Logit =
  surface bias + sum of n-gram weights / sqrt(n) + 0.25 * sum of concept weights. The score of a text
  is the maximum over its variants and windows. Same input, same weights, same score.
* **Training.** `uv run python -m tools.train_classifier` (stdlib only; about two minutes). It reads
  `data/eval/injection_vi_en/train.jsonl` and `dev.jsonl` only, trains with Adagrad and L2, max-pooling
  over windows and variants, prints the dev false-alarm table that the presets were chosen from, and
  writes `weights.json` and the model card with the SHA-256 of the weight file.
* **No new dependency.** NumPy is already in `uv.lock` but is not used. No torch, no download.

## 3. Data (licence "synthetic, this repo")

`data/eval/injection_vi_en/`: `generate.py` (seeded, `--check` verifies the files), `templates.py`
(three template pools: train, dev, held-out; no template text is shared; the test
`test_golden_set_sizes_provenance_and_disjoint_templates` checks it), `paraphrases*.json` (rewordings of
the templates made OFFLINE by the local LLM with `paraphrase.py`, concurrency 2; every item built from one
carries the labeller "synthetic, LLM-paraphrased"), `adversarial.py` (62 probes written by hand, outside
the templates), and the generated `train` / `dev` / `heldout` / `evasion` / `adversarial` `.jsonl` files
with `MANIFEST.json`. Every item has id, source, licence, label and labeller. The detector never calls a model.

Split use: train fits the weights; dev picks hyper-parameters and the frozen thresholds; held-out is
reported and never tuned on; `evasion.jsonl` is the held-out set re-written with 16 evasion kinds
(typo, no diacritics, Telex, code switch, look-alikes, zero-width, NFD, full-width digits, leetspeak,
`$` for `s`, base64, ROT13, reversed, hidden comment, JSON in a string, split fields).

Limits of the data: n counts items, but items share templates, so a Wilson interval understates
variance between templates. The report lists the number of independent template strings and the
misses by template id.

## 4. Thresholds (ILLUSTRATIVE, frozen per model version)

| Name | bp | Use |
|---|---|---|
| `strict` | see card | finding fires (more sensitive) |
| `balanced` | see card | default |
| `lenient` | see card | finding fires (fewer false alarms) |
| pause | see card | pause hint for the configured classes |

The numbers live in the model card and in `detector.py` (`PRESETS`, `PAUSE_THRESHOLD_BP`); a test
compares them. Changing one means a new model version. `pause_threshold_bp` can be raised in the
settings, never lowered.

## 5. The pause rule (R1)

```
 finding score >= pause threshold
   AND tool risk class in pause_tool_classes (default money, credit)   <- the detector sets the hint
   AND detector is the classifier AND call was allowed AND not shadow    <- the gate checks
   AND direction = input AND risk class in money / credit / pii_export
 -> allow becomes PAUSE, rule id GATE-CLASSIFIER-PAUSE (never block)
 -> agent PAUSED (principal rule:GATE-CLASSIFIER-PAUSE), tier 0 pause verdict row,
    a case opens (sync_gate_cases), two people resume (owner + reviewer)
 otherwise: report only
```

Tests (`tests/detectors/test_injection_classifier_gate.py`): an allow only becomes a pause, a block
stays the same block, a read-only tool gets a report, only the classifier may pause, a `block` hint
never blocks, a shadow agent is never paused, the dry run says `would_pause`, a corrupt weight file is
`execution_failed` and does not stop a payment (the entry is not fail closed).

## 6. Settings

| Key | Default | Meaning |
|---|---|---|
| `preset` / `threshold_bp` | balanced | detection threshold |
| `scan_tool_results` | true | scan results and the output side |
| `scan_tool_descriptions` | true | scan `context.tool_description` |
| `pause_tool_classes` | [money, credit] | classes that may get the pause hint (also `pii_export`; never `read_only`) |
| `pause_threshold_bp` | frozen value | can only be raised |
| `max_chars` | 12000 | characters scanned per text (head and tail kept) |

## 7. WP26 adapter

`supervisor.detectors.injection_classifier.score_tool_description(text) -> bp` scores one tool
description (0 to 10000). WP26 can register it with `mcp_lock.register_description_scorer`; the
integrator decides the fail mode (hold the tool for review when the weights are refused).

## 8. Commands

```
uv run python data/eval/injection_vi_en/generate.py --check
uv run python -m tools.train_classifier                       # retrain (new version = new card)
uv run python -m supervisor.detectors.harness --detector injection_classifier
uv run python -m supervisor.detectors.harness --detector injection_classifier --check
uv run python -m supervisor.detectors.harness --detector injection_classifier --md docs/injection-classifier-validation-report.md
```

## 9. Limits

See the validation report and `BACKLOG.md` (WP25 rows): synthetic data; Vietnamese and English only;
spaced-out letters and other languages are not recognised; a long document dilutes a short
instruction; no state across calls; the thresholds are not calibrated on real traffic.
