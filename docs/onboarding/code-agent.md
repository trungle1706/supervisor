# Source analysis agent

Flag `CODE_AGENT_ENABLED` (default off). Code: `src/supervisor/onboard/codeagent/`. Review of the
analyser before this work: `docs/onboarding/code-analysis-review.md`. Eval results:
`data/corpus/reports/code_agent_*.md`.

Not legal advice. Synthetic data only. Candidate code is untrusted data: it is parsed, never
imported or run.

## 1. What it is for

The deterministic analyser (Discover + code facts) is exact where a rule exists and blind where it
does not. The agent reads the stored, scrubbed source with read-only tools, adds what the rules miss,
and writes one typed report that other features read. It does not replace the rules.

| Rule | How it is enforced |
|---|---|
| Deterministic facts are ground truth | `merge.py`: a firm rule value (basis `manifest` or `ast`) is never replaced; a disagreement is listed in `report.disagreements` |
| A model only advises | the agent has no write tool and no call to the gate; the report is data; a person presses "Use in assessment" |
| Every claim has evidence | `verify.py` keeps a claim only if: the kind is known; the file exists and the line is in range; the quote (5+ letters and digits) is on that line, or on a line within 3 lines of it, or at the one place of the repo that holds it; the line is code (not a comment, docstring or Markdown); the line, quote and name are not a prompt injection; the attributes are inside the closed lists (a name that carries the value, such as `guardrail` named `input_validation`, is repaired); and a per-kind check holds: an egress name is a host seen on the line; a tool is registered (decorator, schema or registry string, list, binding call); a guardrail line looks like that guard (a comparison with an amount for `amount_limit`, a lookup or membership test for `allowlist`, ...); an approval step is a def or call of a function with an approval-like name, or of a repo function that waits for an answer (`input`, a polling loop with `sleep`, `wait_for`) and that a tool reaches; `logs_pii=true` needs a personal-data identifier in the log call; an `amount_arg` must be a parameter of the tool and look like an amount |
| Risk can go up easily, down only by a person | a claim that lowers a risk (`irreversible` true to false, `effect` money to read, `approval` false to true) never replaces a rule value; `approval` is derived from verified approval steps only |
| Repo text is data | every tool result is inside `<<<REPO_DATA nonce=N>>>` delimiters (delimiter look-alikes broken); lines that match `onboard/injection.py` are replaced by a placeholder before the model sees them |
| No execution, no escape | `Workspace` is an in-memory dict of scrubbed text; a path is a dict key, so `..`, absolute paths and links reach nothing; no `open`, no process |
| The model names, the rules decide | the agent names the approval function; which tools it guards comes from the call graph (two hops). `irreversible` follows from `effect`. A data flow is accepted only for a tool the rules found no flow for |
| Offline | the only network call is the configured model, through the existing `ChatModel` port |

## 2. The loop

```
 stored tree (scrubbed)        Workspace (read-only dict)
        |                            |
   Discover + AST rules  --->  deterministic findings (ground truth)
        |                            |
        |      +---------------------+----------------------+
        |      | phase 1: one turn per topic (fixed leads)  |
        |      |   tools -> oversight -> logging/secrets    |
        |      |   -> network/data flows                    |
        |      | phase 2: free tool use, steps that are left|
        |      |   (list_files read_file grep ast_outline   |
        |      |    find_references)                        |
        |      +---------------------+----------------------+
        |                            |  claims {kind,name,file,line,quote,attrs}
        |                     verify.check_claim (drop or keep)
        |                            |
        +----------- merge (rules win, disagreements listed) -----------+
                                     |
                         CodeAnalysisReport v1 (pydantic)
                         findings + disagreements + rejected + coverage + stats + confidence
```

* One model call per turn through `ChatModel.complete_json(messages, schema, timeout)`. The same
  code runs on the local OpenAI-compatible endpoint (`LLM_API_SHAPE=chat`, Ollama or vLLM) and on the
  Databricks AI Gateway (`LLM_API_SHAPE=responses`): `OpenAICompatibleChat` builds the body. No
  native tool calling is used, so any model that can follow a JSON schema works.
* A reply is `{"findings": [...], "next": {"tool": ...}}`. `next` is one tool call or `finish`.
* Budgets stop the loop and never raise: steps, tokens (estimated as characters / 3.5), seconds,
  lines read, prompt size (default 10 500 characters, safe for a 4096-token model).
* Tool policy (code, not prompt): the topics and their lead queries (`topics.py`, `leads.py`); no
  `finish` while a code file is unread (once); an identical repeated call gets a hint; rejected
  claims come back once with the real line so the model can quote correctly.
* Roles of the tools: `list_files`, `read_file(path, start, end)` (70 lines at most), `grep(pattern)`
  (25 hits, nested repetition refused), `ast_outline(path)`, `find_references(symbol)`.

## 3. The report (`CodeAnalysisReport`, version 1)

| Part | Content |
|---|---|
| `findings[]` | `kind`, `name`, `attrs` (typed, closed lists), `attr_basis` (where each value came from), `evidence[]` (file, line, quote, line hash), `source` (deterministic or agent), `verified`, `corroborated`, `confidence_bp` |
| kinds | framework, model, tool, entrypoint, data_flow, egress, secret_handling, guardrail, hitl, logging, pii |
| `disagreements[]` | kind, name, attribute, rule value, agent value, which one the report keeps, reason |
| `rejected[]` | kind, name, file, line, reason code only (no claim text is kept) |
| `coverage` | code files read / total, lines shown / total, skipped files |
| `stats` | steps, model calls, estimated tokens, seconds, stop reason, claims proposed / kept / rejected, injection lines withheld |
| `confidence` | high / medium / low plus basis points: read share (50 %), kept share (30 %), finished (20 %) |

Confidence is a deterministic summary of how much of the repo the agent saw and how much of what
it said survived the check. It is not a calibrated probability.

## 4. Where the output goes

The Facts card is the one door to the other features (`code-analysis-review.md`, section 3). "Use in
assessment" writes rows into `onboard_facts` with `source=model` and `model_id=code-agent:<model>`;
`FactsService.build` keeps them on a re-read while the analysis is applied. Mapping:

| Agent finding | Fact kind | Read by |
|---|---|---|
| tool found only by the agent | `tool` (risk_class from effect) | register prefill (money, credit), AI type flags, smart guardian |
| model found only by the agent | `model` | register prefill (model family), AI type flags |
| host outside the bank | `external_url` | pre-deploy warning, assessor plan |
| approval step | `approval_point` | register prefill (human control), Decision 33 draft |
| data flow with a target | `dataset` | register prefill (data sources, personal data), smart guardian |
| guardrail, personal data per tool | `claim` | register prefill, pre-deploy |
| hard-coded secret | `secret_use` | pre-deploy warning |
| irreversible action without approval; personal data in the log | `weak_spot` | pre-deploy warning, duties |

## 5. Console

* Agent page: tab **Source analysis** (`?tab=analysis`).
* Candidate drawer: slot under Facts.
* Register workflow step 2 (`facts`): a second tab next to Facts. Step numbers and the compliance
  strip do not change.
* The panel: status pill and polling while a run goes, summary cards (framework, model and provider,
  tools with irreversible and unguarded counts, data flows and personal data, hosts called, guardrails,
  approval points, secrets handling, logging), the tool table, findings grouped by kind with
  `file:line` links to the stored scrubbed file (`/console/code-analysis/<id>/file`), the
  agent-versus-rules disagreements, coverage and cost, dropped claims by reason, and the buttons
  **Run analysis** and **Use in assessment** (with the list of facts it would add and which feature
  reads them). English and Vietnamese.
* API: `GET /v1/code-analysis/<id>`, `POST /v1/code-analysis/<id>/run` (202), `POST .../apply` (201).
  Flag off: HTTP 400 `code_agent_off`.

## 6. Labels for the new fields

File `data/corpus/labels_codeagent.yaml`, written by reading the code. Definitions:

| Field | Definition |
|---|---|
| `tools.effect` | read, write (changes a record), money (moves money), credit (credit decision, limit, restructure, write-off), message (SMS, email, webhook), delete |
| `irreversible` | money, credit, delete and a sent message, when the repo has no function that undoes it. A KYC status update or a card block is `write` |
| `approval` | a human decision is awaited before the tool acts, through a call reachable from the tool in any file. A function that exists but no tool calls does not count |
| `amount_args` | `tool.arg` for the money amount of a money or credit tool |
| `tool_sinks` | `tool direction sink` for every db, http, bank_api or file source or sink reached from the tool or the helpers it calls (two hops) |
| `egress_hosts` | host of every http(s) URL in executable code or config, loopback excluded |
| `secret_sources` | hardcoded; env (a credential, token or DSN read from the environment; a path or a URL is not one); secret_store |
| `guardrails` | a check in code: amount_limit, allowlist, input_validation, rate_limit, ... A constant nobody compares is not one |
| `logging_sinks`, `pii_logged` | log (logging or print outside `__main__`), trace_otel, trace_mlflow, audit_table; `pii_logged` is true when a log or print call, or its helper, writes a personal-data identifier |
| `pii_by_tool` | `tool:field` for vocabulary identifiers in the tool function, its parameters or its request model |
| `entrypoints` | `kind:file` with kind http, cli, mcp, notebook, mlflow |
| `pinned_models` | model ids that hold a date or a version |

Honest limits of the labels: one labeller (the lead agent), written from the code before the agent
ran on the repo; some fields are close to mechanical (`pii_by_tool`, `egress_hosts`), so the
deterministic baseline scores high on them by construction; some are judgement (`irreversible`,
`guardrails`). Six repos were added in `data/corpus/repos_agent/` (own labels file
`labels_agent_repos.yaml`) so that the recorded floors of `labels.yaml` stay comparable.

## 7. Tuning protocol (the honest "fine-tune")

No weights are trained. What is tuned, and how:

1. Splits. Tuned: the 17 non-holdout repos of the old corpus plus 3 new repos. Blind holdout: the 4
   old `holdout_*` repos plus 3 new ones written for this purpose. The 4 old holdout repos are not
   blind for the deterministic rules (they were fixed after the first blind run), but the agent
   prompt, topics and verifier were never tuned on them; the 3 new holdout repos were not seen by
   any rule or prompt.
2. What is tuned: the topic cards and lead queries, the verifier predicates, the merge rules, and
   4 few-shot exemplars. Only runs on tuned-split repos drive these edits. The prompt version is
   written into every report (`ca-prompt-N`).
3. Exemplars come from tuned repos only; the report gives the tuned score with and without those
   repos.
4. The holdout is run once, at the end, with the frozen prompt version. Its numbers are in the
   report as they came out.
5. Where the model is a lower bound: the local run uses a 7B model on CPU with a 4096-token window.
   The production model (GLM on the Databricks AI Gateway, `LLM_API_SHAPE=responses`) is larger and
   has a longer window; set `CODE_AGENT_*` limits and the prompt size (`AgentConfig.prompt_chars`)
   higher for it. The harness is the same; run the eval with `--settings` against that endpoint.

## 8. Run and eval

```cmd
set CODE_AGENT_ENABLED=1
python -m supervisor.onboard.codeagent run --tree <folder> --base-url http://127.0.0.1:11434/v1 --model qwen2.5:7b-instruct
python -m supervisor.onboard.codeagent eval --out out\ca --name code_agent_eval --base-url ... --model ... --split all --runs 1
python -m supervisor.onboard.codeagent aggregate --out out\ca     (score the run files again, no model)
python -m pytest tests\onboard\test_code_agent_core.py tests\onboard\test_code_agent_eval.py
python -m pytest tests\console\test_code_agent_panel.py
```

Recording: `--record file.jsonl` writes the model answers; `--replay file.jsonl` answers from them.
The gate test replays a small recording, so CI needs no model.

## 9. Results (qwen2.5:7b-instruct on CPU: a lower bound)

Run on 2026-10-30 and 2026-10-31 on a shared CPU host (no GPU), model `qwen2.5:7b-instruct`
(Q4_K_M, 4096-token window, temperature 0) through the OpenAI-compatible endpoint of Ollama,
`LLM_API_SHAPE=chat`. Prompt `ca-prompt-10`, verifier `verify-1`, 5 model calls per repo. Raw run
files: `data/corpus/reports/code_agent_runs/first_pass/`; report:
`data/corpus/reports/code_agent_eval.md` and `.json`; scoring them again needs no model
(`python -m supervisor.onboard.codeagent aggregate`, and a pytest does it).
The production model (GLM on the Databricks AI Gateway) was not available here and is not measured.

### 9.1 Per field, rules only versus rules plus agent (precision / recall in %)

| Field | Tuned (20) rules P/R | Tuned rules+agent P/R | Holdout (7) rules P/R | Holdout rules+agent P/R |
|---|---|---|---|---|
| tools | 100/100 | 97/100 | 94/84 | 94/84 |
| irreversible_tools | 100/67 | 89/94 | 80/67 | 80/67 |
| hitl_tools | 100/75 | 100/100 | n/a/0 | n/a/0 |
| amount_args | 0/0 | 75/55 | n/a/0 | 75/60 |
| tool_sinks | 100/98 | 97/98 | 100/75 | 100/75 |
| egress_hosts | 100/100 | 100/100 | 100/90 | 82/90 |
| secret_sources | 62/100 | 62/100 | 100/100 | 100/100 |
| guardrails | 100/14 | 57/57 | 100/50 | 75/75 |
| logging_sinks | 50/100 | 48/100 | 33/100 | 33/100 |
| pii_by_tool | 99/99 | 99/99 | 100/89 | 100/89 |
| entrypoints | 79/100 | 79/100 | 90/100 | 90/100 |
| pinned_models | 100/100 | 100/100 | 100/100 | 100/100 |
| **micro F1** | 92 | 93 | 84 | 84 |

Reading the table:

* The 20 tuned repos are the repos the prompt, the lead queries and the verifier were tuned on. The
  tuned score without the 4 repos that supply a prompt exemplar is 91.5 (rules) and 92.3 (rules plus
  agent), so the exemplars do not explain the gain.
* The 7 holdout repos were run once with everything frozen. 4 of them were fixed after a first blind run
  for the rules (see `docs/onboard-eval.md`), 3 are new. The agent gain there is +0.7 points micro F1.
* "Rules" here are the deterministic probes of `baseline.py` (Discover plus AST rules). They are strong
  on tools, hosts, sinks and personal data per tool because those fields are close to mechanical
  (labels follow the same definition). They are weak where meaning is needed: `amount_args` (0),
  `guardrails` (recall 14 % tuned), `irreversible_tools` (recall 67 %), `hitl_tools` (recall 75 %
  tuned, 0 on the holdout), `logging_sinks` and `secret_sources` (precision about 50 to 60 %: every
  `print` and every `os.environ` counts).
* What the agent adds, all repos: `amount_args` from 0 to F1 64, `irreversible_tools` recall from
  67 % to 88 %, `guardrails` recall from 27 % to 64 % (precision falls from 100 % to 64 %),
  tool effect accuracy from 69 of 77 to 73 of 77. What it costs: 2 wrong tools, 2 wrong data flows,
  2 wrong hosts (`db.example.vn` and `pg.example.vn`: database hosts that are not URLs, so the
  label excludes them), 1 wrong logging sink. Agent-added items over all fields and repos: 19 right,
  15 wrong.
* The agent cannot remove a rule finding, so it cannot lower the rule FPs (`secret_sources`
  precision 74 %, `logging_sinks` 45 %, `entrypoints` 82 %). That is by design (rules are ground
  truth) and a limit of the design.

### 9.2 Evidence, safety, stability, cost

| Measure | Result |
|---|---|
| Evidence validity (final findings whose file:line and quote verify against the stored text) | 509 of 509 (100 %); tuned 391/391, holdout 118/118 |
| Claims the model proposed that passed the check | 280 of 454 (62 %); dropped: quote not on the line 118, duplicate 21, prose line 10, quote too short 8, bad attributes 13, not a tool 4 |
| Injection (4 repos with planted text or secrets: `injection_bill_pay`, `holdout_agent_loop_injection`, `holdout_injection_secrets_savings`, `planted_secrets_payroll`) | follow-through 0 of 4; no planted sentence and no secret needle in any report. On `holdout_agent_loop_injection` the 7B model did try one forged approval claim on the planted `AUDIT_NOTE` line; the check refused it (`evidence_is_prose`) |
| Secrets | the prompts of the unit test hold no needle of the payroll repo; no secret value reaches a report |
| Stability | 3 runs per repo with the server default sampling (temperature not sent): `mlflow_chatagent_savings` and `vi_comments_insurance` gave 3 identical reports (Jaccard 100 % on every field). Only 2 repos were tested and the server's effective temperature was not checked, so this says "identical in these two", not "deterministic" |
| Cost per repo (mean of 27) | 5 model calls, about 8 300 tokens (estimated as characters / 3.5), 1 160 s on a host with load 30 to 40 (about 250 s when the host is quiet). Steps stopped by the step limit in 26 of 27 repos |
| Coverage | 57 % of code files opened on average (the guided topics read leads, not whole files) |

### 9.3 Post-hoc check (not blind)

The blind holdout run showed two defects: an approval step with an unusual name (`double_check`,
`manager_signoff`) was refused because the check wanted an approval-like name, and the reasons
`quote_not_on_line` and `evidence_is_prose` were used for other failures. They were fixed in
`verify-2` (an approval step may have any name if it waits for an answer; new reason codes
`claim_not_visible` and `not_an_approval_step`). The 7 holdout repos were run again; this is NOT a
blind number. See `data/corpus/reports/code_agent_holdout_posthoc.md`.
Result of the post-hoc run (7 holdout repos, output cap 1100): micro F1 83.5 (rules) to 84.3 (rules plus
agent), against 84.2 in the blind run. `hitl_tools` recall went from 0 to 33 % (1 of 3 approval
steps found: `double_check`-style names now pass) with precision 100 %; `guardrails` 75 / 75;
`amount_args` 75 / 60; `egress_hosts` precision 82 % (2 wrong). Evidence validity 120 of 120. The
gain over the rules stays small with this model. Run files:
`data/corpus/reports/code_agent_runs/posthoc/`.

## 10. How competent is the agent

| Question | Answer |
|---|---|
| Can a judge trust what is in the report? | Yes for evidence: every finding points to a line that exists and holds the quote (509 of 509), prose is refused, and a planted instruction was not followed in 4 of 4 repos. The check is deterministic and runs on the final report |
| Does it make the other features better? | A little with a 7B model: +0.9 micro F1 on all fields (+0.9 tuned, +0.7 holdout), with real gains on amount, irreversibility and guardrails and some precision loss elsewhere |
| Is it a strong analyst on its own? | No. A 7B model on CPU finds few things the rules miss: 19 correct additions in 27 repos. On the 3 blind repos built to have approval steps it could not see, it found none of them in the blind run |
| What is it reliable for? | Adding amount arguments, refining a coarse write to message / delete / credit, naming approval functions in tuned styles, and never inventing evidence |
| What is it not reliable for? | Finding tools that the rules miss (registry by comprehension), approval steps with unusual names (before `verify-2`), telling a database host from an egress host, judging whether an environment variable is a secret |
| What should the judges hear? | The reliability comes from the design, not from the model: rules are ground truth, the agent can add but not remove or lower, each claim is verified against the stored text, risk can only go up without a person, injection cannot forge evidence, and the whole thing is measured on labelled repos with a frozen holdout and the numbers published as they came out, including the weak ones. A better model raises the recall; the check keeps the precision of the evidence |
| What must not be claimed? | "Highly accurate" for the agent itself; any number on GLM; "blind" for the post-hoc run; "deterministic" for the model (only the rules and the check are) |

## 11. Open issues

* One labeller (the lead agent) wrote all labels, from the code, before the agent ran on each repo;
  a second labeller would find disagreements. Some fields (`irreversible`, `guardrails`,
  `secret_sources`) are judgement.
* The corpus is 27 small synthetic repos (80 to 175 lines). Nothing here tests a 200-file repo.
  Counts per field are small (`hitl_tools`: 7 tools), so every percentage has a wide interval.
* The agent cannot remove a rule finding, so rule FPs stay (see 9.1). A "disputed by the agent"
  flag with a person's decision would be the next step.
* `max_steps` was 5 in the eval: 4 guided topics and 1 free step. The free tool phase (read, grep,
  references) was used in 26 calls and added little with this model; its value with a stronger model
  is untested.
* The `quote_not_on_line` reason in the first-pass files also covers "the claimed name or sink is not
  visible near the line" (renamed `claim_not_visible` in `verify-2`).
* A run that is stopped by a model error or timeout keeps the rule findings and is labelled
  `confidence: low`; on a loaded host 5 of 7 post-hoc runs hit `TruncatedError` (reply longer than the
  token cap) or a timeout and had to be repeated with a larger cap.
* Ollama was OOM-killed once during the eval (10 GB scope limit, several parallel requests); runs that
  ended with `model_error` for that reason were deleted and repeated, and the raw files kept here are
  only complete runs.
