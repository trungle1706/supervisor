# Supervisor

Supervisor puts a control layer around AI agents in a regulated company. A deterministic
gateway can block or pause an agent. AI judges only advise. Every decision goes into a
hash-chained evidence store that an auditor can check offline.

It was built for Techcombank. It is not tied to one bank: the rules, the regulation data and
the integration contracts load from files, so another regulated company can use it.

> **Regulation and compliance outputs are advisory. Not legal advice. Bank counsel must
> confirm.** / Khong phai tu van phap ly. The regulation knowledge base, the compliance
> matrix and the readiness scores help you find duties. They do not decide what the law
> requires.

## What it does

| Part | Question it answers | Main output |
|---|---|---|
| Onboard | How does a new agent get under control? | Onboarding Agent reads the repo, proposes policy and a pull request |
| Watch | What did the agent do, and was it allowed? | Gateway, recorder, judges, monitors, cases, reviewer console |
| Prove | Can we show it to an auditor? | Hash-chained evidence, offline verifier, case files |
| Comply | Which duties apply to this product? | Compliance matrix over the regulation knowledge base |
| Assure | Is the agent and the judge good enough? | Assurance packs, judge model-risk (MRM) report |

## Two deployment targets

| Target | Use | Notes |
|---|---|---|
| Bank Windows laptop | Self-host, offline, SQLite store | `SUPERVISOR_MODE=laptop`. See `docs/SETUP_WORK_COMPUTER.md` |
| Databricks App | Shared service, Delta store | OAuth only. See `docs/RUNBOOK.md`, `docs/BANK_DEPLOY_GUIDE.md` |

One Python codebase serves both. Nothing in the app fetches from the internet. The only
network calls are to the configured LLM endpoint and the configured Databricks workspace.

## Capabilities

| Capability | What it is | Read |
|---|---|---|
| Gateway | Rule engine that allows, blocks or pauses a tool call; fail-closed for money tools | `docs/adr/D01-gateway.md` |
| Recorder | Takes traces (OTLP, OTel GenAI attributes), masks PII, stores them | `docs/recorder.md` |
| PII masking | `vn_regex-3` masker, per-entity eval harness (`python -m supervisor.pii_eval`), inline redaction at the gate | `docs/masking.md`, `docs/masker-validation-report.md` |
| Judges | Tier 1 and Tier 2 AI judges; advise only, never call the gate | `docs/adr/D06-judge-hardening.md` |
| Evidence chain | SHA-256 chain, one lane per agent, signed head, offline `verify` | `docs/adr/D05-evidence-chain.md` |
| Monitors | Drift, fairness, groundedness, oversight metrics | `docs/metrics.md` |
| Console | Reviewer pages: queue, agents, cases, sign-off, metrics | `docs/console.md` |
| Onboarding agent | Discover, Understand, Advise, Launch, Retire stages; opens PRs | `docs/onboard.md`, `docs/onboard-eval.md` |
| Regulation knowledge base | 31 instruments, 528 obligations, cited, versioned; internal rules load too | `docs/regulations.md` |
| Compliance advisor | Obligation matrix, gaps, open questions for any product | `docs/compliance-advisor.md` |
| Integration advisor | Readiness score and patches to fit a product into Supervisor | `docs/INTEGRATION_GUIDE.md` |
| Assurance packs | 33 eval packs: accuracy, bias, dependency, security, robustness | `docs/assurance.md` |
| Judge MRM | Model card, validation report, change control, retire | `docs/judge-mrm.md` |
| Enterprise ops | RBAC, audit table, JSON logs, health, retention, backup, support bundle | `docs/enterprise-readiness.md` |

## 10-minute tour

Commands are Windows cmd, run from the `supervisor` folder. Set the source path once:
`set PYTHONPATH=src`. All commands below were run on the dev host (Linux, same Python 3.11);
the paths use `\` for cmd.

| Step | Command | Expect |
|---|---|---|
| 1. Preflight | `uv run python -m supervisor.cli preflight` | `preflight: 12 checks, 0 failed` (`[SKIP]` lines for optional extras) |
| 2. Serve | `uv run python -m supervisor.cli serve` | Console at http://127.0.0.1:8000/console/. Not run in the tour check (it does not exit) |
| 3. Demo | `uv run python -m supervisor.cli demo --loop 1` | `[OK] demo run 1: PASS` |
| 4. Regulations | `uv run python -m supervisor.regkb coverage` | Coverage table, 31 instruments, 528 obligations |
| 5. Assurance | `uv run python -m supervisor.assurance run all --target demo --out out\assurance --no-store` | `run ...: 112 results` and `[MOCK]` label; `out\assurance\report.md` |
| 6. Integration | `uv run python -m supervisor.advisory.integration --target data\corpus\repos\langgraph_loan_triage --out out\integration --mock-llm` | `integration_report.md` and 4 patch files (not applied) |
| 7. Compliance | `uv run python -m supervisor.onboard --target src\supervisor_agents\payments --out out\payments --mock-llm` then `uv run python -m supervisor.advisory.compliance --profile out\payments\profile.json --out out\payments-compliance --mock-llm` | `Decision 33 suggestion: high_risk`; `compliance_matrix.{json,md,html}` |
| 8. Judge MRM | `uv run python -m supervisor.judge.mrm card --out out\mrm --no-store` | `model card written to out\mrm` |

To see the Assurance, Compliance and Integration tabs in the console, turn on their flags
(next section) and serve the demo store (`set DATA_DIR=data\local\demo`). `docs/DEMO.md` has
the stage script.

## Flags that are off by default

Set in `.env` or with `set NAME=1` in cmd. A new feature does not change phase 1 behaviour
until you turn its flag on.

| Flag | Turning it on |
|---|---|
| `CONSOLE_ONBOARD_ENABLED` | Shows the Onboard "Start" action in the console |
| `CONSOLE_COMPLIANCE_ENABLED` | Shows the Compliance tab (read-only obligation matrices) |
| `CONSOLE_INTEGRATION_ENABLED` | Shows the Integration tab (readiness reports and patches as text) |
| `CONSOLE_ASSURANCE_ENABLED` | Shows the Assurance tab (runs, packs, metrics against go / no-go) |
| `ONBOARD_COMPLIANCE_ENABLED` | Onboarding run also writes the compliance matrix |
| `ONBOARD_ADVISOR_ENABLED` | Onboarding run also writes the integration report and patches |
| `ASSURANCE_LAUNCH_ENABLED` | Launch runs agent packs in the sandbox; a failed required pack makes Launch NO-GO |
| `ASSURANCE_DATA_DIR` | Points to bank-supplied datasets, one folder per pack (no value = synthetic data only) |
| `ASSURANCE_LICENCE_ALLOW` | Lists the licences the dependency pack accepts (has a safe default list) |
| `ASSURANCE_JUDGE_GATE_ENABLED` | Note: on by default. A real (non-mock) judge needs its judge packs to pass; set `0` to switch off |
| `ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH` | Lets a Launch GO rest on mock pack results only (default off: mock-only results are a NO-GO item; any mock result labels the reason `assurance (MOCK)`). Demo only |
| `ASSURANCE_JUDGE_MIN_ITEMS` | Not a switch (default `50`): the fewest items a judge pack result needs to validate a real judge, checked for both tier-1 and tier-2 models |
| `ASSURANCE_JUDGE_ALLOW_WARN` | Lets a judge pack result with status `warn` validate a real judge (default off: only `ok` counts) |
| `JUDGE_REQUIRE_VALIDATION` | Judge refuses to start without a passing MRM validation for its current identity |
| `API_RBAC_ENABLED` | Enforces the role matrix on the agent-facing `/gate/*` read routes (`/gate/agents/{id}/state`, `/gate/metrics`). The control routes (pause, resume, quarantine, release) always check identity and role |
| `RATE_LIMIT_ENABLED` | Rate-limits mutating routes (429); agent check path is exempt |
| `RETENTION_ENABLED` | Runs the PDPL retention job: nulls personal columns after their TTL, keeps digests and chain |
| `MASK_AMOUNTS` | Types money amounts `<AMOUNT:...>` in masked text (default: amounts stay intact, the rules need them). See `docs/masking.md` |
| `INLINE_REDACTION_ENABLED` | Gate answer carries masked `transformed_args` for `pii_export` tools; the SDK and the MCP proxy apply them when their own switch is on. `INLINE_REDACTION_TOOLS` adds tools. See `docs/masking.md` |
| `LOG_FORMAT` | Value `json` writes one JSON log line with request id and principal id (default `text`) |

## What is mock

| Item | Mock when | How you can tell |
|---|---|---|
| Judges | No `LLM_BASE_URL` set | `MOCK` badge on verdicts and in the console |
| Assurance targets | Demo agents and the mock judge | `[MOCK]` line and mock label in the report |
| Compliance and integration narrative | `--mock-llm` or no model | "mock, advisory" label in the output |
| Agent output in the demo | Always scripted | `[FIXTURE]` line. The gate, pause, case and chain break are real |

Real numbers for judge accuracy, assurance packs and the narrative need the real model and
the bank's own data. The first step after the LLM key arrives is in `docs/SETUP_WORK_COMPUTER.md`.

## Documentation

All files are listed with audience in `docs/index.md`. Start with these:

| Need | File |
|---|---|
| Rules for agents that write code here | `CLAUDE.md` |
| Install on a work laptop | `docs/SETUP_WORK_COMPUTER.md` |
| Operate and fix | `docs/RUNBOOK.md` |
| Stage demo | `docs/DEMO.md` |
| Phase plans | `docs/BUILD_PLAN.md`, `docs/BUILD_PLAN_PHASE2.md` |
| Every doc | `docs/index.md` |

## Licence and security

Code is Apache-2.0 (`pyproject.toml`). Third-party packages, fonts and datasets are logged
in `docs/LICENSES.md`. To report a vulnerability, read `SECURITY.md`. The threat model of
Supervisor itself is `docs/threat-model.md`.
