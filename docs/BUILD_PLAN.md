# Build plan v2 (2026-10-14) — revised for the bank environment

Supersedes `docs/handoff/analysis/08-build-plan-for-claude-code.md` where they differ. Reason: `docs/BANK_DEPLOY_GUIDE.md` shows the bank laptop is Windows 11 with no admin rights (no Docker, no Postgres), Python 3.11, Nexus packages, offline runtime, and the workspace allows one Databricks App with no Jobs, no Lakebase, no serving-endpoint creation. Decisions D1–D12 (`docs/adr/`) stay in force except where noted below.

## 1. Targets

| | Laptop mode (default) | Databricks App mode | Dev box (this Linux host) |
|---|---|---|---|
| Run | `uv run python -m supervisor.cli serve` on 127.0.0.1:8000 | `python -m uvicorn supervisor.app:app` on 0.0.0.0:8000 | same as laptop; Docker optional |
| Tables | SQLite file, append-only enforced by triggers | Delta tables in `FILL-ME-catalog.FILL-ME-schema` via Statement Execution API | SQLite |
| Mutable state | SQLite | Delta with optimistic concurrency (`row_version`) | SQLite |
| Traces in | OTel SDK in-process + OTLP/HTTP receiver + optional MLflow export | same; MLflow experiment optional | same |
| LLM | OpenAI-compatible URL (Ollama loopback by default) or `MockJudge` | bound `serving_endpoint` (OpenAI-compatible) | any, key from `.env` |
| Scheduler | APScheduler inside the server process | same (background tasks run as the service principal) | same |
| Heavy jobs | in-process | Command Execution API runner on the shared cluster (optional extra) | in-process |
| Auth | dev users file; OAuth CLI profile for Databricks reads | SSO headers (`X-Forwarded-User`, token per request); SP fallback | dev users file |
| Gateway host | route in the same process | route in the same App | same |
| Console | Jinja2 + vendored htmx + vendored CSS (no Node, no CDN) | same | same |

Dropped from plan v1: Docker Compose as a requirement, Postgres, Lakebase, Databricks Workflows jobs, Model Serving pyfunc gateway host, React/Vite console, Presidio as a hard dependency, MLflow as the primary trace path. Each is listed in `BACKLOG.md` with the condition under which it returns.

## 2. Ports (in `core/ports.py`)

`SqlExecutor` (sqlite, databricks_rest), `TableStore` and `StateStore` (built on SqlExecutor), `TraceSource` (otel_inprocess, otlp_receiver, mlflow_export optional), `ChatModel` (openai_compatible, mock), `Signer` (ed25519_file, secret_env), `Anchor` (worm_dir, uc_volume), `Masker` (vn_regex, presidio optional), `Principal` (dev_header, databricks_app), `Notifier` (inbox, webhook), `RepoReader` (local_git, databricks_repo), `WorkspaceReader` (fixtures, databricks_sdk), `Clock`.

Adapter factory: `supervisor.config.Settings` (pydantic-settings, `.env`) picks adapters by `SUPERVISOR_MODE=laptop|databricks_app|dev` plus per-port overrides. Settings resolves all paths to absolute at load, validates `LLM_BASE_URL` is loopback unless `LLM_ALLOW_REMOTE=1`, fails on `DATABRICKS_TOKEN`.

## 3. Work packages (revised)

| WP | Name | Builds | Definition of Done |
|---|---|---|---|
| 0 | Skeleton | `pyproject.toml` (3.11 floor, extras `databricks`, `monitors`, `presidio`, `mlflow`), `uv.lock`, `.python-version`, ruff, pytest, `Makefile` (Linux convenience only), `supervisor.cli` with `serve`, `preflight`, `demo`, `verify`, `export-reqs`, `release`; `truststore` injection helper; `databricks.yml` + `app.yaml` + `requirements.txt` with FILL-ME placeholders; `docs/adr/D01..D12.md`; `BACKLOG.md`; `docs/RUNBOOK.md` (cmd syntax) skeleton; AST tests (forbidden imports, no exec/subprocess outside sandbox); no-secrets test; requirements-matches-lock test | `uv run python -m pytest` green under 3.11; `uv run python -m supervisor.cli preflight` prints `[OK]/[SKIP]` lines and exits 0 on this host; `python -m supervisor.cli serve` answers `/healthz` |
| 1 | Core + schema | Pydantic models (agent, agent_version, agent_event, rule, verdict, case, case_event, signoff, chain_entry, anchor, metrics); `core/canonical.py` with test vectors; `schema/model.yaml` + generator to SQLite DDL (append-only triggers) and Databricks DDL; `SqlExecutor` sqlite adapter; `SqlExecutor` databricks_rest adapter (Statement Execution API via `databricks-sdk`, string casting by schema, chunk following, 120 s deadline, retry cap) with a fake for unit tests; `TableStore`/`StateStore`; `Settings` + adapter factory | Contract tests pass on SQLite; the same tests skip-not-fail without `RUN_DATABRICKS=1`; the REST adapter has unit tests against a recorded fake; DDLs regenerate byte-identical |
| 2 | Synthetic data + three agents + attack set | vi_VN generator (names, CCCD, phone, accounts, tickets, loans); `ChatModel` openai_compatible + mock adapters with JSON-schema output, truncation and repetition guards, configurable timeout; agents customer_service, credit_prequal, payments as plain Python tool-calling loops that emit OTel spans; `agents/redteam/incidents.jsonl` ≥ 120 cases with taxonomy fields; the author of the attack set is a separate sub-agent from the author of rules | Each agent completes 20 scripted tasks with `MockChat`, spans land in `agent_event`; attack set validates against its JSON schema; a scripted replay of 4 demo incidents exists |
| 3 | Gateway | Policy YAML schema + loader; Tier 0a sync rules (allow-list, limits, stateful aggregates per window, permissions); Tier 0b async (masking, injection classifier port with regex default); agent state machine RUNNING/SHADOW/PAUSED/QUARANTINED; fail mode per rule (closed for money/credit/PII export, open+alert for read-only); 2 s hard timeout; FastAPI routes `/gate/check`, `/gate/pause`, `/gate/resume`; MCP proxy mode; `@supervised_tool` SDK; latency bench | All 4 demo incidents blocked or paused by real rules; p50/p95/p99 published by `tests/perf`; fail-closed proven by making the policy store unavailable mid-test |
| 6 | Evidence | Chain writer (lane per agent + root lane, single writer, serialised); Ed25519 signed head every N minutes; anchor job (worm_dir / uc_volume); `supervisor-verify` offline CLI (`python -m supervisor.evidence.verify <export dir>`); case-file generator JSON + HTML + PDF (fpdf2), VN + EN, SBV 24 h / 5-day clocks | Tamper test: edit one row in an export copy, verify reports the break; a case file renders from a real incident |
| 4 | Recorder | OTel span → `agent_event` normaliser; OTLP/HTTP receiver route; proxy-log reader; MLflow export adapter (optional extra); masking at capture with capture levels digest/masked/raw | Same trace gives identical `agent_event` rows via in-process and OTLP paths; VN PII recall ≥ 0.95 on the synthetic labelled set |
| 5 | Judge | Tier 1 / Tier 2 prompts (data-wrapped, JSON-only); router with family check; eval harness (planted, benign, judge-injection, held-out); golden-set format; challenger sampling; verdicts advisory only | Eval report with catch, false-alarm and injection-move rates on the held-out set using MockChat and, when a key exists, a real model; CI fails if judge family equals agent family |
| 8 | Console | Jinja2 + htmx pages: queue, case, sign-off, pause/resume (one-click pause, two-person resume), agents + coverage, metrics panel, chain status, audit-pack export; `Principal` dev and databricks_app adapters; all user errors as HTTP 400 | A reviewer completes the full incident flow in a browser locally; pages render with `SUPERVISOR_MODE=databricks_app` and fake headers |
| 7 | Monitors | Drift band per agent version; fairness slices (Fairlearn, `monitors` extra) on configured attributes; groundedness scorer via `ChatModel`; oversight metrics daily; one multi-agent pattern (split payment) over gateway events; all run from the in-process scheduler | Seeded drift week opens a case with no rule broken; fairness gap computed; metrics table feeds the console |
| 9 | Onboard | Discover (RepoReader + WorkspaceReader), Understand (pydantic profile with file:line evidence, Decision 33 mapping), Plan (catalogue → monitoring plan + playbook), Instrument (branch with policy YAML, tracing hook, dashboard spec; libcst codemod; git ops only through `sandbox.py`; never merge), Launch (red-team pack, baseline, go/no-go report); capability catalogue + manifests; Onboarding Agent registered and watched | Onboarding one mock agent from a clean checkout produces profile, plan, branch and launch report |
| 10 | Databricks deployment kit | `databricks.yml` app resource with `sql_warehouse` CAN_USE + `serving_endpoint` CAN_QUERY bindings, `user_api_scopes: [sql]`, dev/prod targets, app name suffix; `app.yaml`; `requirements.txt` export; bootstrap notebook in Databricks source format that creates the tables in the user's schema; live test kit `RUN_DATABRICKS=1`; Command Execution API runner (optional extra); `docs/RUNBOOK.md` with cmd commands and symptom → cause → fix table; preflight checks (trust store, no PAT, profile valid, warehouse reachable, endpoint READY) | `databricks bundle validate` passes with placeholders; unit tests with fakes pass; runbook complete. Live deploy is run by the owner and results relayed back |
| 11 | Demo + release | Demo harness (seed, inject 4 incidents, tamper test, reset, replay); 20-run e2e test; `SECURITY.md`, threat model; bank-integration stubs (SIEM, ITSM, pager, SCIM) with contracts; `release` command: `git archive` + `uv.toml` (Nexus) + `requirements.txt` + leak sweep | `python -m supervisor.cli demo` from a fresh clone with no network completes the runbook 20 times; release zip unpacks and runs |

Order: 0 → 1 → (2 ∥ 3 ∥ 6) → (4 ∥ 5) → (8 ∥ 7) → (9 ∥ 10 ∥ 11). Milestones M1–M7 as in plan v1.

## 4. House rules adopted from the bank guide (assumptions until the owner says otherwise)

| House rule | Applied as |
|---|---|
| Zero AI egress | `LLM_BASE_URL` must be loopback unless `LLM_ALLOW_REMOTE=1`; validated at startup |
| Read-only data access | Applies to bank data the Onboarding Agent reads: single `SELECT`, checked with `sqlglot` before any connection. Supervisor's own tables in its own schema are writable |
| No exec/eval/subprocess outside one module | `src/supervisor/sandbox.py`; AST test |
| AI output is advisory | Judges never block; rules do. Human sign-off text exported verbatim |
| Secrets never in git | `.env` ignored; FILL-ME placeholders; no-secrets test; release leak sweep |
| Features default off | Every optional adapter and extra is off unless configured |
