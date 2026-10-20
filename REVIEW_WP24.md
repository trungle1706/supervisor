# REVIEW WP24: Inventory graph and shadow-AI scan

Reviewer: Opus (AI-governance lead / Databricks platform engineer / senior Python engineer).
Branch `worktree-agent-ae8b65441b4910e06`, base main bf3a23a. Reviewed: HANDOFF_WP24.md,
docs/inventory.md, ADR D16, full `git diff main...HEAD` (52 files).

## Verdict: APPROVE WITH FIXES

The design is sound: the ids are deterministic, the risk inheritance uses SCCs and is correct,
the workspace scan is rule-based (R1 holds), and Decision 33 is never inferred. Two governance
defects made the A.6 inventory wrong for the real Databricks path. One Databricks API use was
incomplete. The notebook CSV mode could not run. All four are fixed on the branch (4 fix commits plus this file,
see below). No item needs rework. The open items are owner decisions or BACKLOG items.

## Review commits (on the branch, not pushed)

| Commit | What |
|---|---|
| 03f36fe | `list_registered_models`: list UC and workspace-registry models together. Drop the `owner` field. |
| 9197de2 | Agent-table agents become inventory nodes. Nodes that only a removed or retired manifest backed become `gone`. |
| 5f9b1a4 | Allow-list shape guard. Order-free equal-source merge. Job CLI `[FAIL]` instead of a traceback. Shadow case page test. |
| 238bdb8 | Dashboard notebook: CSV mode uses temp views. |

## Findings

| # | Sev | File:line | Issue | Action |
|---|---|---|---|---|
| 1 | High | `inventory/fill.py:198-230` (new block) | An agent in the `agent` table with no repo manifest had no `system` node. This is the usual case for an agent onboarded on Databricks, or onboarded while `INVENTORY_ENABLED` was off. The scan then flagged that agent's own App as shadow AI and opened a case. The handoff says filler (a) includes agent rows, but the rows only enriched manifest agents. | **Fixed.** Each non-retired row with no manifest becomes a `system` node (evidence `manifest: agent_table:<id>`, risk tier, human-set D33 class, owner team; `owner_user` e-mail never copied). Tests: `test_agent_row_without_manifest_is_a_system_node`, `test_registry_agent_makes_its_app_managed`. |
| 2 | High | `inventory/service.py:94`, `inventory/store.py:128-175` | A removed manifest never made its nodes `gone`. Only the workspace kinds had stale handling. A retired agent stayed `active` in the inventory and kept its App "managed", so a later unregistered reuse of that App was not seen as shadow AI. This breaks ISO/IEC 42001 A.6 (inventory must show what is retired). | **Fixed.** New `apply(stale_any=True)` for the complete manifest fill. A node whose only evidence was a removed manifest becomes `gone`, and it comes back when the manifest returns. Test: `test_removed_manifest_agent_becomes_gone`. |
| 3 | Medium | `adapters/workspace/databricks_sdk.py:89` | The code read the workspace (legacy) registry only when the UC call failed. A workspace can hold UC models and legacy models at the same time, so the legacy models were missed. The code also returned `owner`/`user_id` (a user name or e-mail). | **Fixed.** Both registries are read and merged by name. One refused listing is skipped. When both are refused, the UC error is raised, so the section fails and no known model goes `gone`. The owner is not returned. SDK shapes are checked against the installed `databricks-sdk`: `registered_models.list()` -> `RegisteredModelInfo.full_name/name`, `model_registry.list_models()` -> `Model.name`. |
| 4 | Medium | `notebooks/inventory_dashboard.py:28-66` | CSV mode created permanent views that reference temp views (Spark refuses this with INVALID_TEMP_OBJ_REFERENCE). It also selected `last_seen`, which the CSV export does not have. | **Fixed.** CSV mode makes temp views and selects a NULL `last_seen`. Delta mode does not change. Checked with a stub `spark` in both modes (no live run). |
| 5 | Low | `inventory/shadow.py:50-58` | `apps: bi-portal` (a scalar) was read as five 1-letter patterns. A list document caused AttributeError and the job crashed. | **Fixed** + test. |
| 6 | Low | `inventory/graph.py:40` | The docstring said "first wins" but the code made the last claim win at equal source strength (order-dependent). | **Fixed:** at equal strength the higher level wins + test. |
| 7 | Low | `jobs/inventory.py:80` | A bad `--fixture` path caused a Python traceback, not ASCII `[FAIL]`. | **Fixed.** |
| 8 | Low | `graph.py:55` (`add_edge`) | The "smallest ref wins" rule makes a shared edge show evidence from another agent's manifest. For example, under `payments` the `[serves] model:qwen3:4b` edge points to `credit_prequal/manifest.yaml:9`. The edge is correct, but the evidence pointer can confuse a reviewer. | Recorded. Option: keep all refs in a list on the edge. |
| 9 | Low | `store.py:328` | When a human clears `agent.decision33_class`, the stale class stays on the node (the merge only copies a non-null value). It is not inferred, but it can be stale. | Recorded. Fix: copy the row value also when it is null, for manifest/agent-table nodes. |
| 10 | Low | `model.py:40,106` | `MAX_EVIDENCE=20`: a node that is full drops new evidence silently. A full node of manifest refs never gets `workspace_scan` evidence, so classify skips it. | Recorded (an edge case: needs >20 refs). |
| 11 | Low | `fill.py` tables section | When `INVENTORY_SCAN_SCHEMAS` is narrowed, the tables of the removed schemas are marked `gone`, but they still exist. | Recorded. Doc note or per-schema stale scope. |
| 12 | Info | `cases/service.py` (existing) | A shadow-AI case gets the WP19 incident clocks (`report_due_at` +1 day, prelim, formal). A shadow finding is not an incident. If these clocks stay, the incident register and the SBV report clocks get inflated. | Owner decision. Recommend a case type with no regulatory clock for `source_kind=inventory`. |
| 13 | Info | `cases/service.py:440` (existing) | The dedupe on (`inventory`, node id) is permanent. When a case is closed as "not AI" and the App later becomes an agent, no new case opens. The allow-list is the documented path, so this is acceptable. | Recorded. |
| 14 | Info | `shadow.py:30` | The pseudo agent id `inventory` would share a chain lane with a real agent named `inventory`. | Recorded. Suggest reserving the id in agent registration (`agent_id != "inventory"`). |
| 15 | Info | `console/readmodels.py:121` | The nav badge runs one SQL query on every console page when the flag is on. On Delta this is one Statement API call per page. | Acceptable. Cache it if latency matters (WP23). |

## Checklist results

| Area | Result |
|---|---|
| Node ids | sha256(kind NUL canonical); kinds cannot collide; tools and prompts are scoped per agent; App = `system:app:<name>`. An agent with the id `app:x` would collide with App `x`. This is not likely, but nothing prevents it (recorded with #14). OK |
| SCC inheritance | Diamond (A->B,C->D high): all high. Cycle A<->B ->C high: A and B high. The iterative Tarjan emits successors first, so `comp_level` is always ready. Order-independent. OK |
| Idempotent re-fill | Two job runs: same rows and row_version; chain has 8 entries for 4 cases after 2 runs. OK |
| `gone` | Workspace kinds: OK, and a failed listing never marks gone. Manifest removal: fixed (#2). |
| Case dedupe after triage | OK (existing case service, permanent link). |
| Allow-list | Glob, case-insensitive, FILL-ME never matches; self app wins first, then managed, then allow-list. Shape bug fixed (#5). |
| Decision 33 | Never inferred. It is copied only from the human-set row (now also for agent-table agents) and never passed to children (test). OK |
| Databricks fit | Apps (`apps.list` -> name), serving endpoints (`config.served_entities[].entity_name/foundation_model/external_model`), UC tables (`tables.list(catalog_name, schema_name)` -> `full_name`) and registered models match the real SDK. **Fake-only:** `lineage` (the SDK reader has no lineage method) and `list_schemas` (the live mode needs `INVENTORY_SCAN_SCHEMAS`). The live calls have not run against a workspace. |
| Delta writes | Through the existing `SqlStateStore`: named parameters for all values, identifiers from `schema/model.yaml` only. No injection path. A state insert is an insert-only MERGE (`WHEN NOT MATCHED THEN INSERT`), an update is row_version-guarded with 1 retry. One statement per changed row (+ daily last_seen) is acceptable for v1. |
| R1 / R2 / R3 | R1: rules only, a case is the only effect. R2: the chain payload has `summary_sha256` only, and the summary goes through the masker. Owner e-mails are not stored (fixed #3, #1). R3: no new network. OK |
| Defaults off / 4xx | Flag off: page and both routes give 400 (test). Bad id: 400. Unknown agent: 404. Shadow case page for the pseudo agent renders 200 (new test). OK |
| RBAC | `inventory.view` for all roles + `NON_USER_OK` (same as the other read views). An unknown user is refused (test). OK |
| Chain verify with `agent:inventory` lane | Ran: bootstrap, then the job x2 on `workspace_7.json`, then `python -m supervisor.evidence.export`, then `python -m supervisor.evidence.verify --strict`. Result: **RESULT: OK** (lanes `root` 2, `agent:inventory` 8, 2 signed roots). Before and after the fixes. |
| CSV formula guard | Guards `= + - @ TAB CR` on the first character. OK |
| ASCII CLI, no new deps, no secrets | OK (PyYAML and databricks-sdk are already locked. All values are FILL-ME). |

## Tests

| Run | Result |
|---|---|
| Branch as delivered, `python -m pytest -q -x` (`.venv/bin/python`; `python` is not on PATH, `uv run` is the Makefile form) | 2845 passed, 28 skipped |
| After review fixes, full suite `python -m pytest -q -x` | 2851 passed, 28 skipped, 0 failed (+6) |
| Inventory + console inventory tests | 53 -> 59 (+5 in `tests/inventory/test_review_fixes.py`, +1 console case-page test; the registered-models test is rewritten) |
| `ruff check .` / `ruff format --check .` | clean / clean |

## Residual risks

* The Databricks reader has not run live (no access). Run the live kit once: Apps, serving endpoints, both registries, UC tables.
* The shadow cases get incident clocks (#12). Get a decision before the scheduler job is on in production.
* The inventory accuracy depends on agents being in a manifest or the agent table. An agent that is only onboarded with the flag off and never registered is still invisible.
* The App-to-agent match is by exact name (with `-` = `_`) or by declaration. An App with a different name than its agent id must declare `databricks_app` in the manifest, else it is flagged.
* There is no console action to edit the risk or the allow-list (BACKLOG).

## Merge notes (conflict-prone files)

* `src/supervisor/config.py` (end of the class + the absolute-path validator list), `src/supervisor/core/rbac.py` (PERMISSIONS, NON_USER_OK, ROUTES), `src/supervisor/app.py` (router include), `src/supervisor/scheduler.py` (`case_service()` helper extracted from `intake`. WP21 alerts may also touch `build_jobs`).
* `schema/model.yaml` tail, both DDLs and `notebooks/bootstrap_and_smoke.py`: after all wave-1 schema merges, regenerate with `python -m schema.generate` and `python -m supervisor.databricks.notebook`.
* `docs/console.md` role matrix: regenerate from `rbac.matrix_markdown()`. `tests/test_rbac.py` viewer set.
* ADR number `D16`: check that D14/D15 are not taken twice by other wave-1 branches.
* `console/routes.py`, `console/i18n.py`, `templates/base.html` nav: additive. WP22 "Tools" adds a nav entry next to it.
* `src/supervisor/adapters/workspace/databricks_sdk.py`: WP24 owns it; the review changed `list_registered_models`.
