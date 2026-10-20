# Inventory graph and shadow-AI scan (WP24)

Status: built, off by default (`INVENTORY_ENABLED=1` turns it on). Design choices: `docs/adr/D16-inventory-graph.md`.

## What it answers

| Question (reviewer) | Answer |
|---|---|
| What does agent X run on? (ISO/IEC 42001 A.6 inventory) | A subgraph: model endpoint, model, tools, MCP servers, datasets, prompts, hosting App, owner team. Each link has a source and a pointer (`file:line` or a workspace reference). |
| What is the agent's risk level, and why? | Own level plus the level it inherits from what it uses. Both are shown. |
| What runs in the workspace that Supervisor does not know? | The `unmanaged` list: Databricks Apps and Model Serving endpoints with no manifest or agent row. One low-severity case each. |
| What is the Decision 33 class? | Human-set only. Copied from the `agent` table row. Never inferred and never passed up or down the graph. |

## Model

Nodes (table `inventory_node`): `system` (an agent, or a Databricks App seen in the workspace), `model`, `model_endpoint`, `tool`, `mcp_server`, `dataset` (table or file), `prompt`, `supplier` (model vendor, the platform host, or an owner team; `attrs.party` says which).

Edges (table `inventory_edge`): `uses`, `serves`, `reads`, `writes`, `hosted_on`, `owned_by`.

```
system:payments --uses--> tool:payments/transfer
                --uses--> model_endpoint:qwen3:4b --serves--> model:qwen3:4b --owned_by--> supplier:qwen
                --owned_by--> supplier:Payments Ops          (owner team)
                --hosted_on--> system:app:payments           (Databricks App, from the workspace scan)
                --reads--> dataset:main.lending.bureau_scores
```

| Rule | Detail |
|---|---|
| Node id | `inv_` + first 16 hex of sha256(kind, NUL, canonical name). Canonical = trimmed, lower-case, single spaces. A re-fill never duplicates. |
| Tool, prompt names | Scoped to the agent: `payments/transfer`. Models, endpoints, datasets and suppliers are shared across agents. |
| Edge id | Hash of (src, kind, dst, source): one row per claim, so each source keeps its own evidence. |
| Evidence | `source` is `manifest`, `onboarding`, `workspace_scan` or `manual`. `evidence_ref` is `path:line` for repo text and `workspace:<kind>/<name>` for a workspace object. Workspace URLs and ids are not stored. |
| Shared edges | When two agents share an edge (the same model), the smallest reference wins inside one fill, so the result does not depend on fill order. |
| Status | `active`, `unmanaged`, `allowlisted`, `gone` (the workspace no longer lists it). |
| Writes | State tables with `row_version`. Only changed rows are written, plus a `last_seen` refresh once a day. |

## Risk inheritance

Levels: `low < medium < high < critical`; no level ranks below `low`.

```
effective(node) = max( own(node), effective(child) for each child reached by an active `uses` edge )
```

* Only `uses` edges carry risk. `reads`, `writes`, `hosted_on`, `serves`, `owned_by` do not.
* A cycle (A uses B uses C uses A) is one group: every node of the group gets the max over the group and everything it can reach. The result does not depend on insertion order. The code is iterative (Tarjan), so a deep graph cannot hit the recursion limit.
* Own levels: agent = `risk_tier` of the agent row or manifest; tool = from its risk class (`read_only` low, `credit` high, `pii_export` high, `money` critical); `policies/baseline.yaml` is the authority for a tool's class when it lists the tool. A person can set an own level (`InventoryStore.set_manual_risk`); a manual level survives every re-fill.
* The effective level is computed when read and never stored.
* The Decision 33 class is not part of the computation. Only the manifest filler sets it, and only as a copy of the human-set `agent.decision33_class`. A test checks that nothing is passed to child nodes.

## Fillers

| Source | Function | Input | When |
|---|---|---|---|
| (a) manifests | `fill_from_manifests` | `src/supervisor_agents/*/manifest.yaml`, `policies/baseline.yaml`, `agent` rows | `python -m supervisor.inventory manifests`; every scheduler run |
| (b) onboarding | `fill_from_onboarding` | `inventory.json` from `python -m supervisor.onboard` | automatic at the end of Discover when `INVENTORY_ENABLED=1`; or `python -m supervisor.inventory onboarding PATH` |
| (c) workspace | `fill_from_workspace` | Apps, Model Serving endpoints, MLflow registered models (Unity Catalog, else the workspace registry), UC tables of `INVENTORY_SCAN_SCHEMAS`, lineage (fixture reader) | `python -m supervisor.jobs.inventory`; the scheduler job `inventory` |

A bare table name from code (`loan_applications`) is linked to the one Unity Catalog table with the same last segment when exactly one exists; otherwise it stays a separate node.

A manifest may also declare `databricks_app`, `serving_endpoint`, `mcp_servers` and `datasets: {reads: [], writes: []}`; they become edges with `manifest` evidence.

A listing that fails is reported (`errors`: kind and exception class only) and its objects are not marked `gone`. Reading the workspace is read only: `apps.list`, `serving_endpoints.list`, `registered_models.list`, `tables.list`.

### Scheduler job

`inventory` runs every `SCHED_INVENTORY_S` (default 3600 s, minimum 60) when `INVENTORY_ENABLED=1` and the mode is `databricks_app`, or when `INVENTORY_WORKSPACE_FIXTURE` names a JSON file (laptop demo). One refresh = manifests, workspace, shadow-AI check. A new unmanaged item therefore appears within one interval.

## Shadow-AI flow

```
workspace listing --> nodes (status unmanaged) --> classify --> active | allowlisted | unmanaged
                                                                         |
                                                    unmanaged: CaseService.open_case(
                                                       agent_id "inventory", severity low,
                                                       source_kind "inventory", source_ref node id)
```

An App or endpoint is **active** (managed) when: an agent with manifest or onboarding evidence is named like the App (`-` and `_` are equal: `credit-prequal` = `credit_prequal`); or an agent declares it or is `hosted_on` it; or, for an endpoint, an agent `uses` it. It is **allowlisted** when it matches `config/inventory_allowlist.yaml` or `INVENTORY_SELF_APP`. Everything else is **unmanaged**.

* One case per node, once. The case service dedupes on (`inventory`, node id), so repeated scans and closed cases do not open a second one. Case lane: `agent:inventory` on the evidence chain (one lane for all shadow-AI cases).
* The check is deterministic. No model decides (rule R1). A case is a flag for a person; the scan never pauses or blocks anything.
* Registering the agent (onboarding or a manifest) clears the flag on the next refresh. An item that disappears from the workspace becomes `gone` and leaves the count.

### Allow-list

`config/inventory_allowlist.yaml` (committed with FILL-ME placeholders; fill it in your local copy, never commit real names):

```yaml
apps: [FILL-ME-known-non-agent-app-name]
serving_endpoints: [FILL-ME-known-non-agent-endpoint-pattern-*]
```

Names match exactly or as a glob, case-insensitive. An entry that contains `FILL-ME` never matches. Point `INVENTORY_ALLOWLIST_FILE` to another file if needed.

## Console and API

| Where | What | Permission |
|---|---|---|
| `/console/inventory` | Count of unmanaged items (also on the nav entry), the unmanaged table with case links, an agent picker, the agent subgraph as an indented ASCII tree and a node table with own and effective risk and evidence | `inventory.view` (all roles, including viewer) |
| `GET /v1/inventory/{agent_id}` | JSON: `nodes`, `edges` (with `evidence_ref`), `tree`; 404 for an unknown agent, 400 for a bad id | `inventory.view` |
| `GET /v1/inventory/unmanaged` | JSON: `count`, `items` (node, status, evidence, `case_id`) | `inventory.view` |

Off (default): the page and both routes answer HTTP 400 with a message, and the nav entry is hidden. Both are read only.

Sample tree (`python -m supervisor.inventory show payments`):

```
system:Payments assistant agent risk=critical
|-- [owned_by] supplier:Payments Ops risk=-  <manifest: src/supervisor_agents/payments/manifest.yaml:5>
|-- [uses] model_endpoint:qwen3:4b risk=-  <manifest: src/supervisor_agents/payments/manifest.yaml:9>
|   `-- [serves] model:qwen3:4b risk=-  <manifest: ...>
|-- [uses] tool:ext_transfer_api risk=critical  <manifest: src/supervisor_agents/payments/manifest.yaml:38>
`-- [uses] tool:transfer risk=critical  <manifest: src/supervisor_agents/payments/manifest.yaml:34>
```

## Export

`python -m supervisor.inventory export --out DIR` writes `inventory.json` (nodes with effective risk, edges), `inventory_nodes.csv` and `inventory_edges.csv`. Cells that start with `=`, `+`, `-` or `@` are prefixed with `'`. The notebook `notebooks/inventory_dashboard.py` (FILL-ME catalog, schema and volume names) creates three views over the Delta tables (or over the CSV pair) for a Databricks dashboard: unmanaged items, agent links with evidence, counts by kind and status. Effective risk is computed by the app, not in SQL.

## For other modules

```python
from supervisor.inventory.read import inventory_for_agent
info = inventory_for_agent(adapters, "payments")   # None when INVENTORY_ENABLED is off
```

Returns `found`, `own_risk`, `effective_risk`, `decision33_class` and `links` (for example `uses:tool`, `uses:model_endpoint`, `reads:dataset`) with source and evidence. The compliance advisor and the launch report can call it; they are not changed in WP24 (see BACKLOG).

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `INVENTORY_ENABLED` | `0` | Fillers, the job, the page and the routes. Off: tables stay empty, routes answer 400 |
| `SCHED_INVENTORY_S` | `3600` | Workspace refresh interval (seconds, minimum 60) |
| `INVENTORY_SCAN_SCHEMAS` | (empty) | `catalog.schema,catalog.schema` to list Unity Catalog tables from |
| `INVENTORY_SELF_APP` | (empty) | Name of this Databricks App; never reported as shadow AI |
| `INVENTORY_ALLOWLIST_FILE` | `config\inventory_allowlist.yaml` | Allow-list file |
| `INVENTORY_WORKSPACE_FIXTURE` | (empty) | JSON file read instead of a workspace (offline demo, tests) |

Windows cmd: `set INVENTORY_ENABLED=1`.

## Commands

```
set INVENTORY_ENABLED=1
python -m supervisor.inventory manifests
python -m supervisor.jobs.inventory --fixture tests\fixtures\inventory\workspace_7.json
python -m supervisor.inventory unmanaged
python -m supervisor.inventory show payments
python -m supervisor.inventory export --out out\inventory
```

## Harness (expert view: AI governance lead, Databricks platform admin)

| Check the expert makes | Test |
|---|---|
| Every production agent resolves to model endpoint, tools and data with evidence | `tests/inventory/test_e2e_onboarding.py` (real onboarding output of the loan-triage repo), `test_fill_store.py` |
| Anything running that is not registered shows within one refresh | `test_shadow.py` (7 items: 3 managed, 1 allowlisted, 3 unmanaged) |
| One case per unmanaged item, even after re-scan or close | `test_cases_are_low_severity_and_deduped` |
| Risk passes up, cycles end, nothing infers Decision 33 | `test_graph.py` |
| Re-fill adds no row | `test_refill_is_idempotent_no_duplicates`, `test_workspace_refill_is_idempotent` |
| Same on Delta | `test_databricks_mode.py` (recorded REST fake: insert-only MERGE, string rows cast by schema) |
| No regression | `tests/fixtures/inventory/baseline_counts.json` (dated 2026-10-20): 23 nodes and 22 edges from the three manifests; 34 and 34 after the 7-item workspace |

The shadow check is a rule set, not a model, so there is no precision/recall estimate to report: each rule has a test, and the fixture labels are synthetic (`tests/fixtures/inventory/README.md`). Limits are in BACKLOG.
