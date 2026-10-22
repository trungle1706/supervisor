# Model card template: guard model (WP-D3)

Copy this file for the model the bank chooses (`docs/guard-model-decision.md`), fill every
`FILL-ME`, and keep it with the validation report. Follows `docs/judge-mrm.md` (identity, intended
use, data, metrics, failure modes, change log). The machine-readable part is
`data/models/guard_model/model_card.json`: the pause path reads its `approval` block. Not legal
advice.

## Identity

| Field | Value |
|---|---|
| Component | `guard_model@1.0.0` (`supervisor.detectors.guard_model`) |
| Adapter | FILL-ME (`classifier_endpoint` or `chat`) |
| Model id and pinned revision | FILL-ME (the id the endpoint serves: `GUARD_MODEL_NAME` and `model_id` in the JSON card; the revision: `GUARD_MODEL_VERSION` and `model_version`) |
| Model family | FILL-ME (for `chat`: must differ from every agent family; the start-up check enforces it) |
| Serving | FILL-ME (workspace, endpoint name, instance type, scale to zero yes or no, region) |
| Licence | FILL-ME (read by legal on the day of download; copy in `docs/LICENSES.md`) |
| Owner / developer / validator / approver | FILL-ME (see `docs/judge-mrm.md` section 2) |
| Risk level, approval document | FILL-ME (bank) |

## Intended use

Score masked text for two labels: `jailbreak` (a person tries to make the agent break its rules)
and `indirect_injection` (instructions hidden in tool results, tool descriptions or documents).
Input: user text fields of tool arguments, tool results, tool descriptions, extracted documents,
and the output side. Vietnamese and English.

The result is a finding (`guard.jailbreak`, `guard.indirect_injection`). It never blocks. On money
and credit tools it may carry the pause hint, only when this card names the approver.

Not intended for: system prompts (never sent), images and scans, languages other than Vietnamese
and English, toxicity (WP-D4), personal data (`dlp_vn`).

## Data and method

| Item | Value |
|---|---|
| Training data of the model | FILL-ME (from the model's own card) |
| Evaluation data | `data/eval/injection_vi_en` (WP25, synthetic, VI and EN) plus FILL-ME (bank samples, synthetic only) |
| Windowing | 2,000 characters, 500 overlap, the highest score wins, at most `max_windows` per call |
| Token limit of the model | FILL-ME (and the share of a 2,000-character Vietnamese window it sees) |

## Thresholds (basis points; ILLUSTRATIVE until the validation fills them)

| Preset | jailbreak | indirect_injection |
|---|---|---|
| strict | 3500 | 4000 |
| balanced | 5500 | 6000 |
| permissive | 8000 | 8500 |
| pause bar (floor) | 8000 | 8500 |

Frozen per detector version; a test compares them with `model_card.json`. Calibrated values: FILL-ME.

## Metrics (fill from `python -m supervisor.detectors.guard_harness --md ...`)

| Split | Recall bp | False-alarm bp | Typed recall bp | Leak items | p95 us |
|---|---|---|---|---|---|
| dev | FILL-ME | FILL-ME | FILL-ME | FILL-ME | FILL-ME |
| held-out | FILL-ME | FILL-ME | FILL-ME | FILL-ME | FILL-ME |
| adversarial | FILL-ME | - | FILL-ME | FILL-ME | FILL-ME |
| evasion | FILL-ME | - | FILL-ME | FILL-ME | FILL-ME |

Latency and cost: the symbols of `docs/guard-model-decision.md` section 4, measured by the live kit.

## Known failure modes

* A model can be fooled by encoding, split fields, other languages, and text that is long and calm
  with one short attack (the window helps; it does not cure).
* A quote of an attack, for example a security article or a test case, can score high (false alarm).
* A model outage or a timeout leaves the call unscored (`timed_out`, `execution_failed`). It never
  stops a payment unless fail closed is approved.
* Scores of a generative model (`chat` adapter) are verbalised numbers, not probabilities.
* Windows over the token limit are cut by the endpoint, and the tail is not read. FILL-ME.

## Approval (read by the pause path)

The `approval` block of `data/models/guard_model/model_card.json` must hold:

| Field | Needed for the pause hint |
|---|---|
| `approver` | A person's name. Empty or `FILL-ME...` means no approval |
| `model_id` | Equal to the card `model_id` and to the model id the adapter serves (`GUARD_MODEL_NAME`) |
| `model_version` | Equal to the card `model_version` and to `GUARD_MODEL_VERSION` (set, not `FILL-ME`). If the endpoint reports a version (`X-Model-Version` header or a `model_version` field), it must equal it too |

Residual: an endpoint that reports no version leaves the version as the operator's declaration. A
model swapped behind the same name and version is then not seen; re-run the harness after any
change on the serving side.

Also set `pause_tool_classes` in `config/detectors.yaml`. For fail closed add
`GUARD_MODEL_FAIL_CLOSED_APPROVED=1` (not recommended).

## Change log

| Date | Change | Validated by |
|---|---|---|
| FILL-ME | First card | FILL-ME |
