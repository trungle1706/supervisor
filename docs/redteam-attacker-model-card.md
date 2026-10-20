# Model card: multi-turn red team, LLM attacker and evidence judge (WP28)

Follows the conventions of `docs/judge-mrm.md` and `docs/masker-model-card.md` (identity,
intended use, data, metrics, failure modes, change log, change control). Two components use a
model, both optional and both off unless asked for. The attack strategies, the oracle and the
mock agent are deterministic code and are covered by `docs/redteam-multiturn-validation.md`.
Not legal advice.

## Identity

| Field | Value |
|---|---|
| Components | `supervisor.redteam.multiturn.attacker.LlmAttacker` (rephrases one attacker turn); `evidence_judge.LlmEvidenceJudge` (two-stage success / benign comparison) |
| Model | Whatever `REDTEAM_ATTACKER_MODEL` names on the configured `LLM_BASE_URL`. Pinned by id in every result row (`attacker_model`). Validated on `qwen3.8-27b-int4` (local, OpenAI-compatible) |
| Prompt versions | `mt-attacker-1`, `mt-evidence-1` (in every row / verdict) |
| Temperature | 0 (sent by the adapter; endpoints that refuse it: `LLM_SEND_TEMPERATURE=0`, then determinism rests on model id and prompt version, see BACKLOG in `docs/llm-adapter.md`) |
| Default | Off. Without `REDTEAM_ATTACKER_MODEL` the template attacker is used; the nightly job never uses a model |
| Offline stand-ins | `TemplateAttacker` and `HeuristicEvidenceJudge` (labelled `mock`) |
| Owner / developer / validator / approver | FILL-ME (bank names them; see `docs/judge-mrm.md` section 2) |
| Risk level, approval document | FILL-ME (bank) |
| Family rule | The attacker model may belong to any family: it never judges, it only rephrases. The evidence judge should differ from the agent family like any judge (`JUDGE_*` registry rules apply when it is wired to a judge endpoint) |

## Intended use

* Attacker: give the six template families a wider range of wording, in Vietnamese and English,
  for a red-team exercise in the sandbox. It cannot change the calls, their order or the
  numbers. It runs by hand (`--attacker llm`), at most 60 attack conversations per run, one call
  at a time.
* Evidence judge: add a second opinion to a conversation next to the deterministic oracle. It
  never decides success, never calls the gate (R1).

Not intended for: generating content against real customers or real systems, anything outside
the sandbox, use as a gate or a classifier, scoring a model's safety from its own output.

## Data and what leaves the process (R2, R3)

Only the configured endpoint is called. The prompt holds the system text, the language, the
stage name and ONE template turn in which every id, amount, tool name and digit string is replaced
by `<<Tn>>` and restored afterwards. No customer text exists in the sandbox (synthetic world).
The evidence judge receives a compact transcript with digit runs of six or more masked. Neither
component writes model text to the chain: the chain holds integers; traces hold turn text (digit
runs masked) in files.

## Metrics (live check, see the validation report)

Live check, 2026-10-20, `qwen3.8-27b-int4` on the local OpenAI-compatible endpoint, concurrency 1,
temperature 0, prompt `mt-attacker-1`, 60 Vietnamese attack conversations (one trial per objective,
all three agents, model pass only). Full context: `docs/redteam-multiturn-validation.md` section 6.

| Check | Result |
|---|---|
| Turns / rephrased by the model / left as template | 535 / 525 / 10 (the 10 are fake-policy turns, never rephrased by design) |
| Fallbacks to the template (`llm_fallback`) | 0 of 525 |
| Rephrased text differs from the template text | 490 of 500 compared turns |
| Placeholders restored, ids / amounts / digit strings never sent | by construction, checked by `tests/redteam/test_probes_attacker_judge.py` with a recording fake chat |
| Oracle result agrees with the template run on the same seeds | 54 of 60 conversations (same turn of first success: 48 of 60) |
| Determinism at temperature 0 | two runs of 6 conversations: 46 of 46 turn hashes identical |
| Latency | 256 s for 60 conversations (4.3 s each, about 0.5 s per rephrased turn) |
| Cost | local model, no per-token charge. A cloud model would see about 300 input and 80 output tokens per turn: 60 conversations are about 130 thousand input and 35 thousand output tokens. The Anthropic dev key was not used |
| Evidence judge (LLM path) | not run live: tested with a fake chat (two calls per conversation, masked transcript, endpoint failure gives `unclear`). Validate on the bank's judge model before any use beyond evidence |

## Known failure modes

1. The model drops or invents a placeholder, or returns a longer text: the template text is used
   (`llm_fallback`, counted per row).
2. The model changes the tone so that a cue the mock agent reads ("as you said", "expand on") is
   lost: the mock pressure is lower. The oracle is unaffected.
3. The model refuses a role-play request or adds a warning: the length and placeholder checks
   catch most of it; a polite refusal that keeps all placeholders would pass. Rows keep the text.
4. Endpoint down or slow: each turn falls back to the template; the run continues.
5. Vietnamese quality is the model's: diacritics errors are possible and are part of the test.
6. The evidence judge can disagree with the oracle in both directions. Its verdict is evidence
   for a human; agreement with the oracle is reported, never optimised.

## Change log

| Version | Date | Change |
|---|---|---|
| `mt-attacker-1`, `mt-evidence-1` | 2026-10-20 | First version (WP28): protected tokens, fallback, cap of 60 conversations, two-stage judge |

## Change control

A change to a prompt text bumps the prompt version and needs a re-run of the live check in the
validation report on the held-out split. A change of model id is a new row in the report, not an
edit of an old one. The cap of 60 conversations per live run is a code constant and a setting
(`REDTEAM_LLM_MAX_CONVERSATIONS`, upper bound 60); raising the bound is a reviewed change.
