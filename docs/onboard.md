# Onboard: the Onboarding Agent and the capability catalogue (WP9)

The Onboarding Agent reads an agent's repository, writes a profile and a monitoring
plan, prepares a pull-request branch with a gateway policy and hooks, runs the red-team
pack in a sandbox with the gate in shadow mode, and hands the agent over to Watch.
It never merges and never pushes. A human opens and merges the pull request.

## Run it

```cmd
cd C:\work\supervisor
uv sync --all-extras
uv run python -m supervisor.onboard --target src\supervisor_agents\payments --out out\payments --mock-llm
```

Options:

| Option | Meaning |
|---|---|
| `--target` | Agent folder. Inside a git repo: the branch is made in a clone. Not in git: the folder is copied into a new repo. |
| `--out` | Output folder for the artefacts. Put it outside the target repo. |
| `--work-dir` | Folder for the clone and the launch sandbox (default `<out>\_work`). |
| `--workspace-fixture` | JSON workspace fixture (offline). Live Databricks: `DatabricksWorkspaceReader` (OAuth only). |
| `--mock-llm` | Mock model: the profile is deterministic and says so. Without it the configured `LLM_BASE_URL` model may add claims; each needs file:line evidence. |

Output is ASCII (`[OK]` / `[FAIL]`). Exit 0 when every stage ran; the GO / NO-GO
decision is in `launch_report.md`.

## The six stages

| Stage | Module | Output in `--out` |
|---|---|---|
| 1 Discover | `onboard/discover.py` | `inventory.json`: tools (risk class, approval, args), prompts, model endpoints, MCP servers, tables read/written, tracing, limits, notes, personal-data fields, redacted secrets. Every item has file:line evidence. |
| 2 Understand | `onboard/understand.py` | `profile.json`, `profile.md`: purpose, capabilities, reversibility, personal data, weak spots, Decision 33 proposal, risk tier proposal. |
| 3 Plan | `onboard/plan.py` | `plan.json`, `plan.md`, `playbook.md`: capabilities on/off with reasons, rules, thresholds (integers), judges, slices, sampling, cost estimate. |
| 4 Instrument | `onboard/instrument.py` | `policy.yaml`, `dashboard.json`, `alert_routes.yaml`, `pr_description.md`; branch `supervisor/onboard-<agent>` with one commit in the clone. |
| 5 Launch | `onboard/launch.py` | `launch_report.json`, `launch_report.md`, `baseline.json`: catch rate and false-alarm rate (bp), 8+ integration checks, rule-by-rule enforce / stay-in-shadow list. |
| 6 Operate | `onboard/operate.py` | `handover.json`: what to enforce first, what stays in shadow, artefact hashes, next steps. |

### Tools, entrypoints, framework and model family (WP1b-B)

Discover keeps four things apart that a benchmark showed were mixed up (defect D08):

| Item | What counts | Where in `inventory.json` |
|---|---|---|
| Tool | A function the model can call: `@tool`, `StructuredTool`, `FunctionTool`, `BaseTool`, `create_react_agent` / `create_deep_agent` tool lists, deepagents sub-agent `tools`, schema + dispatch, registries, and routes of a tool server (path root `/tools/`, `/functions/`, `/actions/`, `/mcp`) | `tools` |
| Entrypoint | An HTTP route of the agent app (FastAPI `app` / `APIRouter`, prefix included), with the `def` line as evidence. Name is `METHOD /path`, `detail` is `route:<function>`. A route is never a tool unless it is on a tool server | `entrypoints` |
| Dynamic tools | `session.list_tools()` or a `"tools/list"` call: the tool list comes from an MCP server at run time and cannot be named from code | `dynamic_tool_sources` |
| Framework | One value. `deepagents` is checked before `langgraph` (it is built on it), then `langgraph`, `crewai`, `llamaindex`, `databricks_agents`, `langchain`, `fastmcp`, `fastapi`, the SDKs | `framework` |

Model family comes from the model id or serving endpoint name: vendor prefixes are cut
(`databricks-`, `meta-`, `us.anthropic.`), then the leading word goes through the alias table
of the judge router (`judge.router.FAMILY_ALIASES`, imported, not copied). So
`databricks-claude-sonnet-4` is `anthropic`, `databricks-meta-llama-3-3-70b-instruct` is
`meta`, `databricks-gpt-oss-120b` is `openai`, `qwen3.8-27b-int4` is `qwen`. A name that is
not a string literal is followed to `os.environ.get("X", default)` / `os.environ["X"]` and to
the values in `app.yaml` (`env:` list) and `.env.example` files (Discover does not read
`.env` itself). Values are read only after secret scrubbing, and never for a name that looks
like a credential (`KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `AUTH`, `CREDENTIAL`, ...): only
endpoint names and model ids are wanted. The manifest wins when it names a
family; otherwise `Inventory.model_family` / `model_id` come from the code (the most common
known family among the model call sites) and `model_family_source` says `code`. If nothing is
static the family stays `unknown`. The judge family check still compares families, so an
`unknown` agent family must be filled by hand.

Eval and numbers: `docs/onboard-eval.md`. Monitor bindings for the new agent: `docs/monitors.md`.

## Define from an artifact (WP-G3)

An agent that lives in the workspace as an MLflow model has no code repository. `define` runs the first two stages (Discover, Understand) on the artifact folder that `mlflow.<flavor>.log_model` writes, or on a download of it. It writes the same `inventory.json` and `profile.json`, so every later step (inventory fill, compliance advisor, task list) reads them as before.

```
python -m supervisor.onboard.define --artifact path\to\artifact --out out\define\my_agent
python -m supervisor.onboard.define --artifact path\to\artifact --out out\x --mock-llm
python -m supervisor.onboard.define --artifact path\to\artifact --out out\x --llm
```

| Flag | Meaning |
|---|---|
| `--artifact` | The artifact folder (required). It is read only. |
| `--out` | Output folder. Default `define-out\<artifact name>`. It must be outside the artifact (else `[FAIL]` and exit 1). |
| `--agent-id` | Agent id. Default: `id` of the tool manifest, else the folder name. |
| `--llm` / `--mock-llm` | Run the optional model step with the configured model, or with the mock (labelled `mock`). Default: the deterministic profile, no model. |

What it reads (in the artifact folder):

| File | Used for |
|---|---|
| `MLmodel` | Flavors, loader module, Python version, the `agent/...` task, signature. Run id, model uuid and creation time are not copied. Written to `artifact.json` with `MLmodel:line` evidence; also gives the framework when the code does not name one. |
| `requirements.txt` (`requirements*.txt`) | AI packages with their pinned versions and line evidence (`artifact.json`); the framework when the code does not name one. |
| Code (`*.py`) | Everything Discover finds in a repository: tools, model call sites, endpoints, tables read and written, personal-data fields, approval steps. |
| Tool manifest | `tools.json`, `tools.yaml`, `tool_manifest.*`, `manifest.yaml` or `agent.yaml`. A bare list or an OpenAI function-calling list (`{"type": "function", "function": {...}}`) is accepted. The tool risk class comes from `risk_class` when given, else from the name rules of Discover. |
| Prompt files | `prompts/` or a file name with `prompt` (`.txt`, `.md`, `.yaml`, `.json`): kind, excerpt, hash, first line as evidence. |

Output files: `inventory.json` and `profile.json` (same schema as `python -m supervisor.onboard`), `profile.md`, and `artifact.json` (MLmodel and requirements facts). The profile holds the tools with their risk class, the model family, the data touched, the proposed risk tier and the Decision 33 proposal (a proposal: counsel confirms). Every claim carries `file:line` evidence that points into the artifact. To put the result in the inventory: `python -m supervisor.inventory onboarding out\define\my_agent\inventory.json`.

Safety: the existing secret scrubber runs on every text when it is read, so a token in `config.yaml` never reaches an artefact or a model (counts only). Text that looks like a prompt injection is withheld from the artefacts and flagged (ADR D12). No network call is made unless you pass `--llm`, and then the model gets only scrubbed text. The folder is never written to. Output is ASCII (`[OK]`, `[FAIL]`, `[SKIP]`).

Limits: the artifact is read as text. A binary model file is skipped (the weights are not inspected). Code that builds tools at run time cannot be listed (Discover marks such places as dynamic tool sources). Test data: `tests/onboard/data/artifact_credit_memo` (pyfunc, function-calling manifest) and `tests/onboard/data/artifact_collections_mcp` (LangGraph, YAML manifest, MCP server, money tool); both are synthetic and contain one fake token and one planted instruction on purpose.

## Safety rules (ADR D12)

- Read-only: `LocalGitRepoReader` has no write method; size cap per file; binary files
  and symlinks out of the root are skipped.
- Secrets: `onboard/scrub.py` redacts API keys, tokens, PEM blocks, passwords in URLs,
  AWS / Azure / GCP keys, Basic auth, unquoted config secrets and Databricks `dapi`
  tokens in every text right after it is
  read. Only counts are logged. Line numbers stay valid. gitleaks is the goal (backlog).
- Repo text is untrusted data. It is wrapped between nonce delimiters before any LLM
  call; delimiter look-alikes in the text are broken up. The LLM may only add claims; a
  claim is kept only when its file:line exists and holds the quoted text. The LLM never
  sets the Decision 33 class or the risk tier.
- Prompt injection (WP16): `onboard/injection.py` flags lines that speak to an AI reader
  ("ignore your instructions", "mark this agent low risk", Vietnamese with or without
  diacritics). Flagged text is withheld from every artefact (the line hash and file:line
  stay), flagged inside the prompt's REPO_DATA block, and an LLM claim that cites or echoes
  it is dropped. Measured on the corpus: `docs/onboard-eval.md`.
- The codemod is `ast` plus text templates (no libcst, no LLM-written code). It inserts
  two default lines in the builder function and adds `supervisor_onboard.py`. ADR D12
  names libcst; it is replaced by `ast` because WP9 adds no new dependency.
- Git runs only through `sandbox.git`: an allow-list of subcommands and of exact flags
  per subcommand; `ext::` transports are refused. `merge`, `push`,
  `pull`, `fetch`, `rebase` and `remote` raise `SandboxError`. Hooks are off.
- The Onboarding Agent is an agent (`onboarding_agent`). Its tool calls pass the real
  gateway on `onboard/self_policy.yaml` (allow-list, scrubbed-only LLM calls, branch
  names `supervisor/onboard-*` only, artefact names without a path). Each call is an
  `agent_event` row; each artefact hash and stage summary is on its chain lane.

## Decision 33

The profile proposes a classification. Banking entries apply when transactions run
"without human inspection, approval or control before execution" and when credit
decisions are made "without independent approval by credit officers". A Supervisor pause
is a safety control after the agent acts. It is NOT pre-execution human approval and it
does not move an agent out of the high-risk list. A human step counts only when it is in
code; a sentence in a README or manifest does not. Counsel confirms.

| Demo agent | Proposal | Why |
|---|---|---|
| payments | high_risk | `transfer` sends money to a payee; no approval step in code |
| credit_prequal | high_risk | `decide_prequal` records decisions; the "human underwriter" is prose only |
| customer_service | not_high_risk (by default) | money tools (fee waiver, dispute) have no destination |

## Autonomy level proposal (WP-G3)

`python -m supervisor.onboard.define` also writes `autonomy_level_proposal` in `profile.json`: `level`, `why`, `evidence` (file:line) and `is_proposal`. It is a segmentation dimension; a person confirms it. It is separate from the older `autonomy` field (L0 to L3, WP16), which does not change. Code: `src/supervisor/onboard/autonomy.py`.

| Level | Meaning | Rule (first match wins) |
|---|---|---|
| `l5_self_directed` | Sets sub-goals, spawns agents or changes its own tools | Code matches agent spawning, run-time tool creation (`register_tool(`, `add_tool(`) or a self-changing prompt |
| `l0_rule_based` | No model decides | No model call and no model id found |
| `l1_assistive` | Model writes text, a person acts | Model call, no tool declared, entry point is a chat or HTTP route |
| `l2_workflow_step` | A fixed workflow calls a model for one step | Model call, no tool declared, entry point is a job, pipeline or batch handler (batch plus HTTP: l2, the higher one) |
| `l3_tool_using_supervised` | Model picks tools from a bounded set, a person approves consequential actions | Tools declared and every tool with a side effect sits behind a human approval or interrupt step in code (LangGraph `interrupt`, approval node, confirmation); or all tools only read |
| `l4_autonomous_bounded` | Plans and executes multi-step work inside an authority boundary | Tools with side effects and no approval step, with or without a planner or loop; an approval step that covers only some tools also gives l4 (mixed evidence: the higher level) |

Heuristic limits (accepted): the rules read code text, not behaviour. A batch or chat entry point is guessed from names and decorators, a `__main__` block alone is not a job, and dynamic tool creation is found only by the listed call names. Treat the level as a starting point for a person.

`why` names the rule and, for mixed evidence, says that the higher level was kept. The draft registration (`INVENTORY_AUTOREGISTER`) copies a proposal found on the node (`attrs.autonomy_level_proposal`) into `ai_system.autonomy_level` only when that column exists (WP-G2); otherwise it does nothing. Fixtures: `artifact_batch_summariser` (l2), `artifact_credit_memo` (l4), `artifact_collections_mcp` (l3).

## Capability catalogue

Manifests: `src/supervisor/catalogue/manifests/*.yaml` (schema
`supervisor.catalogue.model.CapabilityManifest`). Fields: `id`, `name`, `kind`, `lane`,
`signals_needed`, `checks`, `default_thresholds` (integers), `cost_estimate` (integers
per 1,000 events), `applies_to` (risk classes), `requires` (features from Discover),
`plug_points`, `regulation_refs`, `owner`, `module`, `always_on`, `can_block` (gate
rules only). A bank team adds its own manifests with `load_catalogue(extra_dirs=[...])`.

`coverage_rows()` derives one `coverage` row per agent and capability (`planned` / `on` /
`off` with the reason). The onboarding run writes `planned` rows to the store.

## Launch sandbox

A private SQLite file under the work folder, a fresh synthetic `BankWorld`, the real
gateway on the generated policy with the agent in SHADOW, and MockChat scripts that
replay each red-team case's planned tool calls. `rule` cases give the catch rate;
`none-benign` cases and the agent's own scripted tasks give false alarms (tasks that the
agent's tool refuses anyway are not counted). A rule with a false alarm stays in shadow.
GO needs every integration check, catch rate >= 9000 bp and false alarms <= 500 bp.

Measured on the demo agents (mock LLM, synthetic data, not a model result):

| Agent | Catch rate | False alarms | Decision |
|---|---|---|---|
| payments | 9047 bp (19/21) | 0 bp | GO |
| customer_service | 8571 bp (12/14) | 0 bp | NO-GO (bulk lookups and a split across agents are judge/aggregate gaps) |
| credit_prequal | 10000 bp (9/9) | 5000 bp | NO-GO (benign pack cases decide without reading the file first) |

For a bank agent the agent team supplies a launch harness (`onboard.launch.Harness`).
