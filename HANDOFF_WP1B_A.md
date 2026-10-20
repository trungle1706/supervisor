# HANDOFF WP1b-A: judge config, family, served config (benchmark defects D14, D05, D15, D13, D12)

Branch `wp1b-a-judge-config` in worktree `/home/trung/supervisor/.claude/worktrees/agent-a575097aa11a5184c`.
Base: `de8a2ca` (integrated wave 1). Note: the branch `phase3-wave1` could not be checked out in this
worktree (another worktree holds it), so the new branch was created from `de8a2ca` by hand. The
`phase3-wave1` tip has moved on since (WP23 commits `6e68256`..`56bf53b`); the diff against `de8a2ca`
is the right one to review. No push, no merge.

## Result

| Item | State |
|---|---|
| D14 strict schema and temperature flags | Done. Contract test on recorded Anthropic 400s and a recorded 200. Live run done |
| D05 derived judge family, `family_source` | Done. In verdict rows, chain records, model card, validation report |
| D15 challenger scope | Done. One extra bug found by the live run and fixed (below) |
| D13 `POLICY_DIR`, `FACT_SOURCE` | Done for `wiring.py` and `gateway/wiring.py`. Laptop runtime test and databricks_app-settings test |
| D12 `HttpGate` path | Done. Falls back to `/gate/check` on a 404 |
| Tests | 3283 before, 3332 passed after (28 skipped, as before). Ruff check and format clean |

## Commits (all end with the Fable 5.1 trailer)

1. D12 HttpGate `/v1/gate/check` (+ follow-up: a base URL that already ends in `/v1` is not doubled)
2. D14, D05, D15 code and tests
3. D13 code and tests
4. Docs (llm-adapter, fact-sources, ADR D21, judge-mrm, README, CHANGELOG, BACKLOG, threat model)
5. ADR renumbered D20 (D19 is the WP23 ADR on the wave-1 head)
6. D15 follow-up from the live run

## Flags and settings (all default to the old behaviour)

| Setting | Default | Effect |
|---|---|---|
| `LLM_STRICT_SCHEMA` | `0` | `strict: true` and a schema copy without `minimum`, `maximum`, `pattern`, `maxItems`, ...; reply validated against the FULL schema |
| `LLM_SEND_TEMPERATURE` | `1` | `0` = no `temperature` in the request |
| `JUDGE_FAMILY_OVERRIDE_TEST_ONLY` | `0` | Accept a declared `JUDGE_*_FAMILY` that disagrees with the model. Refused in `databricks_app` mode (settings validation error) |
| `JUDGE_FAMILY_PROBE` | `0` | Also read the family from the judge endpoint `GET /models`; a clash with the model id refuses startup |
| `JUDGE_AGENTS` | empty | Agent ids whose manifests the challenger is checked against (besides registered non-retired agents) |
| `POLICY_DIR` | empty = `<repo>/policies` | Absolute folder; must exist; validated like the other path settings |
| `FACT_SOURCE` | empty = none | `sqlite:/abs/file.db` (read-only) or `callable:pkg.mod:factory` |
| `FACT_QUERY_MAP` | empty | YAML query map, required for `sqlite:` |

## Behaviour changes with flags off (read these)

1. A declared `JUDGE_T1/T2/CHALLENGER_FAMILY` that does not match the family derived from the model id,
   or that is given for a model whose id shows no family, now stops startup (`FamilyDeclarationError`,
   a `ConfigError`). A declaration that agrees is accepted. This is the D05 fix itself. The existing test
   `test_unknown_family_needs_explicit_setting` was changed to set the override flag.
2. `HttpGate` posts to `/v1/gate/check` (was `/gate/check`). One existing test URL assertion changed
   (`test_http_gate_without_credential_is_unchanged`). A base URL ending in `/v1` still gives
   `.../v1/gate/check`.
3. New nullable column `verdict.family_source` (model.yaml, both DDL files, notebook regenerated).
   Delta: run `python -m supervisor.jobs.bootstrap_schema` before deploying (additive migration).
4. In mock mode, `mrm validate` and the mock router factory swap a configured real challenger for a mock
   one, so a mock run makes no network call (before, a configured challenger was called for real).
5. The challenger is no longer checked against all manifests (D15). T1 and T2 still are.

## Design notes

* Family source values: `derived`, `declared-test-only`, `mock`. A declaration that agrees counts as `derived`.
* Strict mode: the model may break a stripped constraint. The live run showed this: `claude-sonnet-5-5`
  returned more than 5 `policy_refs` several times; the local schema check rejected it and the existing
  one retry ran. The final invalid rate is in the validation JSON (`Traces where Tier 1 gave no valid score`
  style counters of the eval harness). Temperature 0 cannot be sent to Anthropic, so determinism there
  rests on model id and prompt version (both recorded).
* The recorded fixtures were captured live on 2026-10-20 with the dev key (3 small calls); ids redacted:
  `tests/fixtures/llm/anthropic_compat.json`.
* `callable:` fact source imports a module named in settings (same trust as the environment); noted in the
  threat model. `sqlite:` queries must be one SELECT with one bound `?`.

## Live verification (dev key, `claude-haiku-5-5` / `claude-sonnet-5-5`, qwen challenger on the local server)

Commands (key stays in the scratchpad copy of `.env`, never printed or committed; a `.env` in the worktree
root breaks the test suite because the real judge URLs fail the loopback rule, so it was kept outside):

    SUPERVISOR_ENV_FILE=<copy of .env> LLM_ALLOW_REMOTE=1 LLM_STRICT_SCHEMA=1 LLM_SEND_TEMPERATURE=0 \
      python -m supervisor.judge.mrm validate --model settings --no-store --out <dir> --runs 1

Note: `--model settings` is needed for real judges; the plain command in the task text uses mock judges.
`--no-store` keeps the run out of the SQLite file.

Result of the full run (about 30 min, completed on its own before the coordinator asked to stop it;
no shortened proof run was needed and no further long run was started):

* Decision GO. Judges: T1 `claude-haiku-5-5`, T2 `claude-sonnet-5-5`, both `family anthropic`,
  `family_source: derived` (shown in `judge_validation.md` lines 7-8). Challenger `qwen3.8-27b-int4`
  (local server) was built and used, `family_source` derived: D15 works with the qwen demo manifests.
* Verdicts are real, not `unavailable`: held-out catch 86.67 %, false alarm 6.45 %, catch vi 88.24 %,
  en 84.62 %, injection detect 100 %, canary leak 0 %, challenger disagreement 10.11 % (n=89), stability range 0.
  Thresholds are the product's ILLUSTRATIVE defaults. Judge-human agreement was skipped (no human labels).
* Request: `strict: true`, stripped schema, no `temperature`: HTTP 200 on every call; no HTTP 400.
* Rejected-and-retried replies (local full-schema check): 12 in total.
  9 x `claude-sonnet-5-5` `policy_refs: more than 5 items` (2 of them failed the retry too),
  2 x qwen challenger `rationale: longer than 400`, 1 x qwen `evidence_spans[0].quote: longer than 160`.
  Strict mode cannot enforce `maxItems`/`maxLength`, so the model sometimes exceeds them. Each one costs a
  second call. FINDING, not changed: truncating a too-long rationale or quote, or keeping the first 5
  policy_refs, would be safe in principle, but it must happen in the adapter before the schema check and
  would change what `validate_output` accepts for every judge (a validation-relevant behaviour change), so
  it is recorded in BACKLOG instead of a one-line edit. Proposed fix: a `repair` hook in the judge runner
  (truncate rationale/quote, cap policy_refs at 5) with the repair count stored in the verdict row.
* Bug found by this run and fixed: the challenger comparison router in `mrm validate` re-checked the
  challenger as a Tier 1 judge against all manifests (commit 6, with a regression test).
* Report: `/tmp/claude-1003/-home-trung/ead0ba4a-d0d8-47bf-8c2b-0ab56f5277bd/scratchpad/wp1b-mrm/judge_validation.md` (and `.json`).
  Spend: about 600 judge calls on the Anthropic dev key over the two runs (first run died at the challenger step).

## Not done (also in BACKLOG.md)

* `FACT_SOURCE`: no Databricks SQL or REST kind, no cache.
* `POLICY_DIR` is not read by `analytics/tools*`, `assurance/targets.py` and the drill.
* T1 and T2 checks still include retired agents.
* `JUDGE_FAMILY_PROBE` only helps where the endpoint reports weights (vLLM `root`); Anthropic and Databricks
  serving give no family.
* Strict-mode invalid-output rate per model is not a gated metric.
* `mrm validate --model settings` takes about 30 min at `--runs 1` (254 items, sequential judge calls).

## Open questions for the owner

1. Is refusing a disagreeing declared family the wanted default, or should it be a warning for one release?
2. Should `JUDGE_FAMILY_PROBE` default on in `databricks_app` mode?
3. ADR number: D20 was used here because D19 is taken on the wave-1 head; the integrator may renumber.
4. Which system of record will the bank use for facts (decides the next `FACT_SOURCE` kind)?

## Files touched (for the integrator)

New: `src/supervisor/judge/family.py`, `src/supervisor/adapters/facts.py`, `docs/llm-adapter.md`,
`docs/fact-sources.md`, `docs/adr/D21-derived-judge-family-and-served-config.md`,
`tests/fixtures/llm/anthropic_compat.json`, `tests/unit/test_llm_strict_contract.py`,
`tests/judge/test_family_source.py`, `tests/gateway/test_policy_dir_fact_source.py`, this file.

Shared files, minimal edits: `src/supervisor/config.py` (new settings, `_absolute` list, validators in
the model validator), `schema/model.yaml`, `schema/ddl/*.sql`, `notebooks/bootstrap_and_smoke.py`
(regenerated), `README.md`, `CHANGELOG.md`, `BACKLOG.md`, `docs/index.md`, `docs/judge-mrm.md`,
`docs/threat-model.md`.

Code: `adapters/factory.py`, `adapters/llm/openai_compatible.py`, `adapters/llm/jsonschema_lite.py`,
`core/models.py` (`Verdict.family_source`), `gateway/sdk.py`, `gateway/wiring.py`, `wiring.py`,
`judge/router.py`, `judge/runner.py`, `judge/service.py`, `judge/prompts/schema.py`,
`judge/mrm/{_common,card,identity,validation}.py`.

Tests changed: `tests/gateway/test_sdk.py`, `tests/gateway/test_ingress_cli_config.py`,
`tests/judge/test_router.py`.
