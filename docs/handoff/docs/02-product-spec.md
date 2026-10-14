# 02 · Product spec

## Positioning

Supervisor is not a compliance check bolted on afterwards. It is the thing a developer runs to launch an agent, and supervision comes with it. Brand: **Supervisor**; feature names: **Onboard** (lifecycle) and **Watch** (runtime). Tagline: *Onboard any agent. Watch every action. Prove it to anyone.*

## The plain-language analogy

Casino floor. Dealers (agents) handle money. The pit boss (Supervisor) never deals; he watches every table, steps in when a hand looks wrong, and the cameras record everything so a dispute has tape. Supervisor is the pit boss plus the cameras plus the incident report.

## Onboard: the six stages

| Stage | What it does | Output (stored in the evidence vault) |
|---|---|---|
| 1 Discover | Finds the App/endpoint, repo, prompts, model endpoints, tools, MCP servers, tables read/written (Unity Catalog lineage), existing traces | Inventory; agent registered with ID, owner, version |
| 2 Understand | Reads code, prompts, sample traces; purpose, capabilities, reversibility, personal data touched, regulations | **Agent profile** incl. risk tier (Decision 33 mapping) and known weak spots; understanding graph |
| 3 Plan | Picks checks and thresholds from the capability catalogue; drafts actions per alert | **Monitoring plan** (signals, thresholds, judges, slices, sampling, cost estimate); **remediation playbook** |
| 4 Instrument | Generates tracing hooks, gateway route, policy YAML, dashboards, alert routes | **Pull request** (never auto-merged); **data-flow map** with PII marking; **dashboard** |
| 5 Launch | Runs red-team pack in sandbox, records baseline, shadow mode → enforced mode rule by rule | **Launch report** with go/no-go evidence; integration check (8 checks) |
| 6 Operate | Hands over to Watch | Cases, metrics, audit packs |

For an already-deployed agent the flow is identical; it starts from the last 90 days of traces and the first output is an honest report of what the agent has been doing.

## Watch: five steps at two speeds

Watch (trace everything) → Check (hard rules first, AI judge for grey areas) → Spot drift (behaviour, fairness, quality vs baseline) → Act (log / alert / pause) → Prove (signed case file into a log agents cannot edit).

- **Fast lane** (< 1 s, inline, can block): limits, approved tools, permissions, injection screen, PII. Must run as a service, never via Delta round-trip.
- **Slow lane** (minutes, after the fact): full transcripts and reasoning, suspicion score, groundedness, fairness gap, multi-agent patterns, escalation to a named person.

## The components (plain names → technical)

1. **Recorder** — MLflow 3 tracing to Unity Catalog Delta tables; OpenTelemetry GenAI conventions as the contract; agent identity registry (ours).
2. **Gate** — proxy between agent and tools; YAML rules; block/allow/ask; pause switch. Design from Invariant mcp-scan; checks from OpenAI Guardrails (MIT); Llama Prompt Guard 2 for injection; Presidio for PII.
3. **Judge** — tiered: Tier 0 no-LLM, Tier 1 cheap model on 100%, Tier 2 strong model on flags + sample. ControlArena protocol: suspicion score, defer-to-trusted, shut down after repeated suspicious attempts. Different model family from agents.
4. **Drift detector** — Lakehouse Monitoring custom metrics; baseline band per agent version; opens a case when behaviour leaves the band even if no rule broke.
5. **Pattern spotter** — Spark Structured Streaming over the message bus; combined-outcome rules (e.g., two agents each under limit, together over). One pattern for competition; general in H2 2027.
6. **Quality monitor** — MLflow 3 built-in judges (groundedness, relevance, safety, guideline adherence) on live traces; fairness slicing by segment (Fairlearn for parity maths); red-team harness (promptfoo or PyRIT; OWASP Agentic Top 10 and FinVault as taxonomy); per-agent quality thresholds that gate releases.
7. **Evidence vault** — append-only Delta table with hash-chain column and periodic anchors to a write-once location; case-file generator (timeline, rule, regulatory mapping, root cause, sign-off); the supervisor's own decisions are logged here too.
8. **Reviewer console** — Databricks App with workspace SSO; Lakebase for write-back (sign-offs); Unity Catalog groups for RBAC; oversight metrics panel; audit-pack export.
9. **Onboarding Agent** — agentic workflow on the same judge stack; read access to repos/Apps/MLflow/UC; write access only to its output folder and a PR.
10. **Capability catalogue** — each capability is a plug-in with a manifest (signals needed, what it checks, default thresholds, cost). Bank and product teams can add their own (policy packs, product rules).

## Plug points

1. Databricks App or Model Serving endpoint: auto-instrumented via MLflow tracing and inference tables; full capability set.
2. Any agent with an OpenTelemetry exporter: traces to our collector, gate in front of its tools; full capability set.
3. Legacy/black-box agent: traffic through the gate as a proxy; Supervisor learns from the proxy log; reduced capability set.

## Independence guarantees

Read-only copy of traffic in; one narrow verdict out (log / alert / pause); supervisor's own actions in the same tamper-evident log; judge on a different model family; PR-only changes with second approver; the Onboarding Agent runs under Watch.

## Metrics the product reports

Deployment-to-supervised-launch (target < 1 day), coverage (100%), time to detect (< 1 s inline), time to human (< 5 min), red-team catch rate (≥ 90%), false alarm rate (< 5% of flags), log integrity (chain verified), groundedness (≥ 0.9), fairness gap (≤ 5 pts). Targets are design goals, not measured results.

## Example case file (fictional)

```
CASE SUP-2026-0142 · severity HIGH · status CONTAINED
agent payments-agent v3.2 · owner Payments Ops · onboarded 02 Nov 2026
WHAT HAPPENED
14:02:11.384  planned call to ext_transfer_api
14:02:11.391  rule PAY-07 approved tools only: FAIL
14:02:11.392  blocked · agent paused · reviewer paged
14:06:40      N. Tran confirmed injected ticket #88341
WHY IT MATTERS
PAY-07, PAY-02 · high-risk under Decision 33 (banking)
CONTROL EVIDENCE
detect-to-block 7 ms · human sign-off 4 m 29 s
log entries 4,118,902 to 4,118,911 · chain hash verified
```
Regulatory wording to be confirmed with the bank's legal and risk teams before external use.
