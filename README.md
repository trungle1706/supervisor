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
| Monitors | Drift, fairness, groundedness, oversight metrics; per-agent bindings and an explicit `not_applicable` status when a monitor cannot run (`python -m supervisor.monitors.binding_harness`) | `docs/metrics.md`, `docs/monitors.md`, `docs/adr/D20-monitor-bindings.md` |
| Console | Reviewer pages: queue, agents, cases, sign-off, metrics; left sidebar, global search, list pages with filter bar and row drawer (WP-UX1); agent page with eight tabs, Alerts, Sign-off list and Analytics pages, old URLs redirect (WP-UX2); gate decisions, traces, playground, policies, credentials, users, audit log, integrations (WP-UX3, each behind a flag) | `docs/console.md` |
| Onboarding agent | Discover, Understand, Advise, Launch, Retire stages; opens PRs. HTTP routes are listed as entrypoints, not tools; deepagents and the model family are recognised | `docs/onboard.md`, `docs/onboard-eval.md` |
| Regulation knowledge base | 31 instruments, 528 obligations, cited, versioned; internal rules load too | `docs/regulations.md` |
| Compliance advisor | Obligation matrix, gaps, open questions for any product | `docs/compliance-advisor.md` |
| Integration advisor | Readiness score and patches to fit a product into Supervisor | `docs/INTEGRATION_GUIDE.md` |
| Assurance packs | 33 eval packs: accuracy, bias, dependency, security, robustness | `docs/assurance.md` |
| Tool analytics | Per-tool calls, outcomes, latency; allowed-but-unused tools; least-privilege diff (suggestion only) | `docs/tool-analytics.md`, `docs/adr/D18-tool-analytics.md` |
| Judge MRM | Model card, validation report, change control, retire | `docs/judge-mrm.md` |
| LLM adapter and judge models | Strict endpoints, derived judge family, challenger scope | `docs/llm-adapter.md`, `docs/adr/D21-derived-judge-family-and-served-config.md` |
| Policy folder and fact source | `POLICY_DIR`, `FACT_SOURCE` for the served app | `docs/fact-sources.md` |
| Inventory graph | Agents, models, endpoints, tools, MCP servers and datasets with evidence; risk passes up; flags Apps and endpoints with no manifest (shadow AI) | `docs/inventory.md`, `docs/adr/D16-inventory-graph.md` |
| Enterprise ops | RBAC, audit table, JSON logs, health, retention, backup, support bundle | `docs/enterprise-readiness.md` |
| Ingress auth (WP20, off by default) | Per-agent HMAC key or Databricks service-principal token on `/gate/check` and `/v1/traces`; `INGRESS_AUTH_ENABLED=1` | `docs/ingress-auth.md`, `docs/adr/D14-ingress-auth.md` |
| Injection classifier VI+EN (WP25, WP25b model 1.1.0, off by default; validation verdict NO-GO on false alarm and recall, see report) | Local pure-Python classifier detector for arguments, tool results and tool descriptions; may only pause money and credit tools (`GATE-CLASSIFIER-PAUSE`); enable with `detectors.injection_classifier.enabled: true` in `config/detectors.yaml` (needs `DETECTORS_ENABLED=1`); `fail_closed: true` is honoured only with `CLASSIFIER_FAIL_CLOSED_APPROVED=1` and a card approval that names the approver and the approved weights_sha256; `python -m tools.train_classifier` | `docs/injection-classifier.md`, `docs/injection-classifier-validation-report.md`, `docs/adr/D27-injection-classifier.md` |
| Detectors and verdict v2 (WP37, off by default) | One detector contract (`dlp_vn`, `injection_regex`, `judge_advisory`), findings on masked text, `status` / `coverage` / `correlation_id` on `POST /v1/gate/check`, `DETECTORS_ENABLED=1`; harness `python -m supervisor.detectors.harness` | `docs/detectors.md`, `docs/detectors-validation-report.md`, `docs/adr/D23-verdict-contract-v2.md` |
| Latency | Gate p99 on a laptop (SQLite): 4.6 ms with 19 rules, 6.8 ms with 200 (budget 50 ms). HTTP overhead p95 (GAF delta): +3.2 ms. Delta not measured yet. `python -m tools.bench_latency` | `docs/latency.md` |

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
| `TOOL_ANALYTICS_ENABLED` | Runs the daily tool usage rollup and writes least-privilege suggestions (a diff for a person to apply, never applied); serves `GET /v1/analytics/tools`. Commands and flags: `docs/tool-analytics.md` |
| `CONSOLE_NAV` | Console layout: `sidebar` (default, left sidebar with six groups) or `top` (the phase 2 pill header; one-setting rollback). Details: `docs/console.md` |
| `CONSOLE_NAV_PLACEHOLDERS` | Shows a "coming in WP-UX3" link for a new page whose own flag is still off |
| `CONSOLE_DECISIONS_ENABLED` | Shows the Gate decisions page (list, filters, drawer with rule hits and evidence position) |
| `CONSOLE_TRACES_ENABLED` | Shows the Traces list and the span-tree viewer (masked payloads only) |
| `CONSOLE_PLAYGROUND_ENABLED` | Shows the Playground: a dry-run gate check that writes nothing. In `databricks_app` mode also set `PLAYGROUND_ALLOW_APP=1` |
| `CONSOLE_POLICIES_ENABLED` | Shows the Policies page (deployed versions, rules, YAML; read-only) |
| `CONSOLE_CREDENTIALS_ENABLED` | Shows the Credentials page (agent key metadata, never a secret; owner and admin) |
| `CONSOLE_USERS_ENABLED` | Shows the Users and roles page (read-only role map and matrix; admin) |
| `CONSOLE_AUDITLOG_ENABLED` | Shows the Audit log page (`console_action` rows; auditor and admin). Not the same as `CONSOLE_AUDIT_ENABLED`, which writes the rows |
| `CONSOLE_INTEGRATIONS_ENABLED` | Shows the Integrations status page (SIEM, webhook, pager, ITSM, SCIM; read-only) |
| `CONSOLE_SCAN_CAP`, `CONSOLE_TRACE_SCAN` | Newest rows the Gate decisions / Audit log pages (default 20000) and the Traces list (default 5000) read before they filter |
| `CONSOLE_TOOLS_ENABLED` | Shows the Tools tab (usage per agent and tool, unused allowed tools, diff download for owners) |
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
| `INGRESS_AUTH_ENABLED` | Requires a per-agent credential (HMAC key, Databricks SP token or Apps proxy identity) on `/gate/check`, `/v1/gate/check` and `/v1/traces`; refusals are 401 / 403 and audited. See `docs/ingress-auth.md` |
| `RATE_LIMIT_ENABLED` | Rate-limits mutating routes (429); agent check path is exempt |
| `INVENTORY_ENABLED` | Fills the inventory graph, runs the workspace refresh job (databricks_app mode), shows the Inventory tab and `/v1/inventory/...`; shadow-AI items open low-severity cases |
| `LLM_STRICT_SCHEMA` / `LLM_SEND_TEMPERATURE` | Strict json_schema without the keywords Anthropic's OpenAI-compatible endpoint refuses (`1`), and leaving `temperature` out of the request (`0`). Defaults `0` and `1` keep the old request. See `docs/llm-adapter.md` |
| `JUDGE_FAMILY_OVERRIDE_TEST_ONLY` | Lets a declared `JUDGE_*_FAMILY` replace the family derived from the model id (tests only; refused in `databricks_app` mode). Rows then say `family_source=declared-test-only`. `JUDGE_FAMILY_PROBE=1` also asks the endpoint's `/models`. `JUDGE_AGENTS` lists agent ids whose manifests the challenger is checked against. See `docs/llm-adapter.md` |
| `JUDGE_FAMILY_STRICT` | Default `1`. `0` (one release only) accepts a declared `JUDGE_*_FAMILY` for a model id that shows no family (a custom serving endpoint name), as `family_source=declared-unverified`; a clash with the id is still refused and `mrm validate` gives NO_GO. See `docs/llm-adapter.md` |
| `POLICY_DIR` / `FACT_SOURCE` / `FACT_QUERY_MAP` | The served app loads another policy folder and a fact source (`sqlite:/abs/file.db` read-only with a query map, or `callable:pkg.mod:factory`, the module under `FACT_CALLABLE_ALLOW_PREFIX`, default `supervisor.`). See `docs/fact-sources.md` |
| `RETENTION_ENABLED` | Runs the PDPL retention job: nulls personal columns after their TTL, keeps digests and chain |
| `MASK_AMOUNTS` | Types money amounts `<AMOUNT:...>` in masked text (default: amounts stay intact, the rules need them). See `docs/masking.md` |
| `INLINE_REDACTION_ENABLED` | Gate answer carries masked `transformed_args` for `pii_export` tools; the SDK and the MCP proxy apply them when their own switch is on. `INLINE_REDACTION_TOOLS` adds tools. See `docs/masking.md` |
| `SIEM_ENABLED` | Sends evidence events to the bank SIEM through `SIEM_SINK` (`file`, `http`, `delta`) in `SIEM_FORMAT` (`jsonl`, `cef`, `ocsf`); see `docs/siem.md` |
| `ALERTS_ENABLED` | Runs the alert rules in `config/alerts.yaml` and routes alerts to inbox, SIEM, webhook, pager; Alerts section on the Metrics page; see `docs/alerts.md` |
| `NOTIFY_WEBHOOK_ENABLED` | Webhook notifier sends notices to `NOTIFY_WEBHOOK_URL` from the scheduler job `notify` (a console request only queues; retry, dead-letter file); without a URL it only queues |
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
| Release notes (v0.3.0-pre: new flags, Delta deploy order) | `CHANGELOG.md` |

## Licence and security

Code is Apache-2.0 (`pyproject.toml`). Third-party packages, fonts and datasets are logged
in `docs/LICENSES.md`. To report a vulnerability, read `SECURITY.md`. The threat model of
Supervisor itself is `docs/threat-model.md`.
