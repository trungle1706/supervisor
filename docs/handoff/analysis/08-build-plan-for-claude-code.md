# 08 · Build plan for Claude Code: one repo, two targets

Date: 2026-10-14. Reader: Claude Code (the builder) and the project owner. Replaces the dated week plan in `06` with a work-package plan that has no bank dependency. Design decisions D1–D12 (06 §3) still apply.

## 1. Goal

Build the `supervisor` repository so that, when the owner copies it to a work computer, one command runs the full product as a local web app, and one command deploys the same code to a Databricks workspace. Bank-specific facts (region, IAM, SIEM, ITSM, keys, legal rulings) are configuration and adapters, not code paths. Nothing in the build waits for the bank.

```
                 ┌──────────────── same Python core, same console ────────────────┐
                 │  gateway · recorder · judge · evidence · monitors · onboard    │
                 └───────────┬────────────────────────────────┬───────────────────┘
          local target       │                                │      Databricks target
   docker compose up         ▼                                ▼      databricks bundle deploy
   Postgres · MLflow server · FastAPI · React        UC Delta · Lakebase · MLflow 3 traces in UC
   mock judge or any OpenAI-compatible LLM           Foundation Model APIs · Databricks App · Jobs
```

## 2. Rules for the build

| # | Rule | Why |
|---|---|---|
| R1 | Ports and adapters. The core never imports `databricks`, `pyspark` or `psycopg` directly. It calls a port; an adapter implements it. | Two targets, one code path |
| R2 | Every table has one DDL in `schema/` with two dialects (Postgres, Databricks SQL) generated from one YAML model. | No drift between targets |
| R3 | Every job is a CLI entry point (`python -m supervisor.jobs.<name>`). Databricks Workflows call the same entry point. | No notebooks |
| R4 | No Spark in the core. Jobs use SQL + pandas/polars. Spark is an optional adapter for scale. | Runs on a laptop |
| R5 | Offline-first. `make demo` works with no network and no LLM key (deterministic mock judge, labelled on screen). | Work-computer firewalls |
| R6 | Never fake the gate block, the pause switch or the chain break. Mocks are allowed for LLM judges only, and are labelled. | Demo honesty (04) |
| R7 | Pinned everything: `uv.lock`, `package-lock.json`, committed console `dist/`, optional `wheelhouse/`. | Copy and run with no install step |
| R8 | Synthetic data only. Vietnamese synthetic customers (name, CCCD, phone, account) from a generator in the repo. | PDPL; demo on any machine |
| R9 | Contract tests run on the local adapter always, and on the Databricks adapter when `DATABRICKS_HOST` is set. | One test suite, two targets |
| R10 | Each work package ends with a Definition of Done (DoD) that a test proves. No DoD, no merge. | Progress you can check |

## 3. Target matrix: one component, two adapters

| Component | Port | Local adapter | Databricks adapter | Status |
|---|---|---|---|---|
| Append-only tables (events, verdicts, chain, metrics) | `TableStore` | Postgres (SQLAlchemy) | UC Delta via `databricks-sql-connector` + SQL warehouse | build now |
| Mutable workflow (cases, sign-offs, agent state) | `StateStore` | Postgres | Lakebase (Postgres protocol, same code) | build now |
| Trace capture | `TraceSource` | MLflow 3 tracking server (SQLite backend) | MLflow 3 → UC trace tables (needs MLflow ≥ 3.14 in workspace, verify) | build now |
| OTel ingest | `TraceSource` | OTLP/HTTP receiver in FastAPI | same receiver as Databricks App | build now |
| LLM for judges and agents | `ChatModel` | OpenAI-compatible URL (Ollama, vLLM, OpenAI, Anthropic via shim) or `MockJudge` | Foundation Model APIs (OpenAI-compatible endpoint) | build now |
| Gateway host | — | FastAPI under uvicorn | Databricks App (FastAPI) **or** Model Serving pyfunc wrapper; pick after latency spike B | build both hosts (thin) |
| Console host | — | FastAPI + React `dist/` | Databricks App with SSO headers | build now |
| Auth | `Principal` | dev header `X-Dev-User`, local users file | `X-Forwarded-User` / access token from the App proxy; UC groups | build now |
| Secrets | `Secrets` | `.env` | Databricks secret scope | build now |
| Scheduler | — | APScheduler in one process or `make jobs` | Workflows jobs in `databricks.yml` | build now |
| Signing key for chain head | `Signer` | local Ed25519 key file | secret scope key; HSM/KMS later | build now; HSM later |
| Anchor target | `Anchor` | write-once directory with hash receipts | UC Volume; bank WORM store later | build now; WORM later |
| Repo reader for Onboard | `RepoReader` | local git path | Databricks Repos / Git folder via SDK | build now |
| Workspace inventory for Onboard | `WorkspaceReader` | fixtures JSON | `databricks-sdk`: Apps, serving endpoints, UC lineage | fixtures now; live later |
| Alerts | `Notifier` | console inbox + log file | webhook (Teams/email); SIEM/ITSM/pager adapters = stubs | stubs now |
| Masking | `Masker` | Presidio + VN recognisers | same, as a Python UDF in the ingest job | build now |

## 4. Repository layout

```
supervisor/
  README.md  RUNBOOK.md  SECURITY.md  CONTRIBUTING.md
  pyproject.toml  uv.lock  Makefile  docker-compose.yml  .env.example
  databricks.yml                      # DAB: targets dev / uat / prod
  resources/                          # DAB resources: jobs, app, schema bootstrap, (serving)
  schema/                             # model.yaml → ddl/postgres.sql, ddl/databricks.sql, alembic/
  src/supervisor/
    core/        models.py (pydantic), canonical.py (hash spec), states.py, ports.py
    adapters/    postgres/, databricks/, mlflow_local/, mlflow_uc/, llm/, secrets/, auth/
    gateway/     rules/, policy_schema.py, engine.py, state_machine.py, hosts/{fastapi,pyfunc}.py, sdk.py, mcp_proxy.py
    recorder/    normalise.py (MLflow, OTLP, proxy log → agent_event), otlp_receiver.py, masking/
    judge/       prompts/, tier1.py, tier2.py, router.py (family check), scorers.py (MLflow), eval/
    evidence/    chain.py, signer.py, anchor.py, verify.py (CLI), casefile/ (templates VN+EN)
    monitors/    drift.py, fairness.py, quality.py, multiagent.py, oversight.py
    onboard/     discover.py, understand.py, plan.py, instrument.py, launch.py, catalogue/, templates/
    console/     api/ (FastAPI), web/ (React + Vite, dist/ committed)
    jobs/        __main__ entry points: ingest, drift, anchor, metrics, redteam, bootstrap_schema
    demo/        seed.py, inject.py, reset.py, replay.py, runbook.md
  agents/        customer_service/  credit_prequal/  payments/  common/  redteam/incidents.jsonl
  data/          synthetic generator (vi_VN), golden set skeleton, fixtures
  tests/         unit/  contract/ (both adapters)  e2e/ (demo runbook)  perf/ (gate latency)
  docs/          adr/ (D1–D12), architecture.md, threat-model.md, bank-integration.md, databricks-prereqs.md
```

## 5. Work packages in build order

Effort is in Claude Code sessions (one session ≈ one focused build run with tests green at the end). Order is dependency order; WP6 comes early because every later module writes to the chain.

| WP | Name | Builds | Definition of Done | Sessions |
|---|---|---|---|---|
| 0 | Skeleton + tooling | `uv` project, ruff, pytest, pre-commit, Makefile, docker-compose (postgres, mlflow, gateway, console, agents), DAB skeleton with three targets, ADRs D1–D12, `.env.example`, CI workflow | `make check` green on empty repo; `docker compose up` starts all services; `databricks bundle validate` passes offline | 1 |
| 1 | Core + schema | Pydantic models for agent, version, event, rule, verdict, case, chain entry; canonical JSON + hash spec; `schema/model.yaml` → both DDLs; Postgres adapter; Databricks SQL adapter; Alembic | Contract tests pass on Postgres; same tests skip-not-fail without Databricks; hash spec has fixed test vectors | 1–2 |
| 2 | Synthetic data + three agents + attack set | vi_VN synthetic customers, accounts, tickets; agents customer_service, credit_prequal, payments with tools and MLflow tracing; `ChatModel` port with OpenAI-compatible + mock; `redteam/incidents.jsonl` (≥ 120 cases, OWASP agentic + FinVault taxonomy, author ≠ rule author) | Each agent completes 20 scripted tasks locally with traces visible in MLflow; attack set validates against its JSON schema | 2 |
| 3 | Gateway | Policy YAML schema + loader; Tier 0a sync rules (allow-list, limits, stateful aggregates, permissions); Tier 0b async (masking, injection classifier port); agent state machine + fail mode per rule; FastAPI host; MCP proxy mode; `@supervised_tool` SDK; pyfunc host wrapper; latency bench | All 4 demo incidents blocked or paused by real rules; p50/p95/p99 published from `tests/perf`; fail-closed proven by killing the policy store mid-test | 2 |
| 4 | Recorder | MLflow span → `agent_event` normaliser; OTLP receiver; proxy-log reader; masking at capture with three capture levels; ingest job | Same trace produces identical `agent_event` rows from MLflow path and OTLP path; VN PII recall ≥ 0.95 on the synthetic labelled set | 1 |
| 5 | Judge | Tier 1 and Tier 2 prompts (data-wrapped, JSON-only); router with family ≠ agent check; MLflow scorers; eval harness (planted, benign, judge-injection, held-out); golden-set file format; challenger sampling; `MockJudge` | Eval report with catch rate, false-alarm rate, injection move rate on held-out set; CI fails if judge family equals agent family | 2 |
| 6 | Evidence | Chain writer (one lane per agent + root lane, single writer); Ed25519 signed head every N minutes; anchor job; `supervisor-verify` offline CLI; case-file generator (JSON + HTML + PDF, VN + EN, SBV 24 h / 5-day clock) | Tamper test: edit one row → `supervisor-verify` reports the break offline on a copy of the data; case file renders from a real incident | 2 |
| 7 | Monitors | Drift band per agent version; fairness slices (Fairlearn) on allowed attributes from config; groundedness via MLflow judges; oversight metrics daily; one multi-agent pattern (split payment) over gateway events | Seeded drift week opens a case with no rule broken; fairness gap computed on synthetic slices; metrics table feeds console | 1–2 |
| 8 | Console | FastAPI API + React SPA: queue, case, sign-off, pause/resume (one-click pause, two-person resume), agents + coverage score, metrics panel, chain status, audit-pack export; auth port with dev and Databricks App modes | A reviewer completes the full incident flow in the browser locally; same build runs as a Databricks App with SSO headers (tested when workspace exists) | 2 |
| 9 | Onboard | Discover (RepoReader + WorkspaceReader), Understand (pydantic profile with file:line evidence, Decision 33 mapping), Plan (catalogue → monitoring plan + playbook), Instrument (PR with policy YAML, tracing hook, dashboard; libcst codemod; never auto-merge), Launch (red-team pack, baseline, go/no-go report); capability catalogue + manifests | Onboarding one of the three mock agents from a clean checkout produces profile, plan, PR branch and launch report; Onboarding Agent runs under Watch with its own agent ID | 2–3 |
| 10 | Databricks deployment | DAB resources: schema bootstrap job, ingest/drift/anchor/metrics jobs, console App, gateway App or serving endpoint, secret scope names; `docs/databricks-prereqs.md`; smoke test `make db-smoke` | `databricks bundle deploy -t dev` then `make db-smoke` passes on a workspace; contract tests pass on the Databricks adapter | 1–2 (needs workspace) |
| 11 | Demo + operations | Demo harness (seed, inject 4 incidents, tamper test, reset, replay), 20-run e2e test, RUNBOOK, SECURITY, threat model, bank-integration stubs (SIEM, ITSM, pager, SCIM) with documented contracts, `make release` (lock, dist, wheelhouse) | `make demo` from a fresh clone on a machine with Docker and no network completes the runbook 20 times; release archive unpacks and runs | 1 |

Total: about 18–22 sessions. WP0–WP9 and WP11 need no bank input. WP10 needs a workspace URL, a token or service principal, a catalog name and a SQL warehouse.

## 6. Build order and parallel lanes

```
WP0 ─▶ WP1 ─▶ WP2 ─▶ WP3 ─▶ WP6 ─▶ WP4 ─▶ WP5 ─▶ WP8 ─▶ WP7 ─▶ WP9 ─▶ WP11
                                                                  │
                     (WP10 can start after WP1 when a workspace exists) ─▶ WP10
```

Milestones you can see:

| Milestone | After | What you can do |
|---|---|---|
| M1 "it blocks" | WP3 | Run three agents locally; watch the gate block a planted transfer |
| M2 "it proves" | WP6 | Tamper with a row; the verifier catches it offline; a case file prints |
| M3 "it judges" | WP5 | Read the eval report with measured catch and false-alarm rates |
| M4 "it is a product" | WP8 | Open the console; run the whole incident flow as a reviewer |
| M5 "it onboards" | WP9 | Onboard a mock agent end to end with a PR |
| M6 "it ships" | WP11 | Copy the archive to the work computer; `make demo` |
| M7 "it runs on Databricks" | WP10 | `databricks bundle deploy`; same tests pass on UC + Lakebase |

## 7. What waits for the bank (configuration, not code)

| Item | Where it lands | Default until then |
|---|---|---|
| Databricks region and enabled models | `config/models.yaml` | OpenAI-compatible URL from `.env`; Tier 2 = same as Tier 1 with a warning banner |
| Residency wording | `docs/architecture.md`, console footer | "Processing region: as configured" |
| Fairness attributes permitted | `config/fairness.yaml` | gender, age band, province, language on synthetic data only |
| SCIM groups and service principals | `config/auth.yaml` | dev users file |
| SIEM / ITSM / pager endpoints | `Notifier` adapters | console inbox + log |
| Notary key custody (HSM/KMS) | `Signer` adapter | local Ed25519 file, marked "dev key" in every chain head |
| WORM anchor target | `Anchor` adapter | write-once directory / UC Volume |
| Retention periods | `config/retention.yaml` | raw 90 d, masked 365 d, chain 5 y |
| Private Link, egress allow-list | `docs/databricks-prereqs.md` | documented as open |
| Real agent to onboard | `onboard` on a real repo | the three mock agents |

## 8. Toolchain (pinned)

| Layer | Choice | Reason |
|---|---|---|
| Python | 3.12 (host and Databricks serverless both 3.12) | one runtime |
| Packaging | `uv` + `uv.lock`; `uv export` for `requirements.txt` on Databricks | reproducible, offline |
| API | FastAPI + pydantic v2 | runs under uvicorn and inside a Databricks App |
| DB | SQLAlchemy 2 + Alembic; psycopg 3; `databricks-sql-connector` | Postgres = Lakebase protocol |
| Tracing | MLflow 3 (≥ 3.14 for UC trace tables; verify in workspace) | same API both targets |
| LLM client | `openai` SDK against any compatible URL | FMAPI is OpenAI-compatible |
| Masking | Presidio + custom VN recognisers | MIT |
| Fairness | Fairlearn | MIT |
| Console | React 18 + Vite + TypeScript; `dist/` committed | no npm at the bank |
| PDF | fpdf2 (pure Python) | no system libraries |
| Crypto | `cryptography` Ed25519; SHA-256 canonical JSON | offline verify |
| Deploy | Databricks Asset Bundles; `databricks` CLI | dev / uat / prod |
| Local | Docker Compose: postgres, mlflow, gateway, console, agents | one command |

Licence rule: MIT / Apache-2.0 only in copied code. Prompt Guard 2 (Llama licence) is an optional adapter behind a flag, logged as an exception, off by default.

## 9. First session (WP0 + start of WP1)

1. `git init ~/supervisor`; copy `docs/` and `analysis/` from the handoff into `docs/handoff/`.
2. Write `pyproject.toml`, `Makefile`, `docker-compose.yml`, `.env.example`, `databricks.yml` with three targets, `resources/` placeholders.
3. Write ADR files `docs/adr/D01..D12.md` from 06 §3.
4. Write `schema/model.yaml` and the generator that emits both DDL dialects; commit `ddl/postgres.sql` and `ddl/databricks.sql`.
5. Write `core/models.py`, `core/canonical.py` with test vectors.
6. `make check` and `docker compose up` green. Tag `v0.0.1-skeleton`.

## 10. Risks in the build itself

| Risk | Effect | Control |
|---|---|---|
| Gate host on Model Serving is not a fit for FastAPI routes | WP10 rework | Gate core is a library; both hosts are < 200 lines; decide by spike B latency |
| MLflow version in the workspace below 3.14 | UC trace tables unavailable | `agent_event` is the read model (D8); MLflow tables are optional |
| Lakebase not available in the workspace | Console write-back | `StateStore` falls back to Delta with optimistic concurrency, slower |
| Work computer has no Docker | `make demo` blocked | `make demo-lite`: SQLite + file MLflow + single uvicorn process |
| No LLM endpoint reachable at the bank | Judge tiers idle | `MockJudge` keeps the flow; eval report marks "mock" |
| Scope creep inside a WP | Sessions slip | DoD is the stop line; extras go to `BACKLOG.md` |
