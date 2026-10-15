# Backlog (items removed from plan v1 and extras found during the build)

| Item | Returns when |
|---|---|
| Docker Compose dev stack (Postgres, MLflow server) | A Linux/Mac dev machine with Docker is the main dev target |
| Lakebase for mutable state | The workspace exposes Lakebase and the owner has rights to create an instance |
| Databricks Workflows jobs | The workspace allows job workloads for this user |
| Model Serving pyfunc host for the gateway | Endpoint creation rights exist and spike B shows the App adds too much latency |
| React/Vite console | A richer UI is needed and Node is available where the build runs |
| Presidio as default masker | spaCy model wheels are on Nexus; until then `presidio` is an optional extra |
| MLflow as primary trace path | MLflow ≥ 3.14 confirmed in the workspace with CREATE TABLE in a schema |
| HSM/KMS notary key, bank WORM anchor | Bank key custody and storage decisions |
| SIEM / ITSM / pager live adapters | Bank endpoint owners named |
| YAML → Cedar policy compiler (D11) | H1 2027 when policies need formal analysis |
| gitleaks binary for repo scrubbing | Bank supplies an approved binary; regex scrubber until then |
| OTLP receiver authentication (any caller can write spans for any agent id) | WP8 Principal adapters; per-agent ingest tokens |
| Masking recall measured on real Vietnamese text (synthetic set scores 1.000 by construction) | Bank supplies a labelled sample; a masking miss is an incident |
| Payee cooling-period rule (new payee then transfer within N minutes) | Needs the `add_payee` result (`payee_id`) as a fact in the gate context; add a result-fact channel to the gateway |
| FactSource adapter to the bank's system of record (documents on file, approved payees) | Demo uses the in-memory BankWorld; the app has no fact source, so CRD-01 fails closed outside the demo |
| Judge retries only on timeouts; `--split dev` default in the eval CLI | Reviewer suggestions from WP5, low priority |
| Verdict table `score` float column retained for compatibility | WP7 adds `score_bp`; drop `score` at the first schema reset before any live data |
| Red-team pack vs default rules: credit_prequal launch is NO-GO on false alarms (benign cases decide without reading the application), customer_service NO-GO on catch rate | Decide per agent whether the pack or the default rules change; use the bank golden set when available |
| App service principal needs USE CATALOG / USE SCHEMA grants; dev target app-name prefix vs 30-char limit; /Volumes mount in the App container | Confirm on the live workspace (WP10 live kit) |
| Judge models in App mode stay mocks until JUDGE_* settings name the bound serving endpoint | Owner fills FILL-ME values; set JUDGE_T1_MODEL/JUDGE_T2_MODEL |
| Scheduler lease renewal during very long jobs; paging in monitor read_range | WP7 follow-up |
| Monitors open cases via monitors/common.open_case, console via cases/service | Unify on cases/service in the next refactor |
| WP18: caller credential on agent ingress `/gate/check`, `/v1/gate/check`, `/v1/traces` (ASVS V2/V13) | Needs bank decision: per-agent credentials or a broker (extends the OTLP item above) |
| WP18: turn on `API_RBAC_ENABLED` (now covers only the read routes `/gate/agents/{id}/state` and `/gate/metrics`; control routes always enforce RBAC since W3-sec), `RATE_LIMIT_ENABLED`, `LOG_FORMAT=json` for the bank deployment | Needs bank decision (off / text by default to keep phase-1 behaviour) |
| WP18: retention on Delta append-only tables is report-only; data-subject request path; masked excerpts in chain payloads; retention of sign-off text and case summaries; final day counts (ADR D13) | Needs bank decision |
| WP18: RPO / RTO, backup retention, DR drill owner and schedule (RUNBOOK FILL-ME) | Needs bank decision |
| WP18: Prometheus-format metrics endpoint; console and OTLP load tests; Delta fault rig for the drill | Needs infrastructure (scraper, load host, live workspace) |
| WP18: TLS, HSTS, `Secure` cookies, session expiry (ASVS V3/V9) | Needs infrastructure: follows the platform proxy; `HSTS_ENABLED` exists |
| WP18: tenancy / business-unit scoping of agents and cases | Needs bank decision |
| WP18: accessibility audit (skip link, contrast, automated WCAG 2.2 check) | Needs bank decision on the target level and tool |
| Release signing of the zip and the wheelhouse (ASVS V14.2) | Bank key custody decision; SBOM and OSV match now ship as assurance packs (WP17) |
| WP18: competence, training, management review, internal audit programme (ISO 42001 7.2, 9.2, 9.3) | Bank process; the tool supplies evidence only |
| OTLP receiver accepts JSON only; the Python OTLP exporter sends protobuf, so Python agents go through a Collector today | Add protobuf decoding (pure-Python `opentelemetry-proto` has cp311 wheels) or document the Collector as the supported path |
| Prefilter typo evasions (57 % caught) and two code-switch cases | Fuzzy matching (edit distance on the stripped form) with a false-positive budget |
| Masker residuals: bare 10-15 digit runs (timestamps) are over-masked as accounts; digits glued to letters (`sdt0912345678`) and `+84 912 345 678` leak; email domains with `_` or non-ASCII letters | Extend vn_regex-3 with the bank's labelled sample (see "Masking recall" above) |
| `licence_allowlist` fails on this host: 58 % of installed packages have no readable licence metadata | Bank Nexus wheels with metadata, or an allow-list file per release (`ASSURANCE_LICENCE_ALLOW`) |
| Judge-gate packs ship with fewer than 50 synthetic items (`halueval_vi` 40, `perturbation_vi` 20), so a real judge cannot pass `ASSURANCE_JUDGE_MIN_ITEMS=50` without bank data | Bank golden set, or a deliberate lower `ASSURANCE_JUDGE_MIN_ITEMS` for the first run |
| PAY-03 daily cap 150M VND and the payments manifest 300M exceed Circular 53/2026 Art. 5(1)(g) (100M per day per individual); the compliance matrix shows the gap | Owner decision: lower the baseline policy or document the exception |
| Retire has no console button (`agent.retire` permission); incident urgency cannot be re-classed by a reviewer; "15 days" read as calendar days | Bank decisions on process; small console follow-up |
| OTel GenAI attributes with no `agent_event` column: provider, request/response model, token usage, finish reasons, conversation id, tool call id | Add columns at the next schema reset; map in `recorder/semconv.py` |
| OpenAI Guardrails checks (MIT) were in plan v1 as "copy code" and were not ported; Prompt Guard 2 adapter (flagged, off) was not built | Port the secrets and PII regex set behind a flag; Prompt Guard only if the bank accepts the Llama licence |
| Unverified review notes: `audited` does not catch `CancelledError`; `onboard_runs.artefact_path` has no `resolve()` for planted symlinks | Reproduce, then fix in the next ops pass |
| Compliance advisor counts a monitor as present when it is planned, not when its runtime flag is on (`FAIRNESS_ENABLED` etc.) | Read deployment settings into the product facts |
| Onboard eval: held-out set is no longer blind after the post-blind fixes | Write a fresh blind set (new repos, worker does not read the analyser) before quoting the gates externally |
| `model_version` is the model tag; include the endpoint-reported digest when available | A model endpoint that reports a digest or revision |
