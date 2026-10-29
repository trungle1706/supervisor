# Databricks showcase plan (v0.10)

Owner request (2026-10-29): show the product end to end on the bank's Databricks workspace.
Everything is synthetic. Every seeded row carries the tag `demo:showcase` and is removed by one
command. Model-using steps run on the bank's gateway model (GLM 5.3 flash) on Databricks; on a
laptop they run only when `LLM_BASE_URL` is set.

## 1. Storyline (about 25 minutes)

| Act | Minutes | What the audience sees | Built by |
|---|---|---|---|
| 1 Portfolio | 3 | My overview with 300 AI systems: systems by risk class, eight risk types by system, open duties, incidents, overdue reviews | WP-D1 |
| 2 Three journeys | 10 | Three candidate Apps found by the scan, each taken through the nine steps to a different class (low, medium, high), assessed on eight risk types, fitted with guardians, approved, then live with real traffic | WP-D2 |
| 3 AI factory | 6 | Two new assessment agents built by two risk teams: policy upload, helper drafts, golden cases, sample batch, full gate with kappa, simulation review, two-person release | WP-D3 |
| 4 Guardian factory | 4 | Two new guardians: plain words to artifact, benchmark against the live detector, shadow on live traffic, go-live, then a call blocked or masked | WP-D3 |
| 5 Proof | 2 | Regulator pack of the high-risk system, offline verify, the law-change banner | existing |

## 2. Act 2: the three journeys

| Candidate App | Story | Expected class | Why (articles) | Guardians proposed |
|---|---|---|---|---|
| `kb-helpdesk-bot` (A1 knowledge chatbot) | Staff ask about internal HR and policy documents | low | internal, no customer, supports only (Decree 142 Art. 8(2), 9(3)) | dlp_vn on the floor |
| `cs-assistant` (A2 customer service, LangGraph, human interrupt) | Customers chat about cards and fees | medium | customers may mistake it for a person (Law Art. 9(1)(b)); TT53 Art. 20(3) disclosure | dlp_vn, injection_regex, judge sample |
| `payment-ops-copilot` (A3 payments ops, L4) | Prepares and executes transfers | high, self-assess | auto payment above the SBV threshold without pre-approval (QĐ 33 IV.1, TT53 Art. 4(2)) | injection pair, money pre-approval, session limits, the new transfer guardian |

Each journey shows: the candidate on the Candidates tab with a triage score; source intake; the
facts card; the classification tree with the highlighted path; the eight risk types run by the
orchestrator (live factory agents where they exist, rule proposals elsewhere); the duties step;
the smart-guardian proposal and the pre-deploy test; the stage approval by a second person;
SHADOW then RUNNING; then live traffic from a traffic generator showing allowed, masked, paused
and blocked calls on the agent page and Activity.

## 3. Act 3 and 4: the factories

| Item | Team | Content |
|---|---|---|
| Agent 1: `credit-model-risk-assessor` | Model Risk | from the `model` template; internal policy TCB-MRM-POL-07 (synthetic) uploaded through internal documents; checklist drafter proposes rows; 60 golden cases; sample batch; full gate; simulation review on the three journey systems; release by the team lead and the second line |
| Agent 2: `customer-data-privacy-assessor` | Data Office | from the `data_governance` template; internal policy TCB-DG-STD-02 (synthetic); loop harness with the rules evaluator; same gate path |
| Guardian 1: `vn-account-number-mask` | Data Office | regex, tool_call, redact; starter pack from the generator; benchmark vs dlp_vn; shadow; go-live |
| Guardian 2: `transfer-above-limit-needs-approval` | Payments and Cyber | policy: forbid `transfer` with amount above 20,000,000 VND unless approved; benchmark; shadow on the payments traffic; go-live; a call above the limit is blocked live |

## 4. Act 1: the 300-system portfolio (database only)

Realistic synthetic metadata for 300 AI systems across the bank, written straight to the tables
(SQLite or Delta through the same state backend), not real models. Distribution (illustrative):

| Dimension | Values |
|---|---|
| Business unit | Retail, SME, Corporate, Treasury, Operations, HR, IT, Risk, Compliance, Marketing, Contact Centre |
| AI type | assistant, decision, automation, platform, feature; generative, agentic, customer-facing, decides flags |
| Class | prohibited 2, high certify 6, high self-assess 38, medium 96, low 118, not an AI system 12, not classified yet 28 |
| Stage | initiation 30, design 34, validation 42, deployment 36, operation 140, re-evaluation 12, retirement 6 |
| Eight risk types | per system, statuses consistent with the class and stage (high and operation mostly pass, a few fail; design mostly not started) |
| Duties | obligation status rows for the instruments that apply, with gap tasks for the open ones |
| Guardians, gate | bindings, 30 days of daily gate-decision rollups (allowed, blocked, masked, paused) for systems in operation, a few incidents and cases |
| Inventory | graph nodes and edges for each system (agent, model, endpoint, tools, datasets, owner team, vendor) and 40 unmanaged candidates |

### How to seed (WP-D1)

The seeder is `src/supervisor/demo/showcase_portfolio.py`. It needs `SHOWCASE_ENABLED=1` (it
refuses without it, also inside a Databricks App) and a store with the schema in place
(`python -m supervisor.jobs.bootstrap_schema`). It writes state tables only (no evidence-chain
record, no case event), 300 systems, about 22,000 rows, 5 seconds on SQLite. On Delta it sends
batched `INSERT` statements through the Statement Execution API. Same `--seed` gives the same
ids; a second run skips every row that exists.

Windows cmd, from the repository folder, with `SQL_BACKEND=databricks_rest` in `.env`:

```
set SHOWCASE_ENABLED=1
uv run python -m supervisor.demo.showcase portfolio --systems 300 --dry-run
uv run python -m supervisor.demo.showcase portfolio --systems 300 --seed 1
uv run python -m supervisor.demo.showcase portfolio --remove
```

Databricks notebook cell (the repository folder is on the cluster path; the notebook runs as a
person, so the App service principal needs no extra grant for the seed):

```
import os, sys
sys.path.insert(0, "/Workspace/FILL-ME-repo-folder/src")
os.environ["SHOWCASE_ENABLED"] = "1"
os.environ["SQL_BACKEND"] = "databricks_rest"
from supervisor.config import load_settings
from supervisor.demo import showcase_portfolio
showcase_portfolio.run(load_settings(), systems=300, seed=1)
# showcase_portfolio.run(load_settings(), remove=True)   # delete exactly the showcase rows
```

For the blocks of Act 1 turn on `GOVERNANCE_ENABLED`, `CONSOLE_NAV_V3`, `CONSOLE_OVERVIEW_V4`,
`INVENTORY_ENABLED`, `CLASSIFICATION_V2`, `RISK_DIMENSIONS` and `OVERVIEW_PORTFOLIO` in the
App. A laptop try-out: add `--demo-dir data\local\showcase` (a SQLite store of its own; run
`bootstrap_schema` with the same data dir first).

Tags and removal. `ai_system.tags` and `inventory_node.attrs` carry `demo:showcase`; the note,
summary and reason texts start with `[demo:showcase]`; every other row has a system, agent, case
or incident id that starts with `shw_` (nodes: name `shw-`, edges: reference `shw:`).
`--remove` deletes by those prefixes and by nothing else. The gate rollup writes
`decision_daily` rows of dimension `agent` only; the `total` rows belong to the rollup job.

## 5. Work packages

| WP | Content |
|---|---|
| WP-B1 | Code backlog of the handoff note: detector-settings writer, autonomy-cap enforcement, law-changes nav link, watcher noise fix, user groups |
| WP-D1 | Portfolio seeder: `python -m supervisor.demo.showcase portfolio --systems 300 [--remove]` |
| WP-D2 | Journeys: scripted runner for the three candidates, traffic generator, showcase script |
| WP-D3 | Factory showcase: two agents and two guardians with full test results |

Rules: synthetic data only; the tag `demo:showcase` on every row; `--remove` deletes exactly
the tagged rows; no row in the evidence chain pretends to be real (chain records of seeded rows
carry `demo: true`); default off (`SHOWCASE_ENABLED=1` needed); never in a production App
without the flag.
