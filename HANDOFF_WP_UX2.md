# HANDOFF WP-UX2: console page migrations

Branch `wp-ux2-pages` (from `wp-ux1-shell`, merged with the reviewer commits up to 7e55d89). Not pushed, not merged.
Spec: `/home/trung/supervisor-testbed/phase3/CONSOLE_DESIGN_SPEC.md` sections 2.3, 2.4, 3.3, 3.5, 4, 6.

## What was built

| Item | Result |
|---|---|
| Agent page | `GET /console/agents/{id}`, tabs Overview, Policy, Tools, Inventory, Traces, Cases, Assurance, Compliance. Each tab is an htmx partial at `/console/agents/{id}/tab/{name}`; `?tab=` gives the full page with the same body. Tools, Inventory, Assurance and Compliance show only when their flag is on and the role may read them; off = 400 with the flag name. Lifecycle controls (pause, two-person resume, quarantine, release) moved to Overview; the POST route, RBAC and the two audit rows are unchanged. The answer is the agent card plus an out-of-band swap of the header pills. Agents list: cards removed, row drawer links to the page (`agent_detail.py`, `_agent*.html`). |
| Alerts | `/console/alerts` (+ `/rows`, `/{id}/drawer`): state tiles, filter bar (severity, agent, rule), sortable paged table, row drawer (no-JS `?drawer=`). Acknowledge is the same audited `POST /console/alerts/{id}/ack`; its answer is the list and keeps the filters. Metrics keeps a tile (`id="alerts"`) that links here (`alerts_list.py`). |
| Sign-off list | `/console/signoff` (+ `/rows`, `/{case_id}/drawer`): cases waiting for a signature, signatures so far, SBV clock. The drawer holds the existing sign-off panel (audited POST unchanged). New `CaseService.waiting_approvals()` (reuses the reviewer's public `approvals()`); the sidebar badge uses it too. |
| Analytics | `/console/analytics` (+ `/tab/{name}`): tabs Gate, Tools, Oversight metrics, Latency; one toolbar (range 7/30/90 days or default, agent). Blank range = each tab's own window, so the old Metrics behaviour is kept. Tools tab = old Tools page (shared partial `_tools_agents.html`, bars in the calls cell, totals tiles). `/console/tools/{agent}/diff` unchanged (`analytics.py`). |
| Redirects (303) | `/console/metrics` -> `/console/analytics?tab=metrics`; `/console/tools` -> `/console/analytics?tab=tools` (`agent_id` read as `agent`). Query string kept (lang, filters, sort). Table in `docs/console.md` "Old URLs". Sidebar Alerts, Sign-off, Analytics link to the new pages; collapsed code `AN` for Analytics (reviewer's two-letter code scheme; `tools` and `metrics` codes removed). |
| Migrated onto components | Cases (filter bar, sortable paged table, row drawer, `_cases_table.html`), Inbox (filter bar, sort, pages), Inventory (sortable paged unmanaged table, agent picker), Evidence, Assurance, Compliance list, Health (crumbs and page header), Case page (crumbs, shared `ui.tabs`, same 5 tabs). |
| i18n, a11y, CSP | About 95 new keys EN and VI in a `# --- WP-UX2` block (`_T.update`, one existing hint text edited). `aria-sort`, `role=tablist`, skip link, `aria-live`; no inline script or handler; no external URL (tests assert it on every new page, both languages). |
| RBAC | New GET routes in `rbac.ROUTES` (`# --- WP-UX2 ---` block): `console.view` for agent, cases drawer, signoff; `metrics.view` for alerts and analytics; `inventory.view` for `/inventory/rows`. No new permission, matrix and docs table unchanged. |

## Commands

```
python -m pytest tests/console -q
python tools/console_screenshots.py --reseed --out <dir>   # now also seeds alerts, tool rollup, inventory; flags on
```
No new setting or flag.

## Tests

| | Count |
|---|---|
| Before (wp-ux1-shell at start, as in its handoff) | 3455 passed |
| After (full suite, merged with 7e55d89) | 3536 passed, 27 skipped; `ruff check` and `ruff format --check` clean |
| New | `test_agent_detail.py` (12), `test_redirects.py` (7), `test_alerts_page.py` (8), `test_signoff_list.py` (6), `test_analytics.py` (12), `test_lists_ux2.py` (12) |

Existing tests changed because a page moved (no assertion weakened):

| File | Change |
|---|---|
| `test_agents_screen.py` | card assertions read `/console/agents/<id>` instead of the list; added "list has no cards" |
| `test_console_pages.py` | list row marker `data-row`, not `data-agent` |
| `test_shell.py` | agent action answer: card + `id="agent-pills"` OOB, not the `#list` OOB; `console_tools_enabled` removed from the sidebar flag table (Tools is now a tab) |
| `test_alerts_panel.py` | list assertions use `/console/alerts` instead of `/console/metrics`; ack tests unchanged |
| `tests/analytics/test_console_api.py` | nav assertion: `/console/analytics?lang=` and `tab=tools` instead of `/console/tools?lang=` |
| not changed | `test_monitor_status`, `test_audit_two_rows`, `test_metrics_inbox`, tools tests: they follow the 303 to the new page |

## Screenshots

57 pairs (EN, VI, plus `-full`) in `/home/trung/supervisor-testbed/phase3/ux2-shots/`, port 8765: every agent tab, alerts (+ drawer), sign-off, analytics (4 tabs), cases drawer, inbox, inventory, dark overview. Checked by eye: agent overview, policy VI, sign-off, analytics tools, alerts, alerts drawer. The alerts table is tight when the drawer is open at 1360 px; the Tools table scrolls sideways inside its wrapper (as before).

## Not done (BACKLOG rows added)

- Case Story tab does not use the span tree (component exists from the reviewer; first user should be the WP-UX3 trace viewer).
- "Monitor status to Health" not done. Evidence, Assurance, Compliance have only the new header (no paging or sorting).
- Analytics range is a list, not a date picker; Gate tab scans at most 20 000 events; Latency is live counters only.
- No browser test of drawer or htmx focus; only server HTML and screenshots.
- The PNGs are not copied into `docs/design/screens/` (the spec asks for it after all WP; do it at integration).

## Notes for the integrator and owner

- Merge order: UX1, then UX2 or UX3 one at a time. My edits to shared files: `routes.py` (imports, queue, agent action, metrics and tools redirects, inbox and inventory rows, one block `# --- WP-UX2 ---` before `/home`), `i18n.py` (block before `translator`), `rbac.py` (labelled block), `nav.py`, `readmodels.py` (`signoff_waiting`), `cases/service.py`.
- WP-UX3: the agent Traces tab links to a trace viewer only if a route starting `/console/traces/` exists (`agent_detail.traces_page_exists`). Name your viewer route that way or change that function. If UX3 removes a `soon` placeholder, keep `nav.CODES` in step.
- Review points: `_policy` reads the private `readmodels._allowed_tools` (`noqa: SLF001`). The agent page rebuilds all agent cards (one `agent_event` query per agent); same cost note as the drawer in the UX1 review. Agent Traces tab maps trace to case through case links of that agent (bounded by 50 cases, 2000 events).
- Open question 1: should the Sign-off item count and list include cases with 0 signatures (now yes, same rule as the badge)?
- Open question 2: is a blank range meaning "each tab's own window" acceptable, or should the toolbar always carry a number?
- R1 to R3 not touched; no secret, network call, `exec` or 500 path found (bad input is `ListingError`, `AgentDetailError`, `AnalyticsInputError` = 400; tests cover it).

## Files touched

New: `console/{agent_detail,alerts_list,analytics,cases_list,inbox_list}.py`; templates `agent`, `alerts`, `analytics`, `signoff_list`, `_agent_pills`, `_agent_tab_{overview,policy,tools,inventory,traces,cases,assurance,compliance}`, `_alerts_list`, `_alert_drawer`, `_analytics_tab_{gate,tools,metrics,latency}`, `_tools_agents`, `_cases_table`, `_case_drawer`, `_signoff_rows`, `_signoff_drawer`, `_inventory_unmanaged` (all `.html`); six test files above; this file.
Removed: `tools.html`, `metrics.html`, `_alerts_panel.html`.
Changed: `routes.py`, `i18n.py`, `core/rbac.py`, `nav.py`, `readmodels.py`, `cases/service.py`, `assurance_views.py` (`agent_results`), `inventory_views.py` (`unmanaged_view`), templates `agents`, `_agent_drawer`, `queue`, `_queue_rows`, `case`, `_case_body`, `inbox`, `_inbox_rows`, `inventory`, `evidence`, `assurance`, `compliance`, `health`, `base`, `_c_header_top`, `static/console.css`, `tools/console_screenshots.py`, the five existing test files above, `docs/console.md`, `README.md`, `CHANGELOG.md`, `BACKLOG.md`.
