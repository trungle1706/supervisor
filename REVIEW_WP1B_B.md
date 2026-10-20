# REVIEW WP1b-B: onboarding precision (D08) and monitor bindings (D06)

Reviewer: Opus (platform engineer + model-risk validator + senior Python view).
Branch `wp1b-b-onboard-monitors`, base `de8a2ca`. Reviewed commits f3ef83d..679c457 and the full
`git diff de8a2ca...HEAD`. Review fixes are 6 small commits (ef11f5d..9a0cda0 plus this file).
No push, no merge, no history rewrite.

## Verdict

**GO for merge into phase3-wave1, after the review fixes on this branch.** The design is sound
and the eval is not trivially passing. One security gap (env values) and one precedence defect
were significant; both are fixed with tests.

## Findings

| # | Area | Severity | Finding | Action |
|---|---|---|---|---|
| 1 | D08 security | High | `_env_values` read the VALUE of every `KEY=value` in `.env*` files and `env:` lists, including `OPENAI_API_KEY`, `HF_TOKEN`, `DB_PASSWORD`. Short or odd secrets pass the regex scrubber (probe: `abc12`, `hfshort`, `x9` were kept), and `API_KEY = os.environ[...]` then put the value into `_File.consts`. Discover indexes only `.env.example` (not `.env`), so exposure was limited, but the rule is "never read secret values". | Fixed (ef11f5d): names that look like a credential (key, token, secret, pass, pwd, credential, auth, private, cert, signature, salt, cookie, session, dsn, conn, pat) are never read; redaction markers dropped. Test `test_env_files_never_yield_credential_values`. Docs in `docs/onboard.md` (9a0cda0). |
| 2 | D06 precedence | Medium | `_pick` took the whole section from the first layer. A policy that set only `fairness.approve_values` dropped the manifest `decision_tool` and fell back to derivation. `docs/monitors.md` says "for every field the first hit wins". | Fixed (0410b17): field-by-field merge (policy over manifest), source = layer that set the binding field. Test `test_policy_overrides_field_by_field_not_whole_section`. |
| 3 | D06 / R2 fairness | Medium | Forbidden attributes were checked only on the attribute NAME. `{"group": "ethnicity"}` sliced by ethnicity under another name; `Dan-Toc` was not normalised. | Fixed (0410b17): both name and argument key checked after normalising separators. Test extended. |
| 4 | Console | Low-Medium | Template uses `StrictUndefined`; a `monitor_status` entry without `status` made the Metrics page fail (HTTP 400 "unexpected error", not 500, but the page was unusable). | Fixed (8e3a878): view keeps only `ok` / `not_applicable` / `no_data` entries. Test `test_metrics_page_survives_partial_or_bad_status`. |
| 5 | D08 provider | Low | `create_react_agent(os.getenv("M"))` with `databricks-gpt-oss-120b` gave provider `openai`. | Fixed (ef11f5d): `databricks-*` endpoint names give provider `databricks`. Corpus still 100 % provider accuracy. |
| 6 | ADR number | Low | `D19-monitor-bindings` clashes with phase3-wave1 `D19-latency-benchmark`. | Fixed (a0faba5): `git mv` to `D20-monitor-bindings.md`; links fixed in `docs/monitors.md`, CHANGELOG, README, `docs/index.md`, handoff. |
| 7 | Eval honesty | Info | Labels and analyser change are in one commit (f3ef83d), so "labels written before the change" cannot be proven from git. I checked the eval discriminates: old analyser (`de8a2ca`) with the new labels gives tools P 92.65 % (5 route FPs), entrypoints 0/8, model family 0/16, framework 20/21; 3 gates FAIL. New code: all gates OK. n = 8 entrypoints and its interval (67.55 % to 100 %) are stated honestly in `docs/onboard-eval.md`. | No change. Residual risk below. |
| 8 | R2 code check | OK | Fairness reads `args_masked` only (`EventDecisionSource.records`), subject id hashed at once with `subject_hash(key, sid)`; raw id not kept. Statuses are not on the evidence chain. | Verified. |
| 9 | Route detection | OK | Router prefix of `APIRouter(prefix=...)` in the same file is applied; routes under `/tools`, `/functions`, `/actions`, `/mcp` stay tools (and are also entrypoints); `include_router(prefix=)`, Flask, Starlette, `add_api_route` gaps are stated in BACKLOG and `docs/onboard-eval.md` (probe confirms `include_router(s, prefix="/tools")` route is an entrypoint only). | Verified. |
| 10 | Derivation | OK | Two `credit` or several `money` tools (no `transfer`) give `not_applicable` with tool names; a money tool named `reply_*` is not an output tool. Quality takes every reply-like name (not an ambiguity); tool-name collision is documented in the ADR. | Verified. |
| 11 | Schema | OK | `monitor_status` nullable JSON in `model.yaml`, both DDL files, `OversightMetric`; bootstrap notebook regenerated; additive column added by the existing `core/schema_diff.py` migrate path (SQLite `ADD COLUMN`, Delta `ADD COLUMNS`). `policies/schema.json` equals `policy_json_schema()`. | Verified offline. Live Delta ALTER not run. |
| 12 | Rules | OK | R1: monitors only open cases / write metrics; nothing gates. R3: no network. No new dependency. No `exec` / `eval` / `subprocess`. Non-ASCII only in VI console strings. Flags unchanged (`QUALITY/FAIRNESS/DRIFT/MULTIAGENT_ENABLED`); new settings optional and default None. | Verified. |

## Test counts and commands

| Check | Result |
|---|---|
| Full suite before review | 3326 passed, 28 skipped |
| Full suite after review fixes | 3329 passed, 28 skipped (+3 review tests) |
| `ruff check src tests`, `ruff format --check src tests` | clean |
| `python -m supervisor.monitors.binding_harness` | 12 of 12 `[OK]`, golden match |
| `python -m supervisor.onboard.eval --corpus data/corpus/repos --labels data/corpus/labels.yaml` | 21 repos, all 12 gates OK; tools P/R 100 % (n=63, Wilson 94.25 to 100), entrypoints 100 % (n=8, 67.55 to 100), model family 16/16 (80.64 to 100) |
| Same eval with the `de8a2ca` analyser | 3 gates FAIL (entrypoints P, R; model family); tools P 92.65 % |

## Residual risks

1. Same engineer wrote the fixture, labels and rules; no blind held-out repo. Entrypoints n = 8 and
   the 15 back-filled `model_family` labels are derived from older gold labels, not independent.
2. A corrupt `monitor_status` string in the DB (manual SQL) still breaks the Metrics page with a
   JSON decode error in the state layer (generic JSON-column behaviour, not WP1b-B specific).
3. Fairness attribute values taken from call args go into slice names unchanged; a mis-bound key
   that points at a free-text field would create many tiny cells (suppressed by `min_cell_n`,
   and the value is already masked). Consider a length / cardinality cap.
4. Env-name deny list is conservative but name-based; an endpoint stored under a name like
   `MODEL_KEY` is now not resolved (family stays `unknown`, fill by hand).
5. Multi-agent: each (tool, keys) variant has its own cursor; a new variant starts with the
   first-run lookback, so the first scan of a newly bound agent may re-read up to that window.
6. Live Delta: the `ADD COLUMNS monitor_status` migration is tested offline only.

## Merge notes

- Branch base `de8a2ca`; phase3-wave1 is now `f0b6bf4` (WP23). `git merge-tree` shows text
  conflicts in exactly three files: `BACKLOG.md`, `CHANGELOG.md`, `docs/index.md` (all
  append-style; keep both sides). `README.md` auto-merges.
- `docs/index.md` ADR row: after merge write `(D01 to D20)` and list both "latency benchmark"
  and "monitor bindings".
- After merge: regenerate `policies/schema.json` with `policy_json_schema()` if any other WP
  touched `gateway/policy.py`, and re-run the full suite (WP23 perf test needs `RUN_PERF=1`).
- Other shared files touched (no conflict today, watch in later merges): `config.py`
  (`# --- WP1b-B ---` block), `schema/model.yaml` + both DDL + `notebooks/bootstrap_and_smoke.py`,
  `core/models.py`, `gateway/policy.py`, `supervisor_agents/common/manifest.py`,
  `inventory/{model,fill,__init__}.py`, `console/{routes,views,i18n}.py`,
  `templates/metrics.html` (WP21 alerts panel is above the new section), `monitors/sweeps.py`
  (near judge code), `onboard/codefacts.py` (imports `judge.router.FAMILY_ALIASES`).
