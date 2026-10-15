# Build plan, phase 2 (2026-10-15): from competition entry to enterprise product

## Status (2026-10-15)

Waves 1 and 2 are merged on `main`. Wave 3 (review fixes, docs, release v0.2.0) is in progress.

| WP | Name | Merged commit | Headline |
|---|---|---|---|
| 13 | Regulation knowledge base | `fd14d9f` | 31 instruments, 528 obligations |
| 14 | Compliance advisory agent | `89b973c` (merge of WP14) | Matrices for payments, credit_prequal, customer_service; Decision 33 and Circular 53 thresholds |
| 15 | Integration advisory agent | `7e8c2a5` | Readiness score and patches per corpus repo; OTel GenAI mapping |
| 16 | Code-analysis corpus and tuning | `d9c550c` | 20 corpus repos; gates in tests |
| 17 | Assurance eval packs | `b96cc9d` (+ fix `b42dadd`) | 33 packs, 6 dimensions |
| 18 | Enterprise readiness | `6170306` | Readiness 49 % -> 60 % (145 / 297 -> 178 / 297) |
| 19 | Judge MRM pack | `b85b587` | Model card, validation report, incident clock, RETIRED state |

Whole suite on `main`: 2548 tests (figure from the wave 2 merge report, not re-run for this table).

Phase 1 (`docs/BUILD_PLAN.md`, WP0–WP12) shipped release v0.1.0: gateway, recorder, judges,
evidence chain, monitors, console, onboarding agent, Databricks kit, demo. Phase 2 makes
Supervisor a product any regulated company can run, not only Techcombank, while we wait for the
bank's LLM key, workspace run and internal rules.

Every hard constraint in `CLAUDE.md` and `docs/BANK_DEPLOY_GUIDE.md` still applies. The app
stays offline. Research agents may use the internet on the dev host; nothing in `src/` fetches.

## 1. Goals

| # | Goal | Measured by |
|---|---|---|
| G1 | Regulation knowledge base: the basics of Vietnamese AI, banking, data and cyber law, plus international reference frameworks, as structured, cited, versioned data. Internal rules load into the same format at any time. | Coverage table with a VERIFIED mark per instrument; loader tests; `regkb validate` passes |
| G2 | Compliance advisory agent: for any product (not only our three demo agents) produce an obligations matrix with gaps, controls and open questions, citing G1 items. Advisory only. | Three demo agents + one external fixture product get a matrix; every row cites an obligation id |
| G3 | Integration advisory agent: tell a development team how to fit their product into Supervisor (tracing contract, gate SDK, policy scaffold, catalogue) with a readiness score and ready-to-apply patches. | Corpus of 12+ fixture repos scored; patches apply cleanly in the sandbox |
| G4 | Code-analysing agents tested and tuned: precision / recall of Discover and Understand against a labelled corpus; safety against repo-borne prompt injection. | `onboard.eval` report; gates in tests (tools recall ≥ 0.90, LLM-call recall ≥ 0.90, zero injection follow-through) |
| G5 | Assurance eval packs: the industry's known tests for accuracy, hallucination, bias and fairness, dependency risk, adversarial and security risk, robustness, wired into launch gating, continuous monitoring and judge validation. | Pack catalogue with licence per pack; runners offline; results in `eval_result` table, evidence chain, launch pack, console |
| G6 | Enterprise readiness: scored against ISO/IEC 42001, NIST AI RMF, OWASP ASVS (subset) and an operations checklist; top gaps closed. | `docs/enterprise-readiness.md` with before/after score; RBAC, audit log, structured logs, health, retention, support bundle in place |
| G7 | Supervisory agent (judge) under model-risk management: model card, validation report, change control, judge-vs-human agreement, retire stage. | Report generated from golden set + assurance packs; verdict rows carry prompt and model version hashes |

## 2. Work packages

| WP | Name | Builds | Definition of Done |
|---|---|---|---|
| 13 | Regulation knowledge base (RegKB) | `regulations/schema/obligation.schema.json`; `regulations/vn/*.yaml` (one file per instrument); `regulations/intl/*.yaml` (reference frameworks, tagged `binding: false`); `regulations/internal/README.md` + example; `src/supervisor/regkb/` loader, applicability predicates, version hash, `python -m supervisor.regkb {validate,list,show,coverage,diff}`; `tools/regkb_fetch.py` (dev host only: vbpl.vn fetch, stores source text + sha256 under `regulations/sources/`); `docs/regulations.md` | Instruments in §3 covered with status; every obligation has ≥ 1 source URL, fetch date, verification tag; control mapping ids resolve to catalogue manifests, rule ids or monitor names (test); schema test; coverage CLI prints the table; disclaimer "not legal advice" on every output |
| 14 | Compliance advisory agent | `src/supervisor/advisory/compliance/`: `ProductProfile` (from onboard `Understand` or a `product.yaml` questionnaire), deterministic applicability over RegKB, `ObligationMatrix` (applies / status met-partial-gap-bank-process / evidence pointers / deadline / open questions), Decision 33 class suggestion (reuse onboard mapping), optional LLM narrative (mock default, labelled); renders `compliance_matrix.{json,md,html}` vi+en; launch pack artefact; console tab behind `CONSOLE_COMPLIANCE_ENABLED`; CLI `python -m supervisor.advisory.compliance` | Matrices for payments, credit_prequal, customer_service and one fixture product; snapshot tests; internal-rule merge test; every row cites an obligation id; unknown facts become questions, never guesses |
| 15 | Integration advisory agent | `src/supervisor/advisory/integration/`: readiness report (framework, LLM calls, tools, data access, tracing found; what to add: OTel GenAI semconv attributes, `@supervised_tool` call sites, MCP proxy config, policy YAML scaffold, catalogue manifests, settings, test plan), readiness score with rubric, patch files (diffs, not applied) built on `onboard/instrument.py`; recorder normaliser mapped to OTel GenAI semantic conventions (`gen_ai.*`) with a mapping table and test; `docs/INTEGRATION_GUIDE.md` (three patterns: in-process SDK, OTLP export, MCP proxy); console tab behind flag; CLI | Report + patches for every corpus repo (WP16); patches apply in the launch sandbox; semconv mapping test; guide reviewed against the three demo agents |
| 16 | Code-analysis corpus and tuning | `data/corpus/repos/<name>/` 12+ small synthetic agent repos (LangGraph, LangChain, LlamaIndex, raw openai, anthropic SDK, MLflow ChatAgent, FastMCP server, FastAPI tool server, CrewAI-style, notebook export, dynamic tool registry, Vietnamese comments, planted secrets, README prompt injection) + `labels.yaml` (tools, LLM calls, model family, data sinks, PII fields, tracing, Decision 33 class); `python -m supervisor.onboard.eval --corpus ... --report`; tune `discover.py` / `understand.py` until gates pass; `docs/onboard-eval.md` before/after | Precision and recall per field in the report; gates in `tests/onboard/`; injection fixtures produce zero instruction follow-through (ADR D12); scrubber catches all planted secrets |
| 17 | Assurance eval packs | `src/supervisor/assurance/`: `EvalPack` manifest schema (`packs/*.yaml`: id, dimension, source, licence, data mode `synthetic` / `bank_supplied_path` / `vendored_sample`, runner, metrics, thresholds, maps to RegKB duty ids and OWASP / FinVault / ATLAS classes); runners for three targets: supervised agent via launch sandbox, recorded traces, the judge itself; `eval_result` table (`schema/model.yaml` + DDL regen) + evidence record; launch pack "Assurance report"; console screen behind `CONSOLE_ASSURANCE_ENABLED`; CLI `python -m supervisor.assurance {list,run,report}`; `docs/assurance.md` with the catalogue and licence per pack | Packs in §4 present; every runner has a synthetic Vietnamese data path that works offline; thresholds drive launch NO-GO deterministically; judge enablement requires the judge packs to pass; `docs/LICENSES.md` updated for any vendored sample |
| 18 | Enterprise readiness | Assessment first: `docs/enterprise-readiness.md` scored row by row (ISO/IEC 42001 clauses 4–10, NIST AI RMF Govern/Map/Measure/Manage, OWASP ASVS L1 subset, ops checklist). Then close the top gaps that fit the constraints: role matrix enforced on every console action, console action audit table, structured JSON logs with request id, `/health` + `/ready`, retention and deletion job (PDPL), `supervisor.cli support-bundle` (scrubbed), security headers, request size and rate limits, OpenAPI tags and versioned API prefix, SQLite backup/restore + Delta export command, fail-mode drill script | Score table before and after; each closed gap has a test; no new infrastructure; nothing on by default that changes phase-1 behaviour without a flag |
| 19 | Judge MRM pack | Judge model card generator; validation report (golden set + judge packs from WP17 + challenger disagreement + N-run stability); `prompt_hash` and `model_version` on every verdict (check, extend); re-validation trigger list; judge-vs-human agreement metric from sign-offs; Onboard `Retire` stage; SBV 24-hour incident clock fields on cases (check, extend) | Report renders from the demo store; agreement metric in `oversight_metric`; schema and DDL current; tests |

Order: Wave 1 = 13 ∥ 16 ∥ 17 ∥ 18 (assessment). Wave 2 = 14 (after 13) ∥ 15 (after 16) ∥ 18 (hardening) ∥ 19 (after 17). Wave 3 = integration: launch pack, console, docs, release v0.2.0, full review.

## 3. Regulation coverage target (WP13)

Vietnamese instruments (binding or draft, mark each):

| Instrument | Why it matters here |
|---|---|
| Law on Artificial Intelligence (2025) and its guiding decree | risk classes, conformity assessment, registration, human oversight, transparency, incident duties |
| Decision 33 (high-risk AI system list) | classifies credit, payment and customer-facing agents; transition dates |
| SBV Circular 53/2026/TT-NHNN on AI in banking (signed 2026-09-30, in effect 2026-11-15; was a draft when phase 1 was analysed) | model management, logging, incident duties via the AI Law and Decree 142/2026 (72 h preliminary, 5 working days, 15-day formal), bias monitoring, human review of disputed decisions, outsourcing responsibility, high-value thresholds (Art. 4) and the 100M VND per day cap on autonomous payments for an individual (Art. 5) |
| Personal Data Protection Law 91/2025/QH15 + Decree 356/2025 | lawful basis, sensitive data (financial, biometric), cross-border transfer, retention, data subject rights, DPIA |
| Data Law 60/2024 + Decree 165/2025 | core / important data localisation and transfer notice; log retention minimum |
| Cybersecurity Law 116/2025 (and Decree 53/2022 while in force) | localisation, incident reporting, system classification |
| Law on Credit Institutions 32/2024/QH15; Decree 117/2018 | customer information confidentiality |
| SBV Circular 09/2020/TT-NHNN; Circular 50/2024/TT-NHNN (online banking safety); Decision 2345/QD-NHNN (biometric check on transfers) | IT security, transaction authentication thresholds, logging |
| E-Transactions Law 20/2023/QH15 + Decree 23/2025 | legal weight of electronic records and signatures (evidence chain) |
| Law on Protection of Consumer Rights 19/2023/QH15 | disclosure, unfair terms, automated decisions towards consumers |

International reference frameworks (`binding: false`): EU AI Act (high-risk duties, Annex III credit scoring), NIST AI RMF 1.0 + Generative AI Profile, ISO/IEC 42001 and 23894, MAS FEAT principles and 2025 AI risk guidelines, HKMA GenAI guidance, Fed SR 11-7 (model risk), OWASP LLM Top 10 (2025), OWASP Agentic Top 10, MITRE ATLAS, OECD AI Principles.

Rules for WP13: quote the primary text where a primary source was read (Vietnamese legal texts are outside copyright under the IP Law, Art. 15); otherwise summarise and tag `VERIFIED (secondary)` with the URL; never present a draft as in force; every date has a source; the loader refuses an obligation with no source.

## 4. Assurance pack catalogue target (WP17)

| Dimension | Packs (source, licence, data mode) |
|---|---|
| Accuracy and hallucination | TruthfulQA (Apache-2.0, bank_supplied_path + synthetic vi analogue); SimpleQA (MIT, same); HaluEval (MIT, same); RAGAS-style faithfulness, answer relevance and context precision (own implementation, Apache-2.0 reference); SelfCheckGPT-style consistency (own, N samples); existing groundedness monitor reused |
| Bias and fairness | BBQ (CC-BY-4.0, vendored sample allowed with attribution); WinoBias (MIT); BOLD, CrowS-Pairs, StereoSet (CC-BY-SA: importer only, never vendored); Fairlearn metrics (demographic parity difference, equalized odds difference); four-fifths rule (disparate impact); counterfactual probes that swap gender, age band, province, ethnicity in Vietnamese inputs (own) |
| Dependency and supply-chain risk | CycloneDX SBOM from `uv.lock` (own writer); vulnerability match against an offline OSV snapshot (`OSV_DB_PATH`, bank supplied); licence allow-list check; pin and hash check; model dependency inventory (vendor, version pin, hosting region, concentration); MCP server and tool manifest hash drift (OWASP ASI04) |
| Adversarial and security | OWASP LLM Top 10 probe set (own); OWASP Agentic Top 10 (existing 145-case pack, extended); MITRE ATLAS technique mapping; garak-style probe families reimplemented small (direct and indirect injection, jailbreak templates, system-prompt leak, tool misuse, exfiltration through tool args, excessive agency); AgentDojo / InjecAgent-style indirect injection in tool results (own, Vietnamese); HarmBench / AgentHarm-style harmful task refusal, finance subset (own); judge-targeted attacks (existing); PII canaries (existing) |
| Robustness | Perturbation (typos, diacritics stripped, mixed vi/en, Unicode confusables); paraphrase consistency |

Licence rules: no CC-BY-SA data in the repo; CC-BY and MIT/Apache samples may be vendored small with attribution in `docs/LICENSES.md`; every pack works offline with the synthetic path; a pack with no data present reports `[SKIP]`, never a false pass.

## 5. Delegation for phase 2

Lead agents (Opus) own one WP each in a worktree, spawn Sonnet workers for bounded sub-tasks, and one reviewer at the end. A lead may order a worker to redo work when the reviewer finds a significant defect. The supervisor (this session) reviews at the end of each wave, merges, and runs the full test suite before the next wave starts. Report shape per `CLAUDE.md`.
