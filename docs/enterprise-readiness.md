# Enterprise readiness: scored gap assessment (before hardening)

Date: 2026-10-15. Work package: WP18. Before is the product before hardening (Part A). After is the product after WP18 Part B (commit ccf296b), re-scored with the same rule.

## 1. Scope and method

Supervisor is a tool. It supports a bank's AI management system (AIMS). It does not replace it.
Each row scores what the tool provides or evidences. Where a clause is an organisational duty,
the Gap cell says "bank process" and the score is honest (for example 1 when the tool helps in part).

| Score | Meaning |
|---|---|
| 0 | Absent |
| 1 | Partial: some of the requirement exists, a named part is missing |
| 2 | Present but untested |
| 3 | Present with tests |

Evidence rule: any score above 0 has file:line evidence that was read or grepped in this worktree.
A 3 also names the test file (and the test function where easy). No evidence found means 0.
Paths are relative to the repository root. After scoring (Part B) uses the same scale with one convention: a feature behind an off-by-default flag counts as present when the flag path is tested. A row where a named part is still missing (for example the Delta path or an agent ingress credential) stays 1 even when the built part has tests. A 2 means fully present but untested. The Gap cell keeps the before text.

Targets checked: Windows laptop (SQLite) and Databricks App (one process, Delta tables, OAuth only, no new infrastructure).
Test names were read from the test files and the code was read for each After claim. The tests were not run for this assessment.

## 2. Section A: ISO/IEC 42001:2023

| ID | Requirement (short) | Before | After | Evidence (file:line, tests) | Gap |
|---|---|---|---|---|---|
| A-4 | Context of the organisation (4.1-4.4): scope, interested parties | 1 | 1 | docs/threat-model.md sections 1-2 (trust boundaries); docs/BANK_DEPLOY_GUIDE.md section 1. No test. | Tool scope is written. AIMS scope and interested-party list are a bank process. No in-product record. |
| A-5 | Leadership and AI policy (5.1-5.3): policy, roles, authority | 1 | 1 | policies/*.yaml deployed as code, `policy_hash` in every decision (src/supervisor/gateway/policy.py); owner per agent (schema/model.yaml:41); tests/gateway/test_policy.py. SECURITY.md contact is FILL-ME. | The AI policy statement and management commitment are a bank process. Policy deploy is not a chain record (threat-model section 4). |
| A-6.1 | Planning: AI risk assessment | 1 | 1 | Onboard proposes risk tier and Decision 33 class (src/supervisor/onboard/render.py:25-27, src/supervisor/onboard/operate.py:59-60); tests/onboard/test_run_e2e.py. | A proposal per agent only. No risk register, no likelihood/impact scale, no review date. |
| A-6.1b | Planning: AI system impact assessment | 0 | 0 | None found (grep `impact` in src/ and docs/ finds only BUILD_PLAN_PHASE2.md). | No impact-assessment record, template or evidence link. Needs a bank method (PDPL DPIA, Decision 33). |
| A-6.2 | Planning: AI objectives and how to reach them | 1 | 1 | `oversight_metric` (schema/model.yaml:339), src/supervisor/monitors/oversight.py, `policy_threshold` (schema/model.yaml:397); tests/monitors/test_fairness.py, tests/monitors/test_drift.py. | Metrics exist. No stored objective with owner, target and date. |
| A-7.1 | Support: resources | 1 | 1 | src/supervisor/preflight.py (checks), src/supervisor/console/health.py:143; tests/console/test_health_screen.py::test_health_table. **After:** Added: `GET /ready` (src/supervisor/ops/readiness.py:33; tests/ops/test_readiness.py::test_ready_ok_with_scheduler_states). No capacity view. | Checks the runtime only. No capacity or staffing view. Console health is not a probe endpoint. |
| A-7.2 | Support: competence | 0 | 0 | None found. docs/console.md describes roles only. | No training material or competence record. Bank process. |
| A-7.3 | Support: awareness | 1 | 1 | Dev-user banner in the console (docs/console.md Identity); inbox notices (src/supervisor/adapters/notify/__init__.py:31). | No awareness material for agent owners or reviewers. |
| A-7.4 | Support: communication | 3 | 3 | Inbox notifier (src/supervisor/adapters/notify/__init__.py:31); SIEM, ITSM, pager adapters off by default (docs/bank-integration.md); tests/console/test_metrics_inbox.py::test_inbox_mark_read, tests/integrations/test_integrations.py. | Internal channels only. The organisation's communication plan is a bank process. |
| A-7.5 | Support: documented information (create, control, protect) | 3 | 3 | Hash-chained evidence, Ed25519 root, offline verify (src/supervisor/evidence/chain.py, src/supervisor/evidence/verify.py:660); tests/evidence/test_export_verify.py::test_export_then_verify_ok and the tamper tests. | Versioning of policy and docs is by git only. |
| A-8.1 | Operation: operational planning and control | 3 | 3 | Deterministic gateway, fail closed (src/supervisor/gateway/engine.py:6-17, `_fail` at :905); tests/gateway/test_engine.py, tests/gateway/test_fail_closed.py. | Cooperative enforcement until a credential broker exists (threat-model section 4). |
| A-8.2 | Operation: AI risk assessment (per agent, before launch) | 3 | 3 | Launch go/no-go with red-team pack in SHADOW (src/supervisor/onboard/launch.py:172); tests/onboard/test_launch.py::test_payments_launch_report, ::test_no_harness_is_no_go. | Only for agents with a harness. More packs in WP17. |
| A-8.3 | Operation: AI risk treatment | 3 | 3 | Pause, quarantine, resume by two people (src/supervisor/gateway/state.py:253-322, ADR D04); tests/gateway/test_routes.py::test_pause_then_money_denied_read_allowed, ::test_resume_needs_two_people. | A treatment plan record per risk is a bank process. |
| A-8.4 | Operation: AI system impact assessment (re-assessment on change) | 0 | 0 | None found. | Same gap as A-6.1b. No re-assessment trigger on change. |
| A-9.1 | Performance evaluation: monitoring and measurement | 3 | 3 | Drift, fairness, quality, oversight monitors and scheduler (src/supervisor/scheduler.py:359, src/supervisor/monitors/); tests/monitors/test_drift.py, tests/monitors/test_fairness.py, tests/monitors/test_scheduler.py. | Monitors emit only what the bank enables. No Prometheus export. |
| A-9.2 | Performance evaluation: internal audit | 1 | 1 | Auditor role and audit pack (src/supervisor/console/auditpack.py:102, src/supervisor/console/routes.py:711); tests/console/test_review_fixes.py::test_audit_pack_with_non_ascii_user. **After:** Added: `console_action` rows in the audit pack (src/supervisor/console/auditpack.py:123-139; tests/console/test_rbac_matrix.py::test_audit_pack_carries_the_console_action_rows). The audit programme stays a bank process. | Pack exists. Audit programme, schedule and findings log are a bank process. Console action audit is partial (D-2). |
| A-9.3 | Performance evaluation: management review | 1 | 1 | Console overview and metrics pages (src/supervisor/console/readmodels.py); docs/metrics.md. | No periodic management-review report or sign-off record. |
| A-10.1 | Improvement: nonconformity and corrective action | 3 | 3 | Case lifecycle, two sign-offs, ITSM ref (src/supervisor/cases/service.py:589, :696); tests/console/test_case_service.py, tests/console/test_incident_flow.py. | Root cause and corrective-action fields are free text only. |
| A-10.2 | Improvement: continual improvement | 1 | 1 | Drift bands re-baseline per version (tests/monitors/test_drift.py::test_new_version_gets_its_own_baseline); judge eval harness (tests/judge/test_eval_harness.py). | No improvement log. WP19 adds judge re-validation triggers. |
| A.2 | Annex A.2 policies for AI (alignment, review) | 1 | 1 | policies/*.yaml with `policy_hash` (src/supervisor/gateway/policy.py); docs/adr/D11-policy-language.md. | No policy review cycle or approval record. Policy deploy not on the chain. |
| A.3.2 | A.3 internal organisation: roles and responsibilities | 1 | 3 | Roles src/supervisor/adapters/auth/base.py:18; owner per agent (schema/model.yaml:41); role tuples src/supervisor/console/routes.py:66-74. **After:** src/supervisor/core/rbac.py:21-29 (7 roles), :43-71 (permissions); src/supervisor/adapters/auth/authz.py:117 `needs()`; tests/test_rbac.py::test_phase1_grants_are_kept, tests/console/test_rbac_matrix.py::test_every_protected_route_has_the_needs_dependency. | Roles are scattered across modules and not enforced on every action (D-1). |
| A.3.3 | A.3 internal organisation: reporting of concerns | 1 | 1 | SECURITY.md (contact is FILL-ME); cases open from several sources (src/supervisor/jobs/case_intake.py). | No in-product concern channel. The bank fills the contact. |
| A.4.2 | A.4 resources: data | 1 | 1 | Onboard lists data sinks and PII fields (src/supervisor/onboard/understand.py); `agent` registry (schema/model.yaml:38). | No data-resource register beyond the onboarding profile. |
| A.4.3 | A.4 resources: tooling | 3 | 3 | Catalogue manifests (src/supervisor/catalogue/manifests/); tests/onboard/test_catalogue.py; docs/LICENSES.md. | None for the tool itself. |
| A.4.4 | A.4 resources: system and compute | 1 | 1 | src/supervisor/preflight.py (warehouse, serving, paths); app.yaml. | No capacity record or limits. Single process by design. |
| A.4.5 | A.4 resources: human | 0 | 0 | None found. | No staffing or skills view. Bank process. |
| A.5 | A.5 AI system impact assessment (process, documentation, impact on individuals and society) | 0 | 0 | None found. | Same as A-6.1b. |
| A.6.1 | A.6 life cycle: requirements and design | 1 | 1 | Onboard Plan stage proposes the policy (src/supervisor/onboard/plan.py); tests/onboard/test_plan_policy.py. | Covers the guard-rail design only. Requirements of the supervised system are the bank's. |
| A.6.2 | A.6 life cycle: verification and validation | 3 | 3 | Red-team pack in SHADOW (src/supervisor/onboard/launch.py:172); tests/onboard/test_launch.py. Judge eval harness: tests/judge/test_eval_harness.py::test_eval_end_to_end_with_mockchat. | Accuracy, bias and robustness packs come in WP17. |
| A.6.3 | A.6 life cycle: deployment | 3 | 3 | Go/no-go and per-rule enforcement switches (src/supervisor/onboard/launch.py:417); states SHADOW to enforced (src/supervisor/core/models.py:28-29); tests/onboard/test_launch.py::test_enforced_policy_fails_the_shadow_check. | Retire stage is missing (WP19). |
| A.6.4 | A.6 life cycle: operation and monitoring | 3 | 3 | Gate, recorder, monitors (src/supervisor/scheduler.py:359); tests/gateway/test_engine.py, tests/monitors/test_drift.py. | None for the tool. |
| A.6.5 | A.6 life cycle: technical documentation | 2 | 2 | Onboard profile and launch report rendering (src/supervisor/onboard/render.py:25); case file (src/supervisor/evidence/casefile/). | No test found that asserts the rendered profile text. |
| A.6.6 | A.6 life cycle: event logs | 3 | 3 | Evidence chain per lane (src/supervisor/evidence/chain.py); tests/evidence/test_chain.py::test_restart_continues_lanes, tests/evidence/test_export_verify.py::test_export_then_verify_ok. | Application logs are plain text (D-3). |
| A.7.2 | A.7 data for AI: quality | 1 | 1 | `trace_coverage` (schema/model.yaml:143); quality monitor (src/supervisor/monitors/quality.py:92); tests/monitors/test_quality.py. | Trace coverage only. Quality of training data is a bank process. |
| A.7.3 | A.7 data for AI: provenance | 1 | 1 | `case_link` source kinds (schema/model.yaml:248); recorder keeps source ids (docs/recorder.md). | No data lineage for training or knowledge data. |
| A.7.4 | A.7 data for AI: preparation (masking) | 3 | 3 | VN regex masker, keyed pseudonyms (src/supervisor/adapters/masking/vn_regex.py); tests/recorder/test_masking.py::test_recall_precision. | Regex masking can miss PII (ADR D07). Presidio default is in BACKLOG.md. |
| A.8.1 | A.8 information for parties: incident communication | 1 | 1 | Inbox notices and SIEM/ITSM/pager adapters (docs/bank-integration.md); tests/integrations/test_integrations.py. | No regulator or customer notice template. SBV 24-hour clock fields come in WP19. |
| A.8.2 | A.8 information for parties: reporting | 3 | 3 | Case file and audit pack (src/supervisor/evidence/casefile/, src/supervisor/console/auditpack.py); tests/evidence/test_casefile.py. | Regulator report formats are a bank decision. |
| A.9.1 | A.9 use of AI systems: responsible use | 1 | 1 | Human-gate flag in the profile (src/supervisor/onboard/render.py:27); ADR D04. | No acceptable-use policy or user-facing statement. |
| A.9.2 | A.9 use of AI systems: human oversight | 3 | 3 | Two-person resume (ADR D04), two sign-offs for high/critical cases; tests/console/test_console_errors.py::test_reviewer_cannot_resume_alone, tests/gateway/test_routes.py::test_resume_needs_two_people. | None for the tool. |
| A.10.1 | A.10 third parties: suppliers | 1 | 1 | docs/LICENSES.md (licence log); uv.lock pins. | No supplier register, no vulnerability match, no SBOM (WP17 plans CycloneDX). |
| A.10.2 | A.10 third parties: model vendors | 2 | 2 | Loopback-only LLM unless `LLM_ALLOW_REMOTE` (src/supervisor/config.py:167, :392); `model_version`, `prompt_hash` on verdicts (src/supervisor/judge/service.py:371-374); ADR D07. | The remote-allowed path is tested (tests/test_app_config.py:96); the refusal path was not confirmed in tests. No vendor terms record. |

Section A total: before 69 / 126, after 71 / 126 (42 rows).

## 3. Section B: NIST AI RMF 1.0

| ID | Requirement (short) | Before | After | Evidence (file:line, tests) | Gap |
|---|---|---|---|---|---|
| GV-1 | GOVERN 1: policies, processes, legal requirements | 1 | 1 | policies/*.yaml; docs/BUILD_PLAN_PHASE2.md section 3 (RegKB planned); docs/adr/D01-D12. | Legal requirements are not mapped in product until WP13. |
| GV-2 | GOVERN 2: accountability and roles | 1 | 3 | Roles src/supervisor/adapters/auth/base.py:18; owner per agent (schema/model.yaml:41); actor on every case event (schema/model.yaml:233). **After:** Same as A.3.2: src/supervisor/core/rbac.py:90-148 route matrix; tests/console/test_rbac_matrix.py::test_every_route_is_in_the_matrix, ::test_denied_roles_get_403_and_allowed_roles_do_not. | Role matrix not enforced everywhere (D-1). |
| GV-3 | GOVERN 3: workforce diversity and inclusion | 0 | 0 | None found. | Organisational duty. The tool has nothing to evidence. |
| GV-4 | GOVERN 4: risk culture, critical thinking | 1 | 1 | Console shows reasons and evidence; sign-off statements stored verbatim (docs/console.md Identity). | Culture is a bank process. No feedback or training prompts. |
| GV-5 | GOVERN 5: stakeholder engagement | 0 | 0 | None found. | No channel for affected parties or feedback intake. |
| GV-6 | GOVERN 6: third-party and supply-chain policies | 1 | 1 | docs/LICENSES.md; LLM_ALLOW_REMOTE rule (src/supervisor/config.py:167). | No third-party risk policy in product. No SBOM. |
| MP-1 | MAP 1: context and intended use | 2 | 2 | Onboard Understand and profile (src/supervisor/onboard/understand.py, src/supervisor/onboard/render.py:25); docs/onboard.md. | Rendered content not asserted by tests. |
| MP-2 | MAP 2: categorisation of the AI system | 3 | 3 | Decision 33 class and proposed tier (src/supervisor/onboard/operate.py:59-60); tests/onboard/test_understand.py, tests/onboard/test_run_e2e.py. | Proposal, not a legal classification. |
| MP-3 | MAP 3: capabilities, benefits, costs | 1 | 1 | Metrics and judge counts (docs/metrics.md). | No cost or benefit record per agent. |
| MP-4 | MAP 4: risks of third-party components | 1 | 1 | docs/LICENSES.md; uv.lock; tests/test_requirements_current.py::test_requirements_match_lock. | No vulnerability data, no SBOM. |
| MP-5 | MAP 5: impacts on people and society | 0 | 0 | None found. | No impact record. Fairness monitor is under MS-2. |
| MS-1 | MEASURE 1: methods and metrics | 3 | 3 | `oversight_metric` (schema/model.yaml:339); src/supervisor/monitors/; tests/monitors/test_drift.py, tests/monitors/test_quality.py, tests/monitors/test_oversight.py. | None. |
| MS-2a | MEASURE 2: validity, reliability, safety | 3 | 3 | Red-team pack (src/supervisor/onboard/launch.py:172), judge eval, drift; tests/onboard/test_launch.py, tests/judge/test_eval_harness.py. | Accuracy and hallucination packs come in WP17. |
| MS-2b | MEASURE 2: security and resilience | 1 | 1 | Fail-closed gate (src/supervisor/gateway/engine.py:905); tests/gateway/test_fail_closed.py covers the gate, not the console, OTLP or scheduler. **After:** Added: fail-mode drill src/supervisor/demo/drill.py:86 (tests/demo/test_drill.py::test_drill_passes, ::test_drill_fails_when_money_fails_open). It covers the state store only, not OTLP, console or scheduler. Agent ingress still has no credential. | No fault drill across components. OTLP and gate have no caller auth. |
| MS-2c | MEASURE 2: privacy | 1 | 1 | Masking, keyed hashes, no PII in chain (src/supervisor/evidence/chain.py, src/supervisor/core/args_hmac.py); tests/recorder/test_masking.py, tests/evidence/test_chain.py::test_masker_is_applied_before_hashing. **After:** Added: retention job (src/supervisor/jobs/retention.py:49; tests/test_retention.py::test_job_redacts_old_keeps_new_and_chain_verifies). Open: Delta is report-only (appendOnly), job off by default. | No retention or deletion of personal columns (D-8). Raw capture has no expiry. |
| MS-2d | MEASURE 2: fairness | 3 | 3 | Fairness monitor with small-cell suppression (src/supervisor/monitors/fairness.py:387); tests/monitors/test_fairness.py::test_injected_gender_bias_gap_and_case, ::test_small_cells_suppressed. | Attribute data comes from a synthetic lookup unless the bank supplies one. |
| MS-2e | MEASURE 2: explainability and interpretability | 2 | 2 | Case story and rules tabs (src/supervisor/console/templates/_tab_story.html, _tab_rules.html). | No test asserts explanation content. Judge reasoning is advisory text. |
| MS-3 | MEASURE 3: tracking emergent risk | 3 | 3 | Drift bands and multi-agent monitor (src/supervisor/monitors/multiagent.py, src/supervisor/monitors/drift.py:172); tests/monitors/test_multiagent.py, tests/monitors/test_drift.py::test_seeded_drift_week_opens_exactly_one_case. | None. |
| MS-4 | MEASURE 4: feedback and measurement efficacy | 1 | 1 | Cohen kappa in the eval harness (tests/judge/test_eval_harness.py::test_cohen_kappa_bp). | No live agreement metric from sign-offs (WP19). |
| MG-1 | MANAGE 1: prioritise and respond to risks | 3 | 3 | Severity-ranked queue and case lifecycle (src/supervisor/console/routes.py:293, src/supervisor/cases/service.py:589); tests/console/test_cases_screen.py, tests/console/test_incident_flow.py. | SLA clocks are WP19. |
| MG-2 | MANAGE 2: maximise benefit, minimise harm, deactivation | 1 | 1 | Pause, quarantine, release (src/supervisor/gateway/state.py:253-322); status `retired` in the model (src/supervisor/core/models.py:28). | Pause and quarantine are tested (tests/gateway/test_state.py). No retire workflow. Scored 1: the retire path is missing. |
| MG-3 | MANAGE 3: third-party risk management | 1 | 1 | LLM remote refusal (src/supervisor/config.py:392); docs/LICENSES.md. | No monitoring of vendor change. Model version recorded per verdict only. |
| MG-4 | MANAGE 4: documented treatment, incident response and communication | 1 | 1 | Case file, chain, notices (src/supervisor/evidence/casefile/, src/supervisor/adapters/notify/__init__.py:31); tests/evidence/test_casefile.py. **After:** Added: support bundle (src/supervisor/ops/support.py:208; tests/ops/test_support_bundle.py::test_bundle_seeded_store_logs_masked) and the DR drill text (docs/RUNBOOK.md, section DR drill). Open: incident communication plan is a bank process. | Incident communication plan and drill missing. No support bundle. |

Section B total: before 34 / 69, after 36 / 69 (23 rows).

## 4. Section C: OWASP ASVS 4.0.3 Level 1 (subset)

| ID | Requirement (short) | Before | After | Evidence (file:line, tests) | Gap |
|---|---|---|---|---|---|
| V2 | V2 Authentication | 1 | 1 | SSO via Databricks headers (src/supervisor/adapters/auth/databricks_app.py:28); dev header refused on the App; tests/console/test_auth.py::test_dev_header_refused_on_databricks_app. **After:** Unchanged. Roles now come from one matrix, but laptop identity is still the dev header and agent ingress has no credential. | Laptop has no real authentication (dev header, banner). `/gate/*` and `/v1/traces` have no caller auth (SECURITY.md Known gaps). |
| V3 | V3 Session management | 1 | 1 | No own session. Cookies `sv_lang` and dev user: HttpOnly, SameSite=strict (src/supervisor/console/routes.py:152, :842). | No `Secure` flag, no expiry, no logout. Platform session on the App. Not tested. |
| V4 | V4 Access control | 1 | 3 | `require()` on mutating actions (src/supervisor/console/routes.py:557, :647, :701, :711, :720, :773; src/supervisor/cases/service.py:560-705); tests/console/test_console_errors.py::test_missing_role. **After:** src/supervisor/core/rbac.py:90-148 route matrix; src/supervisor/adapters/auth/authz.py:117-141 (403 via `PermissionDenied`, handler `_permission_denied` in src/supervisor/app.py); `/gate/*` uses `needs(..., api=True)` (src/supervisor/gateway/routes.py, `API_RBAC_ENABLED`, default off); tests/console/test_rbac_matrix.py::test_gate_on_denies_a_viewer_and_allows_a_reviewer, ::test_gate_on_service_principal_cannot_control. Open: gate enforcement is off by default; `/gate/check` and `/v1/traces` are agent ingress without a human role. | `/gate/{pause,resume,quarantine,release}` and `/gate/metrics` have no role check (src/supervisor/gateway/routes.py:76-85, :112-140). `verify`, `chain/verify`, `inbox read` use `_view()` only (src/supervisor/console/routes.py:199, :444, :662, :822). OTLP open. |
| V5 | V5 Validation, sanitisation, encoding | 3 | 3 | ID regex (src/supervisor/console/routes.py:68), pydantic `extra=forbid` (src/supervisor/gateway/routes.py:29-44), Jinja autoescape (src/supervisor/console/routes.py:80), htmx-only POST as CSRF guard (src/supervisor/console/routes.py:168); tests/console/test_review_wp12.py::test_new_posts_need_htmx, ::test_file_routes_reject_traversal; tests/console/test_console_errors.py::test_other_user_errors_are_400. | None at L1. |
| V7a | V7 Error handling | 3 | 3 | Handlers return 400 with the exception type name only (src/supervisor/app.py:68-95); tests/console/test_console_errors.py::test_programmer_error_is_not_a_500. | None. |
| V7b | V7 Logging | 1 | 3 | Python `logging` calls (src/supervisor/app.py:30, src/supervisor/console/routes.py:52); token never logged (tests/console/test_auth.py::test_group_lookup_uses_token_in_request_only_and_never_logs_it). **After:** src/supervisor/ops/logging_setup.py:97 `JsonFormatter`, :119 `configure_logging`; request id src/supervisor/ops/middleware.py:56-77; principal id set at src/supervisor/adapters/auth/__init__.py:70; `LOG_FORMAT=json` (default `text`, src/supervisor/config.py); tests/ops/test_logging_setup.py::test_json_line_has_context_and_scrubs, ::test_exception_fields_and_scrub. | No logging config: plain text, no request id, no principal id, no JSON. |
| V8 | V8 Data protection | 1 | 1 | Masking and keyed hashes (src/supervisor/adapters/masking/vn_regex.py); tests/recorder/test_masking.py. **After:** src/supervisor/ops/middleware.py:118 `Cache-Control: no-store` on console pages (tests/ops/test_middleware.py::test_security_headers_on_api_and_console); retention job src/supervisor/jobs/retention.py (tests/test_retention.py::test_job_redacts_old_keeps_new_and_chain_verifies). Open: retention is SQLite-only and off by default; sign-off text is kept verbatim. | No `Cache-Control` on console pages. No retention or deletion. Sign-off statements stored verbatim. |
| V9 | V9 Communication | 1 | 1 | Loopback-only LLM rule (src/supervisor/config.py:392); laptop binds 127.0.0.1 (docs/RUNBOOK.md section 5). **After:** HSTS option, off by default (src/supervisor/ops/middleware.py:114-116; tests/ops/test_middleware.py::test_hsts_and_headers_off). TLS stays a platform duty. | TLS is the platform's job on the App. No HSTS. Not tested here. |
| V12 | V12 Files and resources | 3 | 3 | Static whitelist (src/supervisor/console/routes.py:211-225), export name check, no upload; tests/console/test_review_wp12.py::test_file_routes_reject_traversal, tests/console/test_static_assets.py. | None. |
| V13 | V13 API and web service | 1 | 1 | Typed bodies, 400 on error (src/supervisor/gateway/routes.py:29-44, :61); OTLP size and type limits (tests/recorder/test_otlp_receiver.py::test_oversized_body_is_400, ::test_other_content_type_is_415); tests/gateway/test_routes.py. **After:** src/supervisor/ops/middleware.py:129 body limit 413 (tests/ops/test_middleware.py::test_body_limit_413_by_length_and_stream), :233 rate limit 429 (::test_rate_limit_429_and_exemptions, off by default); `/v1/gate` prefix and tags (src/supervisor/ops/openapi.py; tests/test_openapi.py::test_every_gate_path_has_a_v1_twin_and_old_ones_are_deprecated). Open: `/gate/check` and `/v1/traces` have no caller auth. | No auth, no rate limit, no version prefix, no size limit on `/gate/*`. |
| V14a | V14.1 and V14.3 Build and configuration | 3 | 3 | Release leak sweep and stale-lock check (src/supervisor/release.py:234); tests/e2e/test_release.py::test_leak_sweep_fails_the_release, tests/test_no_secrets.py::test_no_secret_patterns. | Dev keys are labelled `dev` (SECURITY.md). |
| V14b | V14.2 Dependencies | 1 | 1 | uv.lock, exported requirements (tests/test_requirements_current.py::test_requirements_match_lock), licence log docs/LICENSES.md. | No SBOM, no vulnerability match. |
| V14c | V14.4 HTTP security headers | 1 | 3 | `X-Content-Type-Options: nosniff` on onboard files only (src/supervisor/console/routes.py:790); tests/console/test_onboard_screen.py:63. **After:** src/supervisor/ops/middleware.py:90-120 CSP, X-Frame-Options DENY, nosniff, Referrer-Policy, HSTS flag, no-store on console; tests/ops/test_middleware.py::test_security_headers_on_api_and_console, ::test_hsts_and_headers_off, ::test_templates_have_no_inline_script_or_handlers; tests/console/test_ops_headers.py::test_console_page_renders_with_security_headers. | No CSP, X-Frame-Options, Referrer-Policy or Cache-Control app-wide (grep finds none). |

Section C total: before 21 / 39, after 27 / 39 (13 rows).

## 5. Section D: Operations checklist

| ID | Requirement (short) | Before | After | Evidence (file:line, tests) | Gap |
|---|---|---|---|---|---|
| D-1 | RBAC matrix enforced (one module, every route) | 1 | 3 | Role tuples in 3 places (src/supervisor/console/routes.py:66-74, :727; src/supervisor/cases/service.py:56-58); `ROLES` src/supervisor/adapters/auth/base.py:18; tests/console/test_console_errors.py::test_missing_role. **After:** One module src/supervisor/core/rbac.py (7 roles, 20 permissions, route map :90-148); `needs()` src/supervisor/adapters/auth/authz.py:117 on every non-public route; tests/test_rbac.py::test_every_route_permission_exists, ::test_docs_table_equals_matrix_markdown; tests/console/test_rbac_matrix.py::test_every_route_is_in_the_matrix, ::test_matrix_has_no_stale_route. Gate API enforcement is behind `API_RBAC_ENABLED` (default off). | Not one module. Console GETs use `_view()` (any role passes, src/supervisor/console/routes.py:199). `/gate/*` POSTs trust a principal header (src/supervisor/gateway/routes.py:76-85). `dev/user` (src/supervisor/console/routes.py:833) has no check (laptop only). Roles `viewer`, `operator` do not exist. |
| D-2 | Console action audit log | 1 | 3 | Case actions in `case_event` (schema/model.yaml:233); `console_gate_action` chain record (src/supervisor/console/routes.py:524); `audit_pack_requested`; tests/console/test_incident_flow.py:121. **After:** Table `console_action` (schema/model.yaml:505; append-only triggers schema/ddl/sqlite.sql:659-665); writer src/supervisor/adapters/auth/audit.py:96 `write_action` (denied, ok and invalid outcomes, before/after hashes); in the audit pack (src/supervisor/console/auditpack.py:123); tests/console/test_rbac_matrix.py::test_other_mutating_routes_write_one_row_each, ::test_every_post_route_is_covered_by_an_audit_test, ::test_console_action_is_append_only, ::test_audit_detail_never_carries_typed_text. GET downloads are not recorded. | No generic append-only table. Not recorded: intake run, onboard start, inbox read, denied attempts, export downloads. |
| D-3 | Structured JSON logs with request id | 0 | 3 | None found: no `basicConfig`, no formatter, no request id (grep of src/). **After:** src/supervisor/ops/logging_setup.py:97-119 (JSON, request id, principal id, PII scrub `scrub` at :59); wired in src/supervisor/app.py (`configure_logging`); tests/ops/test_logging_setup.py::test_json_line_has_context_and_scrubs. `LOG_FORMAT` default is `text`; set `json` to switch. | Plain default logging. No link from a log line to a chain entry. |
| D-4 | Health and readiness endpoints | 1 | 3 | `GET /healthz` returns a static ok (src/supervisor/app.py:103-105); tests/test_app_config.py::test_healthz_and_version. Console page src/supervisor/console/health.py:143. **After:** `GET /health` and `GET /ready` (src/supervisor/app.py; src/supervisor/ops/readiness.py:33); tests/ops/test_app_ops.py::test_ready_200_without_leaks, ::test_ready_503_names_failed_checks_only, ::test_ready_503_without_runtime, ::test_health_and_healthz_unchanged. | No `/ready` (store, policy, chain, scheduler). No `/health` route. |
| D-5 | Metrics endpoint | 1 | 1 | `GET /gate/metrics` JSON (src/supervisor/gateway/routes.py:140); tests/gateway/test_routes.py::test_state_and_metrics. Console page src/supervisor/console/routes.py:632. | Gate counters only, no auth, not Prometheus format, no process metrics. |
| D-6 | Rate and size limits | 1 | 3 | Console form 64 KB (src/supervisor/console/routes.py:67, :177); OTLP body and spans (src/supervisor/config.py:231); tests/recorder/test_otlp_receiver.py::test_oversized_body_is_400. **After:** src/supervisor/ops/middleware.py:129-170 body limit (default 10 MB, 413), :233 rate limit (429, `RATE_LIMIT_ENABLED` default off, agent check path exempt); tests/ops/test_middleware.py::test_body_limit_413_by_length_and_stream, ::test_rate_limit_429_and_exemptions, ::test_rate_limit_off_by_default. | No global body limit and no rate limit (threat-model section 4). |
| D-7 | Security headers | 1 | 3 | nosniff on onboard files only (src/supervisor/console/routes.py:790). **After:** src/supervisor/ops/middleware.py:90-120; tests/ops/test_middleware.py::test_security_headers_on_api_and_console; tests/console/test_ops_headers.py. | Same as V14c. |
| D-8 | Retention and deletion of personal data (PDPL 91/2025) | 1 | 1 | `EVIDENCE_RETENTION_DAYS` sets Delta log retention only (src/supervisor/config.py:206, src/supervisor/core/schema.py:238); tests/databricks/test_schema_migration.py. **After:** src/supervisor/jobs/retention.py:49 (nulls personal columns after TTL, keeps digests and chain), classes in schema/model.yaml `retention:`, scheduler job src/supervisor/scheduler.py:417, docs/adr/D13-retention.md; tests/test_retention.py::test_job_redacts_old_keeps_new_and_chain_verifies, ::test_triggers_allow_only_nulling, ::test_databricks_report_mode. Open: Delta is report-only (bank decision), job off by default, no data-subject request path. | No deletion job. No data-subject request path. Raw capture and sign-off text never expire. The chain is append-only by design (needs ADR D13). |
| D-9 | Backup and restore | 1 | 3 | Demo snapshot and restore only (src/supervisor/demo/reset.py:75, :98); tests/demo/test_harness.py::test_reset_restores_the_snapshot. **After:** src/supervisor/ops/backup.py:91 `backup`, :193 `restore` (sha check, schema check, chain re-verify), :265 `export_delta`; CLI src/supervisor/cli.py (`backup`, `restore`, `export-delta`); tests/ops/test_backup.py::test_roundtrip_backup_wipe_restore, ::test_restore_refuses_sha_mismatch_and_newer_schema, ::test_export_delta_app_mode_fake. | No production backup of the SQLite file or signer key. No Delta export guidance. |
| D-10 | Disaster recovery drill | 0 | 2 | None found. **After:** docs/RUNBOOK.md section DR drill (SQLite mode, about 15 minutes); the steps rest on tests/ops/test_backup.py::test_roundtrip_backup_wipe_restore. Open: manual procedure; no RPO/RTO set (bank decision). | No documented RPO/RTO and no restore drill. Anchors exist (src/supervisor/evidence/anchor.py:47) but are not drilled. |
| D-11 | Schema migration | 3 | 3 | Additive migration, never drops (src/supervisor/jobs/bootstrap_schema.py:67, src/supervisor/core/schema_diff.py:157-191); tests/databricks/test_schema_migration.py, tests/test_schema.py. | No down-migration (by design). |
| D-12 | API versioning and OpenAPI | 1 | 3 | FastAPI app version (src/supervisor/app.py:62); tags `gate`, `console` (src/supervisor/gateway/routes.py:16, src/supervisor/console/routes.py:51). **After:** src/supervisor/ops/openapi.py:66-88 (tags, security schemes devHeader and databricksSSO); `/v1/gate` router plus deprecated `/gate` twin (src/supervisor/app.py); docs/api.md; tests/test_openapi.py::test_document_is_valid_openapi, ::test_every_operation_has_a_declared_tag, ::test_security_schemes, ::test_every_gate_path_has_a_v1_twin_and_old_ones_are_deprecated. | No `/v1` prefix policy for `/gate`. OTLP and health routes untagged. Dev header not a security scheme. No OpenAPI test. |
| D-13 | SDK packaging | 1 | 1 | In-process SDK (src/supervisor/gateway/sdk.py); tests/gateway/test_sdk.py; hatchling build (pyproject.toml:43). | Ships inside the app wheel. No separate client package or version contract. |
| D-14 | Performance and chaos tests | 1 | 1 | tests/perf/test_gate_latency.py::test_gate_latency_p99_under_50ms; tests/gateway/test_fail_closed.py (store down). **After:** Added: fail-mode drill (src/supervisor/demo/drill.py:86; tests/demo/test_drill.py::test_drill_passes). Open: no console or OTLP load test, no Delta fault test. | Gate on SQLite only. No console or OTLP load test. No scheduler or Delta fault test. |
| D-15 | SBOM and release signing | 1 | 1 | Release zip from `git archive HEAD`, leak sweep, lock-checked requirements (src/supervisor/release.py:234); tests/e2e/test_release.py. | No SBOM (grep `cyclonedx` finds none), no checksum file, no signature on the zip. |
| D-16 | Support bundle | 0 | 3 | None found. `scrub` exists (src/supervisor/preflight.py:74) and can be reused. **After:** src/supervisor/ops/support.py:208 `build_support_bundle` (redacted settings :67, log tail :107, PII masked); CLI `support-bundle` (src/supervisor/cli.py); tests/ops/test_support_bundle.py::test_bundle_seeded_store_logs_masked, ::test_url_query_stripped, ::test_non_empty_dir_needs_force. | No CLI to collect version, scrubbed settings, health and logs. |
| D-17 | Tenancy / business-unit scoping | 0 | 0 | None found. Only an `owner_team` field (schema/model.yaml:41), not used as a filter. | All reviewers see all agents and cases. |
| D-18 | i18n completeness (vi + en) | 3 | 3 | src/supervisor/console/i18n.py:10, :879; tests/console/test_i18n.py::test_both_dictionaries_have_the_same_keys, ::test_every_literal_key_in_templates_exists. | Case file renderers and some error messages are English only. |
| D-19 | Accessibility basics (WCAG 2.2 AA subset) | 1 | 1 | `lang` attribute, nav labels, `aria-live` flash, focus ring (src/supervisor/console/templates/base.html:2, :20, :58; src/supervisor/console/static/console.css:80); `role=alert` in `message_html` (src/supervisor/console/routes.py:113). | No skip link, no contrast check, no automated test. |
| D-20 | Documentation for operators | 1 | 2 | docs/RUNBOOK.md, docs/BANK_DEPLOY_GUIDE.md, docs/databricks-prereqs.md. **After:** Added: docs/RUNBOOK.md section 14 (operations), Retention (PDPL), Backup/restore/support bundle, DR drill; docs/api.md. Docs cannot be tested, so the row stays 2. | Docs are not testable. No log, backup, retention or incident-response sections (RUNBOOK sections 1-13). |
| D-21 | Documentation for second-line reviewers | 1 | 1 | docs/console.md (roles, case states), docs/threat-model.md, docs/metrics.md. **After:** Added: docs/console.md role matrix (kept equal to code by tests/test_rbac.py::test_docs_table_equals_matrix_markdown). Still no model-risk reviewer guide. | No guide for model-risk or compliance reviewers: how to read evidence, control mapping, limits. |

Section D total: before 21 / 63, after 44 / 63 (21 rows).

## 6. Totals

| Section | Rows | Before | Max | After |
|---|---|---|---|---|
| A ISO/IEC 42001:2023 | 42 | 69 | 126 | 71 |
| B NIST AI RMF 1.0 | 23 | 34 | 69 | 36 |
| C OWASP ASVS 4.0.3 Level 1 (subset) | 13 | 21 | 39 | 27 |
| D Operations checklist | 21 | 21 | 63 | 44 |
| Overall | 99 | 145 | 297 | 178 |

Overall before: **145 / 297** (49 percent). Overall after: **178 / 297** (60 percent).

## 7. Ranked gap list

Every row with a score of 0, 1 or 2. Risk 1-3 (3 = high). Effort 1-3 (1 = small effort).
Rule: sort by Risk descending, then Effort ascending, then Before score ascending, then document order. Rank 1 is first to fix. Ranks use the before state. Status is the state after Part B.
Plan: `WP18 Part B (item n)` for the ten planned items, else `BACKLOG: <reason>`.

Part B items: (1) role matrix; (2) console action audit table; (3) JSON logs; (4) `/health` and `/ready`; (5) retention and deletion job; (6) support-bundle CLI; (7) security headers, body limit, rate limit; (8) OpenAPI tags, version prefix, security scheme; (9) backup/restore CLI and Delta export guidance; (10) fail-mode drill script.

| Rank | ID | Before | After | Risk | Effort | Gap (short, before) | Plan | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | D-3 | 0 | 3 | 3 | 1 | Plain default logging. No link from a log line to a chain entry. | WP18 Part B (item 3) | closed (score 3) |
| 2 | V7b | 1 | 3 | 3 | 1 | No logging config: plain text, no request id, no principal id, no JSON. | WP18 Part B (item 3) | closed (score 3) |
| 3 | V14c | 1 | 3 | 3 | 1 | No CSP, X-Frame-Options, Referrer-Policy or Cache-Control app-wide (grep finds none). | WP18 Part B (item 7) | closed (score 3) |
| 4 | D-4 | 1 | 3 | 3 | 1 | No `/ready` (store, policy, chain, scheduler). No `/health` route. | WP18 Part B (item 4) | closed (score 3) |
| 5 | D-6 | 1 | 3 | 3 | 1 | No global body limit and no rate limit (threat-model section 4). | WP18 Part B (item 7) | closed (score 3) |
| 6 | D-7 | 1 | 3 | 3 | 1 | Same as V14c. | WP18 Part B (item 7) | closed (score 3) |
| 7 | A-6.1 | 1 | 1 | 3 | 2 | A proposal per agent only. No risk register, no likelihood/impact scale, no review date. | BACKLOG: out of phase (WP14 compliance advisory) | BACKLOG: out of phase (WP14 compliance advisory) |
| 8 | A.3.2 | 1 | 3 | 3 | 2 | Roles are scattered across modules and not enforced on every action (D-1). | WP18 Part B (item 1) | closed (score 3) |
| 9 | GV-2 | 1 | 3 | 3 | 2 | Role matrix not enforced everywhere (D-1). | WP18 Part B (item 1) | closed (score 3) |
| 10 | MS-2b | 1 | 1 | 3 | 2 | No fault drill across components. OTLP and gate have no caller auth. | WP18 Part B (item 10) | BACKLOG: needs bank decision (agent ingress credentials, OTLP auth) |
| 11 | MS-2c | 1 | 1 | 3 | 2 | No retention or deletion of personal columns (D-8). Raw capture has no expiry. | WP18 Part B (item 5) | BACKLOG: needs bank decision (Delta appendOnly vs. deletion, ADR D13) |
| 12 | V2 | 1 | 1 | 3 | 2 | Laptop has no real authentication (dev header, banner). `/gate/*` and `/v1/traces` have no caller auth (SECURITY.md Known gaps). | WP18 Part B (item 1) | BACKLOG: needs bank decision (laptop identity, agent credentials at the gate) |
| 13 | V4 | 1 | 3 | 3 | 2 | `/gate/{pause,resume,quarantine,release}` and `/gate/metrics` have no role check (src/supervisor/gateway/routes.py:76-85, :112-140).... | WP18 Part B (item 1) | closed (score 3) |
| 14 | V13 | 1 | 1 | 3 | 2 | No auth, no rate limit, no version prefix, no size limit on `/gate/*`. | WP18 Part B (item 7) | BACKLOG: needs bank decision (agent ingress credentials) |
| 15 | D-1 | 1 | 3 | 3 | 2 | Not one module. Console GETs use `_view()` (any role passes, src/supervisor/console/routes.py:199). `/gate/*` POSTs trust a principal... | WP18 Part B (item 1) | closed (score 3) |
| 16 | D-2 | 1 | 3 | 3 | 2 | No generic append-only table. Not recorded: intake run, onboard start, inbox read, denied attempts, export downloads. | WP18 Part B (item 2) | closed (score 3) |
| 17 | D-9 | 1 | 3 | 3 | 2 | No production backup of the SQLite file or signer key. No Delta export guidance. | WP18 Part B (item 9) | closed (score 3) |
| 18 | A-6.1b | 0 | 0 | 3 | 3 | No impact-assessment record, template or evidence link. Needs a bank method (PDPL DPIA, Decision 33). | BACKLOG: out of phase (WP14 compliance advisory) | BACKLOG: out of phase (WP14 compliance advisory) |
| 19 | A-8.4 | 0 | 0 | 3 | 3 | Same gap as A-6.1b. No re-assessment trigger on change. | BACKLOG: out of phase (WP14 compliance advisory) | BACKLOG: out of phase (WP14 compliance advisory) |
| 20 | A.5 | 0 | 0 | 3 | 3 | Same as A-6.1b. | BACKLOG: out of phase (WP14 compliance advisory) | BACKLOG: out of phase (WP14 compliance advisory) |
| 21 | D-8 | 1 | 1 | 3 | 3 | No deletion job. No data-subject request path. Raw capture and sign-off text never expire. The chain is append-only by design (needs ADR... | WP18 Part B (item 5) | BACKLOG: needs bank decision (Delta appendOnly vs. deletion, data-subject path) |
| 22 | D-16 | 0 | 3 | 2 | 1 | No CLI to collect version, scrubbed settings, health and logs. | WP18 Part B (item 6) | closed (score 3) |
| 23 | A-7.1 | 1 | 1 | 2 | 1 | Checks the runtime only. No capacity or staffing view. Console health is not a probe endpoint. | WP18 Part B (item 4) | BACKLOG: needs bank decision (capacity limits) |
| 24 | D-12 | 1 | 3 | 2 | 1 | No `/v1` prefix policy for `/gate`. OTLP and health routes untagged. Dev header not a security scheme. No OpenAPI test. | WP18 Part B (item 8) | closed (score 3) |
| 25 | D-20 | 1 | 2 | 2 | 1 | Docs are not testable. No log, backup, retention or incident-response sections (RUNBOOK sections 1-13). | WP18 Part B (item 9) | improved to 2; remaining BACKLOG: needs bank decision (bank-specific procedures) |
| 26 | D-21 | 1 | 1 | 2 | 1 | No guide for model-risk or compliance reviewers: how to read evidence, control mapping, limits. | BACKLOG: out of phase (WP19 judge MRM) | BACKLOG: out of phase (WP19 judge MRM) |
| 27 | D-10 | 0 | 2 | 2 | 2 | No documented RPO/RTO and no restore drill. Anchors exist (src/supervisor/evidence/anchor.py:47) but are not drilled. | WP18 Part B (item 9) | improved to 2; remaining BACKLOG: needs bank decision (RPO/RTO and drill owner) |
| 28 | A-5 | 1 | 1 | 2 | 2 | The AI policy statement and management commitment are a bank process. Policy deploy is not a chain record (threat-model section 4). | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 29 | A-6.2 | 1 | 1 | 2 | 2 | Metrics exist. No stored objective with owner, target and date. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 30 | A-9.2 | 1 | 1 | 2 | 2 | Pack exists. Audit programme, schedule and findings log are a bank process. Console action audit is partial (D-2). | WP18 Part B (item 2) | BACKLOG: needs bank decision (audit programme) |
| 31 | A.2 | 1 | 1 | 2 | 2 | No policy review cycle or approval record. Policy deploy not on the chain. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 32 | A.8.1 | 1 | 1 | 2 | 2 | No regulator or customer notice template. SBV 24-hour clock fields come in WP19. | BACKLOG: out of phase (WP19 judge MRM) | BACKLOG: out of phase (WP19 judge MRM) |
| 33 | A.10.1 | 1 | 1 | 2 | 2 | No supplier register, no vulnerability match, no SBOM (WP17 plans CycloneDX). | BACKLOG: out of phase (WP17 assurance packs / SBOM) | BACKLOG: out of phase (WP17 assurance packs / SBOM) |
| 34 | GV-1 | 1 | 1 | 2 | 2 | Legal requirements are not mapped in product until WP13. | BACKLOG: out of phase (WP13 RegKB) | BACKLOG: out of phase (WP13 RegKB) |
| 35 | GV-6 | 1 | 1 | 2 | 2 | No third-party risk policy in product. No SBOM. | BACKLOG: out of phase (WP17 assurance packs / SBOM) | BACKLOG: out of phase (WP17 assurance packs / SBOM) |
| 36 | MP-4 | 1 | 1 | 2 | 2 | No vulnerability data, no SBOM. | BACKLOG: out of phase (WP17 assurance packs / SBOM) | BACKLOG: out of phase (WP17 assurance packs / SBOM) |
| 37 | MS-4 | 1 | 1 | 2 | 2 | No live agreement metric from sign-offs (WP19). | BACKLOG: out of phase (WP19 judge MRM) | BACKLOG: out of phase (WP19 judge MRM) |
| 38 | MG-2 | 1 | 1 | 2 | 2 | Pause and quarantine are tested (tests/gateway/test_state.py). No retire workflow. Scored 1: the retire path is missing. | BACKLOG: out of phase (WP19 judge MRM) | BACKLOG: out of phase (WP19 judge MRM) |
| 39 | MG-3 | 1 | 1 | 2 | 2 | No monitoring of vendor change. Model version recorded per verdict only. | BACKLOG: out of phase (WP19 judge MRM) | BACKLOG: out of phase (WP19 judge MRM) |
| 40 | MG-4 | 1 | 1 | 2 | 2 | Incident communication plan and drill missing. No support bundle. | WP18 Part B (item 6) | BACKLOG: needs bank decision (incident communication plan) |
| 41 | V8 | 1 | 1 | 2 | 2 | No `Cache-Control` on console pages. No retention or deletion. Sign-off statements stored verbatim. | WP18 Part B (item 5) | BACKLOG: needs bank decision (Delta retention, sign-off text expiry) |
| 42 | V9 | 1 | 1 | 2 | 2 | TLS is the platform's job on the App. No HSTS. Not tested here. | WP18 Part B (item 7) | BACKLOG: needs infrastructure (TLS at the platform proxy) |
| 43 | V14b | 1 | 1 | 2 | 2 | No SBOM, no vulnerability match. | BACKLOG: out of phase (WP17 assurance packs / SBOM) | BACKLOG: out of phase (WP17 assurance packs / SBOM) |
| 44 | D-13 | 1 | 1 | 2 | 2 | Ships inside the app wheel. No separate client package or version contract. | BACKLOG: out of phase (WP15 integration advisory) | BACKLOG: out of phase (WP15 integration advisory) |
| 45 | D-14 | 1 | 1 | 2 | 2 | Gate on SQLite only. No console or OTLP load test. No scheduler or Delta fault test. | WP18 Part B (item 10) | BACKLOG: needs infrastructure (load and Delta fault test rig) |
| 46 | D-15 | 1 | 1 | 2 | 2 | No SBOM (grep `cyclonedx` finds none), no checksum file, no signature on the zip. | BACKLOG: out of phase (WP17 assurance packs / SBOM) | BACKLOG: out of phase (WP17 assurance packs / SBOM) |
| 47 | A.10.2 | 2 | 2 | 2 | 2 | The remote-allowed path is tested (tests/test_app_config.py:96); the refusal path was not confirmed in tests. No vendor terms record. | BACKLOG: out of phase (WP19 judge MRM) | BACKLOG: out of phase (WP19 judge MRM) |
| 48 | GV-5 | 0 | 0 | 2 | 3 | No channel for affected parties or feedback intake. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 49 | MP-5 | 0 | 0 | 2 | 3 | No impact record. Fairness monitor is under MS-2. | BACKLOG: out of phase (WP14 compliance advisory) | BACKLOG: out of phase (WP14 compliance advisory) |
| 50 | D-17 | 0 | 0 | 2 | 3 | All reviewers see all agents and cases. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 51 | A.3.3 | 1 | 1 | 1 | 1 | No in-product concern channel. The bank fills the contact. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 52 | V3 | 1 | 1 | 1 | 1 | No `Secure` flag, no expiry, no logout. Platform session on the App. Not tested. | WP18 Part B (item 7) | BACKLOG: needs bank decision (Secure cookie and session expiry follow the TLS set-up) |
| 53 | D-19 | 1 | 1 | 1 | 1 | No skip link, no contrast check, no automated test. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 54 | A.6.5 | 2 | 2 | 1 | 1 | No test found that asserts the rendered profile text. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 55 | MP-1 | 2 | 2 | 1 | 1 | Rendered content not asserted by tests. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 56 | MS-2e | 2 | 2 | 1 | 1 | No test asserts explanation content. Judge reasoning is advisory text. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 57 | A-4 | 1 | 1 | 1 | 2 | Tool scope is written. AIMS scope and interested-party list are a bank process. No in-product record. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 58 | A-7.3 | 1 | 1 | 1 | 2 | No awareness material for agent owners or reviewers. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 59 | A-9.3 | 1 | 1 | 1 | 2 | No periodic management-review report or sign-off record. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 60 | A-10.2 | 1 | 1 | 1 | 2 | No improvement log. WP19 adds judge re-validation triggers. | BACKLOG: out of phase (WP19 judge MRM) | BACKLOG: out of phase (WP19 judge MRM) |
| 61 | A.4.2 | 1 | 1 | 1 | 2 | No data-resource register beyond the onboarding profile. | BACKLOG: out of phase (WP14 compliance advisory) | BACKLOG: out of phase (WP14 compliance advisory) |
| 62 | A.4.4 | 1 | 1 | 1 | 2 | No capacity record or limits. Single process by design. | WP18 Part B (item 4) | BACKLOG: needs bank decision (capacity limits) |
| 63 | A.6.1 | 1 | 1 | 1 | 2 | Covers the guard-rail design only. Requirements of the supervised system are the bank's. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 64 | A.7.2 | 1 | 1 | 1 | 2 | Trace coverage only. Quality of training data is a bank process. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 65 | A.7.3 | 1 | 1 | 1 | 2 | No data lineage for training or knowledge data. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 66 | A.9.1 | 1 | 1 | 1 | 2 | No acceptable-use policy or user-facing statement. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 67 | GV-4 | 1 | 1 | 1 | 2 | Culture is a bank process. No feedback or training prompts. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 68 | MP-3 | 1 | 1 | 1 | 2 | No cost or benefit record per agent. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 69 | D-5 | 1 | 1 | 1 | 2 | Gate counters only, no auth, not Prometheus format, no process metrics. | BACKLOG: needs infrastructure | BACKLOG: needs infrastructure |
| 70 | A-7.2 | 0 | 0 | 1 | 3 | No training material or competence record. Bank process. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 71 | A.4.5 | 0 | 0 | 1 | 3 | No staffing or skills view. Bank process. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |
| 72 | GV-3 | 0 | 0 | 1 | 3 | Organisational duty. The tool has nothing to evidence. | BACKLOG: needs bank decision | BACKLOG: needs bank decision |

72 rows were open before. 14 are closed (score 3) after Part B. 2 improved but not closed. Rows still below 3: 58.

## 8. Not in scope of a tool

These are organisational duties. The tool can hold records for them. It cannot do them.

- AI policy, management commitment and resourcing (ISO 42001 clause 5, A.2).
- Competence, training, workforce diversity and risk culture (clause 7.2, GV-3, GV-4).
- AIMS scope, interested-party list, management review and internal audit programme (clauses 4, 9.2, 9.3).
- Impact assessment method and DPIA under PDPL (clause 6.1, A.5, MP-5).
- Supplier and model-vendor due diligence, contracts, exit plans (A.10, GV-6, MG-3).
- Data governance for training and knowledge data (A.7).
- Regulator and customer incident notices, SBV 24-hour report (A.8).
- Key custody (KMS or HSM), network controls, TLS termination, platform patching.
- Choice of retention period and lawful basis for personal data.
