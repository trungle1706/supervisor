# 05 · Market scan (vendor claims labelled as claims; Oct 2026)

Three layers: **Enforce at runtime** (ms, inline, can block), **Observe and judge** (minutes, alerts), **Govern** (weeks, registry, compliance packs). No vendor covers all three with real-time blocking; none onboards an agent; none maps to Decision 33 or MAS; tamper-evident case files are rare.

| Product | Category | Deployment | Strengths | Gaps | Fit |
|---|---|---|---|---|---|
| ServiceNow AI Control Tower (June 2026) | Platform suite | SaaS; Private Stack | Registry incl. MCP servers with approval gating; Agentic Threat Monitoring (role drift, injection, PII); EU/US compliance packs; Databricks discovery connector | Detections are findings, no runtime blocking of agent actions; needs ServiceNow | Partial |
| Microsoft Agent 365 | Platform suite | Microsoft SaaS | Entra Agent ID, Defender discovery, Purview DLP, Foundry guardrails | Strongest for Microsoft-built agents; no self-host | Partial |
| IBM watsonx.governance + Guardium AI Security | Platform suite | SaaS/on-prem | Lifecycle governance, custom I/O policies, red teaming, 12 compliance frameworks | Agent audit trails were "future"; prompt-boundary enforcement | Partial |
| Palo Alto Prisma AIRS | Security | Cloud control plane, inline | Injection/leak defence, identity control, audit trails | Security framing, no business-policy judgement | Partial |
| Cisco AI Defense | Security | Cloud-managed | Discovery, model validation, red teaming, MCP policy, Duo identity | Needs Cisco stack | Partial |
| Noma Security | Security | SaaS/self-host | Discovery, posture, runtime, tool-level policy | Not an LLM gateway; no sandbox | Partial |
| Zenity | Security | SaaS only | AISPM + AIDR; inline in Copilot Studio | Microsoft-specific enforcement; SaaS only (residency) | Weak |
| WitnessAI | Security | On-prem/cloud/edge | Network-level observation, intent policies, tokenisation | Shadow-AI focus; no containment | Weak |
| Kosmoy (claims) | Infra | Self-hosted K8s, air-gap | Registry, LLM/MCP/A2A policy gateway, sandboxed execution, kill switch | Small vendor; its own comparison | Partial |
| Databricks AI Gateway + MLflow 3 + Lakehouse Monitoring | Platform native | Bank's workspace | Our plumbing: guardrails, inference tables, UC traces, judges, Apps | No tool-call policy gateway, registry, case files or tamper-evident log | Strong |
| AWS Bedrock AgentCore | Cloud native | AWS VPC | Cedar policies decide each tool call at the Gateway; microVM per session; observability | Bedrock agents only; observability alerts, does not block | Partial (copy the principle) |
| Credo AI | GRC | SaaS | Registry (preview), policy packs, evidence | No runtime; roadmap item | Weak alone |
| LangSmith | Engineering | SaaS/hybrid/self-host | Tracing, eval, sandboxes, gateway (beta) | No inventory, no regulatory tooling; overlaps MLflow | Partial |

Requirement matrix vs the brief (✓ / ~ / –): our target build is ✓ on independence, tool-call blocking, business-policy judgement, drift, regulator evidence, self-host in Vietnam, Databricks fit; ~ on multi-agent view (one pattern in competition). Full matrix in `assets/guardian-market-scan.html`.

Recommendation: build the core; borrow AWS's "model proposes, policy decides"; keep OTel-in / case-files-out contracts so suites attach later; run two vendor PoCs in H1 2027 (security gateway in front; registry above).
