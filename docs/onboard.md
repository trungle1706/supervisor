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
