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
| Tests on main after phase 4 and 5 | 6,595 passed, 46 skipped (run of 2026-10-23 02:02 UTC, commit 1892c00) |
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

## 6. Phase 5 addendum (2026-10-22, evening): guardian detectors

Four detector packages closed most of the TrustGuard catalogue gap. Each is a key in
`config/detectors.yaml`, shows on the Guardians library, can be bound per system (WP-S1), and
passed an independent review before merge.

| Detector | What it does | Shipped state |
|---|---|---|
| `dlp_vn` secrets and custom rules | 29 secret kinds as `secret.<kind>` findings with keyed digests, optional block on any tool class, keyword and regex custom rules with regex-safety checks and a per-leaf cap, head scan on oversize payloads | on for PII; secrets `enabled: false`, action report |
| `document_intake` | PDF, DOCX, text and CSV extraction in pure Python; URL fetch behind an allow list with an SSRF guard that held against every probe; extracted text scanned by injection regex, DLP and the guard model; own scan budget; scans and images are uninspectable and fail closed on risky tools | `DOCUMENT_INTAKE_ENABLED` off; no OCR; PDF needs the `documents` extra |
| `guard_model` | ML jailbreak and indirect-injection scoring over a port with classifier, chat and mock adapters; three presets; own thread pool and deadline; pause only on money and credit with a named approval that pins model id and version | off, NO-GO until a real model run; bank decision memo `docs/guard-model-decision.md` |
| `judge_moderation` | Toxicity and up to five bank-defined topics on input and output, one prompt per window, call and time budget | off, NO-GO until a judge model run; mock labelled |

What the pitch may say: the catalogue covers the same ground as the TrustGuard cards except OCR
and Microsoft Purview. What it must not say: that the ML detectors are validated. They are
built, harnessed and off; the bank must choose and serve a model first.

## 7. Phase 6 addendum (2026-10-23): deploy package and three candidate agents

| Item | State |
|---|---|
| Release v0.5.0 | tagged on main (local); bundles at `~/supervisor-release/v0.5.0/laptop/` and `.../databricks/`, SHA256SUMS in each |
| Laptop launch | `docs/deploy/LAUNCH_LAPTOP.md` (Windows cmd); `tools/smoke_launch.py` passes on Linux; not yet run on Windows |
| Databricks launch | `docs/deploy/LAUNCH_DATABRICKS.md`; app.yaml and databricks.yml carry every phase 4 and 5 switch; live test kit items 1 to 16 are manual and NOT run |
| Candidate A1, bank knowledge chatbot, L1 | MIT upstream, pinned; FastAPI middleware; retrieval-only tool; registered, classified (unclassified until a person answers), gate checks captured |
| Candidate A2, customer service agent, L3 | LangGraph interrupt before the fee waiver; registered, floor = DLP + injection regex + rules; waiver without approval blocked by CSA-01, CCCD masked |
| Candidate A3, payments operations agent, L4 | deepagents planner; registered, Decision 33 high_risk by D33-TRANSACTION, floor adds the session monitor; moved SHADOW to RUNNING by two persons through the API; 150M VND transfer blocked, split transfers blocked, session paused in its own proof |
| Supervisor fixes from the candidates (WP-P2) | agents API, two-person launch route, several policy folders and reload, define and classification cross-check, SDK session ids, masking in SHADOW, key store path |

Demo server: policy folder `supervisor-testbed/phase3/console/policy_demo` (42 rules), four
systems registered. What the pitch must still not claim: any Windows or Databricks run.
