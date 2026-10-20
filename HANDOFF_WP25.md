# HANDOFF WP25: Injection classifier, Vietnamese and English

Branch `wp25-classifier` (off `wp37-verdict-detectors`, merged with its review head `bfc6e09`). Nothing pushed, merged
or rewritten. Flag: `DETECTORS_ENABLED` plus the entry `detectors.injection_classifier.enabled` in
`config/detectors.yaml` (default `false`; that key is the switch). Author: Sonnet 5.5 engineer.

## 1. Verdict in one line

Built and wired end to end, but **validation verdict is NO-GO** against the illustrative targets (recall,
precision, hard-negative false alarm, typo recall, latency). It beats the regex everywhere it was compared.
Keep the entry disabled and do not rely on the pause path until the bank validates on real data.

## 2. What was built

| Part | Where |
|---|---|
| Features (normalisation, leet/`$` fold, homoglyph, Telex variant, base64/ROT13/reversed decoding on trigger, JSON-in-string, hidden comment and zero-width markers, hashed char 3-5 grams + words, bilingual concept lexicon, 150-char windows) | `src/supervisor/detectors/injection_classifier/features.py`, `concepts.py`, `units.py` |
| Model (integer weights JSON, SHA-256 pinned by the card, loader refuses on hash, version, feature version) | `.../model.py`, `data/models/injection_vi_en/1.0.0/{weights.json,model_card.json}` |
| Detector `injection_classifier` (sides input+output, protocols all, schema: `scan_tool_results`, `scan_tool_descriptions`, `pause_tool_classes` default money+credit, `pause_threshold_bp` frozen 8500 and raise-only, `max_chars`; presets 5500 / 6000 / 7000; category `content_security`; `fail_closed: false`) | `.../detector.py`; registered in `detectors/__init__.py`; `config/detectors.yaml` (disabled) |
| WP26 adapter `score_tool_description(text) -> bp` | `injection_classifier/__init__.py`, `detector.py` |
| Pause path `GATE-CLASSIFIER-PAUSE` | `gateway/detector_gate.py` (+ `engine.py`: state change, verdict row, dry-run flag) |
| Training (stdlib only, deterministic) | `tools/train_classifier.py` (`uv run python -m tools.train_classifier`) |
| Golden set + generator + hand-written probes + LLM paraphrases | `data/eval/injection_vi_en/` |
| MRM validation + harness extension + baseline | `.../validation.py`, `detectors/harness.py`, `data/eval/injection_vi_en/baseline.json`, `docs/injection-classifier-validation-report.md` |
| Docs | `docs/injection-classifier.md`, `docs/adr/D27-injection-classifier.md` (D23 was highest; D24-D26 taken), README row, BACKLOG 7 rows, CHANGELOG line, `docs/threat-model.md` 3.11, `docs/detectors.md` pointer |

R1: the classifier never blocks. The gate obeys a `pause` hint only from a slug in `PAUSE_CAPABLE_DETECTORS`
(`injection_classifier`), only on an allowed, non-shadow, input-direction call on a money, credit or pii_export
tool (the detector itself only sets the hint for `pause_tool_classes`, default money and credit). A case opens through
the existing tier 0 pause verdict row (`sync_gate_cases`); two people resume as today. R2: fragments are on masked text; leak
items 0. R3: no network in the detector. WP37 review points: category is not `advisory`; `fail_closed: false` with the reason
that a classifier outage must not stop payments; calls run under the per-call deadline; I do not use `skip_tools` in tests.

## 3. Test counts

| | Count |
|---|---|
| Before (WP37 head `a84351a`, my clean run) | 3,800 passed, 29 skipped |
| After (this branch, merged with the WP37 review head) | **3,884 passed, 29 skipped** (WP37 review added 16; WP25 added 68) |

New tests (`tests/detectors/test_injection_classifier_*.py`): features 9, model 9 (integrity, training determinism, no held-out read), detector 13, gate 13 (pause, two-person resume, read-only, only classifier, block hint, shadow, dry run, allow-only-to-pause property with the real and a fake detector, case opens, both modes laptop and databricks_app), harness 11. Existing tests edited: `test_contract.py`, `test_routes.py` (catalogue now has 4 detectors), `test_harness.py` (WP37 report run limited to its 3 detectors).

## 4. Commands (last lines)

```
$ uv sync
$ uv run python -m pytest -q -x -p no:cacheprovider
3884 passed, 29 skipped, 1 warning in 561.06s (0:09:21)
$ uv run python -m ruff check
All checks passed!
$ uv run python -m ruff format --check
705 files already formatted
$ uv run python -m supervisor.detectors.harness --detector injection_classifier --check
OVERALL: NO-GO
[OK] no drop below the baseline
$ uv run python data/eval/injection_vi_en/generate.py --check
[OK] golden files are current
$ uv run python -m tools.train_classifier        (about 2 min; rewrites weights.json and the card sha)
```

## 5. Validation table (held-out unless noted; balanced preset 6000 bp; thresholds ILLUSTRATIVE, declared before the run)

| Metric | Value (Wilson 95%) | Target | Verdict |
|---|---|---|---|
| recall, direct / indirect / poisoning | 4666 / 7000 / 5133 | 8500 | NO-GO |
| precision, direct / indirect / poisoning | 9589 / 8400 / 6814 | 9000 | GO / NO-GO / NO-GO |
| recall overall (dev 6200 [5743, 6637]) | 5600 [5138, 6052] | 8500 | NO-GO |
| false alarm, hard negatives (n 596) | 907 | 500 | NO-GO |
| false alarm, all benign (n 900) | 655 [511, 837] | 500 | NO-GO |
| typo evasion recall vs regex, same items | 4133 [3087, 5264] vs 400 | 7500 and gain over regex | NO-GO / GO |
| all 16 evasion kinds, classifier vs regex | 5069 vs 1125 | 7000 and gain | NO-GO / GO |
| hand-written probes (n pos 53): recall | 7735 [6447, 8655] (regex 3773) | 6000 | GO |
| probes: benign look-alike false alarm (n 24) | 416 (regex 1250) | 1000 | GO |
| false pauses on money/credit (0 of 539), pause recall 1011 | 0 bp | 100 | GO |
| pauses outside money/credit | 0 | 0 | GO |
| determinism (two model loads, 2,550 items) | 0 mismatches | 0 | GO |
| fragment exactness / leak items | 10000 / 0 | 9000 / 0 | GO |
| weights SHA-256 = card; thresholds = card | yes | yes | GO |
| latency per call p95 (whole registry run) | about 3.6 ms (no finding 2.3, finding 4.6) | 2 ms | NO-GO |

Failure taxonomy (by evasion type, template id, adversarial category) is in the report. Misses: ROT13 (1111), reversed (4444), typo, split fields, paraphrase without cue words, spaced letters, other languages. Regex baseline is given the same text units; in production Tier 0b sees only args of non-read-only calls.

## 6. Honest caveats

* The model learns synthetic template wording. Dev and held-out use disjoint template pools, which is why recall is far lower than on a random split (train fit is 10000). More templates and LLM paraphrase rounds raised dev recall at 500 bp false alarm from about 1,000 to about 5,000 before the model class ran out of room.
* Presets were chosen on an earlier dev version (balanced false alarm 480 bp); after the last paraphrase round dev reads 613 bp. Held-out was never used to tune. The adversarial probes got 15 more positives AFTER the first run (to reach n >= 50 as the coordinator asked); nothing was tuned on them.
* n counts items that share templates (about 100 template strings per pool); Wilson intervals understate template-level variance.
* The local LLM (qwen3.8-27b-int4, concurrency 2) was used only to reword templates, offline; `paraphrases*.json` are committed and items built from them are labelled "synthetic, LLM-paraphrased". The detector never calls a model.
* The secrets regex set named in the roadmap row (keys, tokens, PEM) was not in the WP25 prompt and is not built (BACKLOG).
* No new dependency (NumPy is in `uv.lock` but not used).

## 7. Files touched outside the package

`src/supervisor/gateway/detector_gate.py` (pause constants, `GATE-CLASSIFIER-PAUSE` block 1b, `tool_description` and `prior_calls` copied from context into `meta`), `src/supervisor/gateway/engine.py` (state change on classifier pause, extra tier 0 verdict row when rules also matched, `would_pause`), `src/supervisor/detectors/__init__.py` (registration), `src/supervisor/detectors/harness.py` (classifier slug, thresholds, MRM hook, classifier baseline, shared baseline not rewritten by a classifier-only record), `config/detectors.yaml`, `pyproject.toml` (ruff per-file ignores for the training and data tools), `tests/detectors/{test_contract,test_routes,test_harness}.py`, README, BACKLOG, CHANGELOG, `docs/threat-model.md`, `docs/detectors.md`. No console page touched.

## 8. Open questions for the owner

1. Real labelled Vietnamese injection data (or red-team traffic) is the only route to the recall target; can the bank supply some, or should WP28 generate attack traffic for training?
2. Accept a classifier that is validated NO-GO to ship disabled, or raise the bar (a larger model class means leaving the no-torch rule)?
3. Pause thresholds: pause recall is about 10 percent at 0 false pauses. Is "pause only on blatant injection" acceptable, or should pause stay off until validated?
4. Latency target 2 ms: relax to 5 ms, or invest in caching and cheaper fragment location?
5. Who are model owner, validator and approver (FILL-ME in the card), and should the card join `python -m supervisor.judge.mrm` inventory?
6. WP26: who registers `score_tool_description`, and what is the fail mode when the weights are refused (suggest: hold the tool for review)?
