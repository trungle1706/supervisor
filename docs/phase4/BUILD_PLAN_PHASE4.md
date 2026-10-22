# Phase 4 build plan: two products on a shared core

Date: 2026-10-22. Lead: hub session. Base: `main` at the merge of PR 1 (two-section sidebar and
Catalog page). Direction and object model: `~/supervisor-testbed/saidot/ADOPTION_PLAN.md`
(read sections 3, 4, 6, 14). UX direction: the merged sidebar mockup (section 3 below).

Read first: `CLAUDE.md` (hard constraints, product rules, engineering rules). They all apply.
Every new feature is behind a flag that is off by default. The off path behaves as before and
has a test. Commit after each Definition-of-Done step with the WP name in the message.

## 1. Waves

| Wave | WPs | Depends on |
|---|---|---|
| 1 | **G0** shared core, **UX4a** merged sidebar shell and Supervisor-side pages | main |
| 2 | G1 lifecycle and reviews, G2 rules engine, G3 auto-record, S1 feature bindings, UX4b governance pages on `ai_system` | G0, UX4a |
| 3 | G4 compliance retrieval, G5 governance loop, G6 MCP server and KPIs | G2, G0 |

Shared files (`schema/model.yaml`, `src/supervisor/config.py`, `src/supervisor/core/rbac.py`,
`src/supervisor/console/nav.py`, `src/supervisor/console/i18n.py`, `src/supervisor/app.py`):
edit minimally, list every change in the report. The lead resolves merges.

## 2. WP-G0: shared core (the AI system entity)

Goal: the unit of governance exists, people are scoped to the systems they are on, and both
products can hang data on it. Flag `GOVERNANCE_ENABLED` (setting `governance_enabled`,
default false). Follow the WP29 (`src/supervisor/risk/`) and WP30 (`src/supervisor/controls/`)
pattern for tables, service, routes, chain records and tests.

### 2.1 Schema (`schema/model.yaml`, regenerate both DDLs, keep the "DDL current" test green)

`ai_system` (kind state, pk system_id):
system_id, name, owner_user, owner_team, business_owner?, purpose text, system_type
(assistant | decision | automation | platform | feature), org_role (provider | deployer | both),
user_segment (internal | customer | partner), personal_data (none | identifiable | pseudonymised
| special), money_movement bool, credit_decision bool, human_control (pre_approval |
post_review | none), lifecycle_stage (initiation | design | validation | deployment |
operation | re_evaluation | retirement), risk_level (prohibited | high | medium | low |
unspecified), risk_level_source (manual | inherited | classifier), risk_justification text?,
decision33_class (high_risk | not_high_risk | unclassified), business_impact (high | medium |
low | unspecified), status (draft | active | archived), tags json, created_at, created_by,
updated_at.

`system_team` (pk system_id, user_id): system_id, user_id, team_role (system_owner |
business_owner | technical_specialist | data_steward | compliance_specialist | reviewer |
oversight_manager), added_at, added_by.

`system_component` (pk component_id): component_id (hash of system_id, ref_kind, ref_id,
role), system_id, ref_kind (agent | node), ref_id, role (component_of | built_on |
depends_on), source (manual | onboarding | workspace_scan | gate), evidence_ref, active bool,
first_seen, last_seen.

Chain record type `system_change` (create, update, team change, link change, archive) with
canonical JSON, no PII, integer values only. Reuse the pattern of `control_change`.

### 2.2 Service `src/supervisor/governance/systems.py`

- `register(draft) -> system` with validation of the enums above; name unique; status draft.
- `update_fields`, `archive`, `add_member`, `remove_member`, `link` (agent or inventory node),
  `unlink`.
- `effective_risk_level(system_id)`: max of the manual level and the inherited level over
  linked agents and nodes, using the existing inventory inheritance (`docs/inventory.md`,
  ADR D16). Computed on read, never stored. `risk_level_source` says which won.
- `scope_for(user) -> frozenset[str] | ALL`: roles `admin`, `auditor`, `reviewer`, `approver`
  see all; roles `owner`, `viewer`, `operator` see systems they are on in `system_team`, plus
  systems owned by their team. Constant `SCOPED_ROLES` in one place, with a test.
- `agents_in_scope(user)`: agents linked to a system in scope, plus unlinked agents whose
  `owner_team` equals the user's team.
- Segregation of duties: `reviewer` and `oversight_manager` team roles cannot be the
  `system_owner` of the same system (refuse with a message that starts `segregation of duties:`).

### 2.3 API (`src/supervisor/governance/routes.py`, mounted in `app.py` only when the flag is on)

`GET /v1/systems` (scoped), `POST /v1/systems`, `GET /v1/systems/{id}`,
`PATCH /v1/systems/{id}`, `POST /v1/systems/{id}/team`, `DELETE /v1/systems/{id}/team/{user}`,
`POST /v1/systems/{id}/links`, `DELETE /v1/systems/{id}/links/{component_id}`,
`POST /v1/systems/{id}/archive`. Permissions `systems.view` and `systems.edit` in
`core/rbac.py` (add to `PERMISSIONS`, `ROLES`, `ROUTES`; keep the matrix tests green).
Errors are HTTP 400 with a message.

### 2.4 Console (minimal, old nav; UX4b will restyle)

`GET /console/systems` list (scoped, filter bar, row drawer) and `GET /console/systems/{id}`
with tabs Overview and Components, plus a register form (`POST /console/systems`). Nav item
`systems` under the Onboard group, page flag `console_systems_enabled` (default false). EN and
VI strings in `i18n.py`.

### 2.5 Definition of done

1. Schema, DDLs, generator test green. 2. Service unit tests: enums, scoping per role, SoD,
inheritance, chain record. 3. API tests: every route in the RBAC matrix, 400 on bad input,
404 shape as the repo does it. 4. Off path: with the flag off, no route is mounted and the nav
is unchanged (test). 5. `ruff check`, `ruff format --check`, full `pytest` green.
6. `docs/governance.md` (new) and one line in `docs/console.md`; `CHANGELOG.md` entry.

## 3. WP-UX4a: merged sidebar shell and Supervisor-side pages

Goal: one left bar with 1 + 5 + 6 items and a settings gear, as in the mockup. Flag
`CONSOLE_NAV_V3=1` (setting `console_nav_v3`, default false). Off = the sidebar as it is today,
including the `CONSOLE_NAV_SECTIONS` behaviour. We keep Jinja2, HTMX, our colours and
typography. No JS framework, no CDN, no build step.

### 3.1 The bar (`src/supervisor/console/nav_v3.py`, template `_c_sidebar_v3.html`)

```
 [logo]  search
 My overview                                   (badge: open actions)
 GOVERNANCE · AI management        (kicker, folding section, state remembered)
   Overview | Systems | Catalogues | Risks & controls | Workflows
 SUPERVISOR · AI guardian
   Overview | Activity | Guardians | Cases & alerts (badge) | Analytics | Playground
 v<version> · <mode>                              [gear] Settings
```

Icons: minimalist line icons as inline SVG, our own paths, in a macro file `_icons.html`
(home, overview, systems, layers, shield, branch, pulse, sliders, bell, bars, flask, gear).
Width 18 px, stroke 1.8, currentColor. No icon fonts, no external files.

Items hide when the role lacks the permission or the page flag is off (same rule as today).
Section fold state is kept in `localStorage`, wrapped in try/catch. Badges only on My overview
and Cases & alerts.

### 3.2 Pages and where today's pages go

| Item | Route | Content | Absorbs |
|---|---|---|---|
| My overview | `/console/` when v3 | Greeting; scope switch (my, team, all; applies the existing role filter); tiles: agents in scope by risk tier (systems when `GOVERNANCE_ENABLED`), models in use (inventory nodes of kind model), guardian coverage (agents with all mandatory detectors on, from `config/detectors.yaml` and settings), open actions (tasks + cases assigned + approvals); health table per agent; actions waiting on me; recent events | Overview, Inbox |
| Governance › Overview | `/console/governance` | Tiles: agents or systems in scope, classification rate (Decision 33 class set), control readiness (control_status working / total), overdue tasks; tables: by lifecycle stage, risk posture by band, policy implementation (compliance matrix figures in bp). Reads from the existing registries and WP29-31 services; when G0 lands a follow-up switches it to systems | — |
| Supervisor › Overview | `/console/supervisor` | Tiles: calls checked 24 h, stopped (blocked, paused), guardian coverage, open cases with the SBV clock; health per agent (coverage, blocks 24 h, detector status, latency p95, chain verify state); alerts fired 7 d; judges (mock label) and last pack run | parts of Overview and Metrics |
| Activity | `/console/activity` | Tab strip Decisions, Traces, Sessions over the existing pages | Decisions, Traces |
| Guardians | `/console/guardians` | Tab strip Library (Catalog page), Rules (Policies page), Detectors, Judges, Monitors, Packs (Assurance) | Catalog, Policies, Assurance |
| Cases & alerts | `/console/cases` | Tab strip Cases, Alerts, Approvals (Sign-off) | Cases, Alerts, Sign-off |
| Analytics | existing | Add tab Evidence chain (the Evidence page) | Evidence |
| Playground | existing | unchanged | — |
| Catalogues | `/console/catalogues` | Tab strip Agents, Models, Tools, Datasets, MCP servers over the Inventory and Agents pages | Inventory, Agents |
| Risks & controls | `/console/risks-controls` | Tab strip Risks, Controls, Policies (Compliance) | Risks, Controls, Compliance |
| Workflows | `/console/workflows` | Read-only list of what runs: scheduler jobs, alert rules, approvals, SIEM sink, with state and last run. Honest: no editor yet | — |
| Settings gear | overlay drawer | Links and short status for Integrations, Credentials, Users and roles, Audit log, Health, Policies as code | those six items |

Tab strips: one partial `_c_section_tabs.html`, rendered on every page that belongs to a
section when v3 is on, so a visitor sees where they are. Old URLs keep working; moved pages
redirect (302) to the new route with the right tab. Transparency, Tasks, Onboard and
Integration stay reachable from the agent detail page and from the old URLs.

### 3.3 Definition of done

1. v3 off: byte-identical sidebar and pages to today (tests `tests/console/test_nav_v3.py`,
off path first). 2. v3 on: every item renders per role; hidden when the flag or permission is
missing; EN and VI; each new route 200; bad tab 400 with a message; redirects. 3. Tiles and
tables use existing services only, numbers in integers or basis points, mock judges labelled
`mock`. 4. Screenshots with `tools/console_screenshots.py --out docs/design/screens-v3`
(skip if Playwright is absent; say so). 5. ruff and full pytest green. 6. `docs/console.md`
section "Navigation v3", `CHANGELOG.md`.

## 4. Wave 2 specs

All wave 2 WPs build on `main` after the G0 merge (`src/supervisor/governance/`, tables
`ai_system`, `system_team`, `system_component`, service `SystemService`, flag
`GOVERNANCE_ENABLED`). Read `docs/governance.md` first. New tables follow the G0 pattern
(schema, both DDLs, chain record, service, routes mounted with the governance router, RBAC
entries appended, tests in `tests/governance/`). Console work in wave 2 is minimal (tabs on the
system page under `console_systems_enabled`); UX4b restyles later. Shared files: append only.

### 4.1 WP-G1: lifecycle, stage approvals, reviews, outbound events

1. **Task sizing by risk level.** `config/tasks.yaml` templates gain `min_risk_level` and
   `required_from_level` over the four levels (low, medium, high, prohibited; `unspecified`
   gets the initiation set only, as Saidot does). For an agent linked to a system, the
   effective level is the max of the system's effective risk level and the Decision 33 floor;
   an unlinked agent keeps today's computation (`docs/controls.md` section on sizing). The list
   never gets lighter (existing rule stays).
2. **Stage approval.** Table `stage_approval`: approval_id, system_id, from_stage, to_stage,
   requested_by, status (pending | approved | rejected), decided_by?, reason?, created_at,
   decided_at?. The lifecycle move of a system needs an approved row when
   `config/tasks.yaml` marks the target stage `approval: true` (default: deployment and
   operation). Approver must be a `reviewer` or `oversight_manager` on the team or hold the
   `approver` role, and must not be the requester or the owner (refusal text starts
   `segregation of duties:`). Chain record `stage_change`.
3. **Reviews.** Table `review`: review_id, system_id, kind (internal | external | conformity |
   classification_audit), title, scope json (list of {kind, id}), reviewer_user, status
   (planned | in_progress | completed | reopened), window_start?, window_end?, reports json
   (list of {kind: file | link | note, ref, sha256}), completed_at?, locked bool. Completed
   locks edits; reopen needs a reason and is recorded. Chain record `review_change`.
4. **Outbound events.** Table `outbound_event`: event_id, kind (stage_approved, review_completed,
   system_registered, system_archived), system_id, payload json (ids and enums only), created_at,
   delivered bool, delivered_at?. Written by the service on those events. A `webhook` notifier
   stub behind `WEBHOOKS_ENABLED` (default false) that logs and marks delivered; the real HTTP
   sender is later work. Nothing else consumes the table yet.
5. API: `GET/POST /v1/systems/{id}/approvals`, `POST /v1/systems/{id}/approvals/{aid}/decide`,
   `GET/POST /v1/systems/{id}/reviews`, `PATCH /v1/systems/{id}/reviews/{rid}`,
   `POST /v1/systems/{id}/reviews/{rid}/complete`, `.../reopen`, `POST /v1/systems/{id}/stage`.
   Console: tabs Tasks and Reviews on the system page. Docs: `docs/governance.md` sections.

### 4.2 WP-G2: assignment rules engine and Decision 33 classification

1. **Rules file** `config/assignment_rules.yaml`, strict schema (unknown keys fail at load):
   ```yaml
   - id: AR-PDPL-CUSTOMER
     title: Customer personal data duties
     when: {all: [{field: personal_data, in: [identifiable, special]}, {field: user_segment, eq: customer}]}
     assign: {obligations: [PDPL-*], controls: [CTL-PII-MASK], risks: [RSK-PII-LEAK], tasks: [TSK-PIA], guardian_floor: [dlp_vn, inline_redaction]}
   ```
   Conditions: `all`, `any`, `not`; operators `eq`, `in`, `gte`, `is_true`; fields are
   `ai_system` columns plus derived `component.<kind>.count`, `component.tool.risk_class`
   (from inventory attrs) and `effective_risk_level`. Ids may end in `*` to match a prefix of
   regulation KB obligation ids, control ids, risk starter ids, task template ids. Ship starter
   rules for PDPL, Circular 53 money movement, Decision 33 high risk, and the internal baseline.
2. **Evaluator** `src/supervisor/governance/rules.py`: `evaluate(system) -> Assignments` is pure
   and deterministic, returns for each assignment the rule id and the fields that fired.
   Results persist in table `assignment`: assignment_id (hash of system, kind, ref), system_id,
   rule_id, kind (obligation | control | risk | task | guardian), ref_id, active bool,
   first_seen, last_seen. A run deactivates rows whose rule no longer fires and never deletes.
   Chain record `rule_run` (system id, rule ids fired, counts, rules file sha256). Runs on
   register, on `update_fields`, on link and unlink, and by `python -m supervisor.governance.rules
   run [--system ID]`. `explain --system ID` prints the trace in ASCII.
3. **Hooks into existing engines, additive only:** assigned task template ids are added to the
   task set (WP30 sizing stays the floor); assigned control ids join `control.scope_agents`
   resolution for the system's agents; assigned obligation ids are shown on the compliance
   matrix for the system with source `rule`; `guardian_floor` is exposed by
   `GET /v1/systems/{id}/guardian-floor` (list of feature slugs, with the rule id per slug) for
   WP-S1. Do not change how the gate or detectors run.
4. **Decision 33 classification.** `config/decision33.yaml`: an ordered question flow whose
   answers are derived from system fields and components where possible (money_movement and
   human_control != pre_approval → high_risk; credit_decision and human_control !=
   pre_approval → high_risk; otherwise not_high_risk when every question is answered, else
   unclassified). Table `classification`: classification_id, system_id, outcome, answers json
   (question id, answer, source: rules | ai_prefill | person, justification), status (draft |
   applied), created_by, applied_by?, applied_at?. API: `POST /v1/systems/{id}/classification`
   (draft from rules), `PATCH` (a person edits answers), `POST .../apply` (a person applies; the
   caller must hold `systems.edit` and must not be the system's reviewer). Applying sets
   `decision33_class` and the classifier floor of the risk level (high_risk → high). Optional
   LLM pre-fill behind `CLASSIFIER_AI_PREFILL=1` through the existing LLM adapter, every such
   answer tagged `ai_prefill`, mock labelled `mock`; the service never applies by itself. Chain
   record `classification_change`.
5. Console: tabs Rules (assignments with rule and fields) and Classification on the system page.
   Docs: `docs/assignment-rules.md`, `docs/decision33.md`.

### 4.3 WP-G3: Databricks auto-record v2 and agent auto-define

1. **Scan sources.** Extend the WP24 workspace reader (`docs/inventory.md`, adapter in
   `src/supervisor/adapters/workspace/` or wherever `apps.list` is called) with read-only
   calls, each behind the same `INVENTORY_ENABLED` flag and unit-tested with fakes: MLflow
   registered models and versions (`registered_models`, `model_versions`), serving endpoint
   config (served entities: foundation model provider, external model, agent endpoint flag),
   Genie spaces, jobs and notebook tasks whose config names an LLM endpoint, Vector Search
   indexes, Unity Catalog functions (tools), UC connections of kind MCP. New node kinds as
   needed (`genie_space`, `job`, `vector_index`, `uc_function`); edge kinds stay. Evidence ref
   `workspace:<kind>/<name>`. No workspace URLs or ids stored. The scan still never blocks.
2. **Auto-define.** `python -m supervisor.onboard.define --artifact <dir>`: runs the Discover and
   Understand stages on an MLflow model artifact folder (agent code, tool manifest, prompt
   files, requirements, MLmodel) instead of a git repo, producing the same `inventory.json` and
   `profile.json` (tools with risk class, model family, data touched, Decision 33 proposal,
   file:line evidence). Fixtures: two synthetic artifact folders under `tests/onboard/data/`.
   Secrets are scrubbed before any LLM sees text (existing scrubber). No network.
3. **Draft registration.** Behind `INVENTORY_AUTOREGISTER=1` (default false) and
   `GOVERNANCE_ENABLED`: an unmanaged App, agent endpoint or Genie space creates a draft
   `ai_system` (status draft, risk_level unspecified, source `workspace_scan`) with a default
   owner from `config/governance.yaml` (`default_owner_by_group`, `default_owner_by_catalog`,
   fallback `default_owner`), links the node, and opens the initiation task "confirm context".
   Dedupe on node id. Never blocks or pauses.
4. Docs: `docs/inventory.md` section "Scan sources v2", `docs/onboard.md` section "Define from
   an artifact". CLI output ASCII only.

### 4.4 WP-S1: per-system guardian bindings and the floor (starts after G2)

Table `guardian_binding`: system_id, feature_slug, state (on | off), mandatory bool, set_by,
set_at, reason?. Effective state for an agent = the instance has the feature on (flags and
`config/detectors.yaml`) AND (binding on OR slug in the system's guardian floor). Turning off
a floor slug is refused with 400. Applies to detectors, judge sampling, session monitor,
monitors (reuse WP1b-B bindings); the gate rules themselves are never bindable. Catalog page
gets a per-system column with switches for the owner role; the floor shows a lock. Flag
`GUARDIAN_BINDINGS_ENABLED`. Chain record `binding_change`.

### 4.5 WP-UX4b: governance pages on the AI system (after G0, G1; G2 tabs when merged)

Flags: `CONSOLE_NAV_V3` and `console_systems_enabled` (both exist). No new flag unless a page
needs one. Jinja2 and HTMX only. Use the v3 patterns from UX4a (tiles as filters, filter bar,
row drawer, section tab strip, EN and VI).

1. **System detail tabs**, in this order: Overview · Components · Risks · Controls · Policies ·
   Guardians · Tasks · Reviews · Reports (G2 adds Rules and Classification when merged; leave
   the slots). Overview, Components, Tasks, Reviews exist. Add: Risks (WP29 register rows
   anchored on the system's agents and linked nodes, with the inherited-from column), Controls
   (control_status rows for the system's agents: working, failing, no_data, plus the compliance
   figure in bp), Policies (compliance matrix for the system: obligations that apply, met,
   gap, source), Reports (transparency report link per variant, audit pack, chain verify state
   per agent lane), Guardians (read-only until WP-S1: the detectors, judges and monitors on for
   each linked agent, from the same sources as the Supervisor overview).
2. **Register wizard** at `/console/systems/new`: the intake fields of G0 (and `autonomy_level`
   when the column exists, use `getattr` on the model), scoping rules applied, then a
   "preliminary checks" step that runs, in process and read-only: the integration readiness
   advisor when a repo path is given (`docs/INTEGRATION_GUIDE.md` section 6), the list of
   assurance packs that apply to the declared type, and the G2 classification draft when the
   G2 routes exist (`getattr` guard). One result page: readiness band, risk class proposal,
   packs to run, and the mandatory guardian floor when G2 exposes it. Nothing is applied by the
   wizard; it registers the draft and opens the initiation tasks.
3. **Overviews on systems**: when `GOVERNANCE_ENABLED` is on, My overview and Governance
   overview count systems (not agents): systems in scope by risk level, classification rate by
   `decision33_class` on systems, control readiness per system, overdue tasks, and a breakdown
   by `autonomy_level` when the column exists. Agents stay the unit when the flag is off (the
   UX4a path, unchanged, tested).
4. **Catalogues › Agents** gains a "System" column with a link, and an "unlinked" filter.
5. Tests: off path, each tab 200 for a seeded system, EN and VI, scoping (a scoped user cannot
   open another team's system tabs, 400 or 404 as G0 does), the wizard refuses bad input with
   400, and the overview switch. Screenshots to `docs/design/screens-v3` (replace, keep under
   4 MB). Docs: `docs/console.md` Systems section, `docs/governance.md` console section.

### 4.6 WP-G5: governance loop, incidents, webhook sender flag (after G0, G1)

Flag `GOVERNANCE_ACTIONS_ENABLED` (default false). Follow the G0 and G1 patterns.

1. **Event sources** (read-only adapters over existing tables, no new capture): alert rows
   (`alert` table, every rule id), gate decisions `block` or `pause` on money, credit or
   pii_export tools (`verdict`), detector `failed` findings, monitor status `failing` (drift,
   fairness, quality), assurance `eval_run` with a NO-GO, chain verify failure (the existing
   verify result), new `agent_version` rows (model version change), judge escalation (case kind).
   Each becomes a normalised `GovernanceEvent(kind, severity, agent_id, system_id?, ref,
   at)`; system_id comes from `system_component`.
2. **Rules** `config/governance_actions.yaml`, strict schema: `kind`, `min_severity`
   (low, medium, high, critical), optional `system_class` filter (decision33_class, risk_level,
   autonomy_level gte), `actions` from: `create_incident`, `notify_owner` (notice row to the
   system owner), `raise_risk_level` (manual level up only, never down, source `event`, with
   a `system_change` record), `move_to_re_evaluation` (uses G1 move; re_evaluation needs no
   approval), `create_review` (G1 review, kind internal, scope = the event ref),
   `fire_webhook` (G1 outbound_event, kind `governance_action`), `reopen_control` (sets the
   control instance for that agent to `failing` with the event ref, through the control service).
   Ship a starter file that mirrors the nine SOC alert use cases plus chain break and pack
   NO-GO. A rule never pauses or blocks an agent (rule R1; the gate already did).
3. **Incident** table: incident_id, system_id?, agent_id, kind, severity, title (template, no
   free text from events), event_ref, root_cause?, affected_scope?, status (open |
   investigating | resolved | closed), opened_at, closed_at?, closed_by?, linked case_id?.
   Chain record `incident_change`. Closing needs a person with `cases.transition` or
   `systems.edit`; auto-created only.
4. **Job** `python -m supervisor.jobs.governance_actions` and the in-process scheduler entry
   (`SCHED_GOVERNANCE_S`, default 60 s), idempotent: an event is processed once (dedupe table
   or a processed marker with the event ref hash). Dry-run mode prints what would fire.
5. **API and console**: `GET /v1/incidents`, `GET /v1/incidents/{id}`, `POST .../transition`;
   Cases & alerts page gets an Incidents tab; the system Reports tab lists incidents. EN and VI.
6. Tests: off path first; every action kind; never-lower risk; dedupe; a raising action does
   not stop the others; incidents closed only by a person; chain payloads clean. Docs:
   `docs/governance-actions.md`, `docs/incidents.md`, CHANGELOG.

### 4.7 WP-G6: MCP server, skills, KPI endpoint (after G0, G1, G2, G5)

Flag `MCP_SERVER_ENABLED` (default false). Goal: pipelines and AI assistants work through the
platform the way people do in the console, with the same rules enforced in the server.

1. **Transport.** `python -m supervisor.mcp_server` and a mount under the app at `/mcp`
   (streamable HTTP, JSON-RPC 2.0: `initialize`, `tools/list`, `tools/call`, `ping`). Reuse the
   JSON-RPC and streamable-HTTP code of the WP26 MCP proxy (`docs/mcp-gateway.md`,
   `src/supervisor/gateway/mcp_http*.py`); add no new dependency. Auth: a connected app row
   (`mcp_app`: app_id, name, scopes json, created_by, approved_by, status pending | approved |
   blocked, key_hash) using the WP20 HMAC credential path; the first connection of an app is
   `pending` until an `admin` approves it; every call runs as the app's principal with its
   scopes, and is audited (two console_action rows per write, as G0).
2. **Tools, three groups.**
   - Governance (scope `governance.read` / `governance.write`): `list_entities(kind, filters)`,
     `get_entity(kind, id)`, `register_system(draft)` (draft only, initiation, same validation
     and scoping as the API), `link_component`, `propose_risk` (creates a draft risk row,
     never active), `list_tasks(system_id)`, `complete_task(task_id)` (only tasks owned by the
     app's principal), `transparency_report(system_id, variant)`, `classification_draft(system_id)`
     (draft only). No tool applies a classification, approves a stage, accepts a risk, changes
     a risk level, closes an incident or turns a guardian off; those names are refused at
     registration with a message that points at the console.
   - Library (scope `library.read`): `regulations`, `obligations(query)`, `starter_risks`,
     `starter_controls`, `guardian_catalog`, `assignment_rules`.
   - Supervisor (scope `supervisor.read`): `gate_state(agent_id)`, `decisions(agent_id, since)`,
     `findings(agent_id, since)`, `chain_verify(agent_id)`, `pack_results(agent_id)`, all on
     masked text, same visibility as the console for a viewer.
   - Every write tool takes `confirm: true`; without it the tool returns the planned change and
     writes nothing (confirm-before-write, Saidot's rule). Results are JSON with ids and enums;
     no PII beyond what the console shows to a viewer.
3. **Skills** as Markdown files under `docs/skills/`: `vn-system-registration`, `d33-prep`,
   `risk-triage`, `transparency-report`, `gov-report`. Each names the tools it uses and the
   rule "the server decides; confirm before write; never classify by yourself".
4. **KPI endpoint** `GET /v1/kpis` (scope governance.read, permission console.view): coverage
   (assets by kind, systems by risk level and stage, classification rate, policy coverage),
   quality (risk treatment coverage, acceptable residual rate, control readiness,
   implementation per policy), speed (average days per stage, overdue tasks, inheritance
   rate, automation runs and success from `rule_run` and `governance_action` records), all
   integers or basis points, scoped like G0; the Governance overview reads the same function.
5. Tests: off path first; auth (pending app refused, blocked app refused, wrong scope refused,
   bad HMAC refused); every tool; refused tool names; confirm-before-write; audit rows; no
   PII in results (names masked as in the console); JSON-RPC errors never 500. Docs:
   `docs/mcp-server.md`, CHANGELOG, `docs/console.md` settings row.

### 4.8 Later

G4 policy activation and retrieval.

## 5. Report format (every WP)

What was built. How the DoD was proven (commands and output). Deviations. Open questions.
Files changed outside the package, with the reason. Commits on the branch.
