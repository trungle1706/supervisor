# Phase 7: Navigator-style overview, My agents, and the register workflow

Owner: the hub session. Workers: one Sonnet worker per WP in its own worktree, one independent
reviewer per WP. Rules of `CLAUDE.md` and `docs/BANK_DEPLOY_GUIDE.md` apply. Every switch below
is OFF by default; the off path behaves as before and has a test.

Reference: the SAS AI Navigator home screen (banner "how are we doing" + alerts, approval
pipeline, assessment completion per policy, risk classification bars, totals strip, action items,
asset cards). We keep OUR terms: AI system, agent, guardian tool, gate state, Decision 33 class,
autonomy level, risk level. Do not copy SAS words (use case, asset, usage authorization).

## 0. Shared facts the three WPs build on

| Object | Where it lives | Read with |
|---|---|---|
| Registered agent | table `agent` (+ `agent_version`) | `readmodels.agent_cards`, `AgentRegistry` |
| Policy-only agent (gate knows it, no row) | policy `agents:` section | `runtime.policy.doc.agents`, `GateStates.get_state` (`registered: false`) |
| Unregistered candidate from the workspace scan | `inventory_node` status `unmanaged`, kinds `system` (role `databricks_app`), `model_endpoint` (`agent_endpoint`), `genie_space`, `job` | `InventoryService.unmanaged()`, `Graph` |
| AI system, team, links | `ai_system`, `system_team`, `system_component` | `governance/systems.py` |
| Guardian switches per system and the floor | `guardian_binding`, `RulesService.guardian_floor` | `governance/guardians.py`, `/v1/systems/{id}/guardians` |
| Guardian results per agent | `finding` (detectors), `verdict` (gate), `eval_result` (packs), `case`, judge rows in `verdict`/`case` (is_mock), monitor rows (`oversight_metric`, drift status) | existing read models of the Agent page tabs |
| Readiness, class proposal, floor preview | `console/systems_wizard.py` (`readiness`, `_class_preview`, `_floor_preview`) | reuse |
| Decision 33 draft | `RulesService.draft`, `POST /v1/systems/{id}/classification/draft` | reuse |

Sidebar: `CONSOLE_NAV_V3` bar. "My overview" is the first bar item. The three WPs add a tab
strip under it: **Overview | My agents | Candidates**. Tabs follow the `nav_v3.Tab` pattern.

## 1. WP-N1: My overview as a dashboard, with the candidate triage table

Flag `CONSOLE_OVERVIEW_V4=1` (needs `CONSOLE_NAV_V3=1`). Off: today's `ov_my_systems.html`.

### 1.1 Layout (top to bottom; the grid stacks to one column under 900 px)

```
 +------------------------------------------+----------------------------+-----------------------------+
 | HOW ARE WE DOING  (banner)               | ASSESSMENT COMPLETION      | RISK CLASSIFICATION         |
 | state word + one line + "open items N"   | per dimension: done/of bar | per autonomy level: stacked |
 |------------------------------------------| (intake, class, pre-deploy | bar of risk levels          |
 | REGISTRATION PIPELINE                    |  check, guardians, tasks)  | legend: prohibited high     |
 | candidates -> draft -> intake -> ... ->  |                            |         medium low unspec.  |
 |  in production ; counts per stage        |                            |                             |
 +------------------------------------------+----------------------------+-----------------------------+
 | TOTALS: AI systems N (H high) | agents N (gate: R running, S shadow, P paused) | models N | guardian |
 |         tools on N / N | open cases N | tasks due N                                                   |
 +------------------------------------------------------------------------------------------------------+
 | YOUR ACTION ITEMS (left, 1/3)      | TOP CANDIDATES TO REGISTER (right, 2/3)                         |
 |  needs your attention (N)          |  table: candidate | kind | signals | impact | autonomy | score  |
 |  awaiting your input (N)           |         | description | recommended action [Register]           |
 +------------------------------------+-----------------------------------------------------------------+
 | MY SYSTEMS AND AGENTS: cards (name, kind, stage, risk pill, guardian cover, open cases,              |
 |  description, recommended action)                                                                    |
 +------------------------------------------------------------------------------------------------------+
```

* Banner words (deterministic): `good` (no overdue task, no open high case, no high-score
  candidate), `work to do` (anything open), `attention` (an overdue high task, an open critical
  case, or a candidate with score >= 70). The line names the top reason. Never a smiley.
* Registration pipeline stages = candidates (unmanaged, no draft) -> draft (ai_system status draft)
  -> intake confirmed (task SYS-INTAKE-CONFIRM done) -> classified (Decision 33 applied) ->
  guarded (every floor feature effective) -> in production (lifecycle stage production). Counts
  come from existing tables; no new table.
* Assessment completion per dimension: intake fields complete, class applied, readiness checked
  (task SYS-INTAKE-CHECKS done), guardians at floor, required tasks done. Each row `done / of` with
  a bar. Scope switch (my / team / all) as today.
* Risk classification by autonomy level: one stacked bar per level `l0..l5` + unspecified, segments
  = effective risk level. Colours from the existing pills (crit, bad, warn, neutral).

### 1.2 Candidate triage (the table the owner asked for)

New module `src/supervisor/governance/triage.py`, pure functions over the inventory graph. Output
one row per unmanaged candidate node:

| Field | Rule |
|---|---|
| `impact` 0..100 | signals, each adds points: serves a model with `external_providers` (+20), linked to a UC table whose name matches `(customer|khach|cif|card|the|account|tai_khoan|loan|khoan_vay|payment|thanh_toan|txn|transaction)` (+25), linked to a `uc_function` or `tool` with risk class money/credit/pii_export (+30), a job that writes (+10), endpoint task `agent` or Genie space (+10), kind app with an agent endpoint behind it (+10), owner group known (-0), nothing known (+5 "unknown"). Cap 100. |
| `autonomy` proposal | the WP-G3 auto-define proposal when present (`attrs.autonomy_proposal`), else: Genie space / model endpoint with no tools = `l1_assistive`; app that calls tools = `l3_tool_using_supervised`; job with a schedule and writes = `l4_autonomous_bounded`; unknown = `unspecified`. |
| `complexity` 0..100 | count of linked nodes (models, tools, datasets, mcp servers) scaled: 0 -> 0, 1-2 -> 30, 3-5 -> 60, 6+ -> 90, +10 if an external provider. |
| `score` | `impact * 0.6 + autonomy_rank * 10 + complexity * 0.2`, integer, cap 100. `autonomy_rank`: unspecified 1, l0 0, l1 1, l2 2, l3 3, l4 4, l5 5. |
| `signals` | list of short slugs that fired (`external_model`, `customer_table`, `money_tool`, `writes`, `scheduled`, `no_owner`) |
| `description` | one STE sentence built from the evidence: "Databricks App `x` in group `g`; calls endpoint `e` (external provider `p`); reads 2 customer tables." No URL, no id of the workspace. |
| `recommended_action` | first match: score >= 70 -> `register_now` (link "Register" to WP-N3, prefilled); money or customer signal -> `register_and_classify`; external model only -> `register_review_vendor`; else `register_when_convenient`. Each has a reason string key. |

Rules are in one table in the module (`SIGNALS`), easy to replace by a background analyst agent
later: the module takes an optional `overrides: dict[node_id, TriageRow]` so a future job
(`supervisor.jobs.triage`, not in this WP) can store richer rows in `inventory_node.attrs.triage`
and the page prefers them. Document the row shape in `docs/triage.md` so an agent can fill it.

Table on the page: sortable by score (default), impact, autonomy, kind, name; paged 10; row click
opens a drawer with the signals, the evidence refs and the action button. Also at
`/console/candidates` (the Candidates tab) with the full list and filters (kind, signal, score band).

API: `GET /v1/candidates` (permission `inventory`) returns the same rows (flag on only).

### 1.3 Descriptions and recommended actions for systems and agents

Each card on My overview and each row of the My agents tab gets:
* `description`: the ai_system `purpose` when set; else built from the agent manifest (name,
  model family, host type, tool count, risk tier). One sentence.
* `recommended_action`: first match of a rule list in `governance/next_action.py` (reuse
  `systems_overview.next_action` and extend): overdue task -> "Finish task X"; stage approval
  pending for me -> "Approve stage"; class unclassified -> "Classify (Decision 33)"; guardian
  below floor -> "Switch on <slug>"; gate SHADOW for > 7 days and no open case -> "Request RUNNING";
  open case -> "Triage case"; else "No action".

### 1.4 Definition of done

* Page renders with the flag on, in EN and VI, light and dark, at 1280 and 400 px (screenshots in
  the report). Off path unchanged (test).
* `triage.py`: unit tests for every signal and the score, a golden test on a 6-node fixture graph,
  and a test that no workspace URL or id reaches the row.
* Reads only: no new table, no write on page load. Page time under 1.5 s on the SQLite demo data.
* Targeted tests green; ruff clean. Report per `BUILD_PLAN_PHASE4.md` section 5.

## 2. WP-N2: My agents tab and the agent inside view

Flag `CONSOLE_MY_AGENTS=1` (needs `CONSOLE_NAV_V3=1`). Off: no tab, route answers 400.

### 2.1 My agents (`/console/my/agents`)

An inventory table of the agents in scope (my / team / all):

| Column | Source | Sort |
|---|---|---|
| Agent (name, id, system link) | `agent`, `system_component` | yes |
| Kind | registered / policy-only / candidate (the three kinds of section 0) | yes |
| Gate state | `gate_state` pill (RUNNING, SHADOW, PAUSED, QUARANTINED) + pending resume | yes |
| Autonomy | ai_system `autonomy_level` (via link) or `-` | yes |
| Risk | effective risk level / risk tier | yes |
| Guardian tools | `on N / of M` with a pill: full / below floor / none | yes (by on count) |
| Last activity | newest `agent_event` ts | yes |
| Open cases | count | yes |
| Recommended action | section 1.3 | no |

Filters: text, kind, gate state, risk, guardian cover. Tiles over the table: total, running,
shadow, paused or quarantined, below floor. Row click opens the agent inside view.

### 2.2 Agent inside view (`/console/agents/<id>`, two new tabs; flag-gated like the others)

* **Register** tab: the registry row (id, name, owner user and team, risk tier, host type, plug
  point, model family, gate state and since when), the AI system it belongs to (intake fields,
  stage, class, autonomy), the description, the assessment summary (readiness score and band from
  the last wizard run when stored in `task` evidence, Decision 33 outcome, risk level and source),
  and the recommended action. For a policy-only agent the tab says "known to the gate, not
  registered" with a "Register" button (WP-N3 entry) and the manifest values.
* **Guardians** tab, two parts:
  1. *Status* table, one row per guardian feature of `docs/guardian-bindings.md` section 2 plus
     the gate rules: instance on, binding state for each linked system, floor lock, **effective**
     (on / off) and the reason when off ("flag off", "file off", "binding off by <who>").
  2. *Results* for the enabled ones, last 7 days (window switch 24 h / 7 d / 30 d): detectors ->
     findings per detector with the top codes and the action hints (`finding`); gate rules ->
     checks, allowed, blocked, paused, would-block in SHADOW (`verdict`); judges -> verdicts and
     cases opened, mock label; monitors -> last status per monitor; packs -> last `eval_result`
     per pack with status. Each line links to the existing detail page (Activity, Cases,
     Assurance). Counts only; no excerpt leaves the masked store.

### 2.3 Definition of done

* Off path unchanged (test). Tabs answer 400 with the flag name when off.
* Sorting and filters tested through the route (htmx partial and full page). EN and VI.
* The effective guardian state on the tab equals what the engines resolve (test through
  `BindingResolver` / `DetectorGate.prepare` with a binding off).
* Screenshots at 1280 and 400 px, light and dark, in the report.

## 3. WP-N3: the register workflow (waits for the owner's endorsement of the design)

Flag `CONSOLE_REGISTER_V2=1` (needs `GOVERNANCE_ENABLED=1`, `AGENTS_API_ENABLED=1`). Off:
today's two-step wizard at `/console/systems/new`.

### 3.1 Entry points

```
 Candidates table / My agents row  --[Register, prefilled from the scan]--> step 1
 My overview "+ Register" button   --[blank, "new project"]-------------> step 1
 Policy-only agent, Register tab   --[prefilled from the manifest]-------> step 1
```

### 3.2 Steps (one URL per step, state kept in a `registration_draft` row; resume later)

| # | Step | What the person sees | Suggestions ("analyze" = deterministic from evidence now; an LLM assist later behind `REGISTER_ASSIST_LLM=1`, advise only) |
|---|---|---|---|
| 1 | Identify | name, kind (app, endpoint, Genie, job, other), link to the scanned node or the agent id, owner user, owner team, description | prefilled from the node attrs and edges; description sentence from triage |
| 2 | AI information | purpose, system type, org role, user segment, personal data, human control, autonomy level, money movement, credit decision, model family, data sources | each field shows a "suggested" chip with the reason; one click accepts; a changed field is marked "set by person" |
| 3 | Pre-deployment check | readiness advisor on a repo folder (optional, `ONBOARD_ALLOWED_ROOTS`), the preliminary checks of today's step 2, the policy fragment check (agent id in a policy? tools declared?), SP identity mapped? | score and band, list of gaps, each with the fix |
| 4 | Quick risk assessment | Decision 33 draft questions (from `RulesService.draft`), proposed risk level with the rule that fired, the inherited risk over the graph | the draft is made by the rules; the person answers the open questions; nothing is applied here |
| 5 | Guardian tools | the floor (locked on), the bindable features with the proposed state (all on), the rules in scope from the policy, judge and monitor availability | proposal: everything on; a feature the instance has off shows "needs <flag>" |
| 6 | Review and submit | one page with every section, who approves what, the tasks that will open | - |

Submit writes, in one service call with audit rows: `ai_system` (draft), `system_team` (owner),
`agent` row through `AgentRegistry` (when an agent id is given and the policy knows it; else the
task "Add the agent to the policy" opens), `system_component` link, `classification` draft
(status draft, never applied), `guardian_binding` rows only for features set off, and the
intake tasks. Then it shows the result page with the next actions (confirm intake, add the SP
identity, move SHADOW -> RUNNING later).

A draft can be saved at every step and resumed from My overview "awaiting your input".

### 3.3 Definition of done

* Every write goes through the existing services (no second write path). A failed step is HTTP
  400 with the field name. Off path unchanged.
* Prefill from a scanned node, from a policy-only agent and blank, each tested end to end on
  SQLite. EN and VI. Screenshots of all six steps at 1280 and 400 px.

## 4. Order and merge

```
 N1 (overview + triage) ──┐
                          ├──> hub merges, full suite, release
 N2 (my agents + tabs) ───┤
 N3 (register v2) ────────┘  starts after the owner endorses section 3
```

Shared files (`nav_v3.py`, `i18n.py`, `config.py`, `app.py`): each worker adds only its own keys
and lists every change in its report. The hub merges.
