# 02 · Architecture, supervisor security, OSS verification

Lens: technical architecture, security of the supervisor itself, open-source component check.
Date: 2026-10-14. Status tags: VERIFIED (checked today, source given) or ASSUMED.

## 1. Verdict

The layout is sound: two speeds, deterministic gate, tiered judge, hash-chained log, PR-only changes. But five points are weak or wrong.
(a) The "mcp-scan proxy" source is stale: mcp-scan is now a scanner owned by Snyk, not a gateway. (b) The gate only covers MCP calls; plain Python tools, REST and SQL have no interception point in the docs. (c) "Pause" is undefined: nothing says how a running agent actually stops. (d) A hash chain on Delta, written by a service the supervisor team controls, proves little; the key, the anchor and the independent verifier are not designed. (e) The supervisor has no threat model: it reads attacker text (judge injection), holds a kill switch, and gives an agent repo read access. All five are fixable inside the competition window as design + small demo, and in full by Dec/H1.

## 2. Findings

| # | Gap / risk | Sev | Evidence | Recommendation | Effort | Phase |
|---|---|---|---|---|---|---|
| 1 | Gateway source is stale. `invariantlabs-ai/mcp-scan` now redirects to `snyk/agent-scan` (scanner; README says output is "experimental", not for production workflows). The runtime proxy was a separate repo `invariant-gateway` (Apache-2.0, 82 stars, last push 2025-11-06) and `invariant` policy lang (471 stars, last push 2026-01-12). Both look dormant. | H | VERIFIED: github.com/snyk/agent-scan, /invariantlabs-ai/invariant-gateway | Docs 03/CLAUDE.md: change "mcp-scan proxy pattern" to "Invariant Gateway pattern (dormant; copy ideas, do not depend)". Write own thin gateway (FastAPI/Envoy ext_authz style). Use agent-scan only offline in Discover to scan MCP servers. | 0.5 d doc; gateway 1-2 wk | Comp |
| 2 | Gateway only sees MCP. No interception for Python function tools, REST, SQL. | H | ASSUMED (docs 02/03 only say "proxy between agent and tools") | Define 3 enforcement points (table in sec 3.1). Competition: one SDK wrapper (`@supervised_tool`) + MCP proxy. Prod: egress allow-list and service-credential brokering so bypass is impossible. | 1 wk comp; 3-4 wk prod | Comp / Dec / H1 |
| 3 | "Pause" is undefined. A verdict row in a table stops nothing. | H | docs 02: "one narrow pause verdict out" | Pause = gateway denies all calls for that agent ID + revokes brokered credential + sets Model Serving traffic to 0 / stops Job run. Agent gets a typed `PAUSED` error. Define states: RUNNING, SHADOW, PAUSED, QUARANTINED. | 3 d | Comp |
| 4 | Fail-open vs fail-closed not stated. | H | docs say "latency budget < 50 ms" only | Policy by action class: money movement, credit decision, PII export = fail-closed; read-only, chat = fail-open + alert. Per-agent in the registry. Circuit-breaker with 2 s hard timeout. | 2 d | Comp |
| 5 | Policy language undecided ("YAML rules", Cedar cited). | M | docs 02/03 | Recommend: YAML authoring surface compiled to Cedar. See sec 3.1. Not OPA/Rego for v1. | 1 wk | Dec |
| 6 | Latency budget unrealistic if gate includes Prompt Guard 2 and Presidio. 7 ms in the case-file example is a Tier 0 rules-only number. | M | ASSUMED: transformer 86M on CPU is tens of ms; Presidio spaCy NER is tens of ms per KB | Split: Tier 0a rules/limits/allow-list (<5 ms, in-process); Tier 0b classifiers (target <80 ms p95 [measure], GPU/CPU endpoint, only on untrusted-input paths). Publish measured p50/p95/p99, never a single figure. | 3 d | Comp |
| 7 | Evidence chain: writer is a single trust point; no key owner, no signing, no independent verifier. | H | docs 03 "hash-chain column ... anchors" | See sec 3.2. Hash chain + signature (KMS/HSM key not readable by supervisor operators) + external anchor to immutable blob + offline verifier CLI. | 2 wk | Comp (basic) / Dec |
| 8 | Chain breaks under Delta OPTIMIZE/VACUUM/concurrent writes, and linear chain forces serial writes. | M | ASSUMED (Delta semantics) | Chain by logical `seq` column, not file order. Single writer per chain "lane" (per agent). Daily Merkle root over a day's entries. Disable deletes/updates by table property + no MODIFY grant. | 1 wk | Dec |
| 9 | Judge reads attacker-controlled text: judge prompt injection is not mentioned. | H | docs 02 Judge | Sec 3.3: structured input, delimiters, no tools for judge, output = JSON schema only, injection-canary tests, second model on disagreement. | 1 wk | Comp |
| 10 | No judge evaluation dataset or calibration plan. Targets (catch >=90%, false alarm <5%) have no test set. | H | docs 02 Metrics "design goals" | Build labelled set: planted incidents + benign traces; report ROC, pick threshold on benign FPR. Hold-out split. ControlArena gives method (safety vs usefulness curve). | 1-2 wk | Comp |
| 11 | "Different model family" is a policy statement, not enforced. | M | CLAUDE.md judge policy | Registry stores `model_family` per agent and per judge; a CI check and a runtime check reject a route where families match. Note: Databricks hosts GPT/Claude/Llama; check for fine-tunes and wrappers (e.g. Llama distilled from another). | 2 d | Comp |
| 12 | Tier 1 at 100% of 300k actions/day: feasibility not shown. | M | docs 04: 3k tokens in per Tier 1 read. 300k x 3k = 900M input tokens/day. Average 3.5 actions/s; peak [bank to supply]. | Tier 1 is async, so queue + batch is fine. Needs provisioned throughput or batch inference; pay-per-token rate limits will bite at peak. Cache static prefix (policy text). Add a "degraded mode": sample at X% when queue lag > N min, and log the gap in the evidence chain (coverage metric must show it). | 3 d | Dec |
| 13 | Message bus does not exist. Agents on Databricks share no bus; "Spark Structured Streaming over the message bus table" has no producer. | H | docs 02 comp 5; 03 | Sec 3.4: derive the bus from the trace/gateway log (every call already passes the gate). No new bus. One pattern: aggregate limit across agents (split payments). | 1 wk | Comp |
| 14 | Onboarding Agent read access to repos = secret exposure + prompt injection from repo content (README, comments). | H | docs 03 "repo/App/MLflow/UC readers" | Sec 3.5: read-only deploy token scoped per repo, secret scrubbing before LLM, repo content tagged untrusted, no network egress, write only to output dir + PR. | 1 wk | Comp |
| 15 | Understand output reliability: free text profile feeds risk tier. | M | docs 02 stage 2 | JSON schema (pydantic), evidence pointers (file:line) per claim, validator rejects claims without pointer, human confirms risk tier. Run twice, diff. | 1 wk | Comp |
| 16 | No supervisor threat model. | H | absent from docs | Sec 3.6 table. Write as doc 09 and show on a slide. | 3 d | Comp |
| 17 | Secrets, SBOM, signing of releases. | M | absent | Databricks secret scopes / Key Vault; no keys in policy YAML; CycloneDX SBOM per build; pin and hash dependencies; sign container images. | 3 d | Dec |
| 18 | Meta-governance: who watches the supervisor? Supervisor's health (lag, dropped events, judge errors) is not a metric. | M | docs list 9 product metrics, none on self-health | Add: ingest lag, gate error rate, fail-open count, judge timeout rate, chain gap count. Heartbeat from gateway; dead-man alert if absent. | 3 d | Comp |
| 19 | Kill switch authority/audit undefined. Who may pause a production payment agent? Who may resume? | H | docs: "pause/resume" in console | Pause: any on-call reviewer, one click, always allowed. Resume: two people (reviewer + agent owner). Every action signed and in chain. Break-glass for gateway bypass needs two approvers and auto-expires. | 3 d | Comp (design) |
| 20 | Rate limiting and backpressure not designed. | M | absent | Gateway: per-agent token bucket; bounded queue to Tier 1; shed load by tier (drop sampling first, never Tier 0). Evidence writer: batch + retry with local WAL so no event is lost on Delta outage. | 1 wk | Dec |
| 21 | Testing, CI, load test absent. | M | backlog has no test items | CI: unit, red-team replay (incidents.jsonl), judge regression set, policy tests, chain tamper test, load test (Locust/k6 to 10x peak). Gate merges on them. | 1-2 wk | Comp (core) / Dec |
| 22 | Schema versioning and replay. | M | absent | `schema_version` on every trace/event/verdict row; Delta schema evolution add-only; policy bundle hash stored with each verdict so any decision can be replayed against the exact policy + model version. Delta time travel for reads, but keep own copy (VACUUM). | 1 wk | Dec |
| 23 | Generated PR safety: tests for generated code. | M | docs 02 stage 4 | Generated files are templates + config, not free code. CI on PR: lint, policy schema validation, dry-run of the gateway against recorded traces, diff-size cap. Second approver on rule change (already stated). | 1 wk | Comp |
| 24 | OSS table errors (see sec 4): PyRIT repo archived/moved; mcp-scan moved; NeMo licence shows NOASSERTION; Prompt Guard 2 is not MIT/Apache. | M | VERIFIED | Fix docs 03/06 and CLAUDE.md "MIT/Apache only" rule exception for Llama licence. | 0.5 d | Comp |

## 3. Detailed notes (High findings)

### 3.1 Gateway, enforcement points, pause, policy language (findings 1-6)

Enforcement points by tool type:

| Tool type | Where the gate sits | Bypass risk | Fix |
|---|---|---|---|
| MCP tool | MCP proxy (stdio or HTTP) in front of server | Agent connects direct | Network policy: agent can reach only proxy |
| Python function tool | In-process wrapper `@supervised_tool` calling gateway `/decide` before execution | Developer removes decorator | PR check by Onboarding Agent; runtime heartbeat: tool calls seen in trace but not in gate log = alert |
| REST / SaaS API | Egress proxy (allow-list) with brokered credential | Agent holds own key | Gateway holds the credential; agent gets short-lived token |
| SQL | UC grants for agent service principal (least privilege) + row/column masks; gateway checks statement class | Over-broad grant | Discover reads grants and flags excess |

Honest limit: an in-process wrapper is cooperative, not hard enforcement. Hard enforcement needs credential brokering. Say this on the slide.

"Pause" mechanics: (1) gateway flips agent state to PAUSED, all later calls denied with a typed error; (2) brokered credentials revoked (stops side channels); (3) for long runs, gateway returns a cancel signal and the SDK wrapper raises `SupervisorPaused`; for Databricks Jobs, call Jobs API cancel-run; for serving endpoints, scale to zero or route to a static "unavailable" response [ASSUMED: confirm the API for the bank's setup]. A call already past the gate cannot be recalled; so irreversible actions (payments) need pre-commit hold: gate returns `ASK` and the transfer API itself has a hold/release step.

Fail policy: table above (finding 4). Default for unknown action class = fail-closed. Every fail-open event is logged and counted as a metric.

Policy language, recommendation:
- OPA/Rego: general, mature, but Rego is hard for risk staff and ill-suited to a short build.
- Cedar: designed for principal/action/resource authorization, analyzable (can prove "no policy permits X"), used in AWS AgentCore (cited in docs 03). Apache-2.0, 1,780 stars, last push 2026-10-13 (VERIFIED api.github.com/repos/cedar-policy/cedar). Python bindings exist (cedarpy) [ASSUMED: check maturity].
- Plain YAML: fastest for demo; no formal semantics; stateful limits (daily cap) not expressible.
Choice: authors write YAML (readable by risk staff, easy for the Onboarding Agent to generate); a compiler turns it into Cedar for authorization decisions; numeric/stateful limits (cumulative amount per day) stay in gateway code with counters, referenced by Cedar context. For the 4-week competition build, keep YAML only and show the Cedar compile as roadmap. Do not choose now what you cannot test.

### 3.2 Evidence chain (findings 7, 8)

| Question | Answer to put in design |
|---|---|
| What does a hash chain prove? | Only that rows were not changed after write, if the head hash is held somewhere the writer cannot alter. Alone it proves nothing against the writer. |
| Hash vs sign | Hash links rows. Signature (Ed25519 or ECDSA) by a key in Azure Key Vault Managed HSM / AWS KMS (non-exportable) proves who wrote it. Sign the chain head every N seconds, not every row (cost). |
| Who holds the key | Not the supervisor engineers. A separate "notary" identity with sign-only permission, key admin = security team. Rotation yearly; old public keys kept in the verifier bundle. |
| Anchor | Every [15 min] write the signed head + Merkle root to immutable storage: Azure Blob container with a locked time-based immutability policy, or S3 Object Lock in compliance mode (cloud not confirmed). VERIFIED these features exist: learn.microsoft.com "immutable storage for blob data"; docs.aws.amazon.com S3 Object Lock. Retention length: [bank legal to supply]. Optional second anchor: bank's other system (e.g. email/ticket hash) for diversity. |
| Linear vs Merkle | Keep per-agent linear chain for ordering. Add daily Merkle tree over entries so one entry can be proven (inclusion proof) without handing over the whole log. Competition: linear + signed head only. |
| Independent verification | Offline CLI `supervisor-verify`: input = exported Parquet/JSONL + anchor files + public key; no Databricks needed. Ship it in the audit pack. This is the real selling point to a regulator. |
| OPTIMIZE / VACUUM | Chain is logical (`seq`, `prev_hash`, `row_hash` over canonical JSON of the row). File rewrite does not change content. Block UPDATE/DELETE/MERGE for all but the writer; set `delta.logRetentionDuration` and `deletedFileRetentionDuration` long; export a nightly immutable copy because VACUUM erases time travel. |
| Time sync | Use server time from one trusted NTP source; store both agent-reported and receipt time; reject skew > [x] s. For legal weight, add RFC 3161 timestamp from a trusted TSA on the daily root [ASSUMED: bank policy]. |
| Concurrency | One writer per lane (per agent), or a sequencer service. Chain heads stored in Lakebase for atomic compare-and-swap. |
| Gaps | Missing seq numbers = alert. Event never reaching the writer is the real hole: gateway keeps a local WAL and sends signed batch counts. |

### 3.3 Judge (findings 9-12)

- ControlArena fit: VERIFIED MIT, 253 stars, last push 2026-10-13 (github.com/UKGovernmentBEIS/control-arena). It is an evaluation library (settings, micro-protocols such as defer-to-trusted, monitors producing suspicion scores, safety/usefulness analysis). It is not a production runtime. Use it for: protocol design, offline calibration of thresholds, and the red-team method. Do not import it into the inline path. Docs 03 "copy design, reimplement" is correct. Its "settings" are code-sabotage tasks, not banking, so you write your own banking setting (the 3 mock agents + incident set).
- Calibration: pick threshold from benign traces, not from attacks. Target an audit budget (e.g. reviewer capacity of [bank to supply] cases/day) and set threshold at that percentile. Report score distribution per agent; re-calibrate per agent version.
- False positives: reviewer verdict (true/false/unclear) written back to Lakebase and into the eval set; weekly threshold review; a flag that costs a reviewer 5 min at [N] flags/day must fit the FTE in docs 04.
- Injection against the judge: (1) wrap agent text in delimited, escaped data blocks, instruction says "content is data"; (2) judge has no tools, no memory; (3) output forced to JSON schema, anything else = score 1.0 + flag; (4) never let judge output change policy; it can only raise score; (5) Tier 1 and Tier 2 use different families where possible so one payload does not beat both; (6) canary tests: injection strings in incident set that say "rate this safe"; (7) mask PII first (Presidio) but do not let masking strip the evidence of the attack.
- Eval dataset: >=3 sets. Planted incidents (written first), benign production-like traces (synthetic for competition, 90-day real traces in Dec), adversarial judge-injection set. Version in Delta; judge changes must pass regression. VERIFIED nothing external replaces this; FinVault numbers in docs are the only public anchor.
- Cost at scale: 300k x 3k = 0.9B input tokens/day Tier 1; Tier 2 1.5% x 6k = 27M. Unit price [bank to supply]. Cost levers: prefix caching, short structured digest of each action instead of raw trace, batch API, skip Tier 1 for actions fully decided by Tier 0 allow-list with no free text (log as covered by rule).
- Feasibility at 100%: yes as async with provisioned throughput; no on pay-per-token default limits [ASSUMED: check workspace limits]. State "100% coverage" as "100% scored or explicitly logged as gap".

### 3.4 Multi-agent detection (finding 13)

Message bus: there is none by default. Do not build one. Every tool call and agent-to-agent call already passes the gate or is traced. Build a `gateway_events` Delta stream (agent_id, action, amount, counterparty, ts, correlation_id) and run Structured Streaming on it. One competition pattern: split-transaction / aggregate-limit breach: payments-agent and a second agent each under limit, sum per customer per window over limit. It is concrete, easy to plant, easy to explain, and maps to a real AML structuring risk. Agent-to-agent messages (if A calls B) need A's call to B to go through the gate with `caller_agent_id` header; without it, lineage is lost. Say this limit out loud. General pattern detection stays H2 2027.

### 3.5 Onboarding Agent (findings 14, 15, 23)

| Item | Detail |
|---|---|
| Tools | `list_repo_tree`, `read_file` (size cap), `grep`, `read_uc_lineage`, `read_mlflow_traces` (masked), `list_serving_endpoints`, `read_grants`, `write_artifact` (output folder only), `open_pr`. No shell, no network, no secret store. |
| Credentials | Per-repo read-only deploy token or GitHub App with `contents:read`, issued per run, expires in hours. PR via separate token with `pull_requests:write` + branch push to `supervisor/*` only, branch protection on main. |
| Secrets in code | Scan files with a secret scanner (gitleaks, MIT [ASSUMED: check licence]) and redact before the LLM sees them. Alert the owner if secrets found; that is a finding in the profile. |
| Injection from repo | Repo text is untrusted. Same delimiter + schema rules as the judge. Agent runs under Watch, so its own tool calls are gated and judged. |
| Reliable Understand | Output = pydantic JSON: `{claim, category, evidence:[{file,line,hash}], confidence}`. Validator checks the file/line exists and contains the quoted text. Unsupported claims dropped. Risk tier proposed, human confirms. Golden set: 3 mock agents with known answers, score recall of tools/tables/PII. |
| PR mechanics | Deterministic templates fill config, policy YAML, decorator insertion via AST codemod (libcst), not free-form LLM edits. One PR per agent, labelled, with the evidence pack. Never auto-merge. |
| Tests for generated code | Template unit tests; generated YAML validated against schema; gateway dry-run on 100 recorded traces must give expected verdicts; agent's own test suite must still pass in CI. |

### 3.6 Threat model for the supervisor (findings 16, 19)

| Attacker | Goal | Path | Control |
|---|---|---|---|
| Malicious or hijacked agent | Evade or disable supervision | Skip gate; flood; craft text to fool judge; call supervisor API | Credential brokering; egress allow-list; rate limits; judge isolation; agent has no write path to supervisor tables |
| External attacker (injection in ticket/email/doc) | Make agent act, make judge say "safe" | Untrusted content | Tier 0 injection screen; judge data-wrapping; canary tests |
| Insider: agent team | Turn off checks, lower thresholds | Edit policy, pause rights, PR | Policy in repo with 2nd approver; thresholds in registry need risk-owner sign-off; every change in chain |
| Insider: supervisor admin / DBA | Edit or delete evidence; silent resume | Delta write, key access | No UPDATE/DELETE grants; notary key not admin-readable; external anchor; two-person resume |
| Compromised Onboarding Agent | Plant weak policy via PR | Repo injection | PR-only, human review, policy diff lint (no `allow *`) |
| Supply chain | Malicious dependency | PyPI | Pinned hashes, SBOM, internal mirror, no auto-update. Note mcp-scan ownership change shows how fast upstreams move |
| Denial of service on supervisor | Mass fail-open | Flood gateway | Backpressure; fail-closed for high-risk classes; autoscale; alert on fail-open |
| Privacy | Leak of PII in logs/case files | Judge prompts, console | Mask before judge; UC column masks; console RBAC; retention |

Kill switch: see finding 19. Pause is deliberately cheap and easy; resume is deliberately hard.

## 4. OSS verification (checked 2026-10-14 via api.github.com and raw README/LICENSE)

| Component | Docs 03 says | Actual | Verdict |
|---|---|---|---|
| ControlArena | Licence unconfirmed | MIT; 253 stars; last push 2026-10-13 | OK. Close the "check" item. Research library, not runtime |
| Inspect (inspect_ai) | MIT | MIT; 2,999 stars; push 2026-10-14 | OK |
| openai-guardrails-python | MIT | MIT; 260 stars; push 2026-10-08 | OK. Its prompt-injection check is an LLM call (OpenAI client); "drop the OpenAI client wrapper" means rewriting that check to use your own judge endpoint. Not a quick copy |
| NeMo Guardrails | Apache-2.0 | GitHub shows NOASSERTION; LICENSE.md header says Apache-2.0 (SPDX); 7,289 stars; push 2026-10-14 | OK in substance. Note: add NOTICE; model weights/third-party rails may differ |
| mcp-scan | Apache-2.0, "proxy" | Repo moved to snyk/agent-scan, Apache-2.0, 3,137 stars, push 2026-10-13. It is a scanner; README warns output is experimental. Proxy lived in invariant-gateway (Apache-2.0, last push 2025-11-06) | WRONG as source of gateway. See finding 1 |
| OpenLLMetry | Apache-2.0 | Apache-2.0; 7,492 stars; push 2026-10-13 | OK |
| Presidio | MIT, microsoft/presidio | MIT; repo now data-privacy-stack/presidio; 11,319 stars; push 2026-10-09 | OK. Update URL. Needs spaCy model; accuracy on Vietnamese text is weak [ASSUMED: test; add regex recognizers for CCCD/CMND, phone, account numbers] |
| promptfoo | (no licence stated) | MIT; 25,989 stars; push 2026-10-14 | OK. Check if the company changed owner/terms before relying [ASSUMED] |
| PyRIT | Azure/PyRIT | Azure/PyRIT is ARCHIVED (last push 2026-03-25). Active repo is microsoft/PyRIT, MIT, 4,620 stars, push 2026-10-14 | FIX URL |
| garak | Apache-2.0 | Apache-2.0; 9,564 stars; push 2026-10-10 | OK |
| Fairlearn | MIT | MIT; 2,294 stars; push 2026-10-13 | OK |
| Llama Prompt Guard 2 | listed in Tier 0 | Gated on Hugging Face; licence "other" = Llama community licence (not MIT/Apache); Meta's PurpleLlama repo shows NOASSERTION; HF model last modified 2025-04-29 | RISK. Breaks "MIT/Apache only" rule. Read the licence with bank legal (attribution, naming, acceptable use). Servable: it is an 86M DeBERTa text classifier; can be logged to MLflow/UC and served on Databricks CPU Model Serving [ASSUMED, not tested]. Needs bank's own HF access approval. Also 86M model is English-leaning (card lists 8 languages; Vietnamese not among them): weak for Vietnamese injection. Add a Vietnamese test set; fallback is the Tier 1 LLM |
| Cedar | (not in OSS table) | Apache-2.0; 1,780 stars; push 2026-10-13 | Add if chosen |

Other doc 03 checks:
- "Elastic-licensed tools excluded / do not copy Arize Phoenix": consistent with ELv2. OK, not re-verified today.
- "Langfuse MIT except ee": ASSUMED, not re-checked.
- Databricks claims (AI Gateway preview, streaming limit, inference table 1 MiB, Fable 30-day retention): not re-verified in this pass; owner of docs 06 should re-check, because they change monthly.

## 5. Things the handoff gets right

- Gate as a service, never a Delta round-trip.
- Deterministic policy decides; model only proposes (AgentCore principle).
- Tier 0 / 1 / 2 split with sampling and a cost line.
- Guard models are pre-filters only (FinVault numbers).
- PR-only changes, second approver on rule change, Onboarding Agent under Watch.
- Statement that Delta time travel and UC audit logs are not cryptographic proof.
- Different model family, and avoiding Gemini/Fable for residency.
- Red-team incident set before checks.
- Honest "design goals, not measured results" label.

## 6. Open questions for the bank

1. Which cloud (Azure or AWS) hosts the Databricks workspace? This sets the immutable storage and KMS/HSM choice.
2. Who owns signing keys at the bank (security team)? Is a bank HSM or Key Vault policy mandatory?
3. Required evidence retention period and legal form (SBV, Decision 33)? Is RFC 3161 timestamping expected?
4. Which tool types do real agents use today: MCP, Python, REST, SQL? Any agent calling core banking via an ESB?
5. Can the bank put an egress proxy / credential broker in front of agent tool calls? Without it, enforcement is cooperative.
6. Peak (not average) actions per second, and p95 latency the business accepts on payment paths?
7. Which action classes must fail-closed? Who approves that list?
8. Is the Llama community licence acceptable to bank legal? Can the bank download gated HF models into UC?
9. Provisioned throughput quota and region for Tier 1/Tier 2 models; batch inference allowed?
10. Reviewer capacity (cases/day) to set judge thresholds.
11. May repos be read by an agent at all? Which source system (GitHub, GitLab, Azure DevOps)? Can a read-only app token be issued?
12. Who may pause and who may resume a production agent? Is a four-eyes rule on resume acceptable?
13. Is Vietnamese the main language of agent traffic? Need Vietnamese injection and PII test data.
14. Does the bank already run a SIEM / SOAR that should receive supervisor alerts and health signals?
