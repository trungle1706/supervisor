# Changelog

## Unreleased

| WP | Feature | Docs | ADR |
|---|---|---|---|
| WP37 | Verdict contract v2 on `/v1/gate/check` (`status`, `findings`, `not_executed`, `coverage`, `transformed_payload`, `request_id`, `correlation_id`, `direction`; old fields kept), detector framework (`dlp_vn`, `injection_regex`, `judge_advisory`), `GET /v1/gate/detectors`, table `finding` and three nullable `agent_event` columns (run `python -m supervisor.jobs.bootstrap_schema` on Delta), harness `python -m supervisor.detectors.harness`. Flag `DETECTORS_ENABLED` (default off: answers and rows as in v0.3.0) | `docs/detectors.md`, `docs/api.md` | D23 |
## Unreleased (phase 3, wave 2)

### WP26: HTTP MCP gateway with tool locking (flag `MCP_HTTP_ENABLED`, default off)

* `python -m supervisor.gateway.mcp_http --upstream URL --agent ID --listen 127.0.0.1:PORT`: a
  streamable-HTTP MCP proxy that reuses `McpGateProxy` (same gate path, evidence, ingress signing
  and masked arguments as the stdio proxy), one kept-alive upstream client, one listener per
  application. Refuses to start with the flag off.
* Tool locking: every tool is hashed (name, description, input schema, annotations); a new or
  changed tool is hidden from `tools/list` and refused on `tools/call` (`MCP-TOOL-UNREVIEWED`)
  until two different people approve the same hash; a removed tool is logged; a review case
  `mcp_tool_review` opens. New table `mcp_tool_manifest` (run `bootstrap_schema` on Delta).
  `MCP_TOOL_LOCK` (default `1`), `MCP_LOCK_REFRESH_S` (default `60`).
* Review: `python -m supervisor.gateway.mcp_http tools list|diff|propose|approve`, and routes
  `/v1/mcp/tools` (permissions `mcp.tools.view`, `mcp.tools.propose`, `mcp.tools.approve`; the
  role table in `docs/console.md` changed). Two new ingress routes `/v1/mcp/tools/observe` and
  `/blocked` (signed like gate calls).
* Report-only poisoning scan with a hook for the WP25 classifier score.
* Harness `python -m supervisor.gateway.mcp_http_harness` (110 template items, 33 probes outside
  the templates, Wilson intervals, latency with and without the gate) and its regression test.
* Docs: `docs/mcp-gateway.md`, ADR D24, pattern C in the integration guide, threat model.
* Review fixes (`REVIEW_WP26.md`): the proxy passes only server requests and notifications from an
  upstream event stream (a forged response could reach the client ahead of the filtered
  `tools/list`); `tools/list` with `"id": null` is filtered; `propose` never completes a lock;
  approvals need the full 64-character hash; trust-on-first-use over the agent ingress needs
  `MCP_TOFU_INGRESS=1` (default off) and records the sending credential; a non-loopback listener
  needs the inbound token; a malformed lock view fails closed; a tool named `*` is refused.

## v0.3.0 (phase 3, wave 1) - 2026-10-20

Merged from the integration branch `phase3-wave1` (3,684 tests, 29 skipped). Every new feature is behind a
flag that is off by default. On Delta, run `python -m supervisor.jobs.bootstrap_schema` before deploying
(new columns and tables listed below).

### What is new

| WP | Feature | Docs | ADR |
|---|---|---|---|
| WP20 | Per-agent ingress credentials on `POST /gate/check`, `/v1/gate/check`, `/v1/traces` (HMAC key, Databricks SP bearer, Apps proxy identity), rotation CLI, audited 401 / 403 | `docs/ingress-auth.md` | D14 |
| WP21 | SIEM export (file, http, delta; jsonl, CEF, OCSF 1.1 subset), alert engine (`config/alerts.yaml`), Alerts section on Metrics with acknowledge, queued webhook notifier | `docs/siem.md`, `docs/alerts.md` | D15 |
| WP22 | Tool usage rollup `tool_usage_daily`, least-privilege diff (suggestion only), console Tools page, `GET /v1/analytics/tools` | `docs/tool-analytics.md` | D18 |
| WP24 | Inventory graph (agents, models, endpoints, tools, MCP servers, datasets), shadow-AI scan with low-severity cases (no incident clocks), console Inventory page, `GET /v1/inventory/...` | `docs/inventory.md` | D16 |
| WP23 | Latency benchmark `python -m tools.bench_latency` (in process, HTTP open loop with GAF delta, OTLP, MCP proxy; SQLite and a labelled MOCK Delta path), Delta round-trip notebook, two committed full runs. Laptop gate p99 4.6 ms (19 rules), 6.8 ms (200 rules) against 50 ms. The 50 ms test runs with `RUN_PERF=1` | `docs/latency.md` | D19 |
| WP1b-B | Onboarding: FastAPI routes are `entrypoints` (file:line), not tools; `deepagents` framework; MCP `tools/list`, `create_react_agent` / `create_deep_agent` tool lists; model family from endpoint names and env / `app.yaml` values via the judge alias table; corpus repo `fastapi_deepagents_credit_toy`, eval with precision, recall, Wilson intervals. Monitors: per-agent bindings (manifest and `policies/*.yaml`), defaults from tool classes, `monitor_status` with `not_applicable` reasons on the Metrics page, harness `python -m supervisor.monitors.binding_harness` | `docs/onboard.md`, `docs/onboard-eval.md`, `docs/monitors.md` | D20 |
| WP1b-A | Judge config fixes D05, D12, D13, D14, D15: derived judge family with `family_source`, strict structured output for Anthropic-compatible endpoints, challenger scope, served `POLICY_DIR` and `FACT_SOURCE`, SDK on `/v1/gate/check` (details in the next section) | `docs/llm-adapter.md`, `docs/fact-sources.md`, `docs/judge-mrm.md` | D21 |
| WP24b | Masker `vn_regex-3` (names in every case form, addresses, amounts kept), inline redaction of `pii_export` tool arguments at the gate, `pii_canary` v2, PII eval harness | `docs/masking.md`, `docs/masker-validation-report.md` | D17 |
| WP-UX2 | Console page migrations: agent page `/console/agents/<id>` with eight tabs (Overview with the lifecycle controls moved from the Agents cards, Policy, Tools, Inventory, Traces, Cases, Assurance, Compliance; htmx plus `?tab=`), Alerts page `/console/alerts` (moved out of Metrics, filters, drawer), Sign-off list `/console/signoff` and `CaseService.waiting_approvals`, Analytics page `/console/analytics` (Gate, Tools, Oversight metrics, Latency under one toolbar), 303 redirects for `/console/metrics` and `/console/tools`, Cases, Inbox and Inventory on the list components, Case page on the shared tabs macro, Vietnamese labels | `docs/console.md` | - |
| WP-UX1 | Console shell: left sidebar with six groups (Watch, Act, Prove, Onboard, Analytics, Settings), reduced top bar with global search (`GET /console/search`), `CONSOLE_NAV=sidebar` or `top` (the old header stays behind `top`), `CONSOLE_NAV_PLACEHOLDERS`, a "coming in WP-UX3" page for seven pages, component macros (crumbs, page header, tiles, filter bar, sortable paged table, row drawer, tabs, key-value, timeline, empty state, stat, toast), Overview and Agents list migrated as proof, Vietnamese labels, skip link and `aria-*` | `docs/console.md` | - |
| WP-UX3 | Eight console pages, each behind its own flag (default off) and permission, replacing the placeholders: Gate decisions (list, filters, drawer), Traces (list and span-tree viewer, capture level decides the text), Playground (dry-run gate check through the new `Gateway.evaluate_only`, no side effect, `PLAYGROUND_ALLOW_APP=1` on the App), Policies, Credentials (metadata only), Users and roles, Audit log (`CONSOLE_AUDITLOG_ENABLED`), Integrations. New permissions `decisions.view`, `traces.view`, `playground.run`, `policies.view`, `credentials.view`, `users.view`, `audit.view`, `integrations.view` | `docs/console.md` | D22 |

### WP1b-A: benchmark defects D05, D12, D13, D14, D15

| Defect | Change | Docs |
|---|---|---|
| D14 | `LLM_STRICT_SCHEMA`, `LLM_SEND_TEMPERATURE`: the adapter can talk to Anthropic's OpenAI-compatible endpoint (stripped schema copy, local validation against the full schema); contract test on recorded 400s and a recorded 200 | `docs/llm-adapter.md` |
| D05 | Judge family derived from the model id (and endpoint metadata with `JUDGE_FAMILY_PROBE`); declared family only with `JUDGE_FAMILY_OVERRIDE_TEST_ONLY=1` (refused in `databricks_app`); `family_source` in `verdict` rows, chain records, model card, validation report | `docs/llm-adapter.md`, `docs/judge-mrm.md`, ADR D21 |
| D15 | Challenger checked only against registered non-retired agents and `JUDGE_AGENTS`; `mrm validate` mock mode no longer calls a configured real challenger | `docs/llm-adapter.md` |
| D13 | `POLICY_DIR`, `FACT_SOURCE` (`sqlite:` read-only with `FACT_QUERY_MAP`, `callable:`) wired through `wiring.py` and `gateway/wiring.py` | `docs/fact-sources.md` |
| D12 | `HttpGate` posts to `/v1/gate/check`; falls back once to `/gate/check` on HTTP 404 | `docs/api.md` |

Behaviour change with flags off: a declared `JUDGE_*_FAMILY` that disagrees with the model id (or
is given for a model whose family cannot be derived) now stops startup. New nullable column
`verdict.family_source`: run `python -m supervisor.jobs.bootstrap_schema` before deploying on Delta.

### New flags (all default off)

| Flag | Turns on | Related settings |
|---|---|---|
| `INGRESS_AUTH_ENABLED` | Credential check on the three agent ingress routes | `INGRESS_CREDENTIAL_KIND`, `INGRESS_KEY_STORE`, `INGRESS_KEYS_FILE`, `INGRESS_IDENTITIES_FILE`, `INGRESS_SECRET_SCOPE`, `INGRESS_REPLAY_WINDOW_S`, `INGRESS_AUDIT_THROTTLE_S`, `INGRESS_NONCE_CAP_PER_AGENT`, ... |
| `SIEM_ENABLED` | Scheduler job `siem` sends chain events to the sink | `SIEM_SINK`, `SIEM_FORMAT`, `SIEM_FILE_PATH`, `SIEM_WEBHOOK_URL`, `SIEM_HTTP_TOKEN`, `SIEM_DEAD_LETTER_PATH`, `SCHED_SIEM_S` |
| `ALERTS_ENABLED` | Scheduler job `alerts`, Alerts section on Metrics | `ALERTS_CONFIG`, `ALERTS_LAG_S`, `ALERTS_SUPPRESSION_MAX_S`, `SCHED_ALERTS_S` |
| `NOTIFY_WEBHOOK_ENABLED` | Scheduler job `notify` sends queued notices (needs `NOTIFY_WEBHOOK_URL`) | `NOTIFY_WEBHOOK_TOKEN`, `NOTIFY_WEBHOOK_DEAD_LETTER`, `SCHED_NOTIFY_S` |
| `TOOL_ANALYTICS_ENABLED` | Scheduler job `tool_analytics`, `GET /v1/analytics/tools` | `TOOL_ANALYTICS_WINDOW_DAYS`, `TOOL_ANALYTICS_MIN_HISTORY_DAYS`, `TOOL_ANALYTICS_EXCEPTIONS_FILE`, `TOOL_ANALYTICS_DIR`, `SCHED_TOOL_ANALYTICS_S` |
| `CONSOLE_TOOLS_ENABLED` | Console Tools page | - |
| `INVENTORY_ENABLED` | Inventory fill, scheduler job `inventory`, console Inventory page, `/v1/inventory/...` | `INVENTORY_SCAN_SCHEMAS`, `INVENTORY_SELF_APP`, `INVENTORY_ALLOWLIST_FILE`, `INVENTORY_WORKSPACE_FIXTURE`, `SCHED_INVENTORY_S` |
| `INLINE_REDACTION_ENABLED` | Gate answer carries masked `transformed_args` for `pii_export` tools (SDK / MCP proxy switch must also be on) | `INLINE_REDACTION_TOOLS` |
| `MASK_AMOUNTS` | Types money amounts as `<AMOUNT:...>` in masked text | - |
| `LLM_STRICT_SCHEMA` (default `0`), `LLM_SEND_TEMPERATURE` (default `1`) | Strict structured output for endpoints that require it | - |
| `JUDGE_FAMILY_OVERRIDE_TEST_ONLY` | Accepts a declared judge family (tests only) | `JUDGE_FAMILY_PROBE`, `JUDGE_AGENTS` |
| `JUDGE_FAMILY_STRICT` (default `1`) | `0` = one-release path: a declared family for a model id with no family (custom endpoint name) is accepted as `declared-unverified`; `mrm validate` gives NO_GO | - |
| `POLICY_DIR`, `FACT_SOURCE` | Served app loads another policy folder and a fact source | `FACT_QUERY_MAP`, `FACT_CALLABLE_ALLOW_PREFIX` |

### Behaviour changes with flags off

- Masker version is `vn_regex-3` (was `vn_regex-2`). Masked text and `mask_version` change for
  names, addresses and grouped accounts; amounts are no longer masked as accounts.
- `agent_event` rows carry `latency_us` (integer microseconds) in addition to `latency_ms`.
- `post_json` (gate SDK transport) returns `{}` for an empty 2xx body instead of raising.
- Reserved agent ids `inventory` and `app:*` are refused at registration and Discover.
- Console "Verify chain" writes a `chain_verify` record after each verify.
- WP1b-B: a FastAPI route outside a `/tools/` path is no longer a tool in the onboarding inventory
  (it is an `entrypoints` item); `Inventory.model_family` / `model_id` are filled from code when
  the manifest has none (`model_family_source`); `oversight_metric` gains the nullable column
  `monitor_status`; the policy schema accepts `agents.<id>.monitors`; the inventory graph has an
  `entrypoint` node kind. New settings `MONITOR_POLICY_DIR`, `MONITOR_MANIFEST_DIR` (no flag:
  bindings are additive and the existing monitor flags are unchanged).
- WP1b-A: `HttpGate` posts to `/v1/gate/check` (one fallback to `/gate/check` on HTTP 404); a
  declared judge family that disagrees with the model id stops startup; `verdict` gains the
  nullable column `family_source`.
- Integration: with `POLICY_DIR` set, the monitor bindings (quality sweep, drift, fairness,
  multi-agent) read that folder too, like the gate. Other readers of `<repo>/policies` are
  listed in BACKLOG.

### Deploy note for Delta (databricks_app mode)

The app does not migrate Delta at start. Run the schema bootstrap BEFORE you deploy the new
app version:

    python -m supervisor.jobs.bootstrap_schema

(or the migration cell in `notebooks/bootstrap_and_smoke.py`). It adds the columns
`agent_event.latency_us`, `oversight_metric.monitor_status` (WP1b-B) and `verdict.family_source`
(WP1b-A) and the new tables
`alert`, `siem_event`, `tool_usage_daily`, `inventory_node` and `inventory_edge`. If the app runs
first, every gate decision insert fails on the unknown column `latency_us`, and the monitor jobs
fail on `monitor_status`, and judge verdict inserts fail on `family_source`. SQLite (laptop) is bootstrapped at app start and needs no
step.
