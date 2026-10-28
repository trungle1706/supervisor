# Agent Factory for a Bank Governance Platform: Industry Practice (research, 2026-10-28)

Scope: how enterprise platforms let non-engineers build, test and roll out assessment agents, and how user groups author runtime "guardian" checks. Sources are official docs where available; vendor marketing is marked.

## (a) Comparison table

| Platform | Who authors | How the agent is defined | How tested | How promoted | What is bounded (locked) |
|---|---|---|---|---|---|
| Databricks Agent Bricks / MLflow 3 GenAI [1][2][3] | Data/ML teams; SMEs label via Review App | Code (Agent Framework) + declarative judges; plain-language `Guidelines()` pass/fail criteria | Built-in judges (correctness, groundedness, safety), custom guideline judges, evaluation datasets grown from traces + SME labels; `mlflow.genai.evaluate()`; same scorers on production sample | MLflow version compare; Unity Catalog registration | Judges, tracing, dataset schema are platform-owned; guideline text is the user's |
| Microsoft Copilot Studio + M365 declarative agents [4][5][6][7] | Makers (low-code) | Declarative manifest v1.7: `name`, `description`, `instructions`, `capabilities[]` (typed), `actions[]` (max 12 API plugins), `behavior_overrides`, `user_overrides` | Foundry cloud evaluation (agent target/response/trace, red team, synthetic data); human evaluation with reviewer templates | Solution export as managed package; Power Platform pipelines Dev->Test->Prod; admin publishing/activation/update approval in Agent Registry | Capability types, tenant metering, max actions; instructions editable |
| Salesforce Agentforce [8][9] | Admins (no-code Agent Builder) | Topics: label, classification description, scope, instructions; actions from Flow/Apex/prompt templates with NL input/output descriptions | Testing Center: CSV of utterance + expected topic/action API names; AI-generated test cases; Plan Tracer; batch re-run | Sandbox -> production via metadata; version per agent | Topic/action schema fixed; reasoning engine locked; standard topics read-only |
| OpenAI AgentKit (Agent Builder, Evals, Guardrails, Connector Registry) [10][11][12] | Developers + product teams | Visual canvas; nodes incl. agent, guardrail, MCP, approval; export to Agents SDK code | Trace graders, datasets, prompt optimization | Publish = snapshot major version; API targets version | Connector Registry admin-controlled; Guardrails JSON config (preflight/input/output). Note: Agent Builder shutdown announced for 2026-11-30 [10]; Evals API read-only 2026-10-31 [13] |
| Google Vertex AI Agent Builder / ADK / Agent Engine [14][15] | Developers | ADK code; Agent Engine runtime | GenAI Client evaluation, user simulator, Cloud Trace | `adk deploy`; Agent Engine versions | Runtime, memory, sessions managed; ADK in preview |
| Amazon Bedrock AgentCore (Gateway, Policy, Evaluations) [16][17][18] | Developers; compliance/security write policies in English | Agent code + Gateway tool schema; Cedar/Dogwood policies generated from natural language | 13 built-in evaluators + custom model-based; policy schema check + automated reasoning (over-permissive, unsatisfiable); LOG_ONLY mode before enforce | Policy engine attached to Gateway; CloudWatch audit | Every tool call intercepted outside agent code; deterministic permit/forbid incl. temporal (approval-before-transfer, budgets) |
| LangGraph Platform / LangSmith [19][20][21] | Developers; prompt hub for shared prompts | Code graphs; prompts versioned with tags/commits | Datasets of examples; offline regression tests; LLM-as-judge via SDK or UI; online evals on traces | Prompt commit tags; CI gate on dataset score (community pattern) | Nothing bounded by default; conventions only |
| IBM watsonx.governance [22][23] | Risk/governance teams + developers | Governed agentic catalog: register agents/tools (UI or SDK), external endpoints | Agent metrics (context relevance, faithfulness, HAP, PII, prompt injection); compare two agents side-by-side | Lifecycle states in catalog | Catalog schema, metric set |
| ServiceNow AI Control Tower [24][25] | Governance admins | Registry of systems, models, prompts, datasets, MCP servers with risk class | Monitoring (accuracy, hallucination, cost), bias/drift checks | Policy + approval routing; review/approve before external marketplace submission | Registry fields, lifecycle phases |
| Saidot / Credo AI / Holistic AI [26][27][28] | Legal, risk, responsible-AI teams | Saidot: Agent Catalogue (purpose, autonomy level, tool access, inherited risks), library of 260+ risks/620+ controls/110+ policies; Credo: policy packs as executable controls; Holistic: Agent Graph, Sentinel/Operative agents | Assessment questionnaires and evidence; Holistic runtime threshold checks (vendor claims) | Human approve; "agents draft, people decide" (Saidot) | Controls and policy mappings are curated; outputs are assessment records |
| NeMo Guardrails (Colang) [29][30] | Developers; policy text by SMEs | `config.yml` + Colang flows; policies with ID + NL description | `nemoguardrails eval`: interaction sets, expected outputs (general/refusal/similar), LLM-judge compliance rate, latency, token cost, Eval UI | Config version in repo | Rail types (input/output/dialog/retrieval) |
| Guardrails AI Hub / Lakera / Bedrock Guardrails / Azure custom categories [31][32][33][34] | Developers (Hub), security teams (Lakera), admins (Bedrock console) | Validator class `validate()` -> Pass/Fail; Lakera policy per project with L1-L4 sensitivity + allow/deny lists; Bedrock denied topics, word filters, working draft -> version; Azure category = name + definition + >=50 positive samples | pytest template; Lakera 4-phase eval (attack set, benign set, TPR/FPR, integration); Bedrock test window; Azure hold-out eval | Hub submission; Bedrock immutable versions referenced by ID; Azure 3 versions/category | Validator interface; detector thresholds |

## (b) Ten design principles that recur

1. **Declarative shell, locked runtime.** Authors edit text fields (instructions, topics, guidelines); the platform owns the loop, tracing, judges and tool dispatch (Copilot manifest [5], Agentforce topics [8], Agent Skills [35]).
2. **Small, typed manifest with limits.** Required `name`/`description`, bounded lengths (Skills: 64/1024 chars [35]), bounded lists (Copilot: 12 actions [6]), typed capabilities, JSON Schema published per version [7].
3. **Tools are registered centrally and permissioned, not declared by the agent.** Connector Registry [11], AgentCore Gateway [16], MCP registry `server.json` with `isSecret`/`isRequired` env vars [36], Skills `allowed-tools` [35].
4. **Policy enforcement sits outside agent code.** AgentCore Policy intercepts every tool call at the Gateway with deterministic Cedar; guardrails signals feed policy decisions [16].
5. **Natural language in, formal artifact out, validated.** NL -> Cedar with schema check and automated reasoning for over-permissive/unsatisfiable rules [18]; NL guidelines -> yes/no judge with rationale [3].
6. **Golden set + LLM judge + human labels, versioned together.** Datasets grow from production traces, SMEs label in a review app, judges are calibrated against those labels [1][3][19]; kappa not raw agreement [37].
7. **Gate on deltas and deterministic checks, warn on judge noise.** Absolute floors like "mean > 0.7" miss regressions; use baseline comparison, significance, effect size; promptfoo weighted thresholds and DeepEval per-metric thresholds exist but need judge validation [38][39][40].
8. **Log-only / shadow before enforce.** AgentCore LOG_ONLY [18], Bedrock working draft + test window [33], Lakera benign-set FPR phase [32], Langfuse/MLflow online scoring on sampled traffic [1][13].
9. **Immutable versions and approval gates.** Publish = snapshot (OpenAI [10], Bedrock guardrail versions [33]); managed solutions read-only in Test/Prod with admin approval for publish/activate/update [4][7].
10. **Progressive disclosure and bounded context.** Load only name/description at start, body on activation, references on demand; keep SKILL.md under 500 lines [35].

## (c) Recommended design: Assessment Agent factory for the bank

### Agent definition schema (one YAML/JSON object, JSON Schema published per version)

```yaml
schema_version: "1.0"
id: model-risk-assessor            # lowercase-hyphen, <=64, immutable
name: "Model Risk Assessment Agent"
description: "<=1024 chars: what it assesses and when to use"
owner_group: model-risk            # user group; drives RBAC
risk_tier: high                    # platform-set from use; controls gates
policy_refs:                       # locked references to governed documents
  - {doc_id: "SBV-2345-2024", version: 3, sections: ["Art.5","Art.7"]}
checklist:                         # the assessment rubric
  - id: MR-01
    question: "Is the model owner and validator independent?"
    evidence_required: [doc, system_record]
    severity: high
    pass_rule: "both named; different org units"
evidence_rules:
  allowed_sources: [confluence_space:MRM, jira_project:MOD, databricks_catalog:risk]
  must_cite: true
  max_age_days: 365
tools:                             # references to the central tool registry only
  - {tool_id: search_documents, scope: "space:MRM", mode: read}
  - {tool_id: fetch_model_card, mode: read}
instructions: |                    # free text, <=5000 tokens, lint-checked
  ...
output_schema:                     # fixed by platform template; agent fills values
  type: assessment_report_v1
  fields: [finding_id, checklist_id, verdict(pass|fail|n/a), evidence[], rationale, confidence]
guardians: [pii_mask_v2, tool_scope_guard, citation_required]   # mandatory set + optional
eval_pack: model-risk-golden-v4    # dataset + judges + thresholds
lifecycle: {state: draft, version: 0.3, approvals: []}
```

Locked by platform: schema keys, output_schema types, mandatory guardians, tool registry reference (no inline tool definitions), model/runtime, tracing. Editable by the risk team: description, policy_refs, checklist, evidence_rules, instructions, tool selection within their group's allow-list, eval pack contents. Pattern borrowed from Copilot manifest typed capabilities [5], Agentforce topic/instruction split [8], Skills frontmatter [35], A2A AgentSkill `id/name/description/tags/examples` for catalog listing [41].

### Authoring UI steps (no-code)

1. Pick template (model-risk, data-governance, cyber, legal-compliance, third-party, ethics/bias).
2. Attach governed policy documents and select sections (creates `policy_refs`).
3. Build checklist in a table editor; each row = question, evidence types, severity, pass rule.
4. Choose tools from the group's allow-list (registry shows scope, data class, owner).
5. Write instructions with a linter (length, forbidden phrases, must reference checklist).
6. Pick guardians (mandatory ones pre-checked and not removable).
7. Preview against 3-5 sample cases with Plan Tracer-style view (topic -> tool -> evidence -> verdict) [8].
8. Build eval pack: upload golden cases (CSV/JSON), define guideline judges in plain language, set thresholds; submit for test.

### Test harness

- **Datasets**: golden set per agent (min 50 cases; stratified by checklist item and expected verdict), adversarial set (prompt injection, missing evidence, conflicting documents), regression set (every past production defect). Items hold `input`, `expected_verdicts`, `expected_evidence_ids`, `rubric_notes` (Langfuse dataset JSON schemas [13]; MLflow `ExpectationsGuidelines` per-row [3]).
- **Scorers (layered)**: deterministic first (output schema valid, every verdict cites evidence, cited evidence exists and is in allowed sources, no tool outside scope, no PII in output); then LLM-judge guidelines (verdict correctness vs expected, rationale faithful to evidence, tone) returning yes/no + reason; then human spot-check sample.
- **Judge calibration**: each judge ships with a 150-300 item human-labelled set; report Cohen's kappa and confusion matrix; recalibrate on judge model change [37].
- **Thresholds**: hard gate on deterministic checks (100%); judge gate = no significant drop vs current live version (paired comparison, effect size noise floor) plus absolute floor per risk tier; flaky metrics score-only [39][40].
- **Shadow run**: candidate runs on a sample of live requests in LOG_ONLY, outputs stored but not shown; compare verdict agreement with live version and with human reviewer decisions for N days [18][1].
- **Reports**: compliance rate per checklist item, latency, token cost (NeMo eval metric set [29]).

### Promotion workflow

```
draft --(author submits)--> tested --(harness passes)--> approved --(2 approvals)--> live
  ^                            |                              |                     |
  |<---- fail: back to author  |<---- reviewer rejects -------|     rollback -------|
```

| State | Who acts | Gate |
|---|---|---|
| draft | Author (risk team maker) | Schema valid; lint passes |
| tested | Platform (CI) | Deterministic 100%; judge non-regression; adversarial set; shadow run report |
| approved | Agent owner + independent reviewer (2nd line / Model Risk for high tier; platform admin for tool scope changes) | Signed review of eval report, diff of definition, guardian set |
| live | Platform admin | Immutable version snapshot; previous version kept for one-click rollback; monitored with same scorers on sample traffic |

Changes to `tools`, `guardians`, `output_schema` or `risk_tier` always require re-approval; changes to `instructions`/`checklist` require re-test and owner approval (pattern: Copilot publish/activation/update approvals [4], Bedrock immutable versions [33]).

### Reuse from open source

| Need | Library | License |
|---|---|---|
| Definition format and validator | Agent Skills `skills-ref` conventions (frontmatter, progressive disclosure) [35] | Apache-2.0 (spec repo) |
| Catalog card for discovery | A2A AgentCard / AgentSkill shape [41]; MCP `server.json` for tool registry entries [36] | Apache-2.0 / MIT |
| Eval runner, datasets, judges | promptfoo (MIT) for declarative assertions and CI gates; DeepEval (Apache-2.0) for pytest-style metrics with thresholds and G-Eval [38][39][40] | MIT / Apache-2.0 |
| Tracing, datasets, LLM-judge, prompt versions | Langfuse (MIT core, some EE features commercial) [13][40]; MLflow 3 GenAI (Apache-2.0) if Databricks is in use [1] | MIT / Apache-2.0 |
| Rigorous task/solver/scorer evals | Inspect AI (UK AISI, MIT) [42] | MIT |
| Traces and experiments UI | Arize Phoenix (Elastic License 2.0, not OSI; avoid if resale) [40] | ELv2 |
| Tool-call policy | Cedar policy language (Apache-2.0) as used by AgentCore Policy [16] | Apache-2.0 |

## (d) Guardian / detector authoring by user groups

**Definition schema**: `id`, `name`, `description`, `owner_group`, `type` (regex | keyword-list | classifier | llm-judge | cedar-policy), `stage` (preflight | input | tool_call | output), `scope` (agents, tools, data classes), `config` (pattern, sample set, judge prompt, policy text), `action_on_fail` (block | redact | require_approval | log), `sensitivity` (L1-L4), `benchmark_pack` (attack set, benign set), `thresholds` (min TPR, max FPR, max added latency), `lifecycle`. This mirrors Guardrails AI validator interface [31], Lakera policies with sensitivity levels and allow/deny lists [32], OpenAI Guardrails stage model [12], AgentCore permit/forbid with temporal conditions [16].

**Authoring steps**: 1) choose detector type; 2) write the rule in plain language, platform generates the formal artifact (regex, Cedar, judge prompt, or category definition with >=50 positive samples per Azure practice [34]); 3) platform validates (schema, unsatisfiable/over-broad rule check as AgentCore does [18]); 4) select scope and fail action; 5) run benchmark.

**Test harness**: attack set (true positives), benign set drawn from production traces (false positives), report TPR/FPR/precision at each sensitivity level, p95 latency, cost; compare to the live detector [32]. Gate: FPR below group-set limit on benign set, TPR above floor, latency budget met.

**Promotion**: draft -> benchmarked -> shadow (LOG_ONLY on live traffic, N days, review flagged items) -> approved (owner + platform security) -> live as immutable version attached to agents by ID+version [18][33]. Allow/deny lists are temporary overrides with expiry [32].

## (e) Risks and anti-patterns

1. **Judge without calibration**: high raw agreement hides near-zero kappa; a CI gate at 85% passed production bugs [37][40].
2. **Absolute score floors** as the only gate; use paired deltas vs live version [40].
3. **Inline tool definitions in agent text**: bypasses registry permissions; keep tools by reference only [11][16].
4. **Guardrail in the agent prompt instead of outside**: manipulable; enforce at the gateway [16].
5. **Default paranoid sensitivity**: Lakera warns L4 everywhere yields high FPR; tune per project [32].
6. **Allow-lists as permanent fixes** [32].
7. **Unbounded manifests**: prompts that grow past a few thousand tokens; keep body short, references loaded on demand [35].
8. **Vendor lock on preview products**: OpenAI Agent Builder and Evals API shutting down Nov 2026; Azure custom categories (standard) retiring Sep 2026; AgentCore Policy/Evaluations still preview [10][13][34][17]. Keep definition and eval data in open formats.
9. **Marketing claims as design input**: Holistic AI Sentinel agents, Vanta "95% accuracy" are vendor statements [28][43].
10. **Skipping human review for high tier**: every platform with regulated users keeps a human approval step (Copilot admin approval, Saidot "people decide") [4][26].
11. **Judge uses third-party LLM** that may not be allowed for bank data (Databricks note) [2]; route judges through the bank's approved model endpoint.

## Sources

[1] https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/
[2] https://docs.databricks.com/generative-ai/agent-evaluation/index.html
[3] https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/concepts/judges/guidelines
[4] https://microsoft.github.io/zerotrustassessment/docs/workshop-guidance/AI/AI_154
[5] https://learn.microsoft.com/en-us/microsoft-365-copilot/extensibility/declarative-agent-manifest
[6] https://learn.microsoft.com/en-us/microsoft-365-copilot/extensibility/declarative-agent-manifest-1.4
[7] https://developer.microsoft.com/json-schemas/copilot/declarative-agent/v1.7/schema.json ; https://learn.microsoft.com/en-gb/microsoft-Copilot-studio/guidance/sec-gov-phase2 ; https://microsoft.github.io/mcscatblog/posts/alm-copilot-studio-agents-foundation/
[8] https://developer.salesforce.com/blogs/2025/01/how-to-write-effective-natural-language-instructions-for-agentforce
[9] https://trailhead.salesforce.com/content/learn/modules/agentforce-specialist-certification-maintenance-summer-25/get-up-to-date-on-agentforce-concepts
[10] https://developers.openai.com/api/docs/guides/agent-builder
[11] https://openai.com/index/introducing-agentkit/
[12] https://openai.github.io/openai-guardrails-python ; https://github.com/openai/openai-guardrails-python
[13] https://langfuse.com/resources/engineering/migrate-from-openai-evals ; https://langfuse.com/changelog
[14] https://docs.cloud.google.com/agent-builder/agent-engine/evaluate
[15] https://cloud.google.com/blog/products/ai-machine-learning/more-ways-to-build-and-scale-ai-agents-with-vertex-ai-agent-builder/
[16] https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html
[17] https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-bedrock-agentcore-policy-evaluations-preview
[18] https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-validate-policies.html
[19] https://docs.langchain.com/langsmith/evaluation-types
[20] https://docs.langchain.com/langsmith/prompt-engineering
[21] https://www.markaicode.com/langsmith-cicd-automated-regression-testing/ (community pattern)
[22] https://jp-tok.dataplatform.cloud.ibm.com/docs/content/wsj/analyze-data/gov-agent-catalog.html?context=wx
[23] https://www.ibm.com/new/announcements/ibms-answer-to-governing-ai-agents-automation-and-evaluation-with-watsonx-governance
[24] https://www.servicenow.com/community/now-assist-forum/ai-control-tower-the-one-central-hub-to-govern-every-ai-in-your/td-p/3569187
[25] https://newsroom.servicenow.com/press-releases/details/2026/ServiceNow-expands-AI-agent-governance-through-deeper-integration-with-Microsoft/
[26] https://www.getapp.com/all-software/a/saidot/ (vendor listing)
[27] https://www.credo.ai/glossary/credo-ai-policy-pack ; https://www.credo.ai/product
[28] https://holisticai.com/ai-governance-platform (vendor)
[29] https://docs.nvidia.com/nemo/guardrails/latest/evaluation/index.html
[30] https://docs.nvidia.com/nemo/guardrails/latest/colang-2
[31] https://guardrailsai.com/docs/hub/concepts/validators ; https://guardrailsai.com/docs/cli
[32] https://docs.lakera.ai/docs/policies ; https://docs.lakera.ai/docs/evaluation-overview ; https://docs.lakera.ai/docs/allow-deny-lists
[33] https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html
[34] https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/custom-categories
[35] https://agentskills.io/specification ; https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
[36] https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/generic-server-json.md
[37] https://arxiv.org/abs/2510.09738 ; https://galileo.ai/blog/calibrate-llm-judge-human-annotations ; https://oneuptime.com/blog/post/2026-08-31-calibrate-llm-judge-cohens-kappa/view
[38] https://www.promptfoo.dev/docs/configuration/expected-outputs/
[39] https://deepeval.com/docs/metrics-introduction
[40] https://laoujin.github.io/Atlas/research/2026-06-09-evals-vibes-don-t-scale-a-complete-technical-session-blueprint/wiring-evals-into-ci/ ; https://dev.to/ethanwritesai/promptfoo-is-a-ci-gate-not-an-eval-framework-treating-it-like-one-cost-us-4200-2i67 ; https://aadhar-build.github.io/llm-evals-comparison/frameworks/ (licenses)
[41] https://a2a-protocol.org/latest/specification/
[42] https://inspect.aisi.org.uk
[43] https://vanta.com/compare/drata (vendor)
Also: https://agents.md/ (AGENTS.md, no fixed schema); https://www.llama.com/docs/model-cards-and-prompt-formats/llama-guard-4/ (custom category list in prompt, safe/unsafe output); Flowise sunset noted at flowiseai.com/sunset (unverified); Dify is source-available (not OSI), n8n Sustainable Use License, CrewAI core MIT.

Notes on evidence quality: Salesforce help pages and Agentforce DX docs returned 403; Salesforce facts come from Salesforce developer blog and Trailhead. Saidot, Credo, Holistic AI, Vanta details are vendor or aggregator statements. Guardrails AI and NeMo Guardrails licenses (Apache-2.0) are from their GitHub repos and were not re-verified in this pass.
