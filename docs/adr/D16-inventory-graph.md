# D16 - Inventory graph and shadow-AI scan

Status: Accepted (WP24, 2026-10-20). Bank decisions listed under "Open".

## Context

Supervisor knew agents (the `agent` table, manifests) and could read the Databricks workspace (Apps, serving endpoints, UC tables), but nothing joined them. ISO/IEC 42001 A.6 needs an inventory of AI systems with their parts; a bank also needs to see AI that runs without registration (shadow AI). Saidot (items 1 and 6 in `saidot/COMPARISON.md`) shows the pattern: a graph of products, models, agents, datasets, where risk level passes up from components.

## Decision

1. **Typed graph in two state tables** (`inventory_node`, `inventory_edge`) in both DDLs and `schema/model.yaml`. Node kinds: system, model, model_endpoint, tool, mcp_server, dataset, prompt, supplier. Edge kinds: uses, serves, reads, writes, hosted_on, owned_by. State tables (not append-only) because a refresh updates status and evidence; the evidence chain records the cases it opens.
2. **Deterministic ids**: sha256 of kind and canonical name. A fill is idempotent without any lookup key from outside. Tool and prompt names carry the agent id so two agents with a `transfer` tool stay apart.
3. **One edge row per (src, kind, dst, source)** so each source keeps its own evidence; the reference is `file:line` or `workspace:<kind>/<name>`. Workspace URLs and ids are not stored.
4. **Risk inheritance** = max of own level and the level of every child along `uses` edges, over strongly connected components so a cycle ends and the result is order independent. Computed on read, never stored. Only `uses` carries risk: a dataset an agent reads is not "used" for risk, because the data risk is already carried by the tool that reads it.
5. **Decision 33 class is never inferred.** It is a column on the node only so a reader sees it next to the risk; the only writer is the manifest filler, copying the human-set `agent.decision33_class`. It is not an input to inheritance and nothing passes it to other nodes.
6. **Shadow-AI = rules, not a model.** An App or endpoint is managed when an agent with manifest or onboarding evidence is named like it, declares it, is hosted on it or uses it. It is allowlisted when it matches a committed-with-placeholders file or the app's own name. Otherwise it opens one low-severity case through the existing case service (dedupe on source kind `inventory` plus node id). Cases use one pseudo agent id `inventory`, so the chain gets one extra lane and not one per shadow item. Rule R1 holds: the scan flags to a person and never pauses or blocks.
7. **Refresh** is a scheduler job (`inventory`, `SCHED_INVENTORY_S`) in databricks_app mode; also `python -m supervisor.jobs.inventory`. A failed listing is reported and does not mark objects gone.
8. **Flag** `INVENTORY_ENABLED`, default off: tables stay empty, the page and routes answer 400.

## Alternatives rejected

| Alternative | Why not |
|---|---|
| Graph database (Neo4j) | Not allowed on the laptop or the App; the graph is small (thousands of nodes) and fits two Delta/SQLite tables |
| Store the effective risk | It goes stale when a child changes; computing on read is cheap and always right |
| Infer a Decision 33 class from tool risk | The class is a legal judgement; the product rule is human-set only (CLAUDE.md, ADR D12) |
| Bidirectional risk inheritance | A shared model would raise every agent that uses it; Saidot also passes risk up only |
| One case lane per shadow item | A lane per unregistered workspace name is unbounded and invites noise on the chain |
| Match apps to agents by fuzzy name | A wrong match hides shadow AI. Exact match with `-`/`_` equal, plus explicit declaration, is predictable |

## Consequences

* Two more state tables; one extra UPDATE-per-changed-row on Delta (no batching in v1).
* A manifest-only agent with no App in the workspace is still in the inventory; a workspace item that has not been listed yet is not "gone" until the next complete listing.
* Names of workspace objects are untrusted text: the page escapes them, CSV cells are guarded against formula injection, case summaries pass through the masker.

## Open (owner decisions)

1. The allow-list content (known non-agent Apps and endpoints) and `INVENTORY_SELF_APP`.
2. Which Unity Catalog schemas to scan (`INVENTORY_SCAN_SCHEMAS`).
3. Whether a shadow item should be `low` severity at the bank, or `medium` for serving endpoints that expose a model.
4. Whether the effective risk should also feed the Decision 33 task list (WP30) and the risk register (WP29).
