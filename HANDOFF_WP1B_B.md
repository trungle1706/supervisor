# HANDOFF WP1b-B: onboarding D08 and monitor bindings D06

Branch `wp1b-b-onboard-monitors` (base `de8a2ca`, phase3-wave1 wave 1). 3 commits, trailer Fable 5.1,
no push, no merge. Worktree: `/home/trung/supervisor/.claude/worktrees/agent-a191dc91964c53dab`.
Note: `git checkout phase3-wave1` failed (branch checked out in another worktree), so I branched
from the name with `git checkout -b wp1b-b-onboard-monitors phase3-wave1`. The phase3-wave1 head has
moved since (WP23 work); this branch does not contain it.

## Result

| Check | Before | After |
|---|---|---|
| Full suite `uv run python -m pytest -q` | 3283 pass (wave 1 report) | 3326 passed, 28 skipped (+43) |
| `ruff check`, `ruff format --check` (src, tests) | clean | clean |
| Fixture `fastapi_deepagents_credit_toy`, old analyser | 11 tools (5 are routes; precision 54.55 %), framework `langchain`, family `unknown` | 6 tools, 5 entrypoints, `deepagents`, `anthropic` |
| Corpus (21 repos) tools P / R | 100 / 100 | 100 / 100 (Wilson 94.25 to 100.00, n=63) |
| Monitors on the 3-agent trace, old call sites | 0 of 12 cells written | 12 of 12 cells match the golden file |

## D08: onboarding (medium)

- `onboard/codefacts.py`
  - Routes (FastAPI `FastAPI` / `APIRouter`, router prefix included) go to `facts.entrypoints`. A route is also a tool only under a tool-server path root (`/tools/`, `/functions/`, `/actions/`, `/mcp`), so `fastapi_toolserver_remit` is unchanged.
  - `deepagents` is first in the framework table. Tool lists: `create_deep_agent`, `create_agent`, `create_react_agent`, deepagents sub-agent dicts (`{"name", "tools": [...]}`); `@tool`, `StructuredTool`, MCP schema were already handled. `session.list_tools()` and `"tools/list"` go to `dynamic_tools`.
  - `create_deep_agent(model=...)`, `create_react_agent("provider:model")` give LLM call sites.
  - `model_family()` rewritten: cut vendor prefixes, take the leading word, look it up in `judge.router.FAMILY_ALIASES` (imported), small extra table for `o3`, `o4`, `deepseek`, `mistral`, `mixtral`, `dbrx`, `qwen`. Same result as before on all old inputs; adds `databricks-claude-*`, `databricks-meta-llama-*`, `databricks-gpt-oss-*`, `databricks-gemma-*`.
  - `os.environ.get("X", d)`, `os.getenv`, `os.environ["X"]` resolve through `app.yaml` / YAML `env:` lists and `.env*` files (after scrubbing).
- `onboard/discover.py`, `onboard/models.py`: `Inventory.entrypoints` gets route items (`name` = `METHOD /path`, `detail` = `route:<fn>`, evidence file:line); new `dynamic_tool_sources`, `model_family_source` (`manifest` | `code` | `unknown`); family and model id come from code when the manifest has none.
- Fixture `data/corpus/repos/fastapi_deepagents_credit_toy/` (own code, 6 tools, 5 routes, deepagents, `ChatDatabricks` endpoint named only in `app.yaml`, the code default is a Llama endpoint on purpose). Labels in `data/corpus/labels.yaml` written by hand from the code before the analyser change. New label fields `entrypoints` and `model_family`; `model_family` added to 15 older repos, derived from their gold `llm_calls` labels.
- Eval (`onboard/eval/`): `entrypoints` set field, `model_family` accuracy, Wilson 95 % intervals on every precision, recall and accuracy, three new gates (entrypoints P and R >= 90 %, model family >= 90 %, ILLUSTRATIVE). Baseline file `data/corpus/reports/wp1b_b_baseline.json` (date, commit, floors). Tests: `tests/onboard/test_wp1b_b_codefacts.py` (incl. the regression against the baseline).
- WP24 filler: `inventory/fill.py` maps route entrypoints to `entrypoint` nodes (edge `uses` from the system); `NODE_KINDS` gets `entrypoint`. Test in `tests/inventory/test_fill_store.py`.
- Docs: `docs/onboard.md` (new section), `docs/onboard-eval.md` (corpus row, results with intervals, failure taxonomy, changes), `docs/inventory.md`.

## D06: monitors (medium)

- `core/monitor_bindings.py`: strict pydantic model `MonitorBindings` (`quality.reply_tools/text_arg`, `fairness.decision_tool/decision_arg/subject_arg/approve_values/protected_attribute_keys`, `split_payment.tool/customer_key/payee_key`, `drift.window_s/baseline_windows/min_baseline_windows/min_n`). Ethnicity, religion and the other forbidden attributes are rejected.
- Where it lives: manifest key `monitors:` (`supervisor_agents/common/manifest.py`) and `agents.<id>.monitors` in `policies/*.yaml` (`gateway/policy.py`; `policies/schema.json` regenerated). Policy wins over manifest, manifest over derived defaults.
- `monitors/bindings.py` `BindingResolver`: defaults from tool classes (single `credit` tool = fairness decision; single `money` tool, or `transfer`, = payment; non-money tool named like reply/response/answer/message/memo = output). Ambiguity is not guessed: `not_applicable` with the tool names in the reason. Demo agents keep their old behaviour through the defaults (tested).
- `monitors/status.py`: `set_status` writes `oversight_metric.monitor_status` (new nullable JSON column in `schema/model.yaml`, both DDL files, `core/models.py`, Databricks smoke notebook regenerated). Statuses `ok`, `not_applicable`, `no_data`, with `code`, `reason`, `n`. Unchanged status is not rewritten. Not on the evidence chain.
- Monitors changed (all take an optional `resolver`; without it they behave as before):
  - quality (`QualityScorer.reply_binding`, `QualitySweep(resolver=...)`): per-agent reply tools and text arg; status per known agent.
  - fairness (`EventDecisionSource.bind`, `FairnessMonitor(resolver=...)`, `build_source(allow_arg_attributes=True)`, `NullLookup`): per-agent decision tool and args; attributes from call args via `protected_attribute_keys`; `not_applicable` for unbound agents.
  - drift (`DriftMonitor(resolver=...)`): per-agent window and baseline size; status `ok` / `no_data collecting_baseline` / `not_applicable no_versioned_events`.
  - multi-agent (`MultiAgentMonitor(resolver=...)`): scans each distinct bound (tool, keys) variant with its own cursor; status per agent.
  - jobs `fairness`, `drift`, `multiagent` and `build_quality_sweep` pass `BindingResolver.from_settings(settings)`.
- Console: Metrics page section "Monitor status" (agent x monitor, pill + reason + n), EN and VI strings; `monitor_status` hidden from the numeric table.
- Harness: `python -m supervisor.monitors.binding_harness [--json] [--expected FILE] [--keep DIR]`; synthetic 3-agent trace (`memo_agent` bound, `helpdesk` derived, `lookup_agent` nothing), golden `data/eval/monitor_bindings/expected.json` (12 cells, provenance and rubric in the file). `tests/monitors/test_bindings.py` (golden match, the old silence with `legacy=True`, resolver precedence, ambiguity, bad key, forbidden attribute, policy schema, status idempotence); `tests/console/test_monitor_status.py`.
- Docs: `docs/monitors.md` (new), `docs/adr/D20-monitor-bindings.md`, `docs/metrics.md`, README, CHANGELOG (WP1b-B row, behaviour changes), BACKLOG (3 rows), `docs/index.md`.

## Flags and settings

No new feature flag: the existing `QUALITY_ENABLED`, `FAIRNESS_ENABLED`, `DRIFT_ENABLED`, `MULTIAGENT_ENABLED` are unchanged and still switch the jobs. New optional settings in the `# --- WP1b-B ---` block of `config.py`: `MONITOR_POLICY_DIR`, `MONITOR_MANIFEST_DIR` (extra folders, read after the built-in ones). With the flags off the off path is unchanged (existing monitor tests all pass).

## Commands

```cmd
uv run python -m supervisor.onboard.eval --corpus data\corpus\repos --labels data\corpus\labels.yaml --report out\corpus-eval
uv run python -m supervisor.monitors.binding_harness
uv run python -m pytest tests\onboard\test_wp1b_b_codefacts.py tests\monitors\test_bindings.py tests\console\test_monitor_status.py -q
```

## Files touched outside my own new files (for the integrator)

- Shared: `src/supervisor/config.py` (labelled block only), `schema/model.yaml` + both DDL files + `notebooks/bootstrap_and_smoke.py` (regenerated), `policies/schema.json` (regenerated), `src/supervisor/core/models.py` (`OversightMetric.monitor_status`), `src/supervisor/gateway/policy.py` (one field and one import), `src/supervisor_agents/common/manifest.py` (one field), `src/supervisor/inventory/{model,fill,__init__}.py`, `docs/inventory.md`, `README.md`, `CHANGELOG.md`, `BACKLOG.md`, `docs/index.md`.
- Console: `console/{routes,views,i18n}.py`, `templates/metrics.html` (small additive edits).
- Existing test changed: `tests/advisory/test_corpus.py` (corpus size 20 to 21; the name is now `test_corpus_has_twenty_one_repos`).
- Judge-side files: none touched. `onboard/codefacts.py` imports `FAMILY_ALIASES` from `judge/router.py` (read only). If the judge engineer renames that table or moves it, one import changes.
- `monitors/sweeps.py`: `build_quality_sweep` only gained the `resolver=` / `sample_bp=` arguments in the `QualitySweep(...)` call. The judge-model lines are untouched, but the file is close to the judge area: check the merge.
- Likely merge conflicts: `CHANGELOG.md`, `BACKLOG.md`, `README.md`, `config.py`, `schema/model.yaml` and DDL (append-only edits), `policies/schema.json` (regenerate with `policy_json_schema()` after the merge), ADR number (renamed to D20 in review).

## Self-review

R1: monitors still only advise; nothing calls the gate. R2: no new PII path; the protected attribute value is read from the masked call args, the subject id is hashed at once, ethnicity and religion are rejected at load. R3: no network. Secrets: none; synthetic emails use `example.invalid`. No `exec` / `eval` / `subprocess`. Console page: all template lookups use `.get`, tested with a partial entry (found one Jinja `UndefinedError` that way and fixed it). Defaults off: yes. Both modes: the new column is in both DDL files; the status code uses only `SqlExecutor` and the state store, so SQLite and `databricks_fake` run the same path (the full suite includes the Databricks fakes; no live run).

## Not done and open questions

1. No blind held-out repo for D08, and the new fixture is hand-written by the same engineer as the rules (BACKLOG). The entrypoint interval is wide (n = 8).
2. Routes are found for FastAPI only; Flask / Starlette / `add_api_route` / `include_router(prefix=)` not. MCP `tools/list` is flagged, not enumerated.
3. Onboarding Agent PR does not write `monitors:` yet; no console editor for bindings; no alert when a high-risk agent has a `not_applicable` monitor (BACKLOG). Decision for the owner: severity of such an alert.
4. Statuses are not on the chain. Owner: do auditors need "monitor not applicable" as evidence?
5. Served app still cannot load another gateway policy folder (D13, not my WP); `MONITOR_POLICY_DIR` only feeds the monitors.
6. Name-derived reply tool can pick a wrong tool (a tool called `message_*` that is not the output). Explicit binding overrides it.
7. Drift per-agent window must be set before the baseline exists (documented in D20).
8. ADR renamed to D20 in review (phase3-wave1 has D19-latency-benchmark).
9. Verify live: the new `monitor_status` column needs the bootstrap/ALTER path on an existing Delta table (additive column; covered by `tests/test_schema.py` offline only).
