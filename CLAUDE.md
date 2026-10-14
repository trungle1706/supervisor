# Supervisor — rules for every agent that writes code in this repo

Read in this order: this file, `docs/BANK_DEPLOY_GUIDE.md` (hard constraints, learned from live failures at the bank), `docs/BUILD_PLAN.md` (work packages, Definition of Done), `docs/adr/` (design decisions D1–D12). The product background is in `docs/handoff/` (read `docs/handoff/CLAUDE.md` and `docs/handoff/analysis/05-overall-analysis.md` when you need the why).

## What this is
Supervisor = Onboard + Watch for AI agents at a bank. Deterministic gateway that can block or pause an agent, tiered AI judges that only advise, hash-chained evidence with offline verification, case files, reviewer console, and an Onboarding Agent that opens pull requests. One Python codebase, two targets: a bank Windows laptop (self-host, offline) and a Databricks App.

## Hard constraints (from the bank guide; do not negotiate)
- Python 3.11 is the floor. `requires-python = ">=3.11"`; `.python-version` = 3.11. Run every check with 3.11.
- Launch everything as `python -m <module>`. Never rely on console-script `.exe` stubs. All docs for the user use Windows cmd syntax.
- Dependencies: pure-Python wheels or packages with Windows cp311 wheels on PyPI. No compiler, no Rust build, no torch, no spacy models, no runtime downloads (datasets, fonts, CDN JS). Vendor static assets into the repo.
- Offline runtime. Nothing in the app fetches from the internet. The only network calls: the configured LLM endpoint and the configured Databricks workspace.
- Databricks: OAuth only. Never read or document `DATABRICKS_TOKEN`; preflight fails if it is set. SQL via the Statement Execution API (REST) through `databricks-sdk`, not the thrift connector. Values come back as strings; cast by schema. Cap SDK retries at 60–120 s inside `Config`. Inject `truststore` at the top of every entry point when `SSL_OS_TRUSTSTORE=1`.
- Databricks App: one app, one process, port 8000 on 0.0.0.0, `app.yaml` command `python -m uvicorn ...`, `PYTHONPATH=src`, dependencies from `requirements.txt` exported from `uv.lock`. `/tmp` is wiped on restart: durable state lives in Delta tables in the configured schema. No Jobs, no Lakebase, no Model Serving endpoint creation, no secret-scope resources, no bundle variables. Per-workspace values are `FILL-ME-...` placeholders in committed files; a test asserts no real ids or secrets are committed.
- Paths: resolve to absolute once at config load. `sys.executable` via `os.path.abspath`.
- No `exec`, `eval`, `compile` or `subprocess` outside `src/supervisor/sandbox.py`. An AST test enforces this.
- Errors shown to a user: HTTP 400 with a message, never 500. CLI output ASCII only (`[OK]`, `[FAIL]`, `[SKIP]`).

## Product rules
- Never fake the gate block, the pause switch or the chain break. Mocks are allowed for LLM judges only, labelled `mock` in every verdict and on screen.
- Judges advise. Only deterministic rules block or pause. A judge verdict opens a case or raises severity; it never calls the gate.
- Judge model family must differ from the agent model family (checked in the registry and in CI).
- Evidence chain: canonical JSON (sorted keys, UTF-8, RFC 3339 UTC timestamps, no floats for money: integer minor units), SHA-256, one lane per agent plus a root lane, signed head, offline `supervisor-verify`. PII never enters the chain; hashes and masked excerpts only.
- Synthetic Vietnamese data only. Generator in `src/supervisor/data/`. No real customer data anywhere.
- Licence: MIT or Apache-2.0 for copied code. Anything else is an optional extra behind a flag, off by default, logged in `docs/LICENSES.md`.
- New features default off; the off path behaves as before and has a test.

## Engineering rules
- Ports and adapters: `src/supervisor/core/ports.py` defines protocols; `src/supervisor/adapters/*` implement them. Core and domain modules never import `databricks`, `pyspark`, `sqlite3`, `httpx`, `openai` directly (AST test).
- One schema source `schema/model.yaml`; generator emits `schema/ddl/sqlite.sql` and `schema/ddl/databricks.sql`; both committed; a test checks they are current.
- Every job is `python -m supervisor.jobs.<name>` and also callable from the in-process scheduler.
- Tests: `uv run python -m pytest`. Unit tests always. Contract tests run on SQLite always and on Databricks when `RUN_DATABRICKS=1`. Databricks code is unit-tested with fakes here; a live test kit ships for the user.
- Lint: `uv run python -m ruff check` and `ruff format --check`. Type hints on public functions.
- Commit after each Definition-of-Done step with a message that names the work package (`WP3: gateway state machine + fail mode`).
- Do not touch files outside your work package without saying so in your report. Shared files (`pyproject.toml`, `schema/model.yaml`, `CLAUDE.md`, `docs/BUILD_PLAN.md`) : edit minimally and list every change in your report.
- Prefer standard library. Add a dependency only if it saves real work, has a cp311 Windows wheel, and is MIT/Apache/BSD/PSF.

## Delegation (for lead agents)
A lead agent may spawn Sonnet 5.5 sub-agents for bounded sub-tasks and one reviewer sub-agent at the end. If the reviewer finds a significant defect (DoD not met, constraint broken, test missing), fix it before reporting. Report: what was built, how the DoD was proven (commands + output), deviations from the plan, open questions, files changed outside the package.

## Decisions added after Wave A review (2026-10-14)
- Chain payloads contain no floats. Scores and rates are integer basis points (0–10000); money is integer minor units. `canonical.py` keeps float support for non-chain use only.
- Evidence tables on Delta: `delta.logRetentionDuration` and `delta.deletedFileRetentionDuration` default to `interval 1825 days`, set from `EVIDENCE_RETENTION_DAYS` in settings.
- Secret scrubbing before any LLM sees repo text: regex scrubber in-repo; gitleaks optional if the bank supplies the binary.
- Parallel work packages talk through `EvidenceSink` and `GateHook` in `core/ports.py`. Tests use in-memory adapters.
