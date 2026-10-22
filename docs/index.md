# Documentation index

Audience key: **Op** = operator (runs it), **Dev** = developer integrating a product,
**2L** = second line / risk / compliance, **Aud** = auditor, **Build** = engineer on this repo.

Regulation and compliance documents are advisory. Not legal advice. Bank counsel must confirm.

| Document | Purpose | Audience |
|---|---|---|
| `README.md` (root) | Product overview, capabilities, 10-minute tour, flags | All |
| `CHANGELOG.md` (root) | Release notes: new flags, behaviour changes, deploy order (v0.3.0-pre) | All |
| `SECURITY.md` (root) | How to report a vulnerability; known gaps | Op, 2L, Aud |
| `CLAUDE.md` (root) | Rules for agents that write code in this repo | Build |
| `BACKLOG.md` (root) | Open work that is out of phase | Build |
| `docs/SETUP_WORK_COMPUTER.md` | Install and configure on a Windows work laptop; phase 2 flags | Op |
| `docs/RUNBOOK.md` | Operate, deploy to Databricks, symptom to fix table | Op |
| `docs/BANK_DEPLOY_GUIDE.md` | Hard constraints learned at the bank | Op, Build |
| `docs/databricks-prereqs.md` | What the workspace needs before deploy | Op |
| `docs/live-test-kit.md` | Live tests the owner runs on Databricks | Op |
| `docs/DEMO.md` | Stage demo script, fallbacks, phase 2 demo, fail-mode drill | Op |
| `docs/console.md` | Reviewer console: pages, roles, flags | Op, 2L |
| `docs/api.md` | API versioning policy and paths | Dev |
| `docs/INTEGRATION_GUIDE.md` | Three ways to fit a product into Supervisor | Dev |
| `docs/bank-integration.md` | Bank-side integration contracts (stubs) | Dev, Op |
| `docs/mcp-gateway.md` | HTTP MCP gateway: streamable-HTTP proxy, tool locking, two-person tool review, poisoning scan, harness, latency | Dev, Op, 2L |
| `docs/siem.md` | SIEM export: sinks, jsonl / CEF / OCSF field mapping, Splunk, Sentinel, Databricks examples | Op, Dev |
| `docs/alerts.md` | Alert rules, dedupe, routes, acknowledge, harness | Op, 2L |
| `docs/recorder.md` | Trace recorder, OTLP, masking | Dev |
| `docs/masking.md` | PII masker `vn_regex-3`, amounts, inline redaction, eval harness, `pii_canary` | Dev, 2L |
| `docs/masker-model-card.md` | Model card of the masker (identity, use, metrics, failure modes, change log) | 2L, Aud |
| `docs/masker-validation-report.md` | Masker validation: per-entity recall and precision, taxonomy, GO / NO-GO | 2L, Aud |
| `docs/onboard.md` | Onboarding Agent and capability catalogue | Dev, Op |
| `docs/onboard-eval.md` | Precision and recall of the code analysers on the corpus | Dev, 2L |
| `docs/regulations.md` | Regulation knowledge base: coverage, format, internal rules | 2L, Dev |
| `docs/compliance-advisor.md` | Obligations matrix, Decision 33, threshold check | 2L, Dev |
| `docs/risk-register.md` | Risk register: scoring, inheritance up the inventory graph, evidence from runtime, import, harness (WP29) | 2L, Risk, Audit, Dev |
| `docs/controls.md` | Control catalogue, evidence status, compliance figure, task list sized by Decision 33 class, import (WP30) | 2L, Risk, Audit, Dev |
| `docs/governance.md` | Governance shared core: the AI system entity, team scope, risk inheritance, segregation of duties, API, console (WP-G0) | 2L, Risk, Audit, Dev |
| `docs/governance-actions.md` | Governance loop: events from alerts, gate, detectors, monitors, packs and the chain become actions by rule; the rules file, the seven actions, dedupe, dry run (WP-G5) | 2L, Risk, SOC, Dev |
| `docs/incidents.md` | Incidents made by the governance loop: table, states, who closes, API, Incidents tab (WP-G5) | 2L, SOC, Audit |
| `docs/guardian-bindings.md` | Per-system guardian switches and the mandatory floor: table `guardian_binding`, how detectors, judge sampling, the session monitor and the monitors read it, API, Catalog switches (WP-S1) | 2L, Risk, Dev |
| `docs/assignment-rules.md` | Assignment rules: `config/assignment_rules.yaml`, the deterministic evaluator, the `assignment` table, hooks into tasks, controls and the obligation matrix, the guardian floor (WP-G2) | 2L, Risk, Audit, Dev |
| `docs/autonomy-levels.md` | Autonomy levels L0 to L5 of an AI system, the human role, and how each level maps to the guardian floor and the task set (WP-G2) | 2L, Risk, Audit, Dev |
| `docs/decision33.md` | Decision 33 classification: the question flow, draft, edit and apply by a person, the risk floor, the optional AI pre-fill (WP-G2) | 2L, Risk, Audit, Dev |
| `docs/transparency-report.md` | Transparency report: variants, sections, what it does not show, versions and hashes, harness (WP31) | 2L, Risk, Audit, Dev |
| `docs/inventory.md` | Inventory graph, risk inheritance, shadow-AI scan (WP24) | 2L, Platform admin, Dev |
| `docs/assurance.md` | 33 eval packs with licence and data mode | 2L, Dev |
| `docs/tool-analytics.md` | Tool usage rollup, least-privilege suggestion, Tools page (WP22) | 2L, Op, Dev |
| `docs/judge-mrm.md` | Model card, validation, change control of the judge | 2L, Aud |
| `docs/llm-adapter.md` | LLM adapter flags, strict endpoints, derived judge family, challenger scope (WP1b-A) | Build, 2L |
| `docs/fact-sources.md` | `POLICY_DIR` and `FACT_SOURCE` for the served app (WP1b-A) | Build, Sec |
| `docs/enterprise-readiness.md` | Scored gaps (ISO 42001, NIST AI RMF, ASVS, ops) | 2L, Aud, Op |
| `docs/metrics.md` | Oversight metrics and their definitions | 2L, Op |
| `docs/session-monitor.md` | Session monitor: signals, case and pause rules, settings, route, harness (WP27) | Dev, Op, Aud |
| `docs/session-monitor-validation-report.md` | Session harness result with GO / NO-GO and the WP28 trace catch rates (WP27) | Aud, 2L |
| `docs/detectors.md` | Detector contract, catalogue, verdict v2, precedence, coverage, harness, how to add a detector (WP37) | Dev, Op, Aud |
| `docs/detectors-validation-report.md` | Detector harness result on the mock path with GO / NO-GO (WP37) | Aud, 2L |
| `docs/latency.md` | Gate latency: method, numbers from `tools/bench_latency.py`, budgets, what is not measured | Op, Dev, Aud |
| `docs/monitors.md` | Per-agent monitor bindings and monitor status (`not_applicable`) | Dev, Op, 2L |
| `docs/threat-model.md` | Threat model of Supervisor itself | 2L, Aud |
| `docs/LICENSES.md` | Licence log for packages, assets, datasets | 2L, Aud |
| `docs/BUILD_PLAN.md` | Phase 1 plan (WP0 to WP12) | Build |
| `docs/BUILD_PLAN_PHASE2.md` | Phase 2 plan (WP13 to WP19) and status | Build |
| `docs/ingress-auth.md` | Per-agent credentials on agent ingress: setup, rotation, rubric (WP20) | Build, Sec |
| `docs/adr/` (D01 to D32; number registry `docs/adr/REGISTRY.md`) | Design decisions: gateway, evidence chain, judges, retention, ingress auth, alerts, inventory, masker, tool analytics, latency benchmark (D19), monitor bindings (D20), derived judge family and served config (D21), Playground dry run (D22), verdict contract v2 and detector framework (D23), HTTP MCP gateway and tool locking (D24), multi-turn red team (D25), risk register (D26), injection classifier (D27), collectors and policy modes (D28), session monitor (D29), control catalogue and tasks (D30), transparency report (D31), activity parity and nine alerts (D32) | Build, Aud |
| `docs/phase3/wave1/` | Phase 3 wave 1: handoff and review of each WP, integration report (`INTEGRATION_WAVE1.md`) | Build, Aud |
| `docs/phase3/wave2/` | Phase 3 waves 2 and 3: handoff and review of WP25 to WP31 and WP37 to WP39, integration report (`INTEGRATION_WAVE2.md`) | Build, Aud |
| `docs/design/` | Console design reference and screens | Build |
| `docs/handoff/` | Product background and analysis | Build |
