# LLM adapter and judge models (WP1b-A)

One adapter, `adapters/llm/openai_compatible.py`, talks to any OpenAI-compatible
`/v1/chat/completions` endpoint (httpx only). The judges use it through
`adapters/factory.py:make_judge_chat_model`. This page covers the settings added after the
credit-memo benchmark (defects D14, D05, D15).

## 1. Strict endpoints, for example Anthropic (D14)

Anthropic's OpenAI-compatible endpoint (`https://api.anthropic.com/v1`) answers HTTP 400 to the
default request in three ways. The 400 bodies below are recorded in
`tests/fixtures/llm/anthropic_compat.json` and the contract test
`tests/unit/test_llm_strict_contract.py` replays them.

| Request detail | Recorded 400 message | Flag that fixes it |
|---|---|---|
| `json_schema.strict` is `false` | `response_format.json_schema.strict: Input should be True` | `LLM_STRICT_SCHEMA=1` |
| Schema has `minimum`, `maximum`, `pattern`, `maxItems`, ... | `For 'integer' type, properties maximum, minimum are not supported` | `LLM_STRICT_SCHEMA=1` (the adapter sends a stripped copy) |
| `temperature` is sent | ```temperature` is deprecated for this model.`` | `LLM_SEND_TEMPERATURE=0` |

| Setting | Default | Meaning |
|---|---|---|
| `LLM_STRICT_SCHEMA` | `0` | Send `strict: true` and a copy of the schema without the refused keywords (`jsonschema_lite.STRICT_UNSUPPORTED`). The reply is still validated against the FULL schema here (`validate_output`), so a score of 20000 or a bad policy reference is rejected locally, with the same one retry as before |
| `LLM_SEND_TEMPERATURE` | `1` | `0` leaves `temperature` out of the request |

Both apply to every adapter built from settings (the main model and the three judge roles).
With both off the request is byte-for-byte what it was before. The judge copy of the output
schema is `judge.prompts.schema.STRICT_OUTPUT_SCHEMA`; it is derived, never edited by hand.

Settings for the dev-key run (the key stays in `.env`, never in git):

    LLM_ALLOW_REMOTE=1
    LLM_STRICT_SCHEMA=1
    LLM_SEND_TEMPERATURE=0
    JUDGE_T1_BASE_URL=https://api.anthropic.com/v1
    JUDGE_T1_MODEL=<pinned model id>

Temperature 0 is the harness standard for determinism. When the endpoint refuses it, the
determinism claim rests on the pinned model id and prompt version, which every result row
records. Say so in the validation report notes.

## 2. Judge family is derived, not declared (D05)

The rule "judge family differs from agent family" only works if the judge family is true. It is
now taken from the model, in this order:

1. the model id prefix table (`claude` -> anthropic, `gpt` -> openai, `qwen` -> qwen, ...);
2. with `JUDGE_FAMILY_PROBE=1`, the endpoint's own `GET /models` entry (`root`, `id`,
   `display_name`). If the id and the endpoint name different families, startup is refused.

A declared `JUDGE_T1_FAMILY` / `JUDGE_T2_FAMILY` / `JUDGE_CHALLENGER_FAMILY` is accepted only
when it agrees with the derived family. Any other declaration, including one for a model whose
family cannot be derived, is refused at startup, unless `JUDGE_FAMILY_OVERRIDE_TEST_ONLY=1`.
That flag is refused when `SUPERVISOR_MODE=databricks_app`.

| `family_source` | Meaning |
|---|---|
| `derived` | From the model id / endpoint metadata (a declaration that agrees counts as derived) |
| `declared-test-only` | Declared under the test-only override. Do not use for a validation that counts |
| `mock` | Mock judge (no real model) |

`family_source` is written to: every judge verdict row (`verdict.family_source`, new column) and
its `judge_verdict` chain record, the judge model card (tiers section), the identity block of the
MRM validation report (`t1_family_source`, `t2_family_source`, also in the `judge_validation`
chain record), and `JudgeRouter.describe()`.

Migration: `verdict.family_source` is a new nullable column. On Delta run
`python -m supervisor.jobs.bootstrap_schema` before the new app version (additive migration).

Behaviour change (the only one with flags off): a declared family that does not match the model
id used to be trusted; now it stops startup with `FamilyDeclarationError` (a `ConfigError`).

## 3. Challenger scope (D15)

The challenger scores a 5 % sample and is never acted on. It is now checked only against the
agents it judges: registered agents of the store whose `agent.status` is not `retired`, plus the
committed manifests of the agent ids in `JUDGE_AGENTS` (comma list, default empty). Tier 1 and
Tier 2 are still checked against every manifest and every registry row. Effect: a qwen challenger
no longer stops the judge service or `python -m supervisor.judge.mrm validate` because of the
qwen demo manifests. In a mock-mode validation a configured real challenger is replaced by a mock
one, so the run makes no network call.

## 4. Commands

    python -m supervisor.judge.mrm validate --model settings --out OUT --runs 1
    python -m supervisor.judge.mrm card --out OUT

`--model settings` uses the configured judges. Without it the run uses mock judges and the report
says `MOCK`.
