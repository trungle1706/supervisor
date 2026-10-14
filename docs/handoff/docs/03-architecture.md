# 03 · Architecture and build-vs-copy decisions

## What Databricks already provides (verified Oct 2026)

| Need | Databricks native | Notes |
|---|---|---|
| Trace capture | MLflow 3 Tracing → Unity Catalog Delta tables; SQL access, table-level permissions | Recommended storage; "Store OpenTelemetry traces in Unity Catalog" doc exists |
| Judges on live traffic | MLflow scorers (LLM judges or code checks) run against production traffic | Built-in judges include groundedness, relevance, safety, guideline adherence |
| Model-boundary guardrails | AI Gateway safety + PII (block or mask); Public Preview; output guardrails don't support streaming | A newer "Unity Gateway" is the recommended control plane; build against whatever the workspace has |
| Request/response logs | Inference tables (Delta via UC); payloads > 1 MiB not logged; data appears < 1 hour | Not usable inline |
| Console | Databricks Apps (SSO), Lakebase for write-back | |
| Drift / metrics | Lakehouse Monitoring with custom metrics and slicing | |
| Models | Foundation Model APIs: Claude (Haiku/Sonnet/Opus 5.5; Fable retains prompts 30 days), GPT-5.x, GPT OSS 120B/20B, Llama 4 Maverick / 3.3 70B / 3.1 8B, Gemma 3 12B, Qwen3.5 122B A10B, DeepSeek V4.x, GLM 5.3; Gemini on global endpoint (cross-region) | Provisioned throughput recommended for production; check region availability |

## Component sourcing

| Layer | Decision | From | Effort |
|---|---|---|---|
| Instrumentation | Adapt | MLflow autologging; OpenLLMetry (Apache-2.0) for non-Databricks agents | Days |
| Agent identity registry | Build (small) | Delta table keyed by agent ID + version; follows Anthropic's persistent-identity pattern | Days |
| Fast-lane gateway | Copy pattern | Invariant mcp-scan proxy (Apache-2.0); rewrite as a thin service on Model Serving or container | 1 week |
| Fast-lane checks | Copy code | OpenAI Guardrails (MIT): PII, secrets, jailbreak, prompt injection on tool calls/outputs, custom prompt check; drop the OpenAI client wrapper | Days |
| Dialog/topic rails | Copy selectively | NeMo Guardrails (Apache-2.0), customer-service agent only | Days |
| Judge protocol | Copy design, reimplement | UK AISI ControlArena (runs on Inspect, MIT); MLflow custom scorers; judge on Model Serving | 1–2 weeks |
| Enforcement principle | Copy | AWS Bedrock AgentCore: "the model proposes, deterministic policy decides" (Cedar policies at the gateway) | — |
| PII masking before judge | Copy | Microsoft Presidio (MIT) in a UDF on the trace table | Days |
| Quality monitor | Native + copy | MLflow judges; Fairlearn; promptfoo or PyRIT red-team harness; OWASP Agentic Top 10 + FinVault taxonomy | 1 week |
| Drift detector | Build on native | Lakehouse Monitoring custom metrics, baseline band per version | 1 week |
| Multi-agent combo check | Build | Spark Structured Streaming over message-bus table | 1 week (stretch) |
| Tamper-evident log | Build | Hash-chain column on append-only Delta + periodic anchors to write-once location (Delta time travel and UC audit logs are not cryptographic proof) | 1 week |
| Case-file generator | Build | Template + judge summary; sign-off in Databricks App; stored in Lakebase + vault | 1 week |
| Reviewer console | Build on native | Databricks App; RBAC via UC groups | 1–2 weeks |
| Onboarding Agent | Build | Agent on the judge stack; tools: repo/App/MLflow/UC readers, artefact writers, PR opener | 2–3 weeks (Discover/Understand/Plan for competition; Instrument template-driven; Launch automation December) |
| Capability catalogue | Build | Plug-in manifests modelled on MCP tool schemas | 1 week |

## Licences

Copy/modify freely: OpenAI Guardrails, Presidio, Inspect (MIT); NeMo Guardrails, mcp-scan, OpenLLMetry, Opik (Apache-2.0, keep notices); Langfuse MIT except `ee` folders. **Do not copy Arize Phoenix** (Elastic License 2.0). ControlArena licence not confirmed; check.

## Open-source repos referenced

ControlArena + Inspect (UKGovernmentBEIS), openai/openai-guardrails-python, NVIDIA-NeMo/Guardrails, invariantlabs-ai/mcp-scan, langfuse/langfuse, traceloop/openllmetry, microsoft/presidio, comet-ml/opik, promptfoo, Azure/PyRIT, NVIDIA garak, fairlearn.

## Risks specific to this deployment

- Platform independence vs Databricks-native: keep OpenTelemetry as the contract so non-Databricks agents can be supervised.
- Inline latency: fast lane as a service, not a job over Delta.
- Judge cost: rules on everything, Tier 1 on everything, Tier 2 on 1.5%; 100% Tier 2 only for high-risk agents.
- Region/residency: confirm workspace region and servable judge models; no Gemini (global endpoint); no Fable (retention).
- Moving target: legacy AI Gateway vs Unity Gateway.
- Fairness attributes: which attributes may be sliced is a legal decision before an engineering one.
- Onboarding Agent writes code: PR only, human merge, second approver on rule changes.

## Where a bought product plugs in later

Registry suite above (ServiceNow Control Tower, IBM, Microsoft Agent 365): approved agents in, case files out. Security gateway in front (Prisma AIRS, Cisco, Noma): cleaned traffic in; we still judge business behaviour. GRC tool beside (Credo AI, bank's GRC): consumes the audit pack. None replaces judge, drift, evidence chain or Onboard.
