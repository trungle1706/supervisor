# Risk register (WP29)

Status: built, off by default (`RISK_REGISTER_ENABLED=1` turns on the API, the job and the CLI;
`CONSOLE_RISKS_ENABLED=1` also shows the Risks page and the Risks tab). Design choices:
`docs/adr/D26-risk-register.md`.

## What it answers

| Question | Answer |
|---|---|
| (Reviewer, risk manager) What can go wrong with this agent, and how big is it? | Risks with likelihood, impact, score, band, owner and review date. |
| What does the agent inherit from what it uses? | A risk on a shared model, tool, MCP server or dataset applies to every agent that reaches it in the inventory graph. The agent level is the maximum. |
| Which control holds the risk down, and does it work? | A risk links to compliance matrix rows, gate rules, assurance packs and monitors. Runtime counts show if they work. |
| Why is the residual score lower than the inherent score? | Only when the linked controls show `working` in the last window. The row says why (a fixed reason code). |
| (Auditor, second line) Can I check it? | `risk_evidence` rows (integers and hashes) and a chain record per window; `risk_change` chain records and two `console_action` rows per edit. |

## Model

```
Risk  --anchored on-->  agent (its own inventory node)   or   inventory node (model, endpoint, tool, MCP server, dataset)
  |--- RiskLink --> matrix row (obligation id)      reference
  |--- RiskLink --> gate rule id                    control   (evidence: rule hits)
  |--- RiskLink --> assurance pack id               control   (evidence: pack verdicts)
  |--- RiskLink --> monitor name                    control   (evidence: monitor status)
  `--- RiskLink --> case id                         reference
Risk --1:n--> risk_evidence (one row per window, append-only)
```

| Field | Rule |
|---|---|
| `risk_id` | 1 to 64 characters, `A-Z a-z 0-9 _ . : -`. Generated (`RSK-` + 10 hex) when you do not give one. |
| `category` | `money_movement`, `credit_decision`, `pii`, `injection`, `model_behaviour`, `availability`, `third_party` (fixed list). |
| anchor | `agent_id` (the agent's own node), or `node_id` (an inventory node id `inv_...`). One of them is required. |
| inherent | `inherent_likelihood` and `inherent_impact`, whole numbers 1 to 5. |
| `marginal_risk`, `marginal_note` | The change caused by using AI instead of a fixed process: 1 (much smaller) to 5 (much higher), with a short note. Information only; it is not part of the score. |
| `treatment` | `avoid`, `mitigate`, `accept`, `transfer`. `accept` needs a `treatment_note` (the justification) and a residual equal to the inherent score. `avoid` and `transfer` with a residual below the inherent score need a `treatment_note` too: no runtime evidence checks them. |
| residual | `residual_likelihood`, `residual_impact`: what the owner declares for the treated risk. Not above the inherent value on either axis. Defaults to the inherent value. |
| `owner`, `review_date` | An active risk needs both. A risk is `review_overdue` after `review_date` (plus `review_grace_days`). |
| `status` | `draft` (listed, not counted), `active`, `retired` (kept as history, not counted). |
| `source` | `starter`, `import` or `manual`. Editing a risk by hand makes it `manual`. |

Likelihood scale (adapted from the usual 5-point scale): 1 rare, 2 unlikely, 3 likely, 4 very likely, 5 almost certain. Impact scale: 1 negligible, 2 minor, 3 moderate, 4 major, 5 severe. The bank defines what each step means for money, customers and regulators; the product only stores the integer.

## Scoring

`score = likelihood x impact` (1 to 25), integers only. Band thresholds are in `config/risk.yaml` and are **ILLUSTRATIVE**: the bank's risk function sets and signs the real appetite.

| Band | Illustrative score |
|---|---|
| low | 1 to 4 |
| medium | 5 to 9 |
| high | 10 to 15 |
| critical | 16 to 25 |

The four band names are the four inventory risk levels (`low < medium < high < critical`), so the WP24 graph code carries them. Scores are computed when read and never stored. Every page, export and API answer that shows a band says the bands are illustrative while `illustrative: true` is set in the config.

## Inheritance

```
agent level = max( band of every ACTIVE risk on a node the agent reaches along ACTIVE `uses` edges, itself included )
```

* The graph code is the WP24 code (`Graph.effective_risk`, iterative Tarjan over strongly connected components, so a cycle ends and the result does not depend on the order of edges). `risk/inherit.py` only builds a copy of the graph whose node levels are the bands of the register risks, and calls it. A second function walks the same edges to list which risks reach an agent; a test checks that the two agree on random graphs.
* Only `uses` edges carry risk (same as the inventory). `reads`, `writes`, `hosted_on`, `serves`, `owned_by` do not.
* A node with status `gone` (retired in the inventory) holds no risk and passes none up. An inactive edge passes nothing. `draft` and `retired` risks are listed, not counted.
* Two levels are given for each agent: inherent (no controls) and residual (after the evidence rule).
* A risk written for an agent that has no node in the graph yet (inventory off or not filled) counts for that agent only. Inheritance across agents needs `INVENTORY_ENABLED=1` and a filled graph.
* The Decision 33 class is not an input and is not changed.

## Evidence from runtime

`python -m supervisor.jobs.risk_evidence` (also the scheduler job `risk_evidence`, every `SCHED_RISK_EVIDENCE_S`, default 21,600 s, when `RISK_REGISTER_ENABLED=1`). For each active risk it looks at the **supervised** agents the risk applies to, in the window of the last `RISK_EVIDENCE_WINDOW_DAYS` days (default 7) that ends at the last full hour. A supervised agent has gate state `RUNNING`, `PAUSED` or `QUARANTINED`. `SHADOW`, `RETIRED` and unknown agents are not evidence: they only log or enforce nothing (counted in `agents_excluded`).

| Link | A control is `working` when | `failing` when | otherwise |
|---|---|---|---|
| rule | at least one tier-0, non-advisory, non-mock verdict of that rule id with action `log`, `alert`, `block` or `pause` in the window that the gate enforced: a SHADOW "would" row (label `shadow_*`), a rule error (`rule_error`) and a fail-mode row are not hits | the rule id is not in the deployed policy any more | `idle` (no hit proves nothing) |
| pack | newest non-mock `eval_result` of **every** supervised agent the risk applies to has status `ok` (or `skip`) | any status `fail` or `error` | `idle` (`warn`, an agent with no result, none, mock) |
| monitor | newest daily `monitor_status` of **every** supervised agent is `ok`, for the deterministic monitors `fairness`, `drift` and `multiagent` (`ok` = the monitor ran and produced values) | never | `idle` (`not_applicable`, `no_data`, missing for one agent). `quality` is an advisory LLM scorer (rule R1) and `oversight` and `sweeps` write no status: a link to them is a reference, never evidence |

Matrix and case links are references. They never count as a control.

**Which links are evidence and which are references:**

| Link | Evidence | Reference only |
|---|---|---|
| rule | any rule in the deployed policy | - |
| pack | a pack not scored by a judge model | judge-scored packs (`groundedness_monitor`, `halueval_vi`, `ragas_rag_triad`, `selfcheck_consistency`, `simpleqa_vi`, `truthfulqa_vi`) unless `RISK_EVIDENCE_JUDGED_PACKS=1` (owner decision, default 0) |
| monitor | `drift`, `fairness`, `multiagent` (they write a status) | `quality` (LLM scorer), `oversight`, `sweeps` (no status) |
| matrix, case | - | always |

The harness row `starters` fails when a risk has only reference links.

**The rule that may lower a residual score** (`risk/evidence.py`, `assess`):

1. Only a `mitigate` risk can be lowered. For `avoid`, `accept` and `transfer` the residual is the declared value (the gate cannot see a contract or a decision).
2. The risk state is `failing` if any linked control is failing; `working` if none is failing and at least `min_working_controls` (default 1) are working; otherwise `no_evidence`. With no supervised agent or no linked control the state is `no_evidence`.
3. Residual = the **declared** residual only in state `working`. In every other state, and when the job has not run, the last row is older than two windows (`stale_evidence`) or the risk changed after the last row (`changed_since_evidence`: a new anchor, treatment, inherent or declared value, or a control link added or removed; a text edit does not count), residual = the **inherent** score. So evidence can lower a score from the inherent value to the declared value, never below the declared value, and a broken control raises it again.
4. Every row stores the reason as a fixed code: `controls_working`, `control_failing`, `no_working_control`, `no_links`, `no_supervised_agent`, `treatment_declared`, `stale_evidence`, `no_evidence_yet`, `changed_since_evidence`.

Output per run and risk: one row in `risk_evidence` (append-only; ids `rev_` + hash of the risk, the window end and the evidence basis, so a second run in the same window writes nothing unless the risk or its controls changed) and one `risk_evidence` chain record (lane `agent:<id>` for an agent risk, root lane for a shared-component risk). Both hold integers, codes and hashes only: no text, no names (rules R1 to R3). No judge or classifier is an input.

Limits to know: a rule that fires rarely (for example "unapproved tool") stays `idle`, so a mitigated risk linked only to such a rule keeps its inherent score until a pack or monitor shows the control works; link an assurance pack that replays the red-team cases to such a risk. The agent's gate state is read now to choose the supervised agents; the hits themselves carry the gate's label from the time of the call, so a hit written while the agent was in SHADOW never counts. A shared risk counts rule hits of any supervised agent that reaches it (a rule may be in scope for one agent only), but a pack or monitor must be `ok` for every one of them. Agents that start to use a shared component count from the next pass.

## Console

`/console/risks` (needs `CONSOLE_RISKS_ENABLED=1` and `RISK_REGISTER_ENABLED=1`; permission `risks.view`, all roles). Tiles (active, critical, high), filters (text, agent, category, residual band, owner, status), sortable paged list, row drawer with tabs Details, Links and Evidence (the evidence tab shows the residual score per window as bars and the counts). The Agent page has a **Risks** tab (the agent's inherent and residual level, its own and inherited risks). The page is read only: edit through the API or the importer. It uses the shared listing, drawer and tab components; no style was added.

## API

| Method and path | Permission | Does |
|---|---|---|
| `GET /v1/risks` | `risks.view` | List; filters `agent`, `category`, `band`, `owner`, `status`, `treatment`, `q` |
| `GET /v1/risks/agents/{agent_id}` | `risks.view` | Register level and risks of one agent (own and inherited) |
| `GET /v1/risks/{risk_id}` | `risks.view` | One risk: scores, bands, links, applies-to agents, last 12 evidence rows |
| `GET /v1/risks/{risk_id}/evidence` | `risks.view` | The evidence rows |
| `POST /v1/risks` | `risks.edit` | Create (JSON body, optional `links: [{kind, target}]`) |
| `POST /v1/risks/{risk_id}` | `risks.edit` | Update; optional `row_version` (stale = HTTP 400) |
| `POST /v1/risks/{risk_id}/links` | `risks.edit` | `{"action": "add"\|"remove", "kind", "target"}` |

`risks.edit` is held by `reviewer`, `owner` and `admin`. Every POST writes two `console_action` rows (attempted, then the outcome with the hash of the risk and its links before and after; a denied call writes a `denied` row) and a `risk_change` chain record. User errors are HTTP 400 with the reason, an unknown risk is 404, a missing role is 403; never 500. A link target must exist today (see below). With the flag off every route answers 400 with a message.

## CLI

```
set RISK_REGISTER_ENABLED=1
python -m supervisor.risk import config\risks --source starter --by your.user.id
python -m supervisor.risk list --agent payments --band critical
python -m supervisor.risk score
python -m supervisor.risk export --out out\risk --format both
python -m supervisor.jobs.risk_evidence
python -m supervisor.risk.harness
```

Output is ASCII. `import` writes chain records, and the chain has one writer per lane: run it when the app is stopped, or use the API. `export` writes `risks.json`, `risks.csv`, `risk_links.csv` (cells that start with `=`, `+`, `-` or `@` get a leading `'`).

## Starter risks and how a bank imports its own register

`config/risks/*.yaml` holds 19 starter risks: 6 for payments, 6 for the credit decision agent (`credit_prequal`, the loan pre-qualification agent of this repo), 5 for customer service, 2 on the shared model endpoint `qwen3:4b` (every agent inherits them). They are synthetic and illustrative worked examples. Every rule id, obligation id, pack id and monitor name in them exists today, and a test (`python -m supervisor.risk.harness`, row `starters`) checks it, also that a rule it links is in scope for the agent.

A bank imports its own register in the same format (one file or a folder of `*.yaml`):

```yaml
version: 1
risks:
  - id: BANK-OPS-0042
    agent: payments                 # or:  node: {kind: model_endpoint, name: "qwen3:4b"}
    title: ...
    description: ...
    category: money_movement
    inherent: {likelihood: 4, impact: 5}
    marginal: {score: 3, note: ...}       # optional
    treatment: mitigate
    treatment_note: ...                   # required for accept
    residual: {likelihood: 2, impact: 5}
    owner: ...
    review_date: 2027-04-20
    status: active
    links:
      matrix: [VN-TT50-2024-A10.1-01]
      rule: [PAY-02]
      pack: [owasp_agentic_redteam]
      monitor: [oversight]
```

Rules of the importer:

* All or nothing: every document is checked first, then everything is written. A bad category, a link to something that does not exist, a duplicate id, two documents with the same anchor and title but different treatments (`conflicting treatments`), `accept` with a lowered residual: the file is refused with the reason and nothing is written. `--dry-run` only checks.
* A re-import of the same file changes nothing. It updates a risk whose `source` is `starter` or `import` and replaces its links with the file's links. A risk a person edited (`source` manual) is left alone unless `--overwrite-manual`.
* The importer is the bank's change control for the register: keep the file in git and import it from there. Map the bank's own scales to 1 to 5 once, in the file; the product does not convert.
* Each created or changed risk writes a `risk_change` chain record. It carries `actor_ref`, a keyed hash of the actor id (the id can be an e-mail); the readable actor is only in the `console_action` audit row.
* `python -m supervisor.risk import` has no login. It runs with the operator's own shell and store access, so it needs `--by <your own user id>` and refuses to run without it. The id is written to a `console_action` row (permission `risks.edit`, method `CLI`).

## Reference catalogue

A link is accepted only if its target exists now: `matrix` = an obligation id of the regulation knowledge base (one matrix row each), `rule` = a rule of the deployed policy (the `rule` table; the policy folder when nothing is deployed), `pack` = an assurance pack manifest, `monitor` = a monitor of `regulations/schema/controls.yaml`, `case` = a row of `cases`. `RefCatalogue` (`risk/refs.py`) takes plain callables, so tests and other modules use their own.

## For other modules

```python
svc = RiskService.from_adapters(adapters, evidence=chain_writer)
svc.agent_summary("payments")     # levels, risks with scores, bands and evidence state (plain data)
svc.control_links("RSK-PAY-001")  # [(kind, target)] the evidence rule looks at
svc.add_link("RSK-PAY-001", "rule", "PAY-02", actor)
```

* **WP30 control catalogue:** a control that maps to risks adds `rule`, `pack` or `monitor` links with `add_link`; `control_links` is the one place the evidence rule reads them, so a catalogue can feed it without a change to the evidence code. A new link kind is a change to `LINK_KINDS`, `CONTROL_KINDS` and the `Collector.count` branch.
* **WP31 transparency report:** `agent_summary(agent_id)` and `export_json()` give the register view of an agent as plain data (scores, bands, treatment, owner, review date, links, evidence state and reason). The report builder needs no SQL.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `RISK_REGISTER_ENABLED` | `0` | `/v1/risks` routes, scheduler job `risk_evidence`, CLI. Off: routes answer 400, tables stay empty |
| `CONSOLE_RISKS_ENABLED` | `0` | Risks page and Agent tab (needs the first flag too) |
| `SCHED_RISK_EVIDENCE_S` | `21600` | Evidence pass interval (seconds, minimum 60) |
| `RISK_EVIDENCE_WINDOW_DAYS` | `7` | Length of the evidence window (1 to 90) |
| `RISK_CONFIG` | `config\risk.yaml` | Band thresholds, `min_working_controls`, `review_grace_days` |
| `RISK_EVIDENCE_JUDGED_PACKS` | `0` | `1`: packs scored by a judge model may count as evidence (rule R1: leave off until the owner decides) |
| `RISK_STARTER_DIR` | `config\risks` | Folder of the starter risks |

On Delta run `python -m supervisor.jobs.bootstrap_schema` before turning the flag on (three new tables).

## Harness (expert view: operational risk manager, internal auditor under the Three Lines model)

`python -m supervisor.risk.harness` (also `tests/risk/test_harness.py`, with a baseline in `tests/fixtures/risk/baseline.json`).

| Row | What it holds | Result at build time |
|---|---|---|
| Golden set | 50 synthetic scenarios (`tests/fixtures/risk/golden.jsonl`): 20 score and band, 12 inheritance over a graph, 12 evidence rule, 6 link existence; 30 dev and 20 held-out; id, source, licence, labeller and rubric on each item. Expected values come from an independent reference implementation (`generate.py`) | dev 30 of 30, held-out 20 of 20, Wilson 95% intervals in the report |
| Determinism | The golden run twice gives the same hash | equal |
| Starter consistency | Every starter risk links to ids that exist today; agents and nodes resolve; rules are in scope | 19 risks, 85 links, 0 problems |
| Adversarial | 20 probes the templates do not make: cycle, self loop, 3,000-deep chain, retired node, draft and retired risk, conflicting treatments, duplicate id, `accept` with lowered residual or no note, evidence of a SHADOW agent and of a RETIRED agent, a rule removed from the policy, a mock pack result, a failed pack against rule hits, stale evidence, residual above inherent, type confusion (`True`, `"3"`, `3.0`, 0, 6), bad ids and link targets, CSV formula injection | 20 of 20, reported as a separate row |

What each expert checks:

| Operational risk manager | Test |
|---|---|
| Score is likelihood times impact, band from the thresholds, boundaries right | `score` scenarios, `test_model.py` |
| An agent is as risky as the worst risk it reaches; shared component reaches all | `inherit` scenarios, `test_inherit.py` (workspace_7 fixture) |
| Retired, draft, gone and inactive things stay out | adversarial probes 4 to 6, `test_inherit.py` |

| Internal auditor (Three Lines) | Test |
|---|---|
| A lower residual score has working evidence and a reason code | `evidence` scenarios, `test_evidence.py` |
| A removed or failing control raises the score again | probes 13 and 15 |
| Evidence is not taken from SHADOW, retired or mock sources | probes 11, 12, 14 |
| Every change is attributable | `tests/console/test_risks.py` (two audit rows, chain record) |
| Every link points at something that exists | `link` scenarios, starter check |

There is no model in this capability (the score, the inheritance and the evidence rule are code), so there is no mock path and no model card. GO / NO-GO thresholds (100% on every row) are ILLUSTRATIVE and declared in the harness. A pass on these rows does not show that the bank's scores are right: the likelihood and impact values are human judgement.

## Not done (see BACKLOG)

Console forms to create and edit; risk appetite as an object and the signing step for it; a four-eyes approval of a new or accepted risk; automatic recommendation of risks from a library; a synthetic probe through the gate to prove a rarely firing rule works.
