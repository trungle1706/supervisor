# Code analysis review (before the source analysis agent)

Status: written before the agent was built. It describes the analyser as it was at base commit
`a39cab5`, how well it works, who uses its output, and what is missing. Section 6 turns the gaps
into the scope of the agent (`docs/onboarding/code-agent.md`).

Not legal advice. Everything here is about synthetic repos only.

## 1. What the analyser is

The registration flow takes a candidate source (`onboard/intake.py`: zip or https git), scrubs
secrets in memory, and stores the scrubbed tree under `<DATA_DIR>/intake/<node>/<n>/`. Then:

| Stage | Module | Method | LLM |
|---|---|---|---|
| Discover | `onboard/discover.py` | `ast` + `yaml.safe_load` + regex over the scrubbed tree. Never imports or runs code. | none |
| Code facts | `onboard/codefacts.py` | `ast` rules tuned on the corpus: framework, LLM call sites, data access, tracing, tools, routes, PII identifiers | none |
| Understand | `onboard/understand.py` | fixed rules: purpose, capabilities, reversibility, weak spots, Decision 33, autonomy, risk tier | optional: may only ADD claims; kept only if `file:line` exists and the quote is on that line |
| Facts card | `onboard/facts.py` | writes `onboard_facts` rows (kind, name, detail, file, line, quote, source rule/model) | the Understand step |
| Injection guard | `onboard/injection.py` | regex markers (EN + VI, with and without diacritics) | none |

## 2. What it extracts today

| Output (Inventory / profile) | How | Evidence |
|---|---|---|
| framework (one value) | import prefix table | file:line of the import |
| LLM call sites: provider, family, model | chat-model constructors, SDK client calls, raw HTTP to `/chat/completions` | file:line |
| tools (name, risk class money/credit/pii_export/read_only, args, amount/destination arg, side effects) | decorators, tool constructors, schemas, registries, MCP, FastAPI routes under `/tools` | file:line of `def` |
| data access: kind db/http/bank_api/file, direction, target | call patterns (`execute`, `requests.*`, `open`, pandas) | file:line of the call |
| tracing: otel / mlflow | imports and calls | file:line |
| PII identifiers (vocabulary of 31 names) | AST names, dict keys, SQL columns | first file:line |
| entrypoints (HTTP routes outside `/tools`) | decorators | file:line |
| human approval refs, LangGraph interrupt guards | identifier regex, `interrupt` calls | file:line |
| secrets (kind only) | scrubber markers `[REDACTED:kind]` | file:line |
| limits, notes (not enforced, TODO) | manifest and comments | file:line |
| Decision 33 proposal, autonomy L0-L3, risk tier | fixed rules over the above | file:line list |
| extra claims | optional LLM, evidence checked | file:line + quote |

All of it is deterministic except the optional extra claims. Ground truth for this work is the
deterministic output.

## 3. Who uses the output

The Facts card is the only door. `FactsService.build` writes rows of 13 kinds into `onboard_facts`
and `uses/reads/writes` edges into the inventory graph. Every consumer reads rows by `kind`.

| Consumer | Reads | Effect |
|---|---|---|
| Register v3 step 2/3 prefill (`register_v2/suggest.apply_facts`) | tool, model, endpoint, dataset, file, claim, approval_point, autonomy | fills purpose, data sources, personal data, model family, money movement, credit decision, human control, autonomy (each marked "from facts") |
| AI type flags (`register_v3/flags.derive`) | kinds model, endpoint, tool, mcp_server | generative / agentic flags; system type proposal |
| Classification (Decision 33, `classification_v2`) | the register fields above (money, credit, human control) | draft outcome; a person approves |
| Assessor plan (`onboard/orchestrator._fact_kinds`, `plan`) | set of fact kinds | which of the 8 risk dimensions apply; unknown = applies |
| Smart guardian (`onboard/smart_guardian`) | `fact_kinds`, `fact_tool_re` (tool name patterns), dataset facts | which guardians to propose, with the fact as justification |
| Pre-deploy (`onboard/predeploy.facts`) | weak_spot, secret_use, external_url | `warn` items in the GO / NO-GO report |
| Duties (`register_v2/duties`, `governance/duties_gap`) | row count, autonomy fact | duty matrix inputs |
| Factory (`factory/schemas/facts_v1`, `console/factory_view`) | whole export (frozen `facts_v1`) | agent factory prefill |
| Inventory graph (`facts._feed_graph`) | tool, model, endpoint, dataset | `uses` / `reads` / `writes` edges; tool risk inheritance |

Consequence: any new information is useful downstream only when it reaches one of the 13 kinds with
a `file:line`. The agent therefore writes into the same kinds (see the mapping in the agent doc).

## 4. Measured quality (re-run on 2026-10-30)

Command: `SUPERVISOR_ENV_FILE=/dev/null python -m supervisor.onboard.eval --corpus data/corpus/repos --labels data/corpus/labels.yaml --report <dir>` (21 repos, mock model, 0.5 s).

| Field | Precision | Recall | F1 | TP / FP / FN |
|---|---|---|---|---|
| tools | 100.0 | 100.0 | 100.0 | 63 / 0 / 0 |
| entrypoints | 100.0 | 100.0 | 100.0 | 8 / 0 / 0 |
| LLM calls | 100.0 | 100.0 | 100.0 | 24 / 0 / 0 |
| data access | 100.0 | 100.0 | 100.0 | 67 / 0 / 0 |
| PII fields | 98.3 | 100.0 | 99.2 | 58 / 1 / 0 |
| framework, tracing, Decision 33, autonomy, model family | accuracy 100 % | | | 21/21 each |
| secrets scrubbed before model / leaked | 100 % / 0 | | | 9 secrets |
| injection lines detected / follow-through | 100 % / 0 | | | 10 lines |

How to read it:

| Split | What it is | Honest value |
|---|---|---|
| Baseline (16 repos, before tuning) | `reports/baseline.json` | tools R 30 %, PII R 2 %, framework not present |
| Tuned (16 + 1 repos, after tuning) | rules written against these repos | 100 % is in-sample. It shows the rules follow the README conventions. It does not show accuracy on a new repo. |
| Holdout, blind run (4 repos) | `reports/holdout_blind.json`, run once | tools / LLM calls / data access / PII 100 %; framework 100 %; **Decision 33 75 % (1 of 4 wrong)**; **injection detection 67 % (2 of 3)**; **1 repo with injection follow-through** |
| Final (21 repos) | all repos after post-blind fixes | 100 %, but the 4 holdout repos are now tuned data. `docs/onboard-eval.md` already says a fresh blind set is needed. |

Findings:

1. The corpus is saturated. 0 misses on 21 repos means there is nothing left to tune on. The
   score cannot go up and cannot warn us about a new weakness.
2. The only out-of-sample number the team has is the 4-repo blind run, and it found a wrong
   Decision 33 class and a missed injection phrase. Out-of-sample risk is real.
3. Repos are small (80 to 175 lines, 3 to 10 files). Nothing tests a 200-file repo, deep call
   chains, or code that spreads one flow over several modules.
4. Rules key on names (`transfer`, `pay`, `approval`). A tool called `settle_batch` or an
   approval step called `double_check` is a miss by design. The corpus has only such cases that
   were already fixed.
5. Evidence is a line pointer, not a flow. The analyser says "there is a DB write at
   tools.py:51" and "there is a tool `hoan_phi`". It does not say that `hoan_phi` is the tool that
   does the write.

## 5. LLM versus deterministic

| Part | Deterministic | LLM |
|---|---|---|
| Discover, code facts, Decision 33, autonomy, tier | all | none |
| Facts card rows | rule rows | model rows = Understand extra claims only |
| Extra claims | evidence check (file exists, line in range, quote on the line, no injection) is deterministic | the claim text and category |
| Block / pause / classify | deterministic only | never |

The LLM step has one call, one prompt of at most 12 000 characters of the repo, no tools, no
second look. It cannot ask for a file, search, or follow a call. It adds at most 20 claims in 4
categories (capability, reversibility, personal_data, weak_spot). Its quality is not measured:
the existing eval runs it only with the mock model, to capture the prompt.

## 6. Gaps against what downstream features need

| Need | Used by | Today | Gap |
|---|---|---|---|
| Data flow tool -> sink (which tool writes which table / calls which host) | smart guardian, DPIA-style duties, data-flow dimension | data access and tools are two lists | no link |
| Human-in-the-loop points per tool | Decision 33 gate, human control field, autonomy | one list of approval refs, one L-level | no per-tool "guarded / not guarded"; relies on identifier names |
| External endpoints and egress | third-party / data residency dimension, pre-deploy warn | `http` data access + URL regex rows | no host list, no internal / external split, no purpose |
| Secrets handling | security dimension | secret kinds found by scrubber | no "reads from env / vault / hardcoded" view |
| Model / provider + version | model risk, family-differs rule | provider, family, model string | no "pinned or floating" view, config-resolved model unknown |
| Guardrails present | smart guardian, controls | limits from manifest only | no amount caps, allow lists, input validation, output filters found in code |
| Logging and tracing | monitoring, privacy | otel / mlflow flags | no log calls; cannot tell if PII is logged |
| Write / irreversible actions with amounts | Decision 33, reversibility claims | name regex risk class; `amount_arg` guess | no "irreversible" judgement, no proof of an undo path |
| PII per tool | personal-data dimension, masking plan | one repo-wide set of identifiers | not per tool |
| Entry points | attach / wiring | HTTP routes only | no CLI, queue, schedule, notebook, MCP server entry |
| Reasoning that crosses files | all | per-file AST | cannot follow a helper that a tool calls |
| Quality of the LLM step | all | unmeasured | no precision / recall, no stability, no cost figure |

The source analysis agent (`onboard/codeagent/`) is scoped to close the first ten rows. It does
not replace the deterministic stage; it adds, explains, and reports disagreements.
