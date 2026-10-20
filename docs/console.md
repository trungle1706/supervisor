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

* Items for pages that do not exist yet (Gate decisions, Traces, Policies, Credentials, Users
  and roles, Audit log, Settings > Integrations) open a placeholder page ("coming in WP-UX3").
  They show only when `CONSOLE_NAV_PLACEHOLDERS=1`; with the flag off the link is hidden and
  `/console/soon/<page>` answers HTTP 400 with a message. WP-UX3 replaces each placeholder with
  its page and its own flag.
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

## Screens

| Screen | URL | What it shows | Actions |
|---|---|---|---|
| Search | `/console/search?q=` | Agents, cases and exact trace ids that match (WP-UX1). Read-only | - |
| Placeholders | `/console/soon/<page>` | "Coming in WP-UX3" for seven pages (WP-UX1, needs `CONSOLE_NAV_PLACEHOLDERS=1`) | - |
| Overview | `/console/` | Greeting by the ICT hour with the live counts (agents under supervision, actions stopped today, cases needing a decision, nearest SBV clock); what Supervisor is; the three pillars; four numbers from the stores (gate decisions today and median latency; stops split blocked / paused; open cases with the critical count; evidence chain entries, signed root, anchor, last verify); latest gate decisions (the newest stops always included) linked to their cases; the demo-data line on a demo store. | - |
| Agents | `/console/agents` | Sortable, paged table with state tiles and a filter bar (search, state, risk); a row opens a drawer (Overview, Policy, Cases; `?drawer=<id>&dtab=` without JS) that links to the agent page. | Open the agent page. |
| Agent | `/console/agents/<id>` (WP-UX2) | Header with state pill (rule or person), risk, Decision 33, mock label. Eight tabs, each an htmx partial at `/console/agents/<id>/tab/<name>` (`?tab=<name>` is the no-JS full page with the same body): **Overview** (the card: owner, risk, lifecycle stepper, coverage, the one action; gate last 24 h; evidence lane; open cases), **Policy** (rules in scope with version, action, severity, fail mode, regulation, approvers; policy hash; approved-tools allow-list with tool classes), **Tools** (WP22 table and least-privilege panel of this agent; `CONSOLE_TOOLS_ENABLED`), **Inventory** (WP24 subgraph tree and nodes; `INVENTORY_ENABLED`), **Traces** (newest 20 traces; links to the trace viewer when WP-UX3 has built `/console/traces/<id>`, else to the case transcript), **Cases**, **Assurance** (results whose target is this agent; `CONSOLE_ASSURANCE_ENABLED`), **Compliance** (matrix summary from the advisor read API; `CONSOLE_COMPLIANCE_ENABLED`). A tab whose flag is off is not shown and its URL answers 400 with the flag name. | Pause now, Approve resume (two people), Quarantine, Release: the same audited routes as before (`POST /console/agents/<id>/<action>`), moved here from the Agents list cards. |
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
1360x900 in English and Vietnamese to `docs/design/screens/`.

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
| `CONSOLE_NAV_PLACEHOLDERS` | `0` | WP-UX1: show the sidebar links of pages that WP-UX3 builds (Gate decisions, Traces, Policies, Credentials, Users and roles, Audit log, Integrations); they open a "coming in WP-UX3" page. Off: links hidden, `/console/soon/<page>` answers 400 |
| `CONSOLE_ONBOARD_ENABLED` | `0` | WP12: the Onboard screen may start runs (new feature, off by default) |
| `ONBOARD_COMPLIANCE_ENABLED` | `0` | WP14: the onboarding run also writes `compliance_matrix.json`, `.md` and `.html` (advisory only) |
| `CONSOLE_COMPLIANCE_ENABLED` | `0` | WP14: the Compliance tab (`/console/compliance`, read-only, advisory only) |
| `CONSOLE_INTEGRATION_ENABLED` | `0` | WP15: the Integration tab (reads reports from `INTEGRATION_REPORTS_DIR`, default `<data_dir>/integration`; off: no nav link, routes answer HTTP 400) |
| `ONBOARD_ADVISOR_ENABLED` | `0` | WP15: `supervisor.onboard` also writes `integration_report.*` and `integration_patch_NN_*.patch` (never applied) |
| `INVENTORY_ENABLED` | `0` | WP24: the Inventory screen (`/console/inventory`, nav entry with the unmanaged count), `/v1/inventory/{agent_id}` and `/v1/inventory/unmanaged`, the `inventory` scheduler job and the onboarding hook; off: the paths answer 400. See `docs/inventory.md` (also `SCHED_INVENTORY_S`, `INVENTORY_SCAN_SCHEMAS`, `INVENTORY_SELF_APP`, `INVENTORY_ALLOWLIST_FILE`, `INVENTORY_WORKSPACE_FIXTURE`). Windows cmd: `set INVENTORY_ENABLED=1` |
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
