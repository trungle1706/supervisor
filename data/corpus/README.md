# Code-analysis corpus (WP16)

Small synthetic agent repositories with gold labels. The Onboarding Agent's code
analysers (Discover + Understand) are measured against them with

```cmd
uv run python -m supervisor.onboard.eval --corpus data\corpus\repos --labels data\corpus\labels.yaml --report out\corpus-eval
```

Everything here is synthetic. The code is written for this corpus (no copied code), the data
is invented Vietnamese data, and every "secret" is a fake with `EXAMPLE` or repeated
characters in it. The repos are data, not code of this project: they are excluded from
pytest collection and from ruff (see `pyproject.toml`), they are never imported, and nothing
in `src/` imports them.

## Layout

| Path | What |
|---|---|
| `repos/<name>/` | one repo: 3 to 15 files, short, realistic imports |
| `labels.yaml` | gold labels for every repo (one key per repo under `repos:`) |
| `reports/baseline.json` | the eval report before any analyser tuning (kept for the record) |
| `reports/holdout_blind.json` | the 4 `holdout_*` repos, run once with the analyser frozen after tuning |
| `reports/final.json` | the eval report after tuning, all repos |

Do NOT put labels, notes or answers inside `repos/<name>/`: the analyser reads every file there.

## How to add a repo

1. Make `repos/<name>/` (`snake_case`, framework first, e.g. `langchain_card_support`).
   3 to 15 files. Use the real import paths of the framework you imitate. The code need not
   run (dependencies are not installed) but every `.py` file must parse with Python 3.11.
2. Use synthetic Vietnamese data only (names such as "Nguyen Van An", phone `0900000001`).
   Hosts of internal bank APIs end in `.nganhang.internal`; other hosts are `*.example.vn`
   or `*.example.com`.
3. Add the labels block (below) to `labels.yaml`. Every `file:line` must be exact
   (1-based line in the file as committed). Check with
   `uv run python -m supervisor.onboard.eval --corpus data\corpus\repos --labels data\corpus\labels.yaml --check-labels`.
4. Run the eval and read the misses for the new repo. Fix the analyser, not the labels,
   unless the label is wrong.

## Label schema

```yaml
version: 1
repos:
  <name>:
    framework: langgraph        # one value, list below
    summary: one line, what the agent does
    tools:                      # every tool the LLM can call
      - {name: tra_cuu_so_du, file: tools.py, line: 14}
    llm_calls:                  # every LLM call site
      - {file: agent.py, line: 30, provider: openai, family: openai, model: gpt-4o-mini}
    data_access:                # every data source / sink in agent code
      - {kind: db, direction: read, target: core.customers, file: tools.py, line: 20}
    pii_fields: [cccd, ho_ten]  # sorted, unique
    tracing: [otel]             # subset of [mlflow, otel], sorted; [] means none
    decision33: high_risk       # high_risk | not_high_risk
    autonomy: L3                # L0 | L1 | L2 | L3
    secrets: []                 # planted fake secrets
    injections: []              # planted prompt-injection text
```

### framework (one value per repo: the main agent framework)

`langgraph`, `langchain`, `llamaindex`, `openai_sdk`, `anthropic_sdk`,
`databricks_agents` (MLflow `ChatAgent` / `ResponsesAgent` / `mlflow.pyfunc` agent /
`databricks-agents`), `fastmcp` (an MCP server is the main thing), `fastapi` (a tool server
over HTTP is the main thing), `crewai`, `custom` (own loop, no framework). LangGraph wins
over LangChain when both are imported; a notebook export is labelled by what it uses.

### tools

A tool is a function the LLM can ask to call: `@tool` / `@function_tool` / `@mcp.tool()`
functions, `Tool(...)` / `StructuredTool.from_function(...)` / `FunctionTool.from_defaults(...)`
objects, CrewAI `BaseTool` subclasses, functions listed in an OpenAI / Anthropic tool schema
and dispatched by name, functions put in a registry (dict, decorator, `register(...)`),
HTTP routes of a tool server.

* `name` = the name the model sees: the explicit name if one is given
  (`@tool("tra_cuu")`, `name="..."`, schema `"name"`, registry key), else the function name.
  For a FastAPI route it is the function name.
* `file` / `line` = the `def` line of the implementing function (the line with the `def`
  keyword, not the decorator), or the `class` line of a tool class. Only when no
  implementing function exists in the repo: the line of the name declaration.
* One entry per tool name. A tool that is both declared in a schema and implemented is one
  entry (the implementation line).

### llm_calls

An LLM call site is the line where a model request is made or a chat model is bound:

* raw SDKs: the line where the call expression starts:
  `client.chat.completions.create(`, `client.responses.create(`, `client.messages.create(`,
  `client.messages.stream(`, `litellm.completion(`, `ollama.chat(`,
  `w.serving_endpoints.query(`, `get_deploy_client(...).predict(`, or an HTTP POST to a
  model serving URL (`.../invocations`, `.../chat/completions`).
* frameworks: the line of the chat-model constructor: `ChatOpenAI(`, `AzureChatOpenAI(`,
  `ChatAnthropic(`, `ChatDatabricks(`, `ChatOllama(`, `init_chat_model(`, LlamaIndex
  `OpenAI(` / `Anthropic(` from `llama_index.llms.*`, CrewAI `LLM(`, or an
  `Agent(llm="model-name")` string. Not the later `.invoke(` lines.
* `provider`: `openai`, `azure_openai`, `anthropic`, `databricks`, `ollama`, `litellm`, `unknown`.
* `family`: from the model name, the same table as
  `supervisor.adapters.llm.openai_compatible.model_family` plus a few more:
  `claude*` -> `anthropic`, `gpt*` / `o1*` / `o3*` / `o4*` -> `openai`, `qwen*` -> `qwen`,
  `llama*` -> `meta`, `gemma*` -> `google`, `deepseek*` -> `deepseek`,
  `mistral*` / `mixtral*` -> `mistral`, `dbrx*` -> `databricks`, else `unknown`. Vendor
  prefixes (`databricks-`, `meta-`, `us.anthropic.`, `anthropic.`, `openai/`) are cut first.
* `model`: the model or endpoint name when it is a string literal at the call site or a
  module-level string constant of the same file. `null` when it comes from config, env, a
  registry or a parameter. `family` is `unknown` when `model` is `null`.

### data_access

One entry per call site that reads or writes data outside the process:

* `kind`: `db` (SQL execute, `spark.sql`, `spark.table`, `pd.read_sql`, ORM session query,
  `saveAsTable`), `http` (requests / httpx / urllib to a non-bank host), `bank_api` (HTTP to
  a host ending `.nganhang.internal`), `file` (`open(...)`, `Path.read_text` / `write_text`,
  `pd.read_csv` / `to_csv`, `json.dump` to a file).
* `direction`: `read` or `write` (SQL SELECT / HTTP GET / file read = read; INSERT, UPDATE,
  MERGE, DELETE / POST, PUT, PATCH, DELETE / file write = write).
* `target`: table name, URL or path as written (template parts as `{}`), or `null` when not
  static.
* `file` / `line`: the line where the call expression starts (`cursor.execute(`,
  `requests.post(`, `open(`). When the SQL text is a literal on another line, still use the
  call line.
* LLM calls are NOT data access (they are in `llm_calls`).

### pii_fields

Identifiers in agent code (tool parameters, dict keys, SQL columns, dataclass / pydantic
fields) whose name denotes personal data of a customer, from this vocabulary:

`customer_id`, `full_name`, `customer_name`, `payee_name`, `national_id`, `cccd`, `cmnd`,
`id_number`, `phone`, `phone_number`, `email`, `address`, `dob`, `date_of_birth`,
`account_number`, `account_id`, `card_number`, `income`, `monthly_income`, `salary`,
`tax_code`, `ho_ten`, `so_cccd`, `so_dien_thoai`, `sdt`, `dia_chi`, `ngay_sinh`,
`so_tai_khoan`, `thu_nhap`, `ma_so_thue`.

List each identifier once, exactly as spelled in the code. Words only in comments or prose
do not count.

### tracing

`otel` when the code uses OpenTelemetry (an `opentelemetry` import with a tracer or an
instrumentor). `mlflow` when the code turns on MLflow tracing (`mlflow.*.autolog()`,
`@mlflow.trace`, `mlflow.start_span`, `mlflow.tracing`). Importing `mlflow` only to log or
serve a model is NOT tracing.

### decision33 (same mapping as `docs/onboard.md`)

`high_risk` when (a) a tool executes a money movement to a destination chosen at call time
(transfer, payment, remittance, disbursement to a payee or account) or (b) a tool records a
credit decision (approve / decline / set a limit), AND no human pre-execution approval step
is in code in the same file as that tool (a function such as `request_human_approval`,
`await_officer_approval`, `maker_checker`, `four_eyes`, called before the action). Prose
("an officer reviews") does not count. Otherwise `not_high_risk`. Reading a credit score is
not a credit decision; a fee waiver with no destination is not a transaction to a destination.

### autonomy

`L0` no tools (text only). `L1` every tool only reads. `L2` tools with side effects
(writes, sends, pays, decides, writes files) exist and every one is behind a human approval
step in code. `L3` at least one tool with side effects has no human approval step in code.

### secrets

`{file, line, kind, needle}`: `kind` is the scrubber kind that must catch it
(`aws_access_key`, `llm_api_key`, `databricks_token`, `assigned_secret`, ...). `needle` is a
6 to 12 character substring of the fake secret that is distinctive but does NOT itself
match a secret pattern (the eval checks the needle never reaches the model). Planted
values must be clearly fake (`EXAMPLE`, repeated characters).

### injections

`{file, line, lang, needle}`: one per planted injection sentence. `lang` is `en` or `vi`.
`needle` is a distinctive substring (10 to 40 characters) of the sentence, copied exactly.
