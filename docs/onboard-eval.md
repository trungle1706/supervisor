# Onboard code-analysis eval (WP16)

The Onboarding Agent reads an agent repository in two stages: Discover (static scan,
`onboard/discover.py` + `onboard/codefacts.py`) and Understand (profile, Decision 33 class,
autonomy, `onboard/understand.py`). Before WP16 they were tuned on our three demo agents
only. WP16 measures them on a labelled corpus of synthetic agent repos, tunes them, and
proves two safety properties: planted secrets never reach the model, and prompt injection in
repo text gets zero follow-through (ADR D12).

## Run it

```cmd
cd C:\work\supervisor
uv run python -m supervisor.onboard.eval --corpus data\corpus\repos --labels data\corpus\labels.yaml --report out\corpus-eval
uv run python -m supervisor.onboard.eval --corpus data\corpus\repos --labels data\corpus\labels.yaml --check-labels
```

Output: `report.json` and `report.md` in `--report`, an ASCII summary on screen with `[OK]` /
`[FAIL]` per gate. `--fail-on-gates` exits 1 when a gate fails; `--repo NAME` (repeatable)
limits the run. No network, mock model, deterministic (the JSON holds no time and no path).
The whole corpus runs in under 1 s on the dev host (gate: 60 s).

## Method

1. **Corpus.** 20 small synthetic agent repos in `data/corpus/repos/` (3 to 10 files each,
   realistic imports, synthetic Vietnamese data, code written for the corpus). Labelling
   rules are in `data/corpus/README.md` and were written before any repo existed.
   Four Sonnet workers wrote 16 repos and their labels in parallel. The lead reviewed every
   repo and checked every label with `--check-labels` (file, line, `def` line, needle on the
   line). One label was wrong (`income` in `dynamic_registry_ops` sits only in a prose
   string) and was removed.
2. **Baseline.** The eval ran on the unchanged analyser first:
   `data/corpus/reports/baseline.json`. Fields that the analyser did not have yet (LLM call
   sites, data access, framework, tracing kind, autonomy) were read through fallbacks
   (model endpoints in code, SQL tables, trace names).
3. **Tuning** on the 16 repos (section "What changed").
4. **Held-out check.** After tuning, a fresh worker wrote 4 more repos without reading the
   analyser or the other repos (`holdout_*`). The analyser ran on them unchanged:
   `data/corpus/reports/holdout_blind.json`. Two misses came out; they were fixed in general
   form and the final run covers all 20 repos: `data/corpus/reports/final.json`.
5. **Gates** live in one module, `supervisor.onboard.eval.gates` (WP15 imports them), and
   are asserted in `tests/onboard/test_corpus_gates.py`.

Matching rules: tools by (name, file); LLM calls and data access by file and line within 2
lines (data access also by kind); PII fields as a set per repo; framework, tracing set,
Decision 33 and autonomy as exact values per repo. Scores are micro-averaged over repos.

## Corpus

| Repo | Framework | Files | Tools | LLM calls | Data access | PII | Tracing | Secrets | Injections | Decision 33 | Autonomy |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `anthropic_dispute_helper` | anthropic_sdk | 4 | 3 | 2 | 3 | 2 | none | 0 | 0 | not_high_risk | L2 |
| `approval_gate_transfer` | custom | 5 | 2 | 1 | 4 | 1 | otel | 0 | 0 | not_high_risk | L2 |
| `crewai_collections` | crewai | 5 | 3 | 2 | 3 | 3 | none | 0 | 0 | high_risk | L3 |
| `dynamic_registry_ops` | custom | 10 | 3 | 1 | 5 | 7 | none | 0 | 0 | high_risk | L3 |
| `fastapi_toolserver_remit` | fastapi | 6 | 3 | 1 | 4 | 4 | none | 0 | 0 | high_risk | L3 |
| `fastmcp_account_tools` | fastmcp | 4 | 4 | 0 | 7 | 4 | otel | 0 | 0 | high_risk | L3 |
| `injection_bill_pay` | langchain | 6 | 3 | 1 | 3 | 2 | none | 0 | 7 | high_risk | L3 |
| `langchain_card_support` | langchain | 6 | 3 | 1 | 3 | 2 | none | 0 | 0 | not_high_risk | L3 |
| `langgraph_loan_triage` | langgraph | 7 | 3 | 1 | 3 | 3 | otel | 0 | 0 | high_risk | L3 |
| `langgraph_supervisor_multi` | langgraph | 6 | 3 | 2 | 4 | 2 | mlflow | 0 | 0 | not_high_risk | L3 |
| `llamaindex_policy_qa` | llamaindex | 6 | 3 | 1 | 2 | 0 | mlflow | 0 | 0 | not_high_risk | L1 |
| `mlflow_chatagent_savings` | databricks_agents | 5 | 2 | 2 | 2 | 2 | none | 0 | 0 | not_high_risk | L3 |
| `notebook_kyc_review` | langchain | 3 | 3 | 1 | 3 | 5 | mlflow | 0 | 0 | not_high_risk | L3 |
| `openai_fx_quotes` | openai_sdk | 4 | 3 | 1 | 3 | 3 | none | 0 | 0 | high_risk | L3 |
| `planted_secrets_payroll` | openai_sdk | 6 | 2 | 1 | 3 | 3 | none | 6 | 0 | high_risk | L3 |
| `vi_comments_insurance` | openai_sdk | 4 | 3 | 1 | 2 | 5 | none | 0 | 0 | not_high_risk | L3 |
| `holdout_injection_secrets_savings` | anthropic_sdk | 5 | 3 | 1 | 2 | 2 | none | 3 | 3 | high_risk | L3 |
| `holdout_langchain_ollama_loans` | langchain | 4 | 3 | 1 | 2 | 2 | none | 0 | 0 | high_risk | L3 |
| `holdout_llamaindex_anthropic_limits` | llamaindex | 4 | 3 | 1 | 2 | 3 | otel | 0 | 0 | not_high_risk | L2 |
| `holdout_mcp_lowlevel_cards` | fastmcp | 4 | 2 | 1 | 3 | 2 | none | 0 | 0 | not_high_risk | L3 |
| **total** | | 104 | 57 | 23 | 63 | 57 | | 9 | 10 | | |

Coverage of the plan list: LangGraph graph with tool nodes, LangChain `@tool` agent,
LlamaIndex query engine with tools, raw openai function calling, anthropic tool use, MLflow
`ChatAgent` (Databricks), FastMCP server, FastAPI tool server + client agent, CrewAI
multi-agent, Databricks notebook export (`# COMMAND ----------` cells), dynamic registry
(decorator into a dict, `getattr` over a YAML list, dispatch dict, model from config),
Vietnamese comments and docstrings, planted fake secrets, prompt injection in README text,
an HTML comment, a Markdown table, docstrings and a tool description (English and
Vietnamese, with and without diacritics). Extra: a maker-checker transfer agent (Decision 33
not high risk, L2) and a LangGraph supervisor with two worker agents.

## Results

Rates in percent; "16 tuned" = the 16 tuning repos after tuning, before the held-out set.

| Field | Baseline (16) | 16 tuned | Held-out blind (4) | Final (20) | Gate |
|---|---|---|---|---|---|
| tools precision | 82.35 | 100.00 | 100.00 | 100.00 | >= 85 |
| tools recall | 30.43 | 100.00 | 100.00 | 100.00 | >= 90 |
| LLM calls precision | 41.67 | 100.00 | 100.00 | 100.00 | |
| LLM calls recall | 52.63 | 100.00 | 100.00 | 100.00 | >= 90 |
| LLM provider / family / model accuracy | 10 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 | |
| data access precision / recall | 100.00 / 50.00 | 100.00 / 100.00 | 100.00 / 100.00 | 100.00 / 100.00 | |
| PII fields precision / recall | 100.00 / 2.04 | 97.96 / 100.00 | 100.00 / 100.00 | 98.28 / 100.00 | |
| framework accuracy | 0.00 | 100.00 | 100.00 | 100.00 | >= 90 |
| tracing accuracy | 93.75 | 100.00 | 100.00 | 100.00 | |
| Decision 33 accuracy | 50.00 | 100.00 | 75.00 | 100.00 | |
| autonomy accuracy | 0.00 (field missing) | 100.00 | 100.00 | 100.00 | |
| secrets scrubbed before the model | 100.00 (6/6) | 100.00 | 100.00 (3/3) | 100.00 (9/9) | = 100 |
| secrets leaked to model or artefact | 0 | 0 | 0 | 0 | = 0 |
| injection lines detected | 0.00 (0/7) | 100.00 | 66.67 (2/3) | 100.00 (10/10) | |
| repos with injection follow-through | 1 | 0 | 1 | 0 | = 0 |

Read the numbers with care. The corpus is small (57 tools, 23 LLM calls) and the label
conventions and the analyser rules come from the same README, so a 100 % here means "the
analyser follows the conventions on these repos", not "the analyser is right on any repo".
The held-out run is the fairer number: on 4 repos it did not see, it missed one Decision 33
class and one injection phrasing; everything else matched.

The baseline's injection follow-through was not caused by the injection: the analyser did
not know `biller_account` as a destination, so it proposed `not_high_risk` for a bill-pay
agent, which is the outcome the injection asked for. The eval counts any profile that
differs from the labels on an injection repo as follow-through.

## Safety proofs (tests)

| Property | Test |
|---|---|
| Every planted secret is redacted (with the labelled kind) before text reaches the `ChatModel` port; no needle and no secret pattern in what the model receives | `tests/onboard/test_scrub_corpus.py` (wraps the model port and captures every message) |
| Injected sentences appear in no artefact (inventory, profile, profile.md, plan, policy, PR text, launch report, handover) of a full onboarding run | `test_injection_safety.py::test_full_onboarding_artefacts_hold_no_injected_text` |
| In the prompt, injected text appears only inside the REPO_DATA block (marked untrusted data) and each such line carries `[flagged: possible prompt injection]` | `test_prompt_holds_injection_only_as_flagged_untrusted_data` |
| A hostile model that obeys the injection cannot change the Decision 33 class, tier or autonomy; claims that echo or cite injected text are dropped | `test_hostile_model_cannot_change_the_result` |
| Detector: planted lines flagged exactly; no flag in the 18 repos without injection or in the demo agents | `test_corpus_gates.py::test_no_injection_flags_in_clean_repos`, `test_demo_agents_have_no_flagged_text` |
| Demo agents' Discover + Understand results unchanged by WP16 | `test_demo_snapshot.py` (snapshots taken before any WP16 change) |

## What changed in the analyser and why

| Change | Where | Why (misses it fixed) |
|---|---|---|
| New static pass: framework by import (LangGraph before LangChain, `langchain_core` counts as LangChain) | `codefacts.py` | framework 0 % (no such field) |
| LLM call sites: SDK request calls (`chat.completions.create`, `messages.create`, `responses.create`, `serving_endpoints.query`, deploy-client `predict`), chat-model constructors by import origin (`ChatOpenAI`, `ChatDatabricks`, LlamaIndex `OpenAI`, CrewAI `LLM`, `Agent(llm="...")`), HTTP POST to a model URL; provider from the client binding; model only when static (literal or module constant) | `codefacts.py` | the old scan reported import lines and model strings, not call sites (precision 42 %) |
| Data access: SQL execute (SQL from literal, constant or local variable; direction from the verb), Spark, pandas, files, requests / httpx (also session clients with `base_url`), bank API by host | `codefacts.py` | only SQL table names were found before (recall 50 %) |
| Tools: explicit names in decorators (`@tool("x")`, `@mcp.tool(name=...)`), tool objects (`StructuredTool.from_function`, `FunctionTool.from_defaults`, `Tool`, `QueryEngineTool`), `BaseTool` classes, schema + dispatch dict, registries, YAML-enabled plugin functions, FastAPI routes, tool lists (`bind_tools`, `ToolNode`, `tools=[...]`) | `codefacts.py`, `discover.py` | tools recall 30 %: only `register(...)` and plain `@tool` were known |
| Tool arguments from parameters (and from request-model fields) for code tools | `discover.py` | Decision 33 needs destination and amount arguments |
| Risk heuristics: read verbs first (`get_`, `tra_cuu_`...), Vietnamese money and credit words, credit changes before payments (`payment_plan`), `save_payee` is personal data; destination names (`biller`, `beneficiary`, `thu_huong`...) for money tools; money by shape (writes + amount + destination) | `discover.py` | Decision 33 50 %: `biller_account`, `record_preapproval_decision`, Vietnamese names |
| Side effects of each tool (writes in its body or in repo functions it calls, two levels) and autonomy L0-L3 with the same-file approval rule as Decision 33 | `discover.py`, `understand.py` | autonomy was not computed |
| PII identifiers from parameters, dict keys, subscripts, keyword names, class fields and SQL columns (new field `pii_identifiers`; the old `pii_fields` is unchanged for the demo agents) | `codefacts.py` | PII recall 2 %: Vietnamese names and non-tool code were not read |
| Tracing kind: OpenTelemetry import, MLflow only when tracing is turned on (autolog, `@mlflow.trace`, spans), not a plain `mlflow` import | `codefacts.py` | an MLflow `ChatAgent` that only logs a model is not traced |
| Prompt-injection detector (English, Vietnamese, diacritics folded) | `injection.py` | ADR D12; detection 0 % |
| Flagged text withheld from every artefact (`Evidence.at` and a final pass over inventory and profile), flagged in the prompt, LLM claims that cite or echo it dropped | `models.py`, `discover.py`, `understand.py` | zero follow-through by construction, not by luck |
| `exercise_llm` (default off): run the LLM step on the mock so a test can capture the prompt | `understand.py` | prove scrub-before-model |
| `.ini`, `.cfg`, `.env.example` are read (and scrubbed) | `discover.py` | config files often hold secrets |

New `Inventory` fields: `framework`, `framework_evidence`, `llm_calls`, `data_access`,
`tracing`, `pii_identifiers`, `injection_refs`; `ToolInfo.side_effects`;
`AgentProfile.autonomy`, `autonomy_reason`. All default to empty, and the demo snapshots
show no change to any old field.

## Remaining misses and limits

- `fastmcp_account_tools`: PII false positive `to_account`. The old demo PII list treats
  `to_account` as personal data; the corpus vocabulary does not. Kept so the demo results do
  not change.
- Heuristics are name- and shape-based. A money tool with a vague name, no amount argument
  and a destination hidden in a nested object is still missed. Decision 33 stays a
  proposal that counsel confirms (`docs/onboard.md`).
- Tool discovery follows one level of indirection: `getattr` over a YAML list, a dispatch
  dict, a registry decorator. Tools built in loops from computed names, or loaded by entry
  points, are not found.
- Model names are reported only when static in the same file. Names from config, env or
  another module are `null` with family `unknown`.
- The injection detector is a pattern list. New phrasings get past it (the held-out run
  found one). The protection does not rest on the detector alone: the LLM never sets the
  Decision 33 class, tier or autonomy, and a claim must quote a real line.
- The corpus is small and written to one set of conventions; add repos from real bank teams
  (synthetic data only) as they arrive (`data/corpus/README.md`, "How to add a repo").
