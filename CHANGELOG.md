# Changelog

## v0.3.0-pre (phase 3, wave 1) - not released

Integration branch `phase3-wave1`. `__version__` stays `0.2.0` until the release. WP23 (latency
benchmark) is not in this wave yet; it adds `tests/perf/`, `tools/bench_latency.py` and
`docs/latency.md` and a README line.

### What is new

| WP | Feature | Docs | ADR |
|---|---|---|---|
| WP20 | Per-agent ingress credentials on `POST /gate/check`, `/v1/gate/check`, `/v1/traces` (HMAC key, Databricks SP bearer, Apps proxy identity), rotation CLI, audited 401 / 403 | `docs/ingress-auth.md` | D14 |
| WP21 | SIEM export (file, http, delta; jsonl, CEF, OCSF 1.1 subset), alert engine (`config/alerts.yaml`), Alerts section on Metrics with acknowledge, queued webhook notifier | `docs/siem.md`, `docs/alerts.md` | D15 |
| WP22 | Tool usage rollup `tool_usage_daily`, least-privilege diff (suggestion only), console Tools page, `GET /v1/analytics/tools` | `docs/tool-analytics.md` | D18 |
| WP24 | Inventory graph (agents, models, endpoints, tools, MCP servers, datasets), shadow-AI scan with low-severity cases (no incident clocks), console Inventory page, `GET /v1/inventory/...` | `docs/inventory.md` | D16 |
| WP1b-B | Onboarding: FastAPI routes are `entrypoints` (file:line), not tools; `deepagents` framework; MCP `tools/list`, `create_react_agent` / `create_deep_agent` tool lists; model family from endpoint names and env / `app.yaml` values via the judge alias table; corpus repo `fastapi_deepagents_credit_toy`, eval with precision, recall, Wilson intervals. Monitors: per-agent bindings (manifest and `policies/*.yaml`), defaults from tool classes, `monitor_status` with `not_applicable` reasons on the Metrics page, harness `python -m supervisor.monitors.binding_harness` | `docs/onboard.md`, `docs/onboard-eval.md`, `docs/monitors.md` | D19 |
| WP24b | Masker `vn_regex-3` (names in every case form, addresses, amounts kept), inline redaction of `pii_export` tool arguments at the gate, `pii_canary` v2, PII eval harness | `docs/masking.md`, `docs/masker-validation-report.md` | D17 |

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

### Deploy note for Delta (databricks_app mode)

The app does not migrate Delta at start. Run the schema bootstrap BEFORE you deploy the new
app version:

    python -m supervisor.jobs.bootstrap_schema

(or the migration cell in `notebooks/bootstrap_and_smoke.py`). It adds the column
`agent_event.latency_us` and the new tables `alert`, `siem_event`, `tool_usage_daily`,
`inventory_node` and `inventory_edge`. If the app runs first, every gate decision insert fails
on the unknown column `latency_us`. SQLite (laptop) is bootstrapped at app start and needs no
step.
