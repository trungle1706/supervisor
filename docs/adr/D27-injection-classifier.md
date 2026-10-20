# D27: Injection classifier, Vietnamese and English (WP25)

Status: accepted for WP25 (phase 3, wave 2). It is a detector (`injection_classifier`) behind
`DETECTORS_ENABLED`; its own `enabled` key in `config/detectors.yaml` is `false` by default.
D24 to D26 belong to other packages; this is the next free number on the WP37 branch (D23).

## Context

Tier 0b is a regex list. It caught 57 percent of typo evasions (BACKLOG), looks only at the arguments
of non-read-only calls and never at tool results or tool descriptions (credit benchmark finding D04).
WP37 gave every detector one contract and kept `pause` and `block` hints reserved "for WP25 after
model-risk validation". The owner asked for a small local model for prompt injection that runs on a
bank laptop with no download, no GPU and no compiler (CLAUDE.md), that scans arguments, tool results
and tool descriptions, and that may stop only money and credit tools.

## Decision

1. **A linear model, pure Python.** Hashed character n-gram and word features (65,536 buckets) plus a
   small bilingual concept layer (4,096 buckets), logistic regression, integer weights in a JSON file
   with a model card. No torch, no numpy at run time, no download. Training uses only the standard
   library (`tools/train_classifier.py`). NumPy is in `uv.lock` but is not needed, so it is not used.
   Rejected: a transformer (CLAUDE.md forbids torch and runtime downloads), a naive-Bayes score
   (worse on the dev split), a fuzzy regex (the 57 percent problem moves, it does not go away).
2. **Normalisation before features.** The Tier 0b normaliser (NFKC, zero-width removal, case fold,
   look-alike folding), diacritics removal, leetspeak and `$`-for-`s` folding inside words, Telex
   decoding as a second variant, base64 decoding of long tokens, ROT13 and reversed text only when a
   trigger lexicon says the decoded form looks like an instruction, JSON-in-string flattening,
   markers for hidden HTML comments and invisible characters. Split fields are joined; prior calls come
   from `context.prior_calls`.
3. **Three surfaces, three codes.** `args` gives `injection.direct_injection`, `tool_results` (and the
   output side) `injection.indirect_injection`, the called tool's `context.tool_description`
   `injection.tool_poisoning`. One shared weight vector, one bias per surface.
4. **R1 stays.** The classifier never blocks. Its finding carries `action_hint = "pause"` only when
   the score is at or above the frozen pause threshold and the tool's risk class is in
   `pause_tool_classes` (default money, credit). The gate (`detector_gate.py`) turns the hint into
   `pause` with rule id **`GATE-CLASSIFIER-PAUSE`**, only for a detector in `PAUSE_CAPABLE_DETECTORS`,
   only when the call was allowed, not a shadow call, input direction, risk class in money, credit or
   pii_export. The agent is paused through the normal state machine, the verdict row is a tier 0
   `pause` row (so `sync_gate_cases` opens a case as today) and two people resume as today. A read-only
   tool, an output check or a shadow agent only gets a `report`.
5. **Frozen per model version.** Presets, the pause threshold, the weight file (SHA-256 in the model
   card) and the feature version form one version. The loader refuses a weight file whose SHA-256, version
   or feature version differs from the card. The pause threshold setting can be raised, never lowered.
6. **Not fail closed.** `fail_closed: false`. A classifier outage (a refused weight file, a timeout)
   must not stop payments: the rules still run, and the failure shows in `not_executed`. Category is
   `content_security` (not `advisory`, which WP37 review forces to non-fail-closed anyway).
7. **Validated like a model.** Model card, validation report with GO/NO-GO per metric
   (`docs/injection-classifier-validation-report.md`), Wilson intervals, evasion table against the
   regex on the same items, hand-written probes outside the templates, frozen thresholds, baseline
   file and a regression test. Data are synthetic ("synthetic, this repo"), with disjoint template
   pools for train, dev and held-out; some templates were reworded offline by the local LLM and are
   labelled "synthetic, LLM-paraphrased".
8. **Tool descriptions.** `score_tool_description(text) -> bp` is the adapter for WP26 tool locking
   (`mcp_lock.register_description_scorer`); WP26 is not on this branch, so nothing is registered here.

## Consequences

* New code: `src/supervisor/detectors/injection_classifier/`, `tools/train_classifier.py`,
  `data/models/injection_vi_en/1.0.0/`, `data/eval/injection_vi_en/`.
* Additive edits to WP37 files (listed in HANDOFF_WP25.md): `detector_gate.py` (pause path and two
  context keys), `engine.py` (state change, verdict row, dry-run flag), `harness.py`, `__init__.py` of
  the detectors package, `config/detectors.yaml`.
* The pause threshold and presets are ILLUSTRATIVE; the bank sets them from real data. A model
  trained on synthetic templates is weaker on real attacks. The validation report says by how much it
  is weaker on the data we have, and the BACKLOG lists what is open.
