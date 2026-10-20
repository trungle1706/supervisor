# REVIEW WP1b-A (judge config, family, served config: D05, D12, D13, D14, D15)

Reviewer: Opus (model risk validator SR 11-7 / ISO 42001, application security, senior Python).
Branch `wp1b-a-judge-config`, base `de8a2ca`, reviewed head `f9bdda2`, head after review fixes: see
`git log` (5 review commits on top, plus this file). No push, no merge, no history rewrite.

## Verdict

**APPROVE WITH FIXES APPLIED.** The work is sound and well tested. I found 4 significant items
and fixed them on the branch: the family table was incomplete, so a Gemini or Mistral judge could
not start; the `callable:` fact source allowed code execution by configuration; mock judge runs
outside `mrm validate` could still call a real challenger; and a validation with a declared family
could still give GO. I also renamed the ADR to D21. After the fixes the branch is ready to merge.
Expect the small merge conflicts listed below.

## Findings

| # | Area | Severity | Finding | Action |
|---|---|---|---|---|
| 1 | D05 table | High | `FAMILY_PREFIXES` had no `gemini` or Mistral entries (`mistral:7b` was tested as `unknown`). Before, an unknown id was handled by `JUDGE_*_FAMILY`. Now that the family is derived, an unknown id cannot judge at all in `databricks_app` mode | FIXED (17bc4c8): added gemini -> google and mistral/mixtral/ministral/codestral -> mistral. Added tests for `databricks-claude-*`, `databricks-meta-llama-*`, `databricks-gpt-oss-*`, `openai/gpt-oss-*`, `us.anthropic.claude-*`, `meta-llama/Llama-*`, `databricks-gemma-*`, `databricks-qwen3-*` and a custom name (unknown). All map correctly |
| 2 | D05 refusal with flags off | Medium | On Databricks, serving endpoints often have custom names (`tcb-judge-t1`). These ids show no family, and the override is refused in `databricks_app`. So with the branch as delivered, such a judge cannot start, and the only fix is to rename the endpoint | FIXED (17bc4c8): `JUDGE_FAMILY_STRICT` (default `1`, so refusal stays the default). `0` accepts a declaration ONLY for an id with no derivable family, as `family_source=declared-unverified`, with a warning. It is allowed in every mode. A declaration that disagrees with a derived family is always refused (that is the D05 attack). Documented in llm-adapter, judge-mrm, threat model, ADR, README, CHANGELOG |
| 3 | D05 / MRM | Medium | The docs said "a validation with `declared-test-only` must not be used for go-live", but `mrm validate` could still give GO | FIXED (17bc4c8): new check `judge_family_derived` gives NO_GO when the T1 or T2 source is `declared-test-only` or `declared-unverified`. `mock` and `derived` pass. Tests cover both declared sources and mock |
| 4 | D13 `callable:` | High (security) | `importlib.import_module(<module from settings>)` runs code chosen by configuration (`callable:os:system` was accepted as far as import) | FIXED (761c282): module and factory names must be dotted identifiers, and the module must be under a CSV package prefix in `FACT_CALLABLE_ALLOW_PREFIX` (default `supervisor.`). A prefix matches a package, not a string, so `supervisorx` is refused. Checked in settings validation and again in `make_fact_source`. 8 new tests |
| 5 | D15 mock path | Medium (R3, mock labelling) | `judge.eval` (mock) and `assurance.targets.MockJudgeTarget` still built a configured real challenger. A "mock" run then called the network and mixed real and mock scores | FIXED (06a27be): both now use `with_mock_challenger`. New tests patch `httpx.HTTPTransport.handle_request` and `socket.connect` to fail on any call, set a remote challenger sampled at 100 %, and run `mrm validate`, `judge.eval` and the mock target. I removed the swap on purpose and confirmed that both tests then fail |
| 6 | ADR number | Admin | D20 is used by WP1b-B (`D20-monitor-bindings.md` on phase3-wave1) | FIXED (7b59a23): `git mv` to `D21-derived-judge-family-and-served-config.md`, links fixed in README, CHANGELOG, judge-mrm, threat model, handoff |
| 7 | D14 strict copy | OK | Only `STRICT_UNSUPPORTED` keywords are dropped. Property names under `properties`/`$defs` are kept. The full schema still validates the reply (test). There is 1 retry, then `LLMOutputError` (bounded). `LLM_SEND_TEMPERATURE=0` leaves out `temperature` (contract test on the recorded 400/200) | none. Note: a user-named key under a mapping-valued keyword other than `properties`/`$defs` (for example `dependentSchemas`) would be stripped. The judge schema does not use one |
| 8 | D14 fixtures | OK | `tests/fixtures/llm/anthropic_compat.json`: no `sk-ant`, no `req_`, no org id; the id is `msg_REDACTED` | none |
| 9 | R3 `LLM_ALLOW_REMOTE` | OK | The branch does not change it. The loopback rule and the `databricks_app` "workspace serving URL only" rule still apply to `LLM_BASE_URL` and all three `JUDGE_*_BASE_URL`. The family probe calls only the already-allowed judge base URL | none |
| 10 | D13 sqlite | OK | `file:...?mode=ro` URI (path quoted) plus `PRAGMA query_only`. A query must be one SELECT (no `;`) with exactly one `?`, and the key is bound. Source names use a regex. A relative path resolves to an absolute path under the repo root at config load. A write raises (test). A DB error returns None, so the rule's fail mode applies | none. Low: a BLOB column is returned as `bytes` (gateway behaviour not tested) |
| 11 | D13 `POLICY_DIR` | Low (open) | Used by `wiring.build_runtime` and `gateway.wiring.build_gateway`. These still read `<repo>/policies`: `analytics/tools.py` (`risk_classes`), `analytics/tools_suggest.py`, `assurance/targets.py`, the drill, and also (not in the handoff) `inventory/service.py` (BASELINE), `regkb/loader.py`, `advisory/compliance/demo.py`. On the wave-1 head, WP1b-B's monitor loader reads `<repo>/policies` plus `MONITOR_POLICY_DIR`. Effect: with `POLICY_DIR` set, tool risk classes and monitor bindings can differ from what the gate enforces | BACKLOG (exists for 3). Integrator: route `monitors/sweeps.py` through `resolve_policy_dir` |
| 12 | D12 | OK | `/v1/gate/check`. One fallback, only on HTTP 404 (`.response.status_code`, kept by `post_bytes`/`post_json`), then the legacy path is kept. The signature uses `urlparse(url).path` of the URL actually sent, including on the fallback. A base URL that ends in `/v1` is not doubled and does not fall back. The server mounts the router at `/` and `/v1` | none |
| 13 | Migration | OK | `verdict.family_source` is nullable. I checked an old-schema SQLite file (base DDL) with `bootstrap_schema`: 1 column added, trigger recreated. DDL and notebook current (suite test) | none |
| 14 | Family source of injected chats | Low | `JudgeModel.family_source` uses `"derived"` as the default for a non-mock chat without the attribute (only code-level `chats=` injection) | residual |
| 15 | Secrets / .env | OK | No `.env` tracked or present in the worktree (only `.env.example`, unchanged). No tokens in the diff. Diff is ASCII | none |

## D05 decision on refusal versus a warning mode

A pure one-release warning mode (accept any declared family, warn) would re-open the exact hole D05
closes: a qwen judge declared as anthropic, watching a qwen agent. So disagreement stays a hard
refusal. A custom endpoint name is a real operational case and a different one: the id contains no
family. `JUDGE_FAMILY_STRICT=0` is the narrow escape for that case. It is visible in every row and
cannot produce a passing validation.

## Tests

| Run | Result |
|---|---|
| Base of review (head `f9bdda2`) | 3332 passed, 28 skipped |
| After review fixes | **3359 passed, 28 skipped** (+27 new tests; no test removed or skipped; one base test row changed: `mistral:7b` is now `mistral`, not `unknown`) |
| `ruff check .` / `ruff format --check .` | clean / clean (628 files) |
| Strict contract test `tests/unit/test_llm_strict_contract.py` | 8 passed |
| Live LLM calls | none run by the reviewer |

## Residual risks

* The family is still a name match. A model id that lies about its weights (`claude-x` served by
  qwen) is caught only by `JUDGE_FAMILY_PROBE=1`, and only where the endpoint reports `root`.
  Databricks serving and Anthropic do not report it. A Databricks probe through
  `GET /api/2.0/serving-endpoints/{name}` (served entity name) would close this for the bank. This is a BACKLOG candidate.
* `JUDGE_FAMILY_STRICT=0` is meant for one release. Remove it in the next phase or make it refuse
  in `databricks_app` once endpoint naming or the probe is in place.
* `FACT_CALLABLE_ALLOW_PREFIX` limits which package can be loaded. It does not stop an operator
  who can edit both variables, or anyone who can write into an allowed package on `sys.path`.
* Strict mode cannot enforce `maxItems`/`maxLength`. The live run had 12 retries (9 from
  `policy_refs` > 5), and the extra calls cost money. The proposed `repair` hook is in BACKLOG.
* T1/T2 checks still include retired agents (conservative, BACKLOG).
* `POLICY_DIR` is not read everywhere (finding 11).

## Merge notes

* Base `de8a2ca`. phase3-wave1 is now `8c86977` (f0b6bf4 + WP1b-B merged). `git merge-tree`
  against it shows **2 conflicts, both "keep both"**:
  * `src/supervisor/config.py`: the `# --- WP1b-B ---` block (`monitor_policy_dir`,
    `monitor_manifest_dir`) and the `# --- WP1b-A ---` block (`policy_dir`, `fact_source`,
    `fact_query_map`, `fact_callable_allow_prefix`) at the end of the settings class. Keep both.
    The `_absolute` field_validator list on phase3-wave1 does not name `monitor_policy_dir` or
    `monitor_manifest_dir` (WP1b-B resolves them itself); this branch adds `policy_dir` and
    `fact_query_map` there. Keep this branch's additions.
  * `BACKLOG.md`: two new rows in the same place. Keep both.
* These auto-merge but need a check: `CHANGELOG.md`, `README.md`, `docs/index.md`, `schema/model.yaml`,
  both DDL files and `notebooks/bootstrap_and_smoke.py` (both add a column: WP1b-B
  `monitor_status`, WP1b-A `verdict.family_source`). Run `uv run python -m schema.generate`
  (`make ddl`), then the DDL-current test. `core/models.py` auto-merges.
* `judge/router.py`: `FAMILY_ALIASES` is unchanged on this branch, so WP1b-B's
  `onboard/codefacts.py` import still works. The new prefixes are in
  `adapters/llm/openai_compatible.py` (`FAMILY_PREFIXES`), not in the alias table. If
  codefacts should know gemini/mistral, it must read `model_family()` too.
* `monitors/sweeps.py`: this branch does not touch it. After merge, it should honour
  `POLICY_DIR` (finding 11).
* ADR: this branch now has `D21-...`. WP1b-B keeps `D20-monitor-bindings.md`.
* Delta deploy: run `python -m supervisor.jobs.bootstrap_schema` before the new app version
  (additive `verdict.family_source`).

## Review commits

| Commit | What |
|---|---|
| 7b59a23 | ADR D20 -> D21, links |
| 17bc4c8 | D05: family table, `JUDGE_FAMILY_STRICT`, validation check `judge_family_derived` |
| 761c282 | D13: `FACT_CALLABLE_ALLOW_PREFIX` allow-list for `callable:` |
| 06a27be | D15: mock swap in `judge.eval` and `MockJudgeTarget`, no-network tests |
| (this) | REVIEW_WP1B_A.md, handoff link fix |
