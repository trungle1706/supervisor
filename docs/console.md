# Reviewer console (WP8, rebuilt in WP12)

Server-rendered pages (Jinja2) with htmx 1.9.12 (vendored, see `docs/LICENSES.md`) and
hand-written CSS. Fonts: Plus Jakarta Sans and JetBrains Mono, vendored as woff2 (OFL-1.1,
`docs/LICENSES.md`). No CDN, no font service, no network calls from the browser except to the
app itself. Labels in English and Vietnamese (`?lang=vi` or `?lang=en`; default
`CONSOLE_LANG`). Light and dark themes (the browser setting, or the half-moon button; the
choice is kept in the browser only). The design follows `docs/design/console-prototype.html`
and `docs/design/README.md`; current renders are in `docs/design/screens/`.

Start on the laptop with the demo data (Windows cmd):

```
set PYTHONPATH=src
python -m supervisor.cli demo seed
python -m supervisor.cli demo inject 1
set DATA_DIR=data\local\demo
set SCHEDULER_ENABLED=0
python -m supervisor.cli serve
```

Open `http://127.0.0.1:8000/` (it redirects to `/console/`).

## Layout

Since WP-UX1 (phase 3) the default layout has a **left sidebar** and a reduced **top bar**
(the structure follows the owner's reference console; colours, type and wording are ours).

```
+-----------------+--------------------------------------------------------------+
| supervisor  [<<]| [ Search agents, cases, traces ]   laptop  inbox  EN.vi  role |
| Overview        +--------------------------------------------------------------+
| WATCH           | Watch / Agents                                                |
|  Agents      n  | Page header: title . pills . [actions]                        |
|  Gate decisions | purpose line and why line                                     |
|  Traces         | (tiles) (filter bar)                                          |
|  Alerts      n  | table with sortable headers and a pager       +-------------+ |
| ACT             |                                                | row drawer  | |
|  Cases  Sign-off|                                                | tabs        | |
|  Inbox          |                                                +-------------+ |
| PROVE           +--------------------------------------------------------------+
|  Evidence ...   | footer: version . mode . ICT time                             |
+-----------------+--------------------------------------------------------------+
```

Every screen opens with a one-sentence purpose box and a "why" line. Brand colour: one CSS
token, `--brand` in `static/console.css` (E4002B, a placeholder for the Techcombank brand-guide
value). Gold is used only for evidence and signatures. Status is always a word in a coloured
pill.

Sidebar groups and items (`console/nav.py` holds the list):

| Group | Items |
|---|---|
| (top) | Overview |
| Watch | Agents (count), Gate decisions, Traces, Alerts (open count; opens `/console/alerts`) |
| Act | Cases (count, red when a case is critical), Sign-off (cases waiting for a signature; opens `/console/signoff`), Inbox (unread) |
| Prove | Evidence, Assurance (flag), Compliance (flag) |
| Onboard | Onboard, Inventory (flag; unmanaged count), Integration (flag) |
| Analytics | Analytics (Gate, Tools (flag), Oversight metrics, Latency tabs) |
| Settings | Policies, Credentials, Users and roles, Audit log, Integrations, Health |

* Since WP-UX3 the eight new pages (Gate decisions, Traces, Playground, Policies, Credentials,
  Users and roles, Audit log, Integrations) each have their own flag (table "New pages (WP-UX3)"
  below). With the flag on, the sidebar item opens the real page. With the flag off the item is
  hidden, unless `CONSOLE_NAV_PLACEHOLDERS=1`: then it opens the old "coming" placeholder
  (`/console/soon/<page>`, HTTP 400 with the flag off). The placeholder setting is a legacy
  convenience and may be removed once every page is on by default.
* Flagged pages (Compliance, Integration, Assurance, Tools, Inventory) show only when their
  flag is on, exactly as before. Hidden navigation is not security: every route still checks its
  permission (`core/rbac.py`).
* The sidebar collapses to a two-letter code per item (button `<<`; the choice is kept in the
  browser only). The codes are the same in EN and VI (`console/nav.py` `CODES`: OV Overview,
  AG Agents, GD Gate decisions, TR Traces, AL Alerts, CS Cases, SO Sign-off, IB Inbox,
  EV Evidence, AS Assurance, CO Compliance, ON Onboard, IV Inventory, IG Integration, TL Tools,
  MT Metrics, PO Policies, CR Credentials, US Users and roles, AU Audit log, IS Settings >
  Integrations, HL Health); the full label is the hover tooltip and the accessible name. Under
  1100 px the sidebar hides behind the menu button. Arrow keys move between items.
* Top bar: environment and data badge, **global search** (`GET /console/search?q=`: agents and
  cases by id or name, traces by exact trace id from 8 characters (one SQL call per lookup);
  at least 2 characters; 5 hits per kind; it
  works with htmx as a popover and without JS as a page), inbox with the unread count, `EN . vi`
  switch, theme button, role pill and the user menu (with "Switch user" in `dev_header` mode).
* Accessibility: skip link to `#main`, `aria-current="page"` on the active item, `aria-sort`
  on sorted columns, `aria-live` on the flash area and the search results, visible focus ring,
  Esc closes the drawer and the search popover and focus returns to the row. No inline script
  (the content security policy stays `script-src 'self'`).

### CONSOLE_NAV: the rollback

| Value | Layout |
|---|---|
| `sidebar` (default) | The layout above |
| `top` | The phase 2 header: one row of pills, with the count badges, and the same right-hand cluster. Pages render the same content inside it |

Windows cmd: `set CONSOLE_NAV=top` and restart. Nothing else changes: the same routes, the same
templates below the header, the same tests. The pages migrated in WP-UX1 (Overview, Agents)
keep working in `top` mode.

### Navigation v3 (WP-UX4a, `CONSOLE_NAV_V3`)

One merged left bar for the two products: Governance (AI management) and Supervisor (AI guardian).
Off by default. Off = the sidebar of the sections above, byte for byte (also with
`CONSOLE_NAV_SECTIONS=1`); a test renders the old pages with the flag off and compares them to the
release before. It needs `CONSOLE_NAV=sidebar` (the default); with `top` the bar is not drawn and
only the tab strips show.

```
 [logo]                                         [collapse]
 My overview                                    (badge: open actions)
 GOVERNANCE · AI management      (folds, state kept in localStorage)
   Overview | Systems | Catalogues | Risks & controls | Workflows
 SUPERVISOR · AI guardian
   Overview | Activity | Guardians | Cases & alerts (badge) | Analytics | Playground
 v<version> · <mode>                            [gear] Settings
```

Icons are inline SVG line icons (`templates/_icons.html`, own paths, 18 px, stroke 1.8,
`currentColor`): no icon font, no file, no CDN. Items hide when the role lacks the permission or
the page flag is off, the same rule as the old sidebar. The two section folds work without
JavaScript (`<details>`); `console.js` only remembers the fold per browser, inside try/catch. The
**gear** opens a drawer (CSS `:target`, so it works without JavaScript; Esc closes it) with the six
old Settings items and a one-line status read from settings: Integrations, Credentials, Users and
roles, Audit log, Health, Policies as code. Each shows only for a role that may open it.
Badges: My overview shows the open actions of the person (the number on the page); Cases and
alerts shows open cases plus open alerts.

#### Where the old pages went

A section tab strip (`_c_section_tabs.html`) sits above every page that belongs to a section, so a
visitor sees where they are. Each tab links to a page that exists; a tab is hidden when its page
flag is off or the role lacks the permission. The old URLs keep working and answer 200 as before.
The section routes below answer `302` to the first tab that is on (or to the tab in `?tab=`, with
`lang` kept); an unknown tab or one that is off answers 400 with a message.

| Bar item | Route | Tabs (page) |
|---|---|---|
| My overview | `/console/` | none. Replaces Overview; Inbox stays at `/console/inbox`, linked from the page |
| Governance, Overview | `/console/governance` | none |
| Governance, Systems | `/console/systems` (route and page owned by WP-G0) | The item shows only with `console_systems_enabled`. The Onboard, Integration, Transparency and Tasks pages carry a Systems tab strip meanwhile |
| Governance, Catalogues | `/console/catalogues` | Agents (`/console/agents`), Models, Tools, Datasets, MCP servers (inventory nodes, read only), Unmanaged (`/console/inventory`) |
| Governance, Risks and controls | `/console/risks-controls` (302) | Risks, Controls, Policies (the Compliance page) |
| Governance, Workflows | `/console/workflows` | none |
| Supervisor, Overview | `/console/supervisor` | none |
| Supervisor, Activity | `/console/activity` (302) | Gate decisions, Traces. There is no Sessions page yet |
| Supervisor, Guardians | `/console/guardians` | Library (Catalog), Rules (Policies), Detectors, Judges, Monitors, Packs (Assurance) |
| Supervisor, Cases and alerts | `/console/cases` | Cases, Alerts, Approvals (Sign-off) |
| Supervisor, Analytics | `/console/analytics` | Analytics, Evidence chain (the Evidence page) |
| Supervisor, Playground | `/console/playground` | none |

#### The overview pages

All three take `?scope=my|team|all` (anything else is HTTP 400). My = the agents the person owns
(`agent.owner_user`); team = the agents whose `owner_team` is the team of one of their agents; all =
every agent. The default is my when the person owns an agent, else all. Every number is an integer
or basis points (a percent on screen, the basis points in the tooltip) and comes from a service that
already exists. A figure that cannot be computed shows "not available" and the reason. It is never
filled in.

| Tile or table | Source | Not available when |
|---|---|---|
| Agents in scope, by risk tier | agent registry (`risk_tier`) | never |
| Models in use | inventory nodes of kind `model` and `model_endpoint` (not gone) | `INVENTORY_ENABLED` off |
| Guardian coverage | agents with every **mandatory** detector on, over agents in scope. Mandatory = `fail_closed: true` in `config/detectors.yaml` (there is no other flag); an agent's `enable` and `disable` in the policy file apply; all detectors count as off while `DETECTORS_ENABLED` is off | no detector is `fail_closed`, or the file cannot be read |
| Open actions | open cases assigned to the person, cases that wait for their sign-off, open required tasks of agents they own | never (tasks count only with `CONTROLS_ENABLED`) |
| Classification rate | agents with a registry Decision 33 class, in basis points | no agent in scope |
| Control readiness | latest `control_status` per control and agent in scope: working over all | `CONTROLS_ENABLED` off, or the `control_status` job has not run |
| Overdue tasks | overdue required tasks of agents in scope | `CONTROLS_ENABLED` off |
| By lifecycle stage | `TaskService.current_stage` and open required tasks | `CONTROLS_ENABLED` off |
| Risk posture | active risks by effective residual band, treated or accepted | `RISK_REGISTER_ENABLED` off |
| Policy implementation | compliance matrix per agent: met over applicable, in basis points | `CONSOLE_COMPLIANCE_ENABLED` off |
| Calls checked 24 h, stopped | gate decisions of the last 24 hours (rolling), blocks and pauses from tier 0 verdicts | never (capped at 20,000 rows, then `+`) |
| Health per agent | gate coverage, stops 24 h, mandatory detectors, p95 latency of gate calls, last chain verify | latency is `-` with no call in 24 h |
| Alerts fired 7 d | `alert` rows by rule | never |
| Judges and packs | `JUDGE_ENABLED`, the newest assurance run. **mock** shows when a judge is on without a model, or the run is a mock run | never |

Workflows is a read-only list of what runs: scheduler jobs (state and last run need the
scheduler, which exists only in the process that runs it: elsewhere the page says "not available"),
alert rules from `config/alerts.yaml`, the two-person approvals (case sign-off, resume, waiver) and
the SIEM and webhook sinks. There is no editor yet.

Errors are HTTP 400 with a message. Screenshots: `uv run python tools/console_screenshots.py --v3
--reseed --out docs/design/screens-v3 --data-dir <new folder>`.

### Systems pages (WP-UX4b, `CONSOLE_NAV_V3` and `CONSOLE_SYSTEMS_ENABLED`)

The governance pages on the AI system (`docs/governance.md`). With `CONSOLE_NAV_V3` off, or the
page flags off, nothing below exists and the Systems page is the one of WP-G0.

System page tabs: Overview, Components, Risks, Controls, Policies, Guardians, Tasks, Reviews,
Reports (WP-G2 will add Rules and Classification after Components). A tab needs the permission of
the page it summarises. All tabs read the agents linked to the system.

| Tab | Source | Not available when |
|---|---|---|
| Risks | register rows that reach the linked agents or sit on a linked node, with the anchor ("inherited from") | `RISK_REGISTER_ENABLED` off |
| Controls | `control_status` per control and agent, compliance figure in bp (working over in scope) | `CONTROLS_ENABLED` off |
| Policies | compliance matrices of the linked agents added up by instrument (apply, met, partial, gap); an agent with no matrix is listed apart | `CONSOLE_COMPLIANCE_ENABLED` off, or no matrix |
| Guardians | detectors on per agent (detector file, per-agent enable and disable, `DETECTORS_ENABLED`), mandatory ones, judges (labelled `mock` without a model), monitors, the WP-G2 floor | floor: rules engine not merged |
| Reports | latest transparency report per variant and agent, chain verify state per agent lane, audit pack link, incidents slot | transparency off; incidents until WP-G5 and its flag |

Register wizard `/console/systems/new` (needs `systems.edit`): step 1 intake (plus `autonomy_level`
once WP-G2 adds it, and an optional repository folder for people who may start onboarding; the folder must be inside `ONBOARD_ALLOWED_ROOTS`, default empty = the advisor is off in the wizard; one scan at a time, 30 s limit), step 2
`POST /console/systems/new/checks` runs the preliminary checks and writes nothing, step 3
`POST /console/systems/new` registers the draft and opens the tasks `SYS-INTAKE-CONFIRM` and
`SYS-INTAKE-CHECKS`. The result page shows the readiness score and band (80+ ready, 50-79 needs the
patches, below 50 needs work; static analysis, no model), the class proposal (money movement or a
credit decision without a human approval before the action is high risk; a declared approval stays
unclassified because only a step in code counts; WP-G2 rules win when merged), the assurance packs per dimension and the guardian floor. Scoped people register for
themselves and for a team they already work in. A bad input is HTTP 400 with the reason.

Overviews: with `GOVERNANCE_ENABLED` on, My overview and Governance overview count systems. Scope:
my = systems I own or am on, team = systems of my teams, all = what the role may see. The agent-based
pages are used when the flag is off. Catalogues > Agents has a System column and a linked or
unlinked filter (both flags needed).

#### Tasks and stage approvals as buttons (WP-P1, `CONSOLE_WORKFLOW_ACTIONS`)

Needs `GOVERNANCE_ENABLED=1`, `CONSOLE_SYSTEMS_ENABLED=1` and, for the task buttons, `CONTROLS_ENABLED=1`.
Off (default): the Tasks tab of a system is read only, as before, and the six routes below answer
HTTP 400 with a message that names `CONSOLE_WORKFLOW_ACTIONS` (code `workflow_off`). Windows cmd:
`set CONSOLE_WORKFLOW_ACTIONS=1`.

| Button | Route (all `POST /console/systems/<id>/...`) | Who | Rule added by the console |
|---|---|---|---|
| Done | `tasks/<task>/done` | the role of the task, an admin, or `systems.edit` | the task list still applies its own rule: a task of role reviewer, approver or auditor is closed by that role or an admin |
| Waive | `tasks/<task>/waive` | same as Done | reason of 10 characters or more (`reason_too_short`); the person who created the task cannot ask (`same_person`) |
| Approve waiver, Reject waiver | `tasks/<task>/waive/approve`, `.../reject` | `tasks.approve` (approver, admin) | not the person who asked (`same_person`); reject needs a reason of 10 characters or more |
| Request move | `stage/request` (fields `to_stage`, `reason`) | `systems.edit` | reason of 10 characters or more; only a stage that needs an approval |
| Approve, Reject | `stage/<approval>/decide` (fields `decision`, `reason`) | `systems.approve` and `LifecycleService.can_decide` | the requester cannot answer (`same_person`); the owner of the system cannot answer (segregation of duties, from the service) |
| Move | `stage/move` (field `to_stage`) | `systems.edit` | a stage that needs an approval needs an approved, unused request; a stage that needs none moves at once |

The business rules are the ones of `TaskService` and `LifecycleService`; the console reuses them and
adds only the rows above. A refusal is HTTP 400 and the message starts with the code. A missing
role is HTTP 403. The answer to an htmx post is the refreshed Tasks tab (swap target `#tab-body`)
with the result in `#flash`; a plain form post is a 303 back to the tab. Text from the service that
names an API path is shown without it. The reason of a request is kept in the `reason` column of the
`stage_approval` row while the request waits (the answer replaces it); a waiver reason is kept on the
task row.

Audit: two `console_action` rows as for every action. `detail` holds the action name, the status
before and after, and the first 12 characters of the SHA-256 of the reason (never the reason):
`task_done open>done`, `task_waive open>waive_pending reason_sha=...`, `task_waive_approve`,
`task_waive_reject`, `stage_request initiation>deployment reason_sha=...`, `stage_approve
pending>approved`, `stage_reject`, `stage_move initiation>deployment`. `before_hash` and
`after_hash` are the hashes of the task row (task buttons) or of the system row (stage buttons).

With the flag on, the next action of a system or an agent row (My overview, My agents, the stage
approvals waiting for you) links to `/console/systems/<id>?tab=tasks`, where the buttons are.

#### Duties tab (WP-L3, `RISK_DUTIES`)

The Duties tab of a system (`?tab=duties`) lists the duty rows of the system and has the buttons Close
(`systems.edit`), Waive (`systems.approve`; not the owner of the system) and Re-evaluate (`systems.edit`):
`POST /console/systems/<id>/duties/close`, `.../waive`, `.../reevaluate`. Off (default): no tab and the
three routes answer HTTP 400 `risk_duties_off`. Rules, score, risk line and sweep: `docs/risk-register.md`
"Duties (WP-L3)". Audit: two `console_action` rows per POST (`duty_close`, `duty_waive`, `duty_reevaluate`).

### Components

Server-rendered Jinja2 macros and partials; htmx only; the CSS is in `static/console.css`
(same colour tokens, no new colours); `static/console.js` holds the small glue (sidebar,
drawer, tab keys).

| Component | Where | Notes |
|---|---|---|
| Sidebar nav | `_c_sidebar.html`, `console/nav.py` | Counts come from `readmodels.shell()` (agents, cases, critical, alerts, sign-off, unread, inventory) |
| Top bar | `_c_topbar.html`, `_c_who.html` | `_c_who.html` is shared with the `top` header |
| Breadcrumb | `ui.crumbs(items)` | `aria-current` on the last item |
| Page header with actions | `ui.pagehead(title, pills)` with a `call` block for actions | Reuses `.pagehead` |
| Tiles as filter | `ui.tiles(items, url, rows_url)` | Each tile is a link that sets one filter |
| Filter bar | `ui.filterbar(...)` | A plain GET form; with htmx it swaps the rows partial |
| Data table | `_c_table.html`: `tb.th` (sort link, `aria-sort`) and `tb.pager`; `console/listing.py`: `paginate`, `parse_sort` (allow-listed columns), `sort_rows` | Works without JS. A page outside 1..N is HTTP 400, never 500. An unknown sort column falls back to the default |
| Status pills | `ui.pill`, `ui.sev`, `ui.state_pill`, `ui.verify_pill`, new `ui.action_pill` | A word plus a colour, never a colour alone |
| Row drawer | `_c_drawer.html` (`dr.drawer`), container in `base.html`, `_agent_drawer.html` | Side panel with previous / next row, Copy JSON, close, tabs. Opens by htmx; `?drawer=<id>` is the no-JS fallback. The htmx drawer builds the card of one agent only (previous / next come from light rows, or from all cards when the list is sorted by coverage) |
| Tabs | `ui.tabs(...)` | `role=tablist`, `aria-controls` to the `role=tabpanel`; arrow keys, Home, End; focus stays on the tab after an htmx swap; htmx or a full page |
| Key-value panel | `ui.kv(rows)` | Third item `True` = monospace |
| Timeline | `ui.timeline(items)` | Reuses `.timeline` |
| Empty state | `ui.empty(title, line, href, label)` | |
| Stat tile, bar cell | `ui.stat(...)`, `ui.barcell(value, max)` | CSS bar, no chart library |
| Toast | `ui.toast(message, kind)`; `#flash` | An ok message fades after 6 s by CSS only |
| Span tree | `_c_spantree.html` (`st.spantree(tree)`), `readmodels.span_tree(events)` | One node per span, `<details>` per parent (no JS). Spans with a missing parent and spans in a parent loop (marked "loop cut") go under "Spans without a parent"; at most 500 spans. No page uses it yet (Traces viewer, WP-UX3) |

Migrated in WP-UX1: **Overview** and **Agents**. Migrated in WP-UX2: **Cases** (filter bar,
sortable paged table, row drawer), **Inbox** (filter bar, sort, pages), **Inventory** (sortable
paged unmanaged table), **Evidence**, **Assurance**, **Compliance** and **Health** (breadcrumb
and page header), the **Case** page (shared tabs macro, same five tabs), and the new pages
**Agent**, **Alerts**, **Sign-off list** and **Analytics**. The lifecycle controls moved from the
Agents list cards to the Overview tab of the agent page.

Not done (WP-UX2 and WP-UX3): see `BACKLOG.md`.

### New pages (WP-UX3)

Eight pages, each behind its own flag (default off; off = HTTP 400 with a message, no sidebar
link) and its own permission (the role matrix below). All are read-only, take their data from
the existing stores, and use the list components of WP-UX1 (filter bar, sortable paged table,
row drawer with a no-JS fallback `?drawer=<id>&dtab=<tab>`). Bad filter values answer HTTP 400.
English and Vietnamese labels; no external URL; strict CSP.

| Page | URL | Flag | Permission (roles) | What it shows |
|---|---|---|---|---|
| Gate decisions | `/console/decisions` | `CONSOLE_DECISIONS_ENABLED` | `decisions.view` (all) | One row per gate decision from `agent_event` (event type `gate_decision`) with the tier-0 verdict rows that share its event id. Count tiles (all, allow, block, pause, alert) act as the action filter; filters agent, action, rule, tool, time range, trace id; sort by time, agent, tool, action, rule, latency; 25 per page. Drawer tabs Details, Rules, Evidence: time, agent, tool, trace and span ids, keyed args hash, hashed argument keys, amount, latency in microseconds, reason, rule hits with severity and regulation, evidence lane and sequence, links to the case and to the trace. **Arguments are never shown**, only the keyed hash (R2). Reads the newest `CONSOLE_SCAN_CAP` (default 20,000) records; a hint appears when that cap is reached. |
| Traces | `/console/traces`, `/console/traces/<trace_id>` | `CONSOLE_TRACES_ENABLED` | `traces.view` (all) | List: trace id, agent, start, spans, verdict labels (block / pause / alert, judge count), status (ok, alert, blocked, paused); filters agent, status, time range, id. Viewer: span tree on the left (built from `span_id` and `parent_span_id`; up to 500 spans, then "+N more"; a cycle or a missing parent cannot loop), key-value detail of the selected span on the right (`/console/traces/<id>/span/<span>` partial; `?span=` without JS), gate stops marked P, B, A, judge verdicts marked J. Verdicts attached to the span: gate rule hits, Tier 0b findings and judge verdicts (mock and advisory labelled). **The capture level decides what text is shown**: `digest` shows no text; `masked` and `raw` show the masked column only (the raw table is never read), after the masker runs again; with no masker configured no text is shown. The stop with the highest rank opens by default. |
| Playground | `/console/playground`, `POST /console/playground/run` | `CONSOLE_PLAYGROUND_ENABLED`; in `databricks_app` mode also `PLAYGROUND_ALLOW_APP=1` (owner decision pending) | `playground.run` (reviewer, approver, owner, admin, operator) | Form: agent, version, tool, arguments (JSON object, 16 KB), context (JSON object, 4 KB). "Check (dry run)" calls `Gateway.evaluate_only`, which writes **no** verdict, event or chain record, changes **no** agent state (a pause rule shows "would pause the agent"), adds nothing to the windows and does not count in the metrics; a test proves the store and the chain are byte-identical before and after (`tests/gateway/test_evaluate_only.py`, `tests/console/test_ux3_playground.py`). Rules that count calls over time (sum, count, prior-call) are not evaluated and are listed as such. WP38: a sample library (`data/eval/playground_samples/*.json`, 8 synthetic samples in Vietnamese and English; a link fills the form, nothing is sent until Check) and an extra attributes panel (consumer id, direction, declared tool class) that fills the context; `direction=output` needs `DETECTORS_ENABLED=1`. The result shows the policy mode, the consumer and the `observed_decision`. The answer shows the decision, the rule hits and a masked preview of the arguments (or the transformed arguments when inline redaction is on); the typed arguments are not echoed or stored. The POST writes the two audit rows (`attempted`, `ok`); the `ok` row carries `in:<24 hex of the keyed HMAC of the arguments>` in `detail`, never the arguments. |
| Playground | `/console/playground`, `POST /console/playground/run` | `CONSOLE_PLAYGROUND_ENABLED`; in `databricks_app` mode also `PLAYGROUND_ALLOW_APP=1` (owner decision pending) | `playground.run` (reviewer, approver, owner, admin, operator) | Form: agent, version, tool, arguments (JSON object, 16 KB), context (JSON object, 4 KB). "Check (dry run)" calls `Gateway.evaluate_only`, which writes **no** verdict, event or chain record, changes **no** agent state (a pause rule shows "would pause the agent"), adds nothing to the windows and does not count in the metrics; a test proves the store and the chain are byte-identical before and after (`tests/gateway/test_evaluate_only.py`, `tests/console/test_ux3_playground.py`). Rules that count calls over time (sum, count, prior-call) are not evaluated and are listed as such. The answer shows the decision, the rule hits and a masked preview of the arguments (or the transformed arguments when inline redaction is on); the typed arguments are not echoed or stored. The POST writes the two audit rows (`attempted`, `ok`); the `ok` row carries `in:<24 hex of the keyed HMAC of the arguments>` in `detail`, never the arguments. |
| Transparency (WP31) | `/console/transparency` | `CONSOLE_TRANSPARENCY_ENABLED` and `TRANSPARENCY_ENABLED` | `transparency.view` (all); `transparency.generate` (reviewer, admin) | One line per agent with the latest signed report (version, date, chain check, sections with data) for each of three variants (regulator, customer, internal). A row opens a drawer with the sections of that variant (a PREVIEW of the current facts when none is signed yet) and download links (JSON, HTML, PDF). Reviewer and admin get a "Generate all versions" button (audited; writes files, rows and a chain record when the facts changed). A Transparency tab on the Agent page lists the latest version per variant. See `docs/transparency-report.md`. |
| Policies | `/console/policies` | `CONSOLE_POLICIES_ENABLED` | `policies.view` (all) | Deployed policy versions (hash, in force or retired, effective from, git commit, rule count), the tool and risk-class table, and the rules in force with filters (agent scope, action, severity, risk class, text) and sort. Drawer tabs Details, YAML, Versions: description, scope, fail mode, risk class, regulation reference, owner, approvals, hashes, the expression as YAML, history of the rule, and the gate-rule capabilities of the catalogue that apply to its risk class (manifest file names; no link target exists in the console). Read-only: a change goes through Git and a pull request. |
| Credentials | `/console/credentials` | `CONSOLE_CREDENTIALS_ENABLED` | `credentials.view` (owner, admin) | WP20 ingress key metadata per agent (key id, current or previous, issued from the `k-<time>` key id, expiry, valid now; last use is not tracked, so the column is empty), agents without an active key, and the identity map (principals shortened to first and last four characters). Banner when `INGRESS_AUTH_ENABLED` is off. **Never a secret**: the code reads `key_id`, `state` and `expires_at` only and asks `valid_at()` for a yes or no; an unreadable store shows the error class, not the message or the path. Issue and rotate stay on the command line (`python -m supervisor.gateway.ingress_auth rotate <agent_id>`). |
| Users and roles | `/console/users` | `CONSOLE_USERS_ENABLED` | `users.view` (admin) | The users file (laptop) or the `auth.yaml` role map (App: users and group names per role, the shortened service principal id, `group_lookup`), holders per role, and the role x permission matrix generated from `core/rbac.py` (same table as "Role matrix" below). Read-only. |
| Schema check | `/console/admin/schema` | `SCHEMA_SELFCHECK` (shows `off` when the flag is 0) | `schema.view` (admin) | Result of the start-up comparison of `schema/model.yaml` with the warehouse (`information_schema.columns`, read only): missing tables and columns and the exact SQL plan to copy (CREATE TABLE IF NOT EXISTS, ALTER TABLE ... ADD COLUMNS). The app never runs DDL. A banner on every page an admin sees points here while the schema differs. Answers on a plain page when the console shell cannot start. `?recheck=1` reads again. |
| Audit log | `/console/audit` | `CONSOLE_AUDITLOG_ENABLED` | `audit.view` (auditor, admin) | `console_action` rows: time, actor (kind, method), permission, target, outcome (attempted, ok, denied, error); filters actor, permission, outcome, target, time range; sort; drawer with roles, request line, target, request id, hash before and after (and whether they differ), the fixed `detail` note and the other rows of the same request. Read-only and append-only. The flag is `CONSOLE_AUDITLOG_ENABLED` because `CONSOLE_AUDIT_ENABLED` already switches the writing of audit rows (WP18). |
| Risks (WP29) | `/console/risks` | `CONSOLE_RISKS_ENABLED` and `RISK_REGISTER_ENABLED` | `risks.view` (all) | Tiles (active, critical, high), filters text, agent, category, residual band, owner, status, sortable paged list: inherent and residual score with band, evidence state and reason, treatment, owner, review date. Drawer tabs Details, Links, Evidence (residual score per window, counts of rule hits, packs, monitors). A Risks tab on the Agent page shows the agent's register level and the risks it owns or inherits. Read-only; edits go through `/v1/risks` (`risks.edit`: reviewer, owner, admin). Band thresholds are ILLUSTRATIVE and the page says so. See `docs/risk-register.md`. |
| Integrations | `/console/integrations` (with `COLLECTORS_ENABLED=1` it is the collector catalogue of WP38, see below) | `CONSOLE_INTEGRATIONS_ENABLED` | `integrations.view` (all) | SIEM sink, webhook notifier, pager, ITSM, SCIM: configured, enabled, last delivery, dead-letter count, short detail (sink and format, host name only). Pager, ITSM and SCIM are stubs with in-memory fakes (WP11) and say so. Dead-letter files are counted, never read. No secret and no URL beyond the host name. |
| Controls (WP30) | `/console/controls` | `CONSOLE_CONTROLS_ENABLED` and `CONTROLS_ENABLED` | `controls.view` (all) | Tiles (active, by product, by bank), filters text, agent, type, implemented by, owner, status, sortable paged list with the evidence status counts over agents. Drawer tabs Details, Map, Status by agent. A Controls tab on the Agent page shows the compliance figure and the controls in scope. Read-only; edits go through `/v1/controls` (`controls.edit`). See `docs/controls.md`. |
| Systems (WP-G0) | `/console/systems`, `/console/systems/<id>` | `CONSOLE_SYSTEMS_ENABLED` and `GOVERNANCE_ENABLED` | `systems.view` (all; a scoped role sees its own systems), `systems.edit` for the register form | Tiles, filters, sortable paged list of AI systems in your scope, drawer tabs Details, Team, Components; detail page with tabs Overview and Components; register form. Nav item under Onboard. See `docs/governance.md`. |
| Systems, tabs Rules and Classification (WP-G2) | `/console/systems/<id>?tab=rules`, `?tab=classification` | as Systems | `systems.view` to read, `systems.edit` for the buttons (run rules, draft, save answers, apply) | Rules: guardian floor and the assignments with rule and fields. Classification: Decision 33 questions, answers with source (fields, AI pre-fill, person), apply by a person. See `docs/assignment-rules.md`, `docs/decision33.md`. |
| Systems (WP-G0) | `/console/systems`, `/console/systems/<id>` | `CONSOLE_SYSTEMS_ENABLED` and `GOVERNANCE_ENABLED` | `systems.view` (all; a scoped role sees its own systems), `systems.edit` for the register form | Tiles, filters, sortable paged list of AI systems in your scope, drawer tabs Details, Team, Components; detail page with tabs Overview, Components, Tasks and Reviews (the last two: WP-G1, read only); register form. Nav item under Onboard. See `docs/governance.md`. |
| Tasks (WP30) | `/console/tasks` | `CONSOLE_CONTROLS_ENABLED` and `CONTROLS_ENABLED` | `tasks.view` (all) | Tiles (required open, overdue, waiver waiting), filters, sortable paged list; drawer tabs Details and History. A Tasks tab on the Agent page shows the lifecycle stage, the sizing and the tasks. Read-only; changes go through `/v1/tasks` (`tasks.edit`; the waiver answer, a lifecycle move at high level and an approver task need `tasks.approve`, route `POST /v1/tasks/{id}/approve`). Task sets are ILLUSTRATIVE. |

Commands (Windows cmd): `set CONSOLE_DECISIONS_ENABLED=1` and restart; the same for the other
flags. Screenshots: `python tools\console_screenshots.py --ux3 --reseed --out <dir> --port <free port>`
turns the eight flags on in the server it starts and captures only these pages, each as the role
it needs, in English and Vietnamese, plus a dark shot.

### Activity and analytics parity (WP39, `CONSOLE_DECISIONS_V2`)

Default off: every page below is as in v0.3.0. With `CONSOLE_DECISIONS_V2=1` (and
`CONSOLE_DECISIONS_ENABLED=1`, `CONSOLE_TRACES_ENABLED=1`; verdict data needs `DETECTORS_ENABLED=1`):

| Page | What changes |
|---|---|
| Gate decisions | Count tiles are the **status** (allow, report, transform, pause, block, skip). New filters: status, detection code, not evaluated, consumer (application), direction, correlation id (`corr`), next to agent, action, rule, tool, range, trace id. Each row shows the status, a **Not evaluated** badge with the reasons (a hover title), the finding codes, the consumer and the latency. Scan caps as before (`CONSOLE_SCAN_CAP`, events and findings) |
| Decision drawer | Four tabs. **Request**: the masked request (arguments, tool results, output) with each located fragment highlighted in place and numbered, and the masked record as formatted text and as JSON. **Response**: status, decision, rule ids with severity and regulation, reason (masked), the **Observed decision** line (mode `enforce`, `shadow` or `observe`; what the policy would have done from the `observe_would_block` / `observe_would_pause` verdict rows; approvals present or not when the chain record has them), and the payload after masking (rebuilt from the masked record). **Detections**: one row per finding (detector id, code, score and threshold in bp, entities and fragments as masked tokens, action hint, `mock` label), one row per `not_executed` with its reason, the fragments located in the text and those not located, the coverage. **Metadata**: request id, correlation id, consumer, ids of trace and span, the latency split (total, rules, detectors, overhead, per detector), evidence lane and sequence, links to the trace span, to the other decisions with the same correlation id, to any alert that carries it, and to the case |
| Deep links | `/console/decisions?event=<id>` (a decision id, else a request id) and `?correlation=<id>` (newest decision with that id; with `&agent=<id>` the newest of that agent, which is what the Alerts drawer links to) open the drawer; `console.js` then removes the parameter from the address bar. Unknown or hostile values give HTTP 400 |
| CSV export | Button on the list for `decisions.export` (auditor, admin). POST builds the file for the **current filters**; a link downloads it **once**, only for the user who built it, within 15 minutes (`?exp=` and an HMAC token `t=` with a key that lives in the process; WP39 review). The file is deleted when it is served, and files older than 15 minutes are removed on every export and download; they sit in `CONSOLE_EXPORT_DIR/decisions/`, apart from the audit packs. Columns (an allow-list, 19): `time_utc, decision_id, request_id, correlation_id, trace_id, agent_id, consumer_id, tool, direction, status, action, rule_ids, finding_codes, not_evaluated_reasons, latency_us, latency_rules_us, latency_detectors_us, case_id, kept_arguments` (WP41: the NAMES of arguments the policy passed unmasked, `;` separated, usually empty). No arguments, no fragments, no entity tokens, no argument hash. At most `CONSOLE_EXPORT_MAX_ROWS` rows (default 5000); a cut file is named `...-truncated.csv` and the answer says `truncated: N of M rows`. Audited as `decisions.export` (two `console_action` rows; the note is `rows=N;total=M;truncated=0|1;filters=<16 hex>`, a hash of the filters and sort, so the file can be tied to its query without the values) |
| Traces | The list filters on the correlation id (`corr`). The span tree shows a chip with the number of findings on a span that has them; the head and the span detail show the correlation id and link to the decision |
| Analytics, Gate tab | Tables per agent, per application (consumer), per rule id, per detector and code; columns requests, report, transform, pause, block, skip, not evaluated, each with its share in bp; "Gate outcomes by day" (four inline-SVG series, report, transform, pause, block). Data from `decision_daily` |
| Analytics, Detectors tab | Latency p50 and p95 per detector from the recorded facts, findings per detector and code, and the harness verdict of each detector (`GO (indicative)` when the adversarial recall passes on the point value but its Wilson 95 percent lower bound is under the threshold) |
| Alerts drawer | Shows the correlation id and links to the decision of the same agent |
| Caller ids (WP39 review) | A correlation id, request id or consumer id is a value the caller sends. An e-mail, a phone number, an ID or account number passes the plain-id pattern, so the gate replaces such a correlation or request id with a new one and drops such a consumer id (R2: it would reach the chain, the SIEM and the export). Rows written before that are shown as `<id-hidden>` on every page, in the export and in the rollup, and filters refuse such values (HTTP 400) |

The Analytics tables are read from the table `decision_daily`. Fill it with
`python -m supervisor.jobs.decision_rollup` (`--days N`, `--from D --to D`, `--backfill`); the
scheduler runs it every `SCHED_DECISION_ROLLUP_S` seconds (default 3600) when the flag is on.
Until it has run, the page says so. On Delta run `python -m supervisor.jobs.bootstrap_schema`
first (new columns on `agent_event` and `alert`, new table `decision_daily`).

| Setting | Default | Meaning |
|---|---|---|
| `CONSOLE_DECISIONS_V2` | `0` | WP39: everything in the table above |
| `CONSOLE_EXPORT_MAX_ROWS` | `5000` | WP39: rows of one CSV export (1 to 100,000) |
| `SCHED_DECISION_ROLLUP_S` | `3600` | WP39: interval of the `decision_rollup` job |

Screenshots: `docs/design/screens/wp39-*.png` (made by
`python tools/console_screenshots.py --wp39 --data-dir NEW_FOLDER`). Harness:
`python -m supervisor.console.activity_harness` (all pages in three flag states and both languages,
fingerprint test with planted personal data, 30 adversarial probes (22 by the author, 8 by the review), the alert drills; `--check`
compares with `data/eval/activity/baseline.json`).

## Screens

| Screen | URL | What it shows | Actions |
|---|---|---|---|
| Search | `/console/search?q=` | Agents, cases and exact trace ids that match (WP-UX1). Read-only | - |
| Placeholders | `/console/soon/<page>` | "Coming in WP-UX3" for a page whose flag is off (WP-UX1, needs `CONSOLE_NAV_PLACEHOLDERS=1`) | - |
| Overview | `/console/` | Greeting by the ICT hour with the live counts (agents under supervision, actions stopped today, cases needing a decision, nearest SBV clock); what Supervisor is; the three pillars; four numbers from the stores (gate decisions today and median latency; stops split blocked / paused; open cases with the critical count; evidence chain entries, signed root, anchor, last verify); latest gate decisions (the newest stops always included) linked to their cases; the demo-data line on a demo store. | - |
| Agents | `/console/agents` | Sortable, paged table with state tiles and a filter bar (search, state, risk); a row opens a drawer (Overview, Policy, Cases; `?drawer=<id>&dtab=` without JS) that links to the agent page. | Open the agent page. |
| My agents (WP-N2) | `/console/my/agents` | Inventory of the agents in scope (scope switch my / team / all). Columns: agent (name, id, system), kind (registered, policy-only, candidate), gate state with pending resume, autonomy, risk, guardian tools `on N / of M` with a pill (full, below floor, none), last activity, open cases, recommended action. Every column but the action sorts. Filters: text, kind, gate state, risk, guardian cover. Tiles: total, running, shadow, paused or quarantined, below floor. Candidates (unmanaged apps, agent endpoints, Genie spaces from the workspace scan; needs `INVENTORY_ENABLED`) show in scope `all` with a Register link. Needs `CONSOLE_MY_AGENTS` and `CONSOLE_NAV_V3`. | Open the agent page; Register a candidate. |
| Agent | `/console/agents/<id>` (WP-UX2) | Header with state pill (rule or person), risk, Decision 33, mock label. Eight base tabs plus Risks, Controls, Tasks and Transparency, each of the last four only with its flag, each an htmx partial at `/console/agents/<id>/tab/<name>` (`?tab=<name>` is the no-JS full page with the same body): **Overview** (the card: owner, risk, lifecycle stepper, coverage, the one action; gate last 24 h; evidence lane; open cases), **Policy** (rules in scope with version, action, severity, fail mode, regulation, approvers; policy hash; approved-tools allow-list with tool classes), **Tools** (WP22 table and least-privilege panel of this agent; `CONSOLE_TOOLS_ENABLED`), **Inventory** (WP24 subgraph tree and nodes; `INVENTORY_ENABLED`), **Traces** (newest 20 traces; links to the trace viewer when WP-UX3 has built `/console/traces/<id>`, else to the case transcript), **Cases**, **Assurance** (results whose target is this agent; `CONSOLE_ASSURANCE_ENABLED`), **Compliance** (matrix summary from the advisor read API; `CONSOLE_COMPLIANCE_ENABLED`), **Risks** (WP29: the agent's inherent and residual register level, its own and inherited risks; `CONSOLE_RISKS_ENABLED`), **Controls** and **Tasks** (WP30: compliance figure and controls in scope; lifecycle stage and tasks; `CONSOLE_CONTROLS_ENABLED`), **Transparency** (WP31: the latest report per variant with download links; `CONSOLE_TRANSPARENCY_ENABLED`). A tab whose flag is off is not shown and its URL answers 400 with the flag name. | Pause now, Approve resume (two people), Quarantine, Release: the same audited routes as before (`POST /console/agents/<id>/<action>`), moved here from the Agents list cards. |
| Agent, Register and Guardians tabs (WP-N2) | `/console/agents/<id>?tab=register` and `?tab=guardians` | **Register**: the registry row, the AI system it belongs to (stage, class, autonomy, risk), the description, the assessment summary (Decision 33 outcome, risk level and source) and the recommended action; a policy-only agent shows "known to the gate, not registered", its manifest values and a Register link. **Guardians**: one status row per guardian feature (instance on, binding per linked system, floor lock, effective, reason when off) and, for the enabled features, counts over a window (`?window=24h|7d|30d`): findings per detector with top codes, gate checks, allowed, blocked, paused, would-block, judge verdicts and cases (mock label), last monitor status, last result per pack. Counts only, no excerpt. Both need `CONSOLE_MY_AGENTS`. | None (read only). |
| Cases | `/console/cases` | Severity, agent, a plain headline built from the stopping rule and the stopped tool (rule id and case id under it), opened-by pill (gate / judge / monitor / person), SBV 24 h clock as a bar and text, status, assignee. Filter bar (severity, agent, opened by) plus Open / Archive / All; sortable headers (severity, agent, SBV clock, status, assignee) and pages of 25 (WP-UX2); a Details button opens a row drawer (`/console/cases/<id>/drawer`, `?drawer=<id>` without JS). Refreshes every 30 s. | Refresh cases: the explicit case intake (a GET never writes). |
| Case | `/console/cases/<id>` | Header card (pills, headline, one-line explanation with amount and detect-to-stop time, SBV 24 h and 5-day clocks, Decision 33 line, regulation). Pill tabs (htmx partials at `/console/cases/<id>/tab/<name>`; `?tab=` for a full page): Story (timeline from stored rows only, rules and judges, masked transcript excerpt), Rules & judges, Transcript, Evidence, Case file. | Right column "Your decision": flow open -> triaged -> contained -> closed, the two-person rule, Assign to me, Mark triaged + note, Contain + note, Sign-off (high / critical), Close (disabled with the reason until allowed), comment, ITSM ticket. Evidence card: Verify again, Case file (`/casefile.html`, `/casefile.json`, read-only views). |
| Sign-off list | `/console/signoff` (WP-UX2) | Open high and critical cases that wait for a signature (triaged or contained, fewer than two approvals), with signatures so far (`0/2`, `1/2` and who), SBV clock, sortable and paged. Same count as the sidebar badge (`CaseService.waiting_approvals`). | Sign-off button opens a drawer with the existing sign-off panel; the audited `POST /console/cases/<id>/signoff` is unchanged. Without JS the button links to the full page below. |
| Sign-off | `/console/cases/<id>/signoff` | Sign-offs so far with the statement text verbatim. | Approve or reject with a statement; the signer ticks "I sign this statement as myself". |
| Evidence | `/console/evidence` (`/console/export` redirects) | Entries, last signed root (key id, dev / managed key), last anchor; every lane as squares (one per entry, newest 60, "+N" for earlier ones; colour by record type; root lane gold, signed roots filled); "How to verify offline" with the cmd commands; earlier exports. | Verify now; Export chain (zip: chain export + offline verify report; recorded on the chain); Build audit pack (zip: chain export + verify report + case files + judge eval report + manifest). Auditor, reviewer, approver, admin. |
| Onboard | `/console/onboard` | Six-step wizard (stage from the artefacts of the latest run), last-run cards: profile (Decision 33 proposal, tools, money-moving, human approval step in code), plan (capabilities, rules proposed, judges), launch report (GO / NO-GO, red-team catch rate, false alarms, branch), links to the artefact files. | Start (off by default, `CONSOLE_ONBOARD_ENABLED=1`): runs `supervisor.onboard` in a background thread on the console's own store and chain writer, one run at a time, progress every 2 s. MockChat (labelled) unless the configured LLM answers the preflight probe. Reviewer, owner, admin. |
| Compliance | `/console/compliance` (off by default, `CONSOLE_COMPLIANCE_ENABLED=1`; off = 400 and no nav entry) | Advisory obligations matrix per agent (the three demo agents and onboarded products with a launch-pack matrix): counts by status, Decision 33 class, open questions, threshold findings, rows with filters (instrument, status, duty), and one page per obligation (Vietnamese text, sources, controls). Advisory only. See `docs/compliance-advisor.md`. | Read-only. |
| Integration | `/console/integration` | Off by default (`CONSOLE_INTEGRATION_ENABLED=1`). List of integration reports (agent, framework, readiness, patch count); one report shows the score per area, what was found (framework, LLM calls, tools with risk class, data access, PII fields, tracing), what Supervisor needs (semantic attributes, gate call sites, MCP proxy, catalogue, settings, test plan) and each patch as escaped text (`/console/integration/{name}/patches/{file}` serves it as `text/plain`). Read-only; a malformed report shows a message. | - (permission `onboard.view`) |
| Inventory | `/console/inventory` | Off by default (`INVENTORY_ENABLED=1`; off = 400 and no nav entry). Unmanaged workspace items (shadow AI) with case links, per-agent subgraph as an indented ASCII tree, node table with own and effective risk and evidence. See `docs/inventory.md`. | Read only. |
| Assurance | `/console/assurance`, `/console/assurance/<run_id>` | Off by default (`CONSOLE_ASSURANCE_ENABLED=1`; off = 400 with a message and no nav entry). Runs newest first (time, target spec, counts, mock label); per run: pack, dimension, target, status, each metric against go / no-go, data mode, items, reasons, and the hash of the `assurance_result` chain record (links to Evidence; Evidence has no per-record page). | Read only. Run packs with `python -m supervisor.assurance run all --target demo --out out\assurance`. |
| Tools | tab of Analytics; `/console/tools` redirects (303); `/console/tools/<agent>/diff` is unchanged | Off by default (`CONSOLE_TOOLS_ENABLED=1`; off = 400 with a message and no tab). Totals (calls, blocks, pauses, worst p95) and one block per agent: a sortable table (calls with a bar, allow, block, pause, errors, p50, p95, users, last seen, status used / unused / not declared / exception) and the least-privilege suggestion with a download link for the diff. Plain numbers, no charts. | Read: any role (`tools.view`). Download the diff: owner or admin (`tools.download`). Nothing is applied from the screen; see `docs/tool-analytics.md`. |
| Health | `/console/health` | A plain setup summary (mode and store, identity, judge model or mock, signing key, anchor, Databricks, Onboard start) and the local preflight checks with status pills and fix hints. Secrets are never shown. The live Databricks checks write probes, so they run only from `python -m supervisor.cli preflight`. | - |
| Alerts | `/console/alerts` (WP-UX2, moved out of Metrics) | Tiles (Active, Open, Acknowledged, Closed), filter bar (severity, agent, rule), sortable paged table: rule, severity, agent, window count, repeats, case link, chain position, status. A Details button opens a drawer with every field (hashes, routes, who acknowledged). Default view hides closed alerts. | Acknowledge (`alert.ack`: operator, admin): the audited `POST /console/alerts/<id>/ack`, unchanged. |
| Analytics | `/console/analytics?tab=gate\|tools\|metrics\|latency` (WP-UX2) | One toolbar (range 7 / 30 / 90 days or default, agent) for four tabs, each an htmx partial at `/console/analytics/tab/<name>`. **Gate**: calls checked, blocked, paused and p95 per agent. **Tools**: see above. **Oversight metrics**: the old Metrics page (monitor status, per-agent metrics with sparklines, chain status) with a tile that links to Alerts (`#alerts`). **Latency**: live gateway counters. Blank range = each tab's own window (Tools: `TOOL_ANALYTICS_WINDOW_DAYS`; Gate: 7 days; metrics: all stored days). | Verify the whole chain now (Oversight metrics tab). |
| Inbox | `/console/inbox` (envelope in the header) | Notices from the case workflow (new case, sign-off needed, case closed). Filter bar (status, channel), sortable and paged (WP-UX2). | Mark read. |

Screenshots for review: `uv run python tools/console_screenshots.py --reseed` (dev only; it
needs Playwright in `PLAYWRIGHT_PYTHON`, else it prints `[SKIP]`) writes every screen at
1360x900 in English and Vietnamese (`--out DIR`; `--ux3` adds the WP-UX3 pages).

Phase 3 waves 2 and 3 (integration branch `phase3-wave2`): `docs/design/screens/wave2/` holds
the Risks, Controls, Tasks, Transparency and Integrations (collector catalogue) pages, their
drawers and the four new Agent tabs (`wave2-*`, English and Vietnamese, one dark), made with
`python tools\console_screenshots.py --reseed --wave2 --data-dir <new folder> --out
docs\design\screens\wave2 --port <free port>`, and the verdict v2 Decisions screens with the
reconciled Observed-decision line (`wp39-*`, `--wp39`). Viewport images only.

Committed reference set in `docs/design/screens/` (English, light theme, 1360x900, synthetic
demo store; taken on the merged phase3-wave1 console with `--reseed` and then `--ux3`):

| File | Screen |
|---|---|
| `overview-en.png` | Overview with stat tiles and the sidebar (WP-UX1) |
| `agents-drawer-en.png` | Agents list with the row drawer open (WP-UX1) |
| `agent-overview-en.png` | Agent page, Overview tab (WP-UX2) |
| `case-en.png` | Case page (WP-UX2 header) |
| `alerts-en.png` | Alerts list (WP-UX2) |
| `signoff-en.png` | Sign-off list (WP-UX2) |
| `analytics-gate-en.png` | Analytics, Gate tab (WP-UX2) |
| `decisions-drawer-en.png` | Gate decisions with the drawer open (WP-UX3) |
| `trace-en.png` | Trace viewer: span tree and the gate stop (WP-UX3) |
| `playground-en.png` | Playground dry-run form (WP-UX3) |
| `policies-en.png` | Policies in force (WP-UX3) |
| `audit-en.png` | Audit log (WP-UX3) |

## Case states

```
open --triage (assignee)--> triaged --contain (note)--> contained --close--> closed
                            triaged --close (false alarm only)--> closed
```

Close needs a resolution (`confirmed` or `false_alarm`) and a reason. A `high` or `critical`
case also needs two sign-offs (approve) by two different people, at least one with the
approver role. A low or medium case is closed by one reviewer; the reason is stored as a
sign-off row too.

## Roles

Seven roles. A person can hold several (the sets add up). `owner` is the agent-owner role of
ADR D04. The table below is the role matrix in `src/supervisor/core/rbac.py`; a test keeps this
page equal to `supervisor.core.rbac.matrix_markdown()`, so change the code first, then paste.

| Role | In short |
|---|---|
| viewer | Read-only console pages |
| reviewer | Assign, triage, contain, close, comment, ITSM ref, sign off, record report sent, pause, resume (as the reviewer half), run intake, start onboarding, verify case and chain, mark inbox read, export and download |
| approver | Sign off (the approver half), record report sent, comment, pause, verify case and chain, mark inbox read, export and download |
| owner | Resume (as the owner half), comment, pause, start an onboarding run, verify case and chain, mark inbox read |
| auditor | Read pages, verify case and chain, mark inbox read, build and download audit packs and chain exports |
| admin | Everything a reviewer can do, plus quarantine and release a quarantine |
| operator | Read pages, run case intake, verify the chain, acknowledge alerts |

### Alerts (WP21)

The **Alerts** page (`/console/alerts`; before WP-UX2 a section of Metrics; flag `ALERTS_ENABLED`
makes the job that fills it, the page itself always shows the table). It lists open and acknowledged alerts with rule,
severity, agent, window count, repeats, case link and chain position. The **Acknowledge**
button needs the `alert.ack` permission (operator, admin) and writes two audit rows and an
`alert_ack` evidence record. See `docs/alerts.md`.

### Incidents (WP-G5)

The **Incidents** tab of Cases & alerts (`/console/incidents`, flag `GOVERNANCE_ACTIONS_ENABLED`
with `GOVERNANCE_ENABLED`; item **Incidents** next to Inbox in the old sidebar). It lists the
incidents the governance loop made from events (`docs/incidents.md`): tiles by status, filters,
sortable table, drawer. `incidents.view` is held by every role (a scoped role sees the incidents of
its systems and agents); `incidents.transition` (reviewer, owner, admin) moves an incident on and
closes it, with two audit rows and an `incident_change` record. The **Reports** tab of the AI
system page lists the incidents of that system.

### Law agent drafts (WP-L1)

The page `/console/regkb/<instrument>/drafts` (flag `LAWAGENT_ENABLED`; HTTP 400 while it is off)
lists the duties that the law agent drafted from the stored official text of one instrument,
grouped by article, with the verbatim Vietnamese quote marked in the article. `regkb.view` is held
by every role. `regkb.confirm` (approver, admin) puts **Confirm** or **Drop** on a draft, with two
audit rows per POST and the person written on the row. There is no "Run the agent" button: the
CLI runs the agent (`docs/regulations.md`, "Law agent (WP-L1)"). A draft is never an obligation.
The banner "Not legal advice. Bank counsel must confirm." stays on the page.

### Old URLs (WP-UX2)

A moved page answers `303 See Other` to its new place. The query string is kept (`lang`, filters,
sort), so a bookmark keeps its meaning. A fragment is kept by the browser.

| Old URL | Goes to | Note |
|---|---|---|
| `/console/metrics` | `/console/analytics?tab=metrics` | `/console/metrics#alerts` lands on the Alerts tile of that tab, which links to `/console/alerts` |
| `/console/tools` | `/console/analytics?tab=tools` | `agent_id=` is read as `agent=`; `sort`, `dir`, `days` are kept; off = 400 with the flag name, as before |
| `/console/export` | `/console/evidence` | unchanged since phase 2 |
| agent cards on `/console/agents` | `/console/agents/<id>` | no redirect (a list, not a page): the drawer links to the agent page |
| `/console/cases?status=open` (sidebar Sign-off) | `/console/signoff` | the URL still works; only the sidebar link changed |

### Role matrix

<!-- ROLE-MATRIX:BEGIN -->
| Permission | What it allows | viewer | reviewer | approver | owner | admin | auditor | operator |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `console.view` | Open console pages (queue, case, agents, evidence, case files) | x | x | x | x | x | x | x |
| `health.view` | Health page | x | x | x | x | x | x | x |
| `metrics.view` | Metrics page | x | x | x | x | x | x | x |
| `onboard.view` | Onboarding page, status and generated files | x | x | x | x | x | x | x |
| `compliance.view` | Compliance tab (advisory obligations matrix, read-only) | x | x | x | x | x | x | x |
| `inventory.view` | Inventory page and /v1/inventory (read-only, WP24) | x | x | x | x | x | x | x |
| `gate.read` | Read agent gate state and gate metrics (API) | x | x | x | x | x | x | x |
| `case.assign` | Assign a case |  | x |  |  | x |  |  |
| `case.itsm` | Set the ITSM reference of a case |  | x |  |  | x |  |  |
| `case.transition` | Triage, contain or close a case |  | x |  |  | x |  |  |
| `case.comment` | Comment on a case |  | x | x | x | x |  |  |
| `case.signoff` | Sign off a case (two-person rule) |  | x | x |  | x |  |  |
| `case.report_sent` | Record that an incident report (preliminary or formal) was sent to the authority |  | x | x |  | x |  |  |
| `case.verify` | Verify the evidence lane of one agent |  | x | x | x | x | x |  |
| `chain.verify` | Verify the whole evidence chain |  | x | x | x | x | x | x |
| `intake.run` | Run case intake now |  | x |  |  | x |  | x |
| `inbox.read` | Mark an inbox notice read |  | x | x | x | x | x |  |
| `evidence.export` | Build an audit pack or chain export |  | x | x |  | x | x |  |
| `evidence.download` | Download a built audit pack |  | x | x |  | x | x |  |
| `tools.view` | Tools page and /v1/analytics/tools (tool usage, read-only) | x | x | x | x | x | x | x |
| `tools.download` | Download the least-privilege diff of an agent (WP22; a suggestion, never applied) |  |  |  | x | x |  |  |
| `onboard.start` | Start an onboarding run |  | x |  | x | x |  |  |
| `agent.pause` | Pause an agent (D04) |  | x | x | x | x |  |  |
| `agent.resume` | Approve a resume (D04, two people) |  | x |  | x | x |  |  |
| `agent.quarantine` | Quarantine an agent |  |  |  |  | x |  |  |
| `agent.release` | Release an agent from quarantine |  |  |  |  | x |  |  |
| `alert.ack` | Acknowledge an alert (WP21) |  |  |  |  | x |  | x |
| `decisions.view` | Gate decisions list and drawer (read-only) | x | x | x | x | x | x | x |
| `traces.view` | Traces list and span viewer (masked payloads only) | x | x | x | x | x | x | x |
| `decisions.export` | Export the filtered Gate decisions list as CSV: masked columns only, row cap (WP39) |  |  |  |  | x | x |  |
| `playground.run` | Playground: dry-run gate check, no side effect (WP-UX3) |  | x | x | x | x |  | x |
| `policies.view` | Policies page: deployed rules and versions (read-only) | x | x | x | x | x | x | x |
| `credentials.view` | Credentials page: agent key metadata, never a secret (read-only) |  |  |  | x | x |  |  |
| `users.view` | Users and roles page (read-only) |  |  |  |  | x |  |  |
| `schema.view` | Schema self-check page: SQL plan, read-only (WP-P3) |  |  |  |  | x |  |  |
| `audit.view` | Audit log page: console_action rows (read-only) |  |  |  |  | x | x |  |
| `integrations.view` | Integrations status page (read-only) | x | x | x | x | x | x | x |
| `mcp.tools.view` | List MCP tools and their diffs (read-only, WP26) | x | x | x | x | x | x | x |
| `mcp.tools.propose` | Give the first approval of a new or changed MCP tool (WP26) |  | x | x | x | x |  | x |
| `mcp.tools.approve` | Approve a new or changed MCP tool; the second different person locks it (WP26) |  | x | x | x | x |  |  |
| `risks.view` | Risks page, Risks tab and /v1/risks (read-only, WP29) | x | x | x | x | x | x | x |
| `risks.edit` | Create and change risks, link them to controls and rules (WP29) |  | x |  | x | x |  |  |
| `collectors.add` | Integrations catalogue: Add a collector (issues the first agent key, WP38) |  |  |  |  | x |  | x |
| `session.view` | GET /v1/sessions/{id}: masked timeline and scores of one conversation (WP27) |  | x | x | x | x | x | x |
| `controls.view` | Controls page, Controls tab and /v1/controls (read-only, WP30) | x | x | x | x | x | x | x |
| `controls.edit` | Create and change controls and what they cover (WP30) |  | x |  | x | x |  |  |
| `tasks.view` | Tasks page, Tasks tab and GET /v1/tasks (read-only, WP30) | x | x | x | x | x | x | x |
| `tasks.edit` | Generate, start and finish tasks, ask to waive one (WP30) |  | x |  | x | x |  |  |
| `tasks.approve` | Second person for a task waiver; approve a lifecycle move or an approver task (WP30) |  |  | x |  | x |  |  |
| `transparency.view` | Transparency page, Agent tab and GET /v1/transparency (WP31) | x | x | x | x | x | x | x |
| `transparency.generate` | Build and sign a transparency report (WP31) |  | x |  |  | x |  |  |
| `systems.view` | Systems pages and GET /v1/systems: AI systems in your scope (WP-G0) | x | x | x | x | x | x | x |
| `systems.edit` | Register and change AI systems, their team and their links (WP-G0) |  | x |  | x | x |  |  |
| `systems.approve` | Answer a stage approval of an AI system (WP-G1) |  | x | x | x | x |  |  |
| `systems.review` | Plan, change, complete and reopen reviews of an AI system (WP-G1) |  | x | x |  | x |  |  |
| `incidents.view` | Incidents tab and GET /v1/incidents: incidents in your scope (WP-G5) | x | x | x | x | x | x | x |
| `incidents.transition` | Move an incident on and close it (the holders of case.transition or systems.edit) (WP-G5) |  | x |  | x | x |  |  |
| `mcp.apps` | List, approve and block the apps connected to the MCP server (WP-G6) |  |  |  |  | x |  |  |
| `agents.edit` | Register and change an agent in the registry, POST /v1/agents (WP-P2) |  | x |  | x | x |  |  |
| `agent.mode` | Ask for or approve SHADOW to RUNNING (two persons); RUNNING to SHADOW needs the reviewer or admin role (WP-P2) |  | x | x | x | x |  |  |
| `policy.reload` | Reload the policy folders from disk (WP-P2) |  |  |  |  | x |  |  |
| `regkb.view` | Law agent drafts page: duties drafted from the stored official text (WP-L1) | x | x | x | x | x | x | x |
| `regkb.confirm` | Confirm or drop a law agent draft; the compliance sign-off role (WP-L1) |  |  | x |  | x |  |  |
<!-- ROLE-MATRIX:END -->

Every console route and every `/gate` human route has a permission in `ROUTES` (same file).
Routes marked `PUBLIC` (health, ready, version, docs, static files, redirects), `AGENT`
(`POST /gate/check`, `POST /v1/traces`: the agent's own identity) or `DEV_ONLY`
(`POST /console/dev/user`) have no role check. A service principal or the system identity
keeps its phase-1 treatment: it may open the read-only views (view, health, metrics, onboard
page, verify) and nothing else. The `/gate` control routes
(pause, resume, quarantine, release) and their `/v1/gate/...` aliases ALWAYS check identity
and role, whatever `API_RBAC_ENABLED` says. The caller must be named by the Principal port:
on the laptop the `X-Dev-User` header must be present and name a user in the users file (no
`default_user`, no console cookie); on the App the SSO headers apply. A missing or unknown
identity, or a role without the permission, is HTTP 403 JSON `{"error": "..."}`. The route
never reads `X-Forwarded-User` itself, and the JSON body field `principal` is accepted for
backward compatibility but ignored. Example (Windows cmd):
`curl -X POST -H "X-Dev-User: reviewer.an" -H "Content-Type: application/json" -d "{\"agent_id\":\"payments\",\"reason\":\"check\"}" http://127.0.0.1:8000/v1/gate/pause`.
`API_RBAC_ENABLED` gates only the agent-facing routes (`GET /gate/agents/{id}/state`,
`GET /gate/metrics`); `POST /gate/check` is agent ingress. The `gate_state_change` evidence
record carries `actor_kind` and `auth_method` of the acting principal.

Resume (ADR D04): the gateway needs the agent owner (`agent.owner_user`) and a reviewer listed
in `policies/*.yaml` (`reviewers:`), two different people. The first approval is stored as
pending; the second completes it. The console shows the pending approval on the Agents page.

Two lists decide who may act, and both must agree:

| Action | Console role (users.yaml / auth.yaml) | Gateway authority (deployed policy) |
|---|---|---|
| Resume | reviewer, owner or admin | `agent.owner_user`, or an id in `reviewers:` |
| Release a quarantine | admin | an id in `admins:` |

The ids must match exactly (on the App: the SSO email). When they do not, the console answers
400 and names the missing list. A high or critical case that is a false alarm can be signed
off by two people while still `triaged`, then closed as `false_alarm`.

## Identity

| Target | Adapter | Identity | Roles from |
|---|---|---|---|
| Laptop | `dev_header` (`AUTH_KIND=auto` default) | `X-Dev-User` header, else the "Switch user" cookie, else `default_user` | `config/users.yaml` (synthetic users). Not a real identity: the console shows a banner. |
| Databricks App | `databricks_app` (default when `SUPERVISOR_MODE=databricks_app`) | `X-Forwarded-Email`, else `X-Forwarded-User` | `config/auth.yaml` (replace the FILL-ME values). Optional group lookup `scim_me` uses `X-Forwarded-Access-Token` inside the request only, fresh client per call, never logged or stored. |

No SSO header on the App (or a background task): the app service principal, read-only by
default. `AUTH_KIND=dev_header` is refused when `SUPERVISOR_MODE=databricks_app`.

Every action records who did it and how they were identified: `case_event.actor`,
`actor_kind`, `auth_method`, and the same fields in the evidence-chain payload
(`case_event`, `signoff`, `console_gate_action`, `audit_pack_requested`). Free text is masked
before storage; the chain gets only its SHA-256. Sign-off statements are stored verbatim.

## Console action audit

Every POST under `/console` writes rows to the append-only table `console_action`, and so do
the `/gate` control routes (pause, resume, quarantine, release), also when `API_RBAC_ENABLED` is
off. Columns: `action_id`, `ts`, `request_id`, `actor`, `actor_kind`, `auth_method`, `roles`,
`permission`, `method`, `path`, `target_kind`, `target_id`, `outcome`, `before_hash` and
`after_hash` (SHA-256 of the canonical target row: the case row, the agent row with its active
gate controls, or the notice row), `detail` (an error class or a denial code, never free text
typed by a user). The rows are in the audit pack (`console_action.jsonl`, with the count in
`manifest.json`).

Two rows per action, one `request_id`:

| Row | `outcome` | Written | `before_hash` / `after_hash` |
|---|---|---|---|
| 1 | `attempted` | BEFORE the side effect | target now / null |
| 2 | `ok`, `denied` or `error` | after | target before / target after |

* If row 1 cannot be written, the action is NOT done. The answer is HTTP 400 with "audit store
  unavailable; the action was not done" (a message partial on the console, `{"error": ...}` on
  `/gate`). Nothing changes: no case row, no agent state, no intake run.
* If row 2 cannot be written (the action is already done), the server logs an ERROR and the
  answer carries a WARNING ("the console audit record failed"). It is never a 5xx. Row 1
  already proves the action was tried.
* A permission denial (HTTP 403) writes one `denied` row and no `attempted` row: it has no side
  effect.
* An unknown or missing identity on a mutating route (for example an unknown `X-Dev-User`)
  writes one `denied` row: `actor_kind` `unverified`, `auth_method` of the provider (also on
  the `/gate` path), `actor` `unverified:<claimed id>` (client text cut to the characters
  `A-Za-z0-9_.@+-`, 64 at most) or `unverified:unknown`, `detail` `identity_unknown`. The console
  answer stays HTTP 400 with the usual message; the control routes answer 403.
* `CONSOLE_AUDIT_ENABLED=0` is allowed only with `SUPERVISOR_MODE=dev`. In `laptop` and
  `databricks_app` mode the settings are refused at load, and the runtime ignores the flag
  (auditing stays on). In dev mode with the flag off the app logs a WARNING at startup and
  writes no rows.

## Errors

Every user error (bad transition, the same person approving twice, a stale page, an unknown
user) is HTTP 400 with a short message that appears at the top of the page. A missing role is
HTTP 403 with the same kind of message (WP18; before WP18 it was 400: **default-on behaviour
change**, scripts that checked for 400 must accept 403). Both are 4xx user errors, never 5xx;
`console.js` swaps 400, 403, 413 and 429 message partials into `#flash`. Every
POST must come from the console page (htmx sends `HX-Request: true`); a cross-site form cannot
set that header.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `AUTH_KIND` | `auto` | `dev_header`, `databricks_app` or `auto` (by mode) |
| `USERS_FILE` | `config\users.yaml` | Dev users (laptop) |
| `AUTH_CONFIG_FILE` | `config\auth.yaml` | Role map (Databricks App) |
| `CONSOLE_LANG` | `en` | Default UI language (`en` or `vi`) |
| `CONSOLE_NAV` | `sidebar` | WP-UX1: `sidebar` (left sidebar, default) or `top` (the phase 2 pill header). One setting rolls the layout back. Windows cmd: `set CONSOLE_NAV=top` |
| `CONSOLE_NAV_SECTIONS` | `0` | Two-section sidebar: "AI Management and Governance" (Onboard, Prove, Settings) and "AI Guardian and Supervisor" (Watch, Act, Protect, Analytics). Each section folds open and closed without JS. Off = the six-group sidebar. Order in `console/nav.py` `SECTIONS`. Windows cmd: `set CONSOLE_NAV_SECTIONS=1` |
| `MCP_SERVER_ENABLED` / `MCP_SERVER_HOST` / `MCP_SERVER_PORT` | `0` / `127.0.0.1` / `8765` | WP-G6: the MCP server. On: `POST /mcp`, `GET /v1/mcp/apps`, `POST /v1/mcp/apps/<id>/approve` and `/block` (permission `mcp.apps`, admin), `GET /v1/kpis` (`console.view`) and a KPI block on the Governance overview. Off: nothing is mounted, no table is read, the overview is as before. Host and port are for `python -m supervisor.mcp_server`. See `docs/mcp-server.md`. Windows cmd: `set MCP_SERVER_ENABLED=1` |
| `CONSOLE_NAV_V3` | `0` | WP-UX4a: the merged left bar (My overview, Governance, Supervisor, settings gear), section tab strips, the three overview pages and Workflows. Needs `CONSOLE_NAV=sidebar`. Off = the sidebar as before. See "Navigation v3". Windows cmd: `set CONSOLE_NAV_V3=1` |
| `CONSOLE_OVERVIEW_V4` | `0` | WP-N1: My overview as a dashboard (banner, registration pipeline, assessment completion, risk by autonomy, totals, action items, top candidates, cards with description and recommended action), the Candidates tab `/console/candidates` and `GET /v1/candidates`. Needs `CONSOLE_NAV_V3=1` and `GOVERNANCE_ENABLED=1`; the candidate table also needs `INVENTORY_ENABLED=1`. Off = today's My overview. See `docs/triage.md`. Windows cmd: `set CONSOLE_OVERVIEW_V4=1` |
| `CONSOLE_WORKFLOW_ACTIONS` | `0` | WP-P1: Done, Waive, Request move, Approve, Reject and Move as buttons on the Tasks tab of a system (see "Tasks and stage approvals as buttons"). Needs `GOVERNANCE_ENABLED=1`, `CONSOLE_SYSTEMS_ENABLED=1` and `CONTROLS_ENABLED=1`. Off = the tab is read only and the routes answer HTTP 400 with the flag name. Windows cmd: `set CONSOLE_WORKFLOW_ACTIONS=1` |
| `CONSOLE_MY_AGENTS` | `0` | WP-N2: the My agents tab under My overview. WP-N1 only adds the tab entry (shown when `CONSOLE_OVERVIEW_V4=1` too); the page is built by WP-N2. Windows cmd: `set CONSOLE_MY_AGENTS=1` |
| `ONBOARD_ALLOWED_ROOTS` | empty | WP-UX4b: folders (`;` or `,` separated) the register wizard may run the readiness advisor on. Empty = advisor off in the wizard. Windows cmd: `set ONBOARD_ALLOWED_ROOTS=C:\work\agents` |
| `CONSOLE_CATALOG_ENABLED` | `0` | `/console/catalog`: every guardian capability as a card (gateway controls, detectors, judges, monitors, evidence, connectors), showing whether it is on in this instance and the setting that turns it on. Tabs: Catalog and Active. Read-only: it never changes a setting. With `GUARDIAN_BINDINGS_ENABLED=1` (WP-S1) a system picker adds per-system switches for people with `systems.edit`, see `docs/guardian-bindings.md`. Windows cmd: `set CONSOLE_CATALOG_ENABLED=1` |
| `CONSOLE_MY_AGENTS` | `0` | WP-N2: the **My agents** tab under My overview (`/console/my/agents`, htmx rows at `/console/my/agents/rows`) and the **Register** and **Guardians** tabs of the Agent page. Needs `CONSOLE_NAV_V3=1`. Read-only. Off = no tab, the routes and the two agent tabs answer 400 with the flag name. Windows cmd: `set CONSOLE_MY_AGENTS=1` |
| `CONSOLE_STATE_ACTIONS` | `0` | WP-P2 (phase 8): agent state and separation of duties in the console. (1) Agent page: **Request RUNNING** (agent in SHADOW, reason required) and **Approve RUNNING** by a second, different person who is the agent owner or listed in `reviewers:` of the policy; the requester gets HTTP 400 `same_person`. The rule is the one of `POST /v1/gate/agents/<id>/state` (`AgentStateMachine.change_mode`); the console does not repeat it. The shadow would-block count of the last 7 days (same query as the Guardians tab) shows next to the button. Needs the permission `agent.mode`; `AGENTS_API_ENABLED` is not needed. (2) Decision 33 apply: the system owner (`owner_user` or an active `system_owner` of the team) cannot apply the class on the own system (HTTP 400 `owner_cannot_apply`); every answer a person gives needs a justification of at least 20 characters (HTTP 400 `justification_too_short`). (3) Guardian switch-off: a reason is required; on a system in `deployment`, `operation` or `re_evaluation`, at risk level `high` or `prohibited`, or classed high risk, the switch-off becomes a request (`guardian_off_request`) and takes effect when a second person approves it (`POST /v1/systems/<id>/guardian-off-requests/<rid>/decide`, or Approve on the Catalog page; permission `systems.approve`); the requester gets `same_person`. The guardian floor stays: a floor feature can never be switched off. Off = none of this: no panel, the new routes answer 400 with the flag name, apply and switch-off behave as before. Windows cmd: `set CONSOLE_STATE_ACTIONS=1` |
| `ONBOARD_INTAKE` | `0` | WP-O1 (phase 9): candidate source intake. A **Source** panel in the Candidates drawer and a **Source** tab on the agent page: upload a zip (text files only) or give a git URL; every attempt is numbered, scrubbed before it is stored under `DATA_DIR/intake/<node id>/<n>/` and listed with a **Re-upload** button. `POST /v1/intake/<id>` needs `systems.edit`, `GET` needs `systems.view`; each POST writes two audit rows. Off = no tab, no panel, the routes answer 400 `intake_off`. Details: docs/onboard.md "Intake". Windows cmd: `set ONBOARD_INTAKE=1` |
| `ONBOARD_INTAKE_MAX_MB` | `20` | WP-O1: the largest zip, and the largest total of unpacked files, in MB (1 to 200). |
| `ONBOARD_FACTS` | `0` | WP-O2 (phase 9): the facts card. A **Facts** panel in the Candidates drawer (next to Source) and a **Facts** tab on the agent page: what the stored source says (tools, models, data, secrets by kind, approval points, autonomy, Decision 33 proposal, weak spots), each row with file:line and a quote, a line "n claims dropped (no evidence)" and a **Re-read** button. `POST /v1/facts/<id>/<n>` needs `systems.edit` (two audit rows), `GET /v1/facts/<id>` needs `systems.view`. Needs a stored source (`ONBOARD_INTAKE`). Off = no tab, no panel, the routes answer 400 `facts_off`. Details: docs/onboard.md "Facts card". Windows cmd: `set ONBOARD_FACTS=1` |
| `ONBOARD_PREDEPLOY` | `0` | WP-O3 (phase 9): the pre-deploy assessment. A **Pre-deploy** panel in the Candidates drawer (after Facts) and a **Pre-deploy** tab on the agent page: the verdict (GO, NO-GO, QUESTIONS) from the facts, the readiness advisor, the required assurance packs in the launch sandbox, the multi-turn red team and the duties, the items with their pointers, and a **Run again** button; the panel refreshes itself every 3 s while a run goes. `POST /v1/predeploy/<id>/<n>` needs `systems.edit` (two audit rows), `GET /v1/predeploy/<id>` needs `systems.view`. Register v2 step 3 shows the verdict and a link instead of the folder scan. Needs a stored source (`ONBOARD_INTAKE`). Off = no tab, no panel, the routes answer 400 `predeploy_off`. Details: docs/onboard.md "Pre-deploy assessment". Windows cmd: `set ONBOARD_PREDEPLOY=1` |
| `ONBOARD_ATTACH_VIEW` | `0` | WP-O4 (phase 9): the guardian attachment view. An **Attach** tab on the agent page (after Pre-deploy) and an **Attach** panel in the Candidates drawer: a wiring picture (agent, plug point, Supervisor gate, four guardian groups with one circle per guardian, filled when it showed evidence in the last 7 days, a lock for the guardian floor), the same items as a list with the last evidence time and the 7-day count, a **How to attach** block with the env lines for the plug point (no secret, copy button) and a **Check now** button (`systems.edit`, two audit rows; it reads the Supervisor tables again and does not call the agent). `GET /console/attach/<id>` needs `systems.view`. Off = no tab, no panel, the routes answer 400 `attach_off`. Details: docs/guardian-bindings.md "Attach view (WP-O4)". Windows cmd: `set ONBOARD_ATTACH_VIEW=1` |
| `ONBOARD_GIT_HOSTS` | empty | WP-O1: comma list of host names the intake may clone from over `https://`. Empty = the git source is off. |
| `CONSOLE_NAV_PLACEHOLDERS` | `0` | WP-UX1: show the sidebar links of pages that WP-UX3 builds (Gate decisions, Traces, Policies, Credentials, Users and roles, Audit log, Integrations); they open a "coming in WP-UX3" page. Off: links hidden, `/console/soon/<page>` answers 400 |
| `CONSOLE_DECISIONS_ENABLED`, `CONSOLE_TRACES_ENABLED`, `CONSOLE_POLICIES_ENABLED`, `CONSOLE_CREDENTIALS_ENABLED`, `CONSOLE_USERS_ENABLED`, `CONSOLE_AUDITLOG_ENABLED`, `CONSOLE_INTEGRATIONS_ENABLED` | `0` | WP-UX3: one flag per new page (see "New pages (WP-UX3)"). Off: no sidebar link, routes answer HTTP 400 |
| `CONSOLE_TRANSPARENCY_ENABLED` | `0` | WP31: the Transparency page (`/console/transparency`, list, row drawer, generate) and the Transparency tab on the Agent page. Needs `TRANSPARENCY_ENABLED=1` too; see `docs/transparency-report.md` |
| `CONSOLE_RISKS_ENABLED` | `0` | WP29: the Risks page (`/console/risks`, list, filters, row drawer) and the Risks tab on the Agent page. Needs `RISK_REGISTER_ENABLED=1` too. Read only; see `docs/risk-register.md` |
| `COLLECTORS_ENABLED` | `0` | WP38: the Integrations page becomes the collector catalogue (Add issues the first agent key; permission `collectors.add`, roles admin and operator) |
| `COLLECTORS_PUBLIC_URL` | empty | WP38: base URL put in the setup snippets (default: the address the console was opened with) |
| `CONSOLE_CONTROLS_ENABLED` | `0` | WP30: the Controls and Tasks pages and the Controls and Tasks tabs on the Agent page. Needs `CONTROLS_ENABLED=1` too. Read only; see `docs/controls.md` |
| `CONSOLE_PLAYGROUND_ENABLED` | `0` | WP-UX3: the Playground (dry-run gate check). In `databricks_app` mode it also needs `PLAYGROUND_ALLOW_APP=1` |
| `PLAYGROUND_ALLOW_APP` | `0` | WP-UX3: allow the Playground on the Databricks App (owner decision pending) |
| `CONSOLE_SCAN_CAP` | `20000` | WP-UX3: newest rows the Gate decisions and Audit log pages read before they filter (100 to 200,000); a capped list says so |
| `CONSOLE_TRACE_SCAN` | `5000` | WP-UX3: newest events (and verdicts) the Traces list reads (100 to 50,000) |
| `CONSOLE_ONBOARD_ENABLED` | `0` | WP12: the Onboard screen may start runs (new feature, off by default) |
| `ONBOARD_COMPLIANCE_ENABLED` | `0` | WP14: the onboarding run also writes `compliance_matrix.json`, `.md` and `.html` (advisory only) |
| `CONSOLE_COMPLIANCE_ENABLED` | `0` | WP14: the Compliance tab (`/console/compliance`, read-only, advisory only) |
| `CONSOLE_INTEGRATION_ENABLED` | `0` | WP15: the Integration tab (reads reports from `INTEGRATION_REPORTS_DIR`, default `<data_dir>/integration`; off: no nav link, routes answer HTTP 400) |
| `ONBOARD_ADVISOR_ENABLED` | `0` | WP15: `supervisor.onboard` also writes `integration_report.*` and `integration_patch_NN_*.patch` (never applied) |
| `INVENTORY_ENABLED` | `0` | WP24: the Inventory screen (`/console/inventory`, nav entry with the unmanaged count), `/v1/inventory/{agent_id}` and `/v1/inventory/unmanaged`, the `inventory` scheduler job and the onboarding hook; off: the paths answer 400. See `docs/inventory.md` (also `SCHED_INVENTORY_S`, `INVENTORY_SCAN_SCHEMAS`, `INVENTORY_SELF_APP`, `INVENTORY_ALLOWLIST_FILE`, `INVENTORY_WORKSPACE_FIXTURE`). Windows cmd: `set INVENTORY_ENABLED=1` |
| `SESSION_MONITOR_ENABLED` | `0` | WP27: session monitor (session id on every decision, session score, case `session_escalation`, opt-in session pause, `GET /v1/sessions/<id>`, scheduler job `session_monitor`); off: answers and rows as before. See `docs/session-monitor.md` (also `SCHED_SESSION_S`, `SESSION_WINDOW_S`, `SESSION_K`, `SESSION_COOLDOWN_S`). Windows cmd: `set SESSION_MONITOR_ENABLED=1` |
| `CONSOLE_ASSURANCE_ENABLED` | `0` | WP17: the Assurance screen (`/console/assurance`, run list and per-pack results) and its nav entry; off: the paths answer 400 with a message. Windows cmd: `set CONSOLE_ASSURANCE_ENABLED=1` |
| `ASSURANCE_DATA_DIR` | (none) | WP17: bank-supplied datasets, one folder per pack: `<dir>\<pack_id>\`. Windows cmd: `set ASSURANCE_DATA_DIR=C:\supervisor\assurance-data` |
| `OSV_DB_PATH` | (none) | WP17: local OSV vulnerability dump for the `osv_offline` pack. Windows cmd: `set OSV_DB_PATH=C:\supervisor\osv\osv-db.json` |
| `ASSURANCE_LICENCE_ALLOW` | `MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,PSF-2.0,ISC,Unlicense,0BSD,MPL-2.0,MIT-0` | WP17: licences the dependency licence pack accepts (comma separated). Windows cmd: `set ASSURANCE_LICENCE_ALLOW=MIT,Apache-2.0` |
| `ASSURANCE_LAUNCH_ENABLED` | `0` | WP17: Onboard Launch runs the agent-target packs in its sandbox; a failed, errored or skipped pack with launch gate `required` makes Launch NO-GO and adds `assurance_report.md` and `.json` to the launch pack. Windows cmd: `set ASSURANCE_LAUNCH_ENABLED=1` |
| `ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH` | `0` | W3: Launch with assurance whose evaluated results are all mock is NO-GO (`assurance results are mock only`); `1` accepts it (still labelled MOCK). Any mock result labels the Launch reason and `assurance_report.md` MOCK. Windows cmd: `set ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH=1` |
| `ASSURANCE_JUDGE_GATE_ENABLED` | `1` | WP17: a non-mock judge (`JUDGE_ENABLED=1` with real models) starts only when every pack with `judge_gate` has a latest non-mock result `ok` (see `ASSURANCE_JUDGE_ALLOW_WARN`) with at least `ASSURANCE_JUDGE_MIN_ITEMS` items for `judge:<model id>` of each non-mock primary judge (tier 1 and tier 2) at the current pack version; else the judge sweep stays off and the log names the missing packs. Mock judges are exempt. Windows cmd: `set ASSURANCE_JUDGE_GATE_ENABLED=0` to switch the check off |
| `ASSURANCE_JUDGE_MIN_ITEMS` | `50` | W3: items a judge validation result needs (per pack, per non-mock primary judge) to count. Windows cmd: `set ASSURANCE_JUDGE_MIN_ITEMS=50` |
| `ASSURANCE_JUDGE_ALLOW_WARN` | `0` | W3: `1` lets a `warn` judge validation result count as validated; default only `ok` does. Windows cmd: `set ASSURANCE_JUDGE_ALLOW_WARN=1` |
| `CONSOLE_EXPORT_DIR` | `<DATA_DIR>\exports` | Audit packs. On the App this is ephemeral: download the zip at once. |
| `NOTIFY_WEBHOOK_ENABLED` | `0` | Webhook stub: queues notices (`status=queued`), never sends |
| `API_RBAC_ENABLED` | `0` | WP18: enforce the role matrix on the agent-facing `/gate` read routes (state, metrics). Gate control routes and console routes always enforce |
| `CONSOLE_AUDIT_ENABLED` | `1` | WP18/M4: write the `attempted` and outcome `console_action` rows for every mutating action (default on; `0` is refused unless `SUPERVISOR_MODE=dev`) |

Case intake as a job (only when the app is not running, single chain writer):
`python -m supervisor.jobs.case_intake`.
