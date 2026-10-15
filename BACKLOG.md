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
| Schema migration step (ALTER TABLE ADD COLUMNS for existing SQLite/Delta tables) | WP10: bootstrap_schema must diff live columns against model.yaml and add missing ones |
| OTLP receiver authentication (any caller can write spans for any agent id) | WP8 Principal adapters; per-agent ingest tokens |
| Spool directory on a durable path on the Databricks App (/tmp is wiped) | WP10 runbook + settings default to a UC Volume path |
| Ingest job lock against concurrent runs | WP7 scheduler owns the single ingest run |
| Masking recall measured on real Vietnamese text (synthetic set scores 1.000 by construction) | Bank supplies a labelled sample; a masking miss is an incident |
| Payee cooling-period rule (new payee then transfer within N minutes) | Needs the `add_payee` result (`payee_id`) as a fact in the gate context; add a result-fact channel to the gateway |
| FactSource adapter to the bank's system of record (documents on file, approved payees) | Demo uses the in-memory BankWorld; the app has no fact source, so CRD-01 fails closed outside the demo |
| Key id on `agent_event` args hash rows; HMAC for grouping keys in `args_masked` | Small gateway/recorder follow-up after WP7 |
| Judge retries only on timeouts; `--split dev` default in the eval CLI | Reviewer suggestions from WP5, low priority |
| Verdict table `score` float column retained for compatibility | WP7 adds `score_bp`; drop `score` at the first schema reset before any live data |
| Red-team pack vs default rules: credit_prequal launch is NO-GO on false alarms (benign cases decide without reading the application), customer_service NO-GO on catch rate | Decide per agent whether the pack or the default rules change; use the bank golden set when available |
| App service principal needs USE CATALOG / USE SCHEMA grants; dev target app-name prefix vs 30-char limit; /Volumes mount in the App container | Confirm on the live workspace (WP10 live kit) |
| Judge models in App mode stay mocks until JUDGE_* settings name the bound serving endpoint | Owner fills FILL-ME values; set JUDGE_T1_MODEL/JUDGE_T2_MODEL |
| Scheduler lease renewal during very long jobs; paging in monitor read_range | WP7 follow-up |
| Monitors open cases via monitors/common.open_case, console via cases/service | Unify on cases/service in the next refactor |
| WP18: caller credential on agent ingress `/gate/check`, `/v1/gate/check`, `/v1/traces` (ASVS V2/V13) | Needs bank decision: per-agent credentials or a broker (extends the OTLP item above) |
| WP18: turn on `API_RBAC_ENABLED`, `RATE_LIMIT_ENABLED`, `LOG_FORMAT=json` for the bank deployment | Needs bank decision (off / text by default to keep phase-1 behaviour) |
| WP18: retention on Delta append-only tables is report-only; data-subject request path; masked excerpts in chain payloads; retention of sign-off text and case summaries; final day counts (ADR D13) | Needs bank decision |
| WP18: RPO / RTO, backup retention, DR drill owner and schedule (RUNBOOK FILL-ME) | Needs bank decision |
| WP18: Prometheus-format metrics endpoint; console and OTLP load tests; Delta fault rig for the drill | Needs infrastructure (scraper, load host, live workspace) |
| WP18: TLS, HSTS, `Secure` cookies, session expiry (ASVS V3/V9) | Needs infrastructure: follows the platform proxy; `HSTS_ENABLED` exists |
| WP18: tenancy / business-unit scoping of agents and cases | Needs bank decision |
| WP18: accessibility audit (skip link, contrast, automated WCAG 2.2 check) | Needs bank decision on the target level and tool |
| WP18: AI risk register and impact assessment (ISO 42001 6.1, A.5, A.8.4; NIST MP-5) | Out of phase: WP14 compliance advisory |
| WP18: SBOM, release signing, vulnerability match (A.10, GV-6, MP-4, ASVS V14.2) | Out of phase: WP17 assurance packs |
| WP18: judge re-validation, judge-vs-human agreement, Retire stage, second-line reviewer guide | Out of phase: WP19 judge MRM |
| WP18: separate gate SDK package with a version contract | Out of phase: WP15 integration advisory |
| WP18: competence, training, management review, internal audit programme (ISO 42001 7.2, 9.2, 9.3) | Bank process; the tool supplies evidence only |
