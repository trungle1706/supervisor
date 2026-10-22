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

Nodes (table `inventory_node`): `genie_space`, `job`, `vector_index`, `uc_function` (WP-G3, see "Scan sources v2"), `system` (an agent, or a Databricks App seen in the workspace), `model`, `model_endpoint`, `tool`, `mcp_server`, `dataset` (table or file), `prompt`, `supplier` (model vendor, the platform host, or an owner team; `attrs.party` says which), `entrypoint` (an HTTP route of the agent app, from onboarding; a route is never a tool, WP1b-B).

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
| Evidence | `source` is `manifest`, `onboarding`, `workspace_scan`, `manual` or `gate` (WP41: see below).  `evidence_ref` is `path:line` for repo text and `workspace:<kind>/<name>` for a workspace object. Workspace URLs and ids are not stored. |
| Shared edges | When two agents share an edge (the same model), the smallest reference wins inside one fill, so the result does not depend on fill order. |
| Status | `active`, `unmanaged`, `allowlisted`, `gone` (the workspace no longer lists it, or the manifest or agent row that was its only evidence was removed or retired). |
| Writes | State tables with `row_version`. Only changed rows are written, plus a `last_seen` refresh once a day. |

## Gate-only agents (WP41, D19)

An agent that only calls the gate (a collector, no onboarding run, no manifest in `agents/`) used
to stay out of the inventory, so there was no node for the Agent page, the coverage check or the
control evidence to point at. With `INVENTORY_ENABLED=1`, the first gate decision of an agent that
the **policy lists** puts a `system` node in the graph (`attrs.role = agent`, `attrs.registered_by
= gate`, evidence `{source: gate, ref: first_gate_decision}`), in the background, once per agent and
process. An id the policy does not list is never registered (anonymous input must not fill the
inventory). A later manifest or onboarding fill adds its own evidence to the same node; the
manifest fill's "gone" rule leaves a node that has `gate` evidence alone. It writes no agent row:
the registry row still comes from onboarding, a state change or `register_agents`.

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
| (c) workspace | `fill_from_workspace` | Apps, Model Serving endpoints, MLflow registered models (Unity Catalog and the workspace registry; one refused listing is skipped), UC tables of `INVENTORY_SCAN_SCHEMAS`, lineage (fixture reader) | `python -m supervisor.jobs.inventory`; the scheduler job `inventory` |

A bare table name from code (`loan_applications`) is linked to the one Unity Catalog table with the same last segment when exactly one exists; otherwise it stays a separate node.

An `agent` table row with no manifest file (an agent registered or onboarded on Databricks) also becomes a `system` node with evidence `manifest: agent_table:<id>` (risk tier, human-set Decision 33 class, owner team; never `owner_user`). Rows with status `retired` are left out. Each manifest run is complete, so a node that only a removed manifest or row backed becomes `gone`.

A manifest may also declare `databricks_app`, `serving_endpoint`, `mcp_servers` and `datasets: {reads: [], writes: []}`; they become edges with `manifest` evidence.

A listing that fails is reported (`errors`: kind and exception class only) and its objects are not marked `gone`. Reading the workspace is read only: `apps.list`, `serving_endpoints.list`, `registered_models.list`, `model_registry.list_models`, `tables.list`.

### Scheduler job

`inventory` runs every `SCHED_INVENTORY_S` (default 3600 s, minimum 60) when `INVENTORY_ENABLED=1` and the mode is `databricks_app`, or when `INVENTORY_WORKSPACE_FIXTURE` names a JSON file (laptop demo). One refresh = manifests, workspace, shadow-AI check. A new unmanaged item therefore appears within one interval.

## Scan sources v2 (WP-G3)

The workspace reader (section "Fillers", source c) reads more objects. Same flag (`INVENTORY_ENABLED=1`), same rules: read-only SDK calls through the reader adapter, evidence `workspace:<kind>/<name>`, names only (no workspace URL, object id, creator or connection option is stored), and the scan never pauses or blocks anything. A listing that fails is reported by kind and marks nothing as gone. A reader without the method (an older custom reader) skips that source without an error.

| Source | SDK call (read only) | Node and edges | Evidence ref |
|---|---|---|---|
| MLflow registered model versions | `registered_models.list`, `model_versions.list(full_name)` (Unity Catalog); `model_registry.search_model_versions` (workspace registry) | attrs on the `model` node: `versions_n`, `latest_version`, `aliases` or `stages` | `workspace:model-version/<model>/<version>` |
| Serving endpoint config | `serving_endpoints.list` (config, `served_entities`, task, tags) | `model_endpoint` attrs `agent_endpoint`, `external_providers`; edge `serves` to each served model (foundation, external with a `vendor` supplier through `owned_by`, custom = registered model) | `workspace:serving-endpoint/<name>` |
| Genie spaces | `genie.list_spaces` | `genie_space` node (status `unmanaged` until classified), `reads` edges to the tables of the space | `workspace:genie-space/<title>` |
| Jobs and notebook tasks that name an LLM endpoint | `jobs.list(expand_tasks=True)` | `job` node and a `uses` edge to each serving endpoint whose name appears in a task parameter or job parameter. A job that names no endpoint is not recorded. Only the endpoint name is kept; the parameter text is not stored | `workspace:job/<name>`, edge `workspace:job/<name>/task/<key>` |
| Vector Search indexes | `vector_search_endpoints.list_endpoints`, `vector_search_indexes.list_indexes`, `get_index` | `vector_index` node, `reads` edge to the source table | `workspace:vector-index/<name>` |
| Unity Catalog functions (tools) | `functions.list(catalog, schema)` for each schema in `INVENTORY_SCAN_SCHEMAS` | `uc_function` node | `workspace:uc-function/<full name>` |
| Unity Catalog connections of kind MCP | `connections.list` (the `is_mcp_connection` option decides; options are never returned) | `mcp_server` node (a manifest `mcp_servers` entry of the same name merges into it) | `workspace:uc-connection/<name>` |

New node kinds: `genie_space`, `job`, `vector_index`, `uc_function`. Edge kinds do not change. These nodes carry `attrs.workspace_kind` (`genie_space`, `job`, `vector_index`, `uc_function`, `uc_connection`), so a re-scan marks one gone when only the scan backed it.

Shadow check: a Genie space is **active** when an agent `uses` or `reads` it, **allowlisted** when it matches the new `genie_spaces` list of `config/inventory_allowlist.yaml`, else **unmanaged** (low-severity case, as for an App). A serving endpoint with `agent_endpoint` follows the endpoint rule. Offline test data: `tests/fixtures/inventory/workspace_v2.json`; keys `model_versions`, `genie_spaces`, `jobs`, `vector_indexes`, `functions`, `connections` (see `src/supervisor/adapters/workspace/fixtures.py`).

Not confirmed without a live workspace (checked by test 12 of the live kit, `docs/live-test-kit.md`): the call shapes of `genie.list_spaces` (paged response, attached tables), `jobs.list(expand_tasks=True)` task parameter fields, the vector search calls, the `is_mcp_connection` connection option, and how an agent endpoint is marked (task `agent/...` or a tag).

### Draft registration from the scan (WP-G3)

Off by default. With `INVENTORY_AUTOREGISTER=1` **and** `GOVERNANCE_ENABLED=1`, each refresh turns an **unmanaged** Databricks App, agent serving endpoint (`attrs.agent_endpoint`) or Genie space into a draft AI system (`docs/governance.md`), after the shadow-AI check:

```
unmanaged node --> owner lookup --> ai_system (status draft, risk_level unspecified, tag source=workspace_scan)
                                      |-- system_component (ref_kind node, source workspace_scan, evidence workspace:<kind>/<name>)
                                      `-- task "Confirm context" (stage initiation, owner role owner, due in 14 days)
```

| Rule | Detail |
|---|---|
| Owner | `config/governance.yaml` (or `GOVERNANCE_CONFIG_FILE`): `default_owner_by_group[<owner group>]`, else `default_owner_by_catalog[<catalog of the tables or models the node reads or serves>]`, else `default_owner`. Each value is `owner_user` and `owner_team`. Keys match without case. The committed file holds FILL-ME placeholders: while the chosen owner is a placeholder no draft is made (`skipped_no_owner`). The live SDK reader gives no owner group; the group key works with a fixture or a later reader. |
| Intake fields | Placeholders from `draft_defaults` in the same file (assistant, deployer, internal, identifiable, no human control: the safe side). The task asks the owner to confirm them. |
| Dedupe | On the inventory node id. A node that has any `system_component` row, active or removed, is never registered again, so an archived or unlinked draft does not come back. A name used by a person gets the suffix `(app)`, `(agent endpoint)` or `(genie space)` once; if that is taken too the node is skipped (`skipped_name`). |
| Never blocks | A failure on one node is logged and counted (`errors`); the scan result and the shadow-AI cases do not change. Nothing is paused or blocked. At most 100 drafts per refresh. |
| Chain | The service writes `system_change` (create, link) and `task_change` records as for a person (ids, enums, hashes only; no workspace name). |
| Result | `python -m supervisor.jobs.inventory` prints `[OK] draft registration: N created, ...` or `[SKIP] ...` (governance off). The refresh result has an `autoregister` entry only when the flag is on. |

The Genie space and agent endpoint stay `unmanaged` in the inventory until an agent covers them or they match the allow-list; the shadow-AI case and the draft are two separate signals.

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
* **No incident clock.** A shadow-AI case is an internal flag, not a Decree 142 incident: it opens with the ordinary case timestamps and without report due times, urgency class or "mark report sent" (see `docs/judge-mrm.md` section 6, `NO_CLOCK_SOURCES`).
* **Reserved ids.** Agent ids `inventory` and any id starting with `app:` are reserved. Onboarding Discover, `register_agents` and `fill_onboarding` refuse them with HTTP 400 and a message.
* **Decision 33 follows the human.** Each refresh copies the current `agent.decision33_class`, including an empty value: when a person clears it, the node clears it on the next refresh. Onboarding never sets or clears it.
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
| `INVENTORY_AUTOREGISTER` | `0` | WP-G3: draft AI system for each unmanaged App, agent endpoint or Genie space. Needs `GOVERNANCE_ENABLED=1` |
| `GOVERNANCE_CONFIG_FILE` | `config\governance.yaml` | Default owners, intake placeholders and the initiation task of the draft |

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

## MCP servers seen by the HTTP MCP gateway (WP26)

With `INVENTORY_ENABLED=1` and `MCP_HTTP_ENABLED=1`, the first time the HTTP MCP proxy lists a
remote server, the app registers it as an `mcp_server` node named after the lock id
(`--server-name`, default from the URL) with evidence source `manual` and reference
`mcp_tool_manifest:<server>`, and a `uses` edge from the agent. A manifest `mcp_servers:` entry
with the same name merges into the same node. The tool lock itself is in the table
`mcp_tool_manifest`; see `docs/mcp-gateway.md`.
