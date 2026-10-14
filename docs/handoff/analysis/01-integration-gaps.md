# 01 - Integration gaps: Techcombank systems and the bank's Databricks platform

Lens: enterprise integration. Date: 2026-10-14. Status tags: VERIFIED = checked in docs this session (URL given). ASSUMED = engineering judgement, not checked.

## 1. Verdict

The handoff picks the right Databricks building blocks, but it treats several Preview/Beta features as settled and it skips almost all bank-side plumbing. Three items can break the plan: (a) UC trace storage cannot use Private Link storage or default storage, and is capped at 200 traces/s per workspace by default; (b) there is no Databricks region in Vietnam, so "in-region" means Singapore at best, and a legal answer on cross-border processing is needed; (c) an inline <50 ms gate on Model Serving is plausible (platform overhead < 20 ms) but unproven, and a Databricks App is the wrong host for it. Outside Databricks, the handoff has no identity, SIEM, ITSM, notification, change-management, DR, environment-separation or chargeback design. The data model is named but not specified. None of this blocks the competition demo. All of it blocks the December shadow-mode candidate.

## 2. Findings table

| # | Gap / risk | Sev | Evidence | Recommendation | Effort | Phase |
|---|---|---|---|---|---|---|
| 1 | UC trace storage is Beta-like and has hard limits: needs MLflow >= 3.14, 200 traces/s/workspace and 100 MB/s/table by default, no Private Link storage, no default-storage catalog, enabling tracing on a serving endpoint "may reduce throughput", ALL_PRIVILEGES not enough (grant MODIFY+SELECT) | H | VERIFIED https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog ; Beta wording from search summary | Run a spike in the bank workspace in week 1: write path, perms, region, throughput. Keep an own `agent_event` Delta table (OTel-shaped) as fallback and as the evidence source | 3 days spike | Competition |
| 2 | Inline gate hosting not decided. Model Serving custom endpoint: overhead "< 20 ms with route optimization", 16 MB payload, 300k QPS with route optimization, but 200 QPS cap without it. Apps: no latency or scaling figures in docs | H | VERIFIED https://docs.databricks.com/aws/en/machine-learning/model-serving/model-serving-limits ; Apps page gives no limits | Host gate on Model Serving with route optimization (or in the agent's own VPC as a sidecar). Do NOT host it in a Databricks App. Measure p50/p99 with real policy set before promising < 50 ms | 1 week | Competition (measure), Dec (harden) |
| 3 | Region and residency. No Vietnam region. Singapore (ap-southeast-1) lists Claude Sonnet/Opus/Haiku 5.5, GPT 5.4/5.5, Llama 4 Maverick, Qwen3-Next 80B; Qwen3.5 122B appears NOT listed in Singapore (listed Tokyo, Seoul, Mumbai, Sydney). Page text was flattened, mode (pay-per-token vs provisioned vs cross-geo) not confirmed | H | VERIFIED (partly) https://docs.databricks.com/aws/en/unity-gateway/model-region-availability ; mode columns ASSUMED | Get the bank's actual workspace region first. Confirm per model: pay-per-token vs provisioned vs cross-Geo. If Tier 2 must be "in-region", the Qwen3.5 claim in CLAUDE.md fails in Singapore. Add a legal ruling on SG processing of VN bank data | 2 days + legal | Competition (state assumption), Dec (confirm) |
| 4 | Gateway naming conflict. Databricks docs call the new control plane "Unity Gateway" / "Unity AI Gateway"; one page says it is GA, another summary says Beta. Legacy AI Gateway guardrails: Public Preview, no output guardrails on streaming, inference tables lag up to 1 hour, > 1 MiB not logged | M | VERIFIED https://docs.databricks.com/aws/en/ai-gateway/configure-ai-gateway-endpoints ; https://docs.databricks.com/gcp/en/ai-gateway/ | Treat Databricks gateway as the model-boundary layer only. Keep Supervisor gate as the tool-call layer. Put a thin adapter in front so either gateway works. Re-check status in the bank workspace | 2 days | Dec |
| 5 | Lakehouse Monitoring custom metrics: no current doc found that confirms how it works for GenAI. Databricks now steers GenAI monitoring to MLflow 3 registered scorers (sampling 0.0-1.0 per scorer, trace filter, backfill) | M | VERIFIED (negative) https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/concepts/production-quality-monitoring | Build drift on a plain scheduled Delta job over the trace/metric tables, with Lakehouse Monitoring as an optional view. Do not make it a dependency | 1 week | Competition |
| 6 | Structured Streaming for the multi-agent check: Real-Time Mode announced GA 2026-03-19 (blog), docs still say Preview in places; "as low as 5 ms" is best case; default micro-batch is minutes | M | VERIFIED https://www.databricks.com/blog/announcing-general-availability-real-time-mode-apache-spark-structured-streaming-databricks | Use standard micro-batch (seconds) for slow lane. Claim sub-second only for the gate, not the stream | 0 | Competition |
| 7 | Lakebase and Apps SSO: user authorization (on-behalf-of) listed Preview; Lakebase scale-to-zero cold start about 1-2 s (third-party, anecdotal) | M | VERIFIED https://docs.databricks.com/aws/en/oltp/projects/databricks-apps ; blog ASSUMED | Console writes sign-offs as the app service principal PLUS the user ID in the row. Disable scale-to-zero for the case store | 2 days | Dec |
| 8 | Lineage for Discover: system.access.table_lineage / column_lineage, rolling 1-year window; page names no lineage REST API; serving endpoints and agents not named as lineage nodes; jobs via runs/submit not linked | M | VERIFIED https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-lineage | Query system tables via SQL warehouse (needs system-table grants, usually a platform-team approval). Discover must also parse code and prompts, lineage alone is not enough. Say "last 90 days" is inside the 1-year window | 3 days | Competition |
| 9 | No identity design: Entra ID/AD groups -> Databricks groups (SCIM), service principals for gate/judge/onboarding agent, secrets (scopes or Key Vault), who can read masked vs raw traces | H | ASSUMED (not in handoff) | One identity doc: roles (Reviewer, Approver, Owner, Auditor, Platform admin), SCIM-synced groups, one SP per component, OAuth M2M, no PATs. Split duties: the SP that writes evidence cannot edit it | 1 week | Dec |
| 10 | No network design: private link/ingress to Apps and serving, egress to external model APIs, on-prem reach to core banking, DNS. Model Serving to external endpoints: Private Link "not supported by default" | H | VERIFIED (serving page above) for PL limit; rest ASSUMED | Draw network diagram with bank network team. Prefer FMAPI in-workspace models over external-model egress. Agree allowlist for any egress. Check Private Link on trace storage conflict (finding 1) | 1-2 weeks (bank-bound) | Dec |
| 11 | No SIEM/SOC feed. Cases and verdicts must reach Splunk/Sentinel as the SOC expects | H | ASSUMED | Emit CEF/JSON events per verdict and case state change via a Delta change feed job to Event Hub/Kafka/HEC. Define 10 event types and a stable schema | 1 week | Dec |
| 12 | No ITSM sync (ServiceNow/Jira). Reviewer console would be a second ticket system | M | ASSUMED | One-way create + two-way status sync keyed by case_id. Console stays the evidence UI, ITSM stays the work queue | 1-2 weeks | H1 2027 |
| 13 | No notification path (Teams/email/pager). "Time to human < 5 min" needs a paging tool | H | ASSUMED | Webhook adapter: Teams card, email, PagerDuty/Opsgenie or bank pager. Ack event written back to case. Test after-hours | 3-5 days | Dec |
| 14 | Change management: PR-only is good, but no CI/CD detail: DAB deploy per environment, branch protection, CODEOWNERS for policy YAML (second approver), signed commits, release evidence, rollback of a policy | M | ASSUMED | GitHub/GitLab/Azure DevOps adapter behind one interface. Policy YAML in its own repo path with CODEOWNERS. Bundle `targets:` dev/uat/prod | 1 week | Dec |
| 15 | Data classification, masking, retention, legal hold not specified. Masking is Presidio only; Vietnamese PII (CCCD, phone, account formats) not covered. Traces contain customer data | H | ASSUMED; Presidio has no Vietnamese recognisers by default | Map bank classification levels to UC tags. Add VN recognisers (regex + checksum). Column masks / row filters on raw trace tables. Retention per table. Legal-hold flag blocks purge. Raw-trace access = separate group | 2 weeks | Dec |
| 16 | Delete conflict: UC traces can only be deleted by SQL on tables (no API); evidence chain is append-only | M | VERIFIED trace page | Evidence stores hashes + masked excerpts, never raw. Raw traces get TTL; chain keeps hash of raw so deletion does not break proof | 3 days | Dec |
| 17 | DR/HA absent. Gate is on the critical path of agent traffic. Fail-open or fail-closed? | H | ASSUMED | Decide per rule class: money-moving tools fail-closed, informational fail-open. Multi-instance gate, health check, local policy cache, break-glass bypass logged. Delta tables: deep clone or cross-region replication per bank DR tier | 1-2 weeks | Dec |
| 18 | Environment separation missing. Evidence from dev must not mix with prod | M | ASSUMED | Separate catalogs `sup_dev`, `sup_uat`, `sup_prod`; separate anchors; policy promotion only by PR | 3 days | Dec |
| 19 | Cost chargeback: no tag or per-agent cost attribution of judge tokens | M | Unity Gateway docs say spend attributable to principals/tags (VERIFIED https://docs.databricks.com/gcp/en/ai-gateway/) | Judge calls use a per-agent tag / SP; monthly table `cost_by_agent`; send to FinOps | 3 days | H1 2027 |
| 20 | Agent-side: legacy/black-box agents get "proxy only" with no spec for what is learnable (see section 5) | H | Handoff plug point 3 | Define minimum viable proxy log schema and what each missing signal costs in coverage | 1 week | H1 2027 |
| 21 | Data model unspecified (see section 6) | H | Handoff names tables without columns | Freeze v0 DDL in week 1; every component codes to it | 3 days | Competition |
| 22 | Bank agent estate unknown: which framework, where hosted (Databricks, Azure, on-prem), calls to T24/Temenos, cards, CRM | H | ASSUMED | Run a 2-week estate survey with 3-5 teams before building adapters | 2 weeks (bank-bound) | Dec |
| 23 | Azure vs AWS differences not covered; choice changes IAM, network, model list | M | Search only gave generic results (not verified for Claude/FMAPI parity) | Ask which cloud first (open question 1). Then verify model list on that cloud's docs (learn.microsoft.com mirror) | 1 day | Competition |
| 24 | Third-party/model-vendor terms: Claude on Databricks is served under Databricks terms; GPT is also hosted. Retention for Fable noted already. Prompt retention on other models not checked | M | Handoff covers Fable only | Get written zero-retention confirmation per model used by judge | 2 days + vendor | Dec |

## 3. Detailed notes on High findings

**F1 - Trace store limits.** The plan puts MLflow 3 UC tracing at the centre. Docs show real limits. 200 traces/s per workspace is fine for demo, tight for a bank fleet (a chatty agent makes one trace per request, spans inside). Private Link storage is unsupported for trace tables, which may clash with the bank's network rules. Do the spike first. Keep a Supervisor-owned `agent_event` table so the evidence chain never depends on a Beta feature. Map OTel span fields to it with one job.

**F2 - Gate host.** Model Serving gives < 20 ms overhead with route optimization (VERIFIED). Your own code adds policy eval, Presidio and Prompt Guard. Prompt Guard 2 is a model: run it on CPU only if small. Presidio is slow on long text (ASSUMED). Budget: platform 20 ms + rules 5 ms + PII regex 10 ms + injection 15 ms = about 50 ms, no spare. Plan two modes: sync (rules + regex, < 50 ms) and async-fast (ML checks, 100-300 ms, applied on high-risk tools only). Change the metric from "< 50 ms" to "p99 < [bank to set]".

**F3 - Region.** No VN region exists in the model page. Singapore carries Claude 5.5 tiers and GPT 5.x. Qwen3.5 122B seems absent there. Vietnam rules on cross-border transfer of bank data are a legal question, not an engineering one. Options: (1) mask first, then send to SG; (2) judge runs on Qwen3-Next 80B in SG; (3) bank-hosted open model on provisioned GPU. State the chosen option on the deck. Also check the docs' note that workspace-level enablement can fail even when the table lists a model (community report, anecdotal).

**F9 - Identity.** Minimum set: SCIM from Entra ID; groups `sup-reviewers`, `sup-approvers`, `sup-agent-owners`, `sup-auditors`, `sup-admins`. SPs: `sp-gate`, `sp-judge`, `sp-onboard`, `sp-evidence-writer`, `sp-console`. Onboarding Agent SP gets read on repos and UC, write only on its output volume and PR token. Gate-to-agent trust: signed agent ID (JWT from registry) on each call.

**F10 - Network.** Questions to settle: where do agents run; can the gate reach them; does judge traffic leave the workspace; does the on-prem core banking sit behind a bank API gateway the gate could also sit behind.

**F11/13 - SIEM and paging.** "Time to human < 5 min" is a bank-process metric. Tool-agnostic webhook plus a SIEM event schema covers both. Add a heartbeat: if Supervisor stops emitting, SIEM alerts (a watcher that is silent is the worst failure).

**F15 - Classification.** Without a classification map, masking rules are guesses. Provide default mapping: Public / Internal / Confidential / Restricted -> UC tag `classification`, column mask policy, who can see unmasked, retention days.

**F17 - Fail mode.** Not stated in handoff. A reviewer will ask "what if Supervisor is down". Answer: per-rule fail mode in policy YAML, tested with a kill drill in the demo.

**F20/22 - Estate.** Plug point 3 is where most bank agents will start, so it is not a side case. See section 5.

**F21 - Data model.** See section 6.

## 4. Bank-side integration map

```
Entra ID --SCIM--> Databricks groups --> UC grants / App roles
Agents (Databricks | Azure | on-prem)
   |-- OTel / MLflow --> collector --> UC trace tables
   |-- tool calls ---> GATE (Model Serving or sidecar) --> tools / core banking API gateway
Supervisor Delta (sup_<env>) --change feed--> SIEM (Splunk/Sentinel)
                           --> notifier --> Teams / email / pager
                           --> ITSM (ServiceNow/Jira)   (case_id key)
Console (App) <-> Lakebase (sign-offs, queue)
Evidence anchors --> WORM store (bank object lock) 
Repo (GitHub/GitLab/ADO) <-- PRs from Onboarding Agent --> CI --> DAB deploy (dev -> uat -> prod)
```

| Area | Minimum for Dec shadow mode | Later |
|---|---|---|
| IAM | SCIM groups, 5 SPs, OAuth M2M, secrets in bank vault | JIT access for auditors |
| Network | Private ingress, allowlisted egress, no PAT | Private Link to model providers if supported |
| SIEM | JSON events to HEC/Event Hub, heartbeat | Detection rules owned by SOC |
| ITSM | Ticket create with case_id | Two-way sync |
| Notify | Teams + email + pager webhook | Escalation ladder |
| Change | PR + CODEOWNERS + DAB targets | Signed releases, release evidence in chain |
| Data | UC tags, masks, retention, legal hold flag | Automatic DSAR search |
| DR | Fail mode per rule, 2 gate instances | Cross-region replica |
| Env | 3 catalogs | Synthetic data generator for UAT |
| Cost | Tags per agent | Chargeback report |

## 5. Agent-side integration (how bank agents are really built)

Estate is ASSUMED, not verified. Expect a mix. Ask the bank (question 5).

| Build style | Likely share [bank to supply] | Instrument path | Gap |
|---|---|---|---|
| Databricks Mosaic AI Agent Framework / Agent Bricks, deployed to Model Serving | [__] | MLflow autolog + inference tables. Full set | Agent endpoints cap at 4 MB payload (VERIFIED serving page) |
| LangGraph / LangChain / LlamaIndex in Python | [__] | MLflow/OpenLLMetry autolog, OTel exporter, wrap tool nodes with gate client | SDK version drift; need a pinned `supervisor-sdk` with 3 functions: `trace()`, `gate()`, `identity()` |
| MCP tool servers | [__] | Proxy in front of MCP (mcp-scan pattern). Best fit for gate | Auth passthrough; tool description poisoning checks |
| Vendor SaaS copilots (CRM, ITSM, Microsoft Copilot Studio) | [__] | Only logs/webhooks they export | No inline gate. Observe-only |
| Bank-built Java/.NET services with LLM calls | [__] | OTel Java/.NET agent; HTTP proxy to model | No MLflow; need OTel GenAI semantic conventions mapping |
| Legacy RPA / rules + LLM | [__] | Network proxy only | Reduced set |

Plug points in practice:

| Plug point | Needs | Cost to agent team |
|---|---|---|
| SDK (Python) | pip package, 5-10 lines | Low, but needs release cycle |
| OTel exporter | env var change (OTLP endpoint + auth) | Lowest |
| Sidecar / reverse proxy | deploy container next to agent; mTLS | Medium; gives inline block |
| Egress proxy (forward) | network route change; TLS inspection | High; needs network team |
| Log scrape | read-only access to app logs | Lowest, gives slow lane only |

Calls to core banking (T24/Temenos, card switch, CRM) normally go through the bank's API gateway or an ESB. ASSUMED. Implication: gate placed at the agent's tool layer sees intent; the API gateway sees the actual call. Best control = both, correlated by a shared `trace_id` header. Add that header requirement to the Plan stage.

Missing for black-box agents (not in handoff):
1. A minimum proxy log schema (request, response, tool call, headers, latency, caller ID).
2. Tool-call extraction when the agent speaks a private protocol.
3. Identity: black-box agents often share one service account, so "which agent" is unknown. Registry needs a `identity_binding` (cert, API key hash, source IP).
4. A coverage score per agent (which of the 10 capabilities work) shown on the console, so nobody believes a proxy-only agent is fully watched.
5. Streaming responses: output guardrails do not work on streams in Databricks' legacy gateway (VERIFIED); our gate needs a buffer-or-post-check decision.
6. Multi-agent: message bus is assumed. Real banks may have none. For H1, use correlation IDs on API gateway logs.

## 6. Minimum data model (v0)

Catalog per environment: `sup_<env>`. Schemas: `trace`, `registry`, `policy`, `verdict`, `case`, `evidence`, `metrics`.

| Table | Location | Key columns (minimum) | Notes |
|---|---|---|---|
| `trace.*_otel_spans` (created by MLflow) | UC Delta | trace_id, span_id, parent, name, start/end, attributes | Platform-owned. Do not alter. |
| `trace.agent_event` (own, normalised) | UC Delta | event_id, trace_id, span_id, agent_id, agent_version, event_type (llm_call, tool_call, message, handoff), tool_name, args_hash, args_masked, result_masked, ts, env, classification, source (mlflow/otel/proxy) | Fallback and single read model for Watch. Raw payload in a restricted column or volume. |
| `registry.agent` | UC Delta (source of truth), cached in Lakebase for console | agent_id, name, owner_team, owner_user, business_owner, risk_tier, decision33_class, host_type, plug_point, model_family, status (onboarding/shadow/enforced/paused/retired), created_at | SCD2 history |
| `registry.agent_version` | UC Delta | agent_id, version, code_ref (git sha), prompt_hash, tool_manifest_hash, model_endpoint, deployed_at, baseline_id | Drift band ties to version |
| `registry.identity_binding` | UC Delta | agent_id, binding_type, binding_hash, valid_from/to | For black-box agents |
| `registry.coverage` | UC Delta | agent_id, capability_id, status (on/off/partial), reason | |
| `policy.rule` | UC Delta (git is source, table is the deployed copy) | rule_id, version, agent_scope, expression, action (log/alert/block/pause), fail_mode, severity, regulation_ref, owner, approved_by_1, approved_by_2, git_sha, effective_from/to | |
| `policy.threshold` / `policy.baseline` | UC Delta | agent_id, version, metric, band_low, band_high, window, computed_at | |
| `policy.capability` | UC Delta | capability_id, manifest_json, signals_needed, default_thresholds, cost_estimate | From catalogue |
| `verdict.decision` | UC Delta (append-only) | verdict_id, ts, trace_id, event_id, agent_id, tier (0/1/2), checker_id, model_id, model_family, score, label, action, latency_ms, rule_id, rationale_masked | One row per check outcome; gate decisions written async from a queue, not inline |
| `case.case` | Lakebase (Postgres) for mutable state; snapshot to UC Delta on every state change | case_id, agent_id, severity, status, opened_at, assignee, itsm_ref, regulation_refs, summary, closed_at | Mutable workflow data fits Lakebase |
| `case.case_event` | UC Delta (append-only) | case_id, seq, ts, actor (user or SP), action, comment_masked | Who did what, feeds chain |
| `case.signoff` | Lakebase, mirrored | case_id, reviewer_id, decision, reason, ts, auth_method | Reviewer ID from SSO, not app SP |
| `evidence.chain` | UC Delta (append-only, no UPDATE/DELETE grants) | seq, ts, record_type, record_ref, payload_hash, prev_hash, entry_hash, writer_sp, env | Single writer SP, serialised insert (concurrency design needed: partition per agent chain + a periodic root chain) |
| `evidence.anchor` | UC Delta + external WORM | anchor_id, seq_from, seq_to, root_hash, anchored_at, anchor_target, receipt | Target: bank object lock / timestamp authority [bank to choose] |
| `evidence.case_file` | UC Volume (PDF/JSON) + row | case_id, file_path, file_hash, generated_at, template_version | Hash goes into the chain |
| `metrics.oversight_daily` | UC Delta | date, agent_id, coverage, ttd_ms, tth_s, catch_rate, false_alarm_rate, chain_ok, groundedness, fairness_gap | Feeds console panel |
| `metrics.cost` | UC Delta | date, agent_id, tier, model, tokens_in/out, cost | Chargeback |
| `audit.access_log` | system tables (VERIFIED idea: UC audit logs) | | Not cryptographic proof (handoff already says so) |

Rules for the model:
1. Mutable workflow state in Lakebase. Anything that must prove something in UC Delta append-only, with the hash in `evidence.chain`.
2. Hash chain concurrency: two writers will fork the chain. Use one writer job, or one chain per agent plus a root chain. Decide in week 1.
3. Hash the canonical JSON (sorted keys, UTF-8, fixed time format). Write the spec.
4. Verdicts from the inline gate go to a queue (Event Hub/Kafka or a serving-side buffer), then batch to Delta. Do not write Delta in the request path.
5. Delta time travel and VACUUM can remove history: set retention on `evidence.*` tables long, forbid VACUUM below the legal period (ASSUMED setting).

## 7. Databricks feature reality check (summary)

| Feature | Status found | Tag |
|---|---|---|
| MLflow 3 traces to UC tables | Works, MLflow >= 3.14, limits above, Private Link storage unsupported, Beta wording uncertain | VERIFIED (limits) |
| Unity Gateway vs AI Gateway | Legacy AI Gateway page says new Unity Gateway is GA; other summary says Beta. Guardrails (legacy) Public Preview. Name varies: "Unity Gateway", "Unity AI Gateway" | VERIFIED, conflicting |
| Inference tables | Up to 1 h lag; > 1 MiB not logged | VERIFIED |
| Apps + SSO + Lakebase | Apps OAuth fine; user authorization Preview; Lakebase autoscale to 64 CU | VERIFIED (partly) |
| Lakehouse Monitoring custom metrics | Not confirmed for GenAI; MLflow scorers are the current path | Not verified |
| Model Serving as inline proxy | < 20 ms overhead with route optimization; measure | VERIFIED (vendor claim) |
| Structured Streaming | RTM GA claimed Mar 2026; use micro-batch for slow lane | VERIFIED (blog) |
| FMAPI regions | No VN. Singapore has Claude/GPT/Llama/Qwen3-Next; Qwen3.5 122B not seen in SG | VERIFIED (partly) |
| Provisioned throughput | Listed per region; community report of workspace enablement failure | VERIFIED (anecdote) |
| UC lineage | System tables, 1-year window, no REST API named on page | VERIFIED |
| DAB | Standard path, not re-checked | ASSUMED |
| Azure vs AWS | Same core platform; Azure adds Entra/Purview/Foundry fit; Claude parity per cloud not verified | ASSUMED |

## 8. What the handoff gets RIGHT

1. Fast lane as a service, not a Delta job (confirmed by the 1-hour inference-table lag).
2. Hash chain plus external anchors; saying UC audit logs and time travel are not proof.
2. OTel as the contract, so non-Databricks agents are not locked out.
3. PR-only changes with a second approver.
4. Different model family for judge; avoid Fable retention and Gemini global endpoint.
5. Lakebase for write-back and UC groups for RBAC.
6. Opening plug point 3 for legacy agents, with an honest "reduced set".
7. Bracketed placeholders for numbers the bank must supply.

## 9. Open questions for the bank

1. Which cloud runs the Databricks workspace (AWS or Azure), and in which region?
2. Is Unity Gateway enabled in the account? Are MLflow UC trace storage and the "OpenTelemetry on Databricks" preview enabled?
3. May masked bank data be processed in Singapore? Who rules, and how long does it take?
4. Which models are already approved by model-risk, and is zero-retention confirmed for each?
5. Which agent frameworks and hosts exist today? Which 3-5 teams are the first targets?
6. What is the network path from agents to tools; is there an API gateway or ESB in front of T24/Temenos, cards, CRM?
7. Which SIEM (Splunk/Sentinel), ITSM (ServiceNow/Jira), pager and chat tool are standard? Who owns the integration accounts?
8. Which source control and CI (GitHub, GitLab, Azure DevOps)? Is DAB deploy allowed, or must Terraform/other pipeline be used?
9. Bank data classification scheme, masking standard, retention periods, legal-hold process?
10. Does the bank have a write-once store or timestamp service for anchors? Who runs it?
11. DR tier required for a control that sits in the agent path? Fail-open or fail-closed by action type?
12. Who pays for judge tokens and Supervisor compute; is there a chargeback model?
13. Is there a system-table access process (lineage, audit, billing) for a new project?
14. What p99 latency can an agent team tolerate from the gate?

## Sources checked

- https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog
- https://docs.databricks.com/aws/en/unity-gateway/model-region-availability
- https://docs.databricks.com/aws/en/machine-learning/model-serving/model-serving-limits
- https://docs.databricks.com/aws/en/ai-gateway/configure-ai-gateway-endpoints
- https://docs.databricks.com/gcp/en/ai-gateway/
- https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-lineage
- https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/concepts/production-quality-monitoring
- https://www.databricks.com/blog/announcing-general-availability-real-time-mode-apache-spark-structured-streaming-databricks
- https://docs.databricks.com/aws/en/oltp/projects/databricks-apps
