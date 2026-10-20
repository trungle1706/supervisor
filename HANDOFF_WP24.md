# HANDOFF WP24: Inventory graph and shadow-AI scan

Branch `worktree-agent-ae8b65441b4910e06` (from main bf3a23a). Not pushed, not merged.

## What was built

| Part | Where |
|---|---|
| Model, ids, risk order | `src/supervisor/inventory/model.py` (8 node kinds, 6 edge kinds, id = sha256(kind, canonical name)) |
| In-memory graph, risk inheritance (SCC, cycle safe), subgraph, ASCII tree | `inventory/graph.py` |
| Fillers (a) manifests + `policies/baseline.yaml` + `agent` rows, (b) onboarding `inventory.json`, (c) workspace (Apps, serving endpoints, registered models, UC tables, lineage) | `inventory/fill.py` |
| Store over `StateStore` (idempotent apply, stale handling, manual risk) | `inventory/store.py` |
| Shadow-AI rules + allow-list | `inventory/shadow.py`, `config/inventory_allowlist.yaml` (FILL-ME) |
| Service (fill, refresh, shadow cases, reads, JSON/CSV export) | `inventory/service.py` |
| Read API for the compliance advisor and launch report | `inventory/read.py` (`inventory_for_agent`) |
| JSON routes `GET /v1/inventory/{agent_id}`, `/v1/inventory/unmanaged` | `inventory/api.py` |
| Console page "Inventory" (flag-gated) | `console/inventory_views.py`, `templates/inventory.html`, route in `console/routes.py`, nav in `base.html`, i18n EN/VI |
| Scheduler job + CLI | `jobs/inventory.py`, `scheduler.py`, `python -m supervisor.inventory`, `python -m supervisor.jobs.inventory` |
| Onboarding link | `onboard/run.py` `_fill_inventory` (after Discover; only when `INVENTORY_ENABLED=1`; never stops onboarding) |
| Reader extension | `adapters/workspace/databricks_sdk.py` and `fixtures.py`: `list_registered_models` (UC, fallback to workspace registry) |
| Tables `inventory_node`, `inventory_edge` | `schema/model.yaml`, both DDLs, `notebooks/bootstrap_and_smoke.py` regenerated |
| Dashboard notebook (FILL-ME names) | `notebooks/inventory_dashboard.py` |
| Docs | `docs/inventory.md`, `docs/adr/D16-inventory-graph.md`, README (capability + flag rows), `docs/console.md` (tab, flag, role matrix), `docs/index.md`, `docs/threat-model.md` (gap row), `BACKLOG.md` (8 rows) |

## Flags and settings (block `# --- WP24 ---` in `config.py`)

`INVENTORY_ENABLED=0` (default off), `SCHED_INVENTORY_S=3600`, `INVENTORY_SCAN_SCHEMAS`, `INVENTORY_SELF_APP`, `INVENTORY_ALLOWLIST_FILE`, `INVENTORY_WORKSPACE_FIXTURE`. Off: tables stay empty, page and routes answer 400, no nav entry, no scheduler job.

## Commands

```
set INVENTORY_ENABLED=1
python -m supervisor.inventory manifests | onboarding PATH | show AGENT | unmanaged | export --out DIR
python -m supervisor.jobs.inventory --fixture tests\fixtures\inventory\workspace_7.json
python -m pytest -q tests\inventory tests\console\test_inventory_screen.py
```

## Tests

Before: 2791 (brief). After: full suite 2845 passed, 28 skipped, 0 failed (53 new: 46 in `tests/inventory/`, 7 in `tests/console/test_inventory_screen.py`). Ruff check and format clean.

* Fixture workspace `tests/fixtures/inventory/workspace_7.json`: 7 Apps/endpoints, 3 managed, 1 allow-listed, 3 unmanaged; provenance in the README next to it.
* Exact node/edge sets for a mini manifest and for an onboarding fragment; inheritance incl. cycle, self-loop, order independence, 3000-deep chain; Decision 33 never inferred.
* Idempotent re-fill (counts and row_version unchanged), shadow-case dedupe (3 cases after 4 refreshes, also after a case is triaged), gone/return, failed listing does not mark gone, registering clears the flag.
* Delta: recorded REST fake (insert-only MERGE per row, string rows cast by schema), DDL parity; SQLite for everything else. There is no full SQL emulator for Delta, so the Delta path is statement-level only (as for other WPs).
* Regression baseline `tests/fixtures/inventory/baseline_counts.json` (2026-10-20): 23 nodes / 22 edges from the 3 manifests; 34 / 34 with the workspace fixture.
* E2E: real `run_onboarding` (mock chat) on `data/corpus/repos/langgraph_loan_triage`, then fill from its `inventory.json`: 3 tools with `tools.py:46` etc., endpoint `graph.py:17`, tables `tools.py:37/52`, effective risk `high` from the credit tool.

## Shared files touched (minimal, additive)

`config.py` (WP24 block + two path settings added to the absolute-path validator list), `app.py` (router include), `console/routes.py` (one route + import), `console/readmodels.py` (shell badge), `console/templates/base.html` (nav entry), `console/i18n.py` (keys), `core/rbac.py` (permission `inventory.view` for all roles, 3 route entries, added to `NON_USER_OK`), `ops/openapi.py` (human-path prefix), `scheduler.py` (job appended only when it can run; small `case_service()` helper extracted from `intake`), `onboard/run.py` (hook), `schema/model.yaml` + DDLs, `docs/console.md` role matrix (regenerated from code).

Two existing tests changed (additive, forced by the new permission): `tests/test_rbac.py::test_new_roles` now lists `inventory.view` in the viewer set. The scheduler job is omitted from `build_jobs` when it cannot run, so `tests/monitors/test_scheduler.py::test_build_jobs_all_flags_run` is unchanged.

## Not done (also in BACKLOG)

Advisor and launch report do not call `inventory_for_agent` yet; no console action to edit risk or the allow-list; Delta writes are per row (no batching); the reader does not see Genie, Vector Search, jobs/notebooks or an App's bound resources; live lineage not read; shadow severity fixed `low`. Not run against a live workspace (no access): `list_registered_models`, Apps and endpoints listing are covered by fakes; run the live kit once.

## Open questions for the owner

1. Allow-list content and `INVENTORY_SELF_APP` for the real workspace.
2. Which UC schemas to scan.
3. Shadow severity (low vs medium for model-serving endpoints).
4. Should effective risk feed the Decision 33 task list (WP30) and the risk register (WP29)?
5. Pseudo agent id `inventory` for shadow cases adds one chain lane `agent:inventory`; confirm this is acceptable.

## Notes for the integrator

* Neighbouring finding (not fixed): `tests/integrations/test_integrations.py::test_chain_feed_writes_schema_events_once` failed once on the base commit (first full run) because a random 10-digit run in a hash matched its PII regex; it passed on re-run. It is flaky, unrelated to WP24.
* Merge hot spots: `config.py` end of class, `rbac.py` PERMISSIONS/ROUTES, `schema/model.yaml` tail and both DDLs, `notebooks/bootstrap_and_smoke.py` (regenerate with `python -m supervisor.databricks.notebook` after merging all schema changes), `docs/console.md` role matrix (regenerate from `rbac.matrix_markdown()`), `scheduler.py`, `tests/test_rbac.py` viewer set.
* No new dependency (PyYAML already used).

## Review follow-up (items 12, 14, 9)

| Item | Change | Test |
|---|---|---|
| 12 shadow cases have no Decree 142 clocks | `cases/service.py`: `NO_CLOCK_SOURCES = ("inventory",)`; `open_case` skips the clock columns and the clock fields of the chain record for those sources; `unclocked(case_id)`; `incident_status` returns `clocked: false`; `record_report_sent` refuses; case view hides clocks and the report-sent button. Documented in `docs/judge-mrm.md` section 6 and `docs/inventory.md` | `tests/inventory/test_shadow.py::test_shadow_cases_have_no_incident_clock`, console case page test |
| 14 reserved agent ids | `core/errors.py`: `check_agent_id`, `ReservedAgentIdError` (a `SupervisorError`, so HTTP 400). Refused in Discover, `register_agents` and `InventoryService.fill_onboarding`: `inventory` and `app:*` | `test_reserved_agent_ids_are_refused` |
| 9 cleared Decision 33 class | `Node.d33_copy` (not stored): fillers that copy the `agent` row set it, and the store copies the value including empty. Onboarding never touches it | `test_cleared_decision33_class_is_cleared_in_the_inventory`, `test_onboarding_never_sets_or_clears_decision33_class` |

Extra files touched: `cases/service.py`, `console/readmodels.py`, `console/templates/_case_decide.html`, `core/errors.py`, `onboard/discover.py`, `wiring.py`, `docs/judge-mrm.md`.

