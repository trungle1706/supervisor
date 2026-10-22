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

## 4. Later WPs (for reference, specs follow in this file when the wave starts)

G1 lifecycle and reviews · G2 assignment rules and Decision 33 flow · G3 workspace scan v2
and agent auto-define · G4 policy activation and retrieval · G5 governance actions, incidents,
webhook flag · G6 MCP server, skills, KPI home · S1 per-system guardian bindings and floor ·
UX4b governance pages on `ai_system` (Systems tabs, Catalogues from inventory, Workflows editor).

## 5. Report format (every WP)

What was built. How the DoD was proven (commands and output). Deviations. Open questions.
Files changed outside the package, with the reason. Commits on the branch.
