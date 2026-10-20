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
| WP24b | Masker `vn_regex-3` (names in every case form, addresses, amounts kept), inline redaction of `pii_export` tool arguments at the gate, `pii_canary` v2, PII eval harness | `docs/masking.md`, `docs/masker-validation-report.md` | D17 |

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
| `POLICY_DIR`, `FACT_SOURCE` | Served app loads another policy folder and a fact source | `FACT_QUERY_MAP` |

### Behaviour changes with flags off

- Masker version is `vn_regex-3` (was `vn_regex-2`). Masked text and `mask_version` change for
  names, addresses and grouped accounts; amounts are no longer masked as accounts.
- `agent_event` rows carry `latency_us` (integer microseconds) in addition to `latency_ms`.
- `post_json` (gate SDK transport) returns `{}` for an empty 2xx body instead of raising.
- Reserved agent ids `inventory` and `app:*` are refused at registration and Discover.
- Console "Verify chain" writes a `chain_verify` record after each verify.

### Deploy note for Delta (databricks_app mode)

The app does not migrate Delta at start. Run the schema bootstrap BEFORE you deploy the new
app version:

    python -m supervisor.jobs.bootstrap_schema

(or the migration cell in `notebooks/bootstrap_and_smoke.py`). It adds the column
`agent_event.latency_us` and the new tables `alert`, `siem_event`, `tool_usage_daily`,
`inventory_node` and `inventory_edge`. If the app runs first, every gate decision insert fails
on the unknown column `latency_us`. SQLite (laptop) is bootstrapped at app start and needs no
step.
