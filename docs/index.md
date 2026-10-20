# Documentation index

Audience key: **Op** = operator (runs it), **Dev** = developer integrating a product,
**2L** = second line / risk / compliance, **Aud** = auditor, **Build** = engineer on this repo.

Regulation and compliance documents are advisory. Not legal advice. Bank counsel must confirm.

| Document | Purpose | Audience |
|---|---|---|
| `README.md` (root) | Product overview, capabilities, 10-minute tour, flags | All |
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
| `docs/inventory.md` | Inventory graph, risk inheritance, shadow-AI scan (WP24) | 2L, Platform admin, Dev |
| `docs/assurance.md` | 33 eval packs with licence and data mode | 2L, Dev |
| `docs/tool-analytics.md` | Tool usage rollup, least-privilege suggestion, Tools page (WP22) | 2L, Op, Dev |
| `docs/judge-mrm.md` | Model card, validation, change control of the judge | 2L, Aud |
| `docs/enterprise-readiness.md` | Scored gaps (ISO 42001, NIST AI RMF, ASVS, ops) | 2L, Aud, Op |
| `docs/metrics.md` | Oversight metrics and their definitions | 2L, Op |
| `docs/threat-model.md` | Threat model of Supervisor itself | 2L, Aud |
| `docs/LICENSES.md` | Licence log for packages, assets, datasets | 2L, Aud |
| `docs/BUILD_PLAN.md` | Phase 1 plan (WP0 to WP12) | Build |
| `docs/BUILD_PLAN_PHASE2.md` | Phase 2 plan (WP13 to WP19) and status | Build |
| `docs/ingress-auth.md` | Per-agent credentials on agent ingress: setup, rotation, rubric (WP20) | Build, Sec |
| `docs/adr/` (D01 to D15, D17) | Design decisions: gateway, evidence chain, judges, retention | Build, Aud |
| `docs/design/` | Console design reference and screens | Build |
| `docs/handoff/` | Product background and analysis | Build |
