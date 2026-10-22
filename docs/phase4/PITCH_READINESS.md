# Pitch readiness after phase 4 (2026-10-22)

What the demo can show today, what it must not claim, and what is still open. Written by the
lead after the nine phase 4 work packages were merged into `main` (G0, UX4a, G1, G3, G2, G5,
UX4b, S1, G6). Every package passed an independent review before merge; High findings were
fixed first. The demo server runs `main` with the phase 4 flags on
(`supervisor-testbed/phase3/console/wave2-nav3.env`).

## 1. One-line result

The platform now has two products on one shared core, in one console: a Governance product on
the Saidot model (AI systems, graph, rules, classification, lifecycle, incidents, KPIs, MCP) and
the Supervisor product on the TrustGuard model (gate, detectors, judges, cases, per-system
guardian bindings with a mandatory floor). All of it runs offline on a laptop with synthetic
data. Nothing has run on a live Databricks workspace.

## 2. What the demo can show, in the order of the story

| Step | Page | What happens | Flag |
|---|---|---|---|
| 1 Register a product | Governance › Systems › Register | Intake of 12 fields incl. autonomy level; preliminary checks (readiness, risk class proposal, packs to run, guardian floor); nothing applied; draft created with intake tasks | GOVERNANCE_ENABLED, CONSOLE_SYSTEMS_ENABLED |
| 2 Rules fire | System › Rules | Assignment rules assign obligations, controls, risks, tasks and the guardian floor from the intake fields and linked components; every row shows the rule and the fields that fired | same |
| 3 Classify | System › Classification | Decision 33 question flow pre-filled from the fields; a person answers the rest and applies; a stale draft is refused; the risk floor follows | same |
| 4 Inherit risk | System › Overview, Risks | Risk level inherits from linked agents, models, tools and data; manual vs inherited vs classifier shown | INVENTORY_ENABLED |
| 5 Lifecycle | System › Tasks, Reviews | Tasks sized by level and class, stage approval with segregation of duties, reviews with lock and reopen, outbound events | GOVERNANCE_ENABLED |
| 6 Guard it | Guardians › Library with a system selected | Per-system switches; floor slugs locked; gate rules never bindable | GUARDIAN_BINDINGS_ENABLED |
| 7 Watch it | Supervisor › Overview, Activity | Calls checked, blocks, pauses, detector health, latency, chain state per system | existing |
| 8 React | Cases & alerts › Incidents | Events (block, detector failed, pack NO-GO, chain break, model change) map to actions: incident, notify, raise risk, re-evaluate, review, webhook row | GOVERNANCE_ACTIONS_ENABLED |
| 9 Prove | System › Reports | Transparency report, incidents, chain verify, audit pack link | TRANSPARENCY_ENABLED |
| 10 Agent-first | MCP `/mcp`, `GET /v1/kpis` | 21 tools (draft-only writes, confirm before write, decision tools refused by name), masked results, KPIs for coverage, quality, speed | MCP_SERVER_ENABLED |
| 11 Auto-record | Catalogues (with a workspace) | Scan of MLflow, endpoints, Genie, jobs, Vector Search, UC functions, MCP connections; auto-define from an MLflow artifact with an autonomy proposal; draft registration | INVENTORY_SCAN_V2, INVENTORY_AUTOREGISTER |

Step 11 can be shown only with fixtures until the live kit runs.

## 3. What the pitch must not claim

- **Live Databricks.** Nothing has run on a real workspace. The SDK response shapes for the new
  scan sources are unconfirmed (docs/inventory.md, live kit test 12). Delta latency is unknown.
- **Zero-code enforcement.** Blocking still needs the agent to call the gate (SDK, middleware,
  MCP proxy, LiteLLM guardrail). The scan discovers and registers; it never blocks.
- **AI classification.** The Decision 33 flow is deterministic; AI pre-fill is off and labelled.
  Judges run as `mock` until a model key is configured.
- **Injection detection quality.** The classifier is NO-GO and ships off; regex and DLP are on.
- **MCP from a desktop client.** Stock MCP clients cannot sign HMAC; a signing proxy or OIDC is
  later work.
- **Bank tools.** Jira and email are stubs behind flags; the outbound event table exists.
- **Masking limits.** The masker catches names with cues, emails, CCCD and phones; a bare name
  with no cue can pass (known masker limit).

## 4. Numbers

| Item | Value |
|---|---|
| Work packages merged | 9 (phase 4) |
| Tests on main before G6 | 5,939 passed, 33 skipped |
| High defects found by review and fixed before merge | 8 |
| New flags, all off by default | GOVERNANCE_ENABLED, CONSOLE_SYSTEMS_ENABLED, CONSOLE_NAV_V3, GOVERNANCE_ACTIONS_ENABLED, GUARDIAN_BINDINGS_ENABLED, MCP_SERVER_ENABLED, INVENTORY_SCAN_V2, INVENTORY_AUTOREGISTER, WEBHOOKS_ENABLED, CLASSIFIER_AI_PREFILL |
| Demo systems registered | 1 (SME credit memo assistant); payments and customer service not seeded on the demo server |

## 5. Open items, by owner

| Owner | Item |
|---|---|
| Bank | Run the live test kit (12 checks); set the Delta p99 budget; LLM key for judges; OIDC; team field in the users file |
| Second line | Agree starter thresholds in config/governance_actions.yaml and the risk bands; approve the pending control and risk files from G2; decide who may lower a risk level |
| Lead | G4 compliance retrieval (BM25); seed the three demo systems; release tag; push to GitHub when told |
| Later | Signing proxy or OAuth for MCP clients; real webhook sender; Jira and email adapters; smart guardian (auto-tune), deferred by the owner |
