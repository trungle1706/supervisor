# Console redundancy and clean-up audit

Audit only. No product code was changed. Base commit `a39cab591a7a441bf9ca10a8be609ab36a2a99dc` (branch `audit/ui`), console v0.11.0, 2026-10-30.

## 1. Scope and method

| Item | Value |
|---|---|
| App | local FastAPI app, port 8790, `SUPERVISOR_ENV_FILE=/dev/null`, fresh `DATA_DIR`, stopped after the run |
| Flags | the 61 `0/1` values of `guardian-v0.11.0-filled/app.yaml` (`SCHEDULER_ENABLED=0`) + `STORE_READ_CACHE=1`; sidebar shows "AI management / AI guardian" |
| Data | `bootstrap_schema`; `showcase portfolio --systems 300 --seed 1`; `showcase journeys --step 1`; `FACTORY_SEED_STARTERS=1` |
| User | `X-Dev-User: admin.chi` (admin) |
| Pages scanned | 82 distinct pages (every group, tab and sub-tab of `nav_v3.py`, plus system, agent, candidate, case, factory agent, compliance agent and obligation detail pages); 138 URLs in total with drawer variants; 1440 px light en for all, 1280 px dark vi for the top 11 pages |
| Automatic checks | page horizontal overflow, scroll boxes (`overflow:auto` with overflowing content), python-repr / debug patterns, identical text blocks, empty headings, ellipsis without `title`, empty panels, ids shown, vi text on en pages and en text on vi pages, console and network errors, all `href` on every page requested as admin |
| Evidence files | `/tmp/claude-1003/-home-trung/ead0ba4a-d0d8-47bf-8c2b-0ab56f5277bd/scratchpad/uiaudit/png/` (names below are relative to it) and `.../uiaudit/findings.json` |

Severity: **High** = misleading or broken. **Medium** = redundant or confusing. **Low** = polish. Estimate: S = under half a day, M = about 1 day, L = several days or a design decision.

Not in this config (page flags off, not audited, correct to hide): Risks, Controls, Tasks, Decisions, Traces, Transparency, Policies, Playground, Assurance, Users, Audit, Credentials, Integrations. Every link to one of them that is still shown is listed as a finding.

## 2. Summary

| Severity | Findings |
|---|---|
| High | 13 |
| Medium | 70 |
| Low | 22 |
| Total | 105 |

What is healthy: no page has horizontal page overflow at 1440 or 1280 px; no python repr or `None`/`NaN`/`undefined` in the UI (the only hit is the intended bilingual "Không có / None" in the case file); no console JS errors; only 4 pages have scroll boxes that are not intended (see UI-360); dark mode showed no unreadable text or lost borders on the 5 dark pages viewed in full (Home, Governance, System detail, Cases, Guardians).

### Top 10

| # | Id | Sev | Where | One line |
|---|---|---|---|---|
| 1 | UI-190 | High | Incidents | All 12 "Details" buttons end in "incident does not exist" (HTTP 400). |
| 2 | UI-001 | High | Home, Governance, Duties tab, MCP, Attach (also UI-091, UI-092) | "View all" and other links go to pages that are OFF in this config (Risks, Integrations), and Inventory links to an unregistered agent: HTTP 400. |
| 3 | UI-040 | High | Governance overview vs Home | Home says 21 overdue tasks; Governance says "Controls are off / Not measured". 5 of 9 blocks are empty. |
| 4 | UI-060 | High | System detail > Overview | Value column 1 to 3 characters wide: text breaks one word per line and inside words. |
| 5 | UI-061 | High | System detail > Risks, Controls | Tabs open a page with only a "not available" chip. |
| 6 | UI-062 | High | System detail > Duties, Tasks | 27 / 28 / 30 duties, badge 22, Tasks badge 1 vs 3 open. |
| 7 | UI-063 | High | System detail > Risk assessment | "No run yet" above a table full of Pass / In progress. |
| 8 | UI-110 | High | Compliance > Decision 33 | Limits table has a duplicated PAY-03 row and rows named by raw rule keys. |
| 9 | UI-184 | High | Case file | Placeholder "FILL-ME: Decision 33 classification ..." printed in an auditor document. |
| 10 | UI-300 | High | All pages | Sidebar tagline and 6 breadcrumbs still say Onboard / Watch / Act / Prove. |

Also High: UI-350 (counts that disagree across pages).

## 3. Broken links found by the link check

| Link | Result | Found on |
|---|---|---|
| `/console/risks` | 400 Risks page is off | /console/, /console/governance |
| `/console/risks?drawer=RSK-DUTY-...` | 400 Risks page is off | /console/systems/<id>?tab=duties (View risk) |
| `/console/integrations` | 400 Integrations page is off | /console/catalogues?tab=mcp |
| `/console/integrations?agent=<id>` | 400 Integrations page is off | /console/agents/<id>?tab=attach |
| `/console/agents/shw-app-<id>?tab=inventory` | 400 agent is not registered | /console/inventory (Nodes) |
| `/console/incidents/<id>/drawer and ?drawer=<id>` | 400 incident does not exist (12 of 12) | /console/incidents |

## 4. Findings per page

Each table: id, severity, finding, evidence (screenshot file and selector), fix (template, CSS or view), estimate, batch (section 7).

### My overview / Home (`/console/`)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-001 | High | The "View all" links (3 on this page, one is "View all 21" on Risk assessments past review date) go to `/console/risks`, a page that is OFF in the deployed config. Click gives HTTP 400 "The Risks page is off". Governance overview has the same link. | 1440__console.png · `section.u5-panel > div.g1-ph > a` ("View all 21"), `section.u5-attn` link · link check | Hide or re-point the link when the Risks page flag is off. `_ov4_portfolio.html`, `ov_my_v4_ux5.html`; flag test from `ux3.py` pages map. | S | 1 |
| UI-002 | Medium | Three different overdue numbers on one page: banner says "9 more items are open / All 10", KPI says "21 Tasks overdue", table says "Risk assessments past their review date, View all 21". Different definitions, no label that explains it. | 1440__console.png · `section.u5-attn.g1-attn`, `section.u5-strip.g1-strip`, `section.u5-panel > div.g1-ph` | Use one definition per number and link each number to the list that holds it. `overview_v4.py`, `_ov4.html`. | M | 1 |
| UI-003 | Medium | Same facts repeated: "10 open cases" appears as a chip, as a KPI tile and as the sidebar badge; "0 items wait for you" chip repeats the sidebar badge "0" on My overview. | 1440__console.png · `div.g1-facts > a.u5-chip`, `section.u5-strip.g1-strip`, sidebar `aside .k` | Drop the chip row (keep the KPI strip). Hide a badge when its value is 0. `ov_my_v4_ux5.html`, `_c_sidebar_v3.html`. | S | 2 |
| UI-004 | Medium | Risk-assessment table at 1280 px (vi): the 8 dimension columns do not fit, the last column (Reputation) is cut by an inner scroll box (`scrollWidth 1009 > clientWidth 910`). Cell text "Not applicable" is the widest cell in the table. | 1280dark_vi__console.png · `section.u5-panel > div.g1-scroll > table.g1-grid` | CSS only: let the first column shrink and let the status cells use a narrow icon style under 1400 px. `ux5_g1.css`. | M | 4 |
| UI-005 | Medium | vi: the Attention banner shows the task title in English ("Confirm human supervision for the Decision 33 high-risk class before enforcement") inside a Vietnamese sentence. | 1280dark_vi__console.png · `section.u5-attn.g1-attn .g1-attn-main b` | Translate task titles by task code (DEP-D33 ...) in the view model. `overview_v4.py`, `i18n_ux5_g1.py`. | M | 3 |
| UI-006 | Low | "300" systems is shown 4 times in the first screen (subtitle, KPI, Autonomy header, "x / 300" rows). Four bar-list styles (ticks, bars with fraction, dot list, plain bar) for the same kind of data. | 1440__console.png · `.u5-panel` | Keep one bar-list component. `_ui.html` `barcell`, `ux5.css`. | S | 4 |

### My agents (`/console/my/agents`)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-010 | Medium | Agent cell repeats the name three ways: bold name (with the suffix " agent"), then the id, then the full name again in monospace. Rows wrap to 3-4 lines. | 1440__my_agents.png · `table.my-agents-tbl tbody#rows td .idline` | Show name once, id once. `_my_agents_list.html`, `my_agents.py` (drop the " agent" suffix). | S | 2 |
| UI-011 | Medium | Near-duplicate of Catalogues > Agents (`/console/agents`): same registry, same columns (Agent, Gate state, risk, Cases), different totals (192 / 150 running here, 152 / 147 on Home and Agents). The 3 "Known to gate only" agents and 37 candidates explain the gap but nothing on screen says so. | 1440__my_agents.png, 1440__agents.png | Make one Agents page with a Mine/Team/All scope and a Registered/Candidates filter; remove the second nav entry. `my_agents.py`, `agents_list.py`, `nav_v3.py`. | L | 2 |
| UI-012 | Medium | Guardian tools cell says "4 of 14 on" and a chip "full" (two ways to say one thing). "Last activity" is "-" in all rows. "Recommended action" shows a raw rule key ("Turn on injection_regex"). Kind chip "Registered" is on every row (no information). | 1440__my_agents.png · `table.my-agents-tbl tbody#rows tr.row > td > span.mono` (4 of 14 on), `td.wrap > a` (action) | One indicator; hide an all-empty column; map rule key to guardian name; show Kind chip only for the exception. `_my_agents_list.html`. | S | 2 |
| UI-013 | Medium | At 1280 px the table is wider than its box (`1336 > 950`), so a stray horizontal scroll bar appears inside the page. | 1280dark_vi__my_agents.png · `div#list > div.tablewrap > table.agents-tbl` | CSS only: hide the two least useful columns below 1400 px (`Last activity`, `Cases`) and wrap the action text. `ux5_g1.css`. | S | 4 |
| UI-014 | Low | Lowercase headers and filters ("risk", "risk: All") next to Title Case ("Agent", "Kind: All"). Gate state is UPPERCASE in a chip, risk is lowercase in a chip. | 1440__my_agents.png · `th`, `.fbar select` | Pick one case rule in i18n labels and in `ui.state_pill`. `i18n*.py`, `_ui.html`. | S | 3 |

### Candidates (`/console/candidates`) and its drawer

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-020 | Medium | Signal chip "no owner" is on 43 of 43 rows, "customer table" on most. Chips repeat in every row and hide the one chip that differs. | 1440__candidates.png · `table.cand-tbl tbody tr.row > td` (Signals column) | Show shared signals once in a header line; show only exceptions per row. `_cand_rows_ux5.html`. | S | 2 |
| UI-021 | Medium | Three button labels in one column ("Register", "Register and classify", "Register when convenient") with three widths. The drawer repeats it a third time ("Register now" + Register button). | 1440__candidates.png · `table.cand-tbl td > a.btn.sm`; 1440__candidates_drawer_inv_0d33cdf0bc7aeebb.png | One label "Register"; put the recommendation in a hint. `_cand_rows_ux5.html`, `_cand_drawer.html`. | S | 2 |
| UI-022 | Medium | Same 43 objects as Catalogues > Inventory > "Unmanaged items 43". Two lists, two names (Candidates / Unmanaged), two kind spellings ("Genie space" vs `genie_space`). | 1440__candidates.png, 1440__inventory.png | Keep Candidates; make Inventory show registered nodes only and link to Candidates. `inventory_views.py`, `_inventory_unmanaged.html`, `nav_v3.py` (tab `unmanaged`). | M | 2 |
| UI-023 | Medium | Drawer: Source and Attach tables are wider than the 401 px drawer (`584`, `640`, `440` px), so 3 nested horizontal scroll bars appear and cells are cut ("payme", SHA-256 column). | 1440__candidates_drawer_inv_0d33cdf0bc7aeebb.png · `#intake-panel .tablewrap.flat`, `#attach-panel .at-wrap` | CSS only: inside `#drawer` make `.tablewrap.flat table` display as stacked rows (`display:block` per `tr`). `ux5_g4.css`. | M | 4 |
| UI-024 | Low | Drawer repeats data: kind and name in the summary sentence and chips; score in a chip and in the key/value list; dev button "Copy JSON" is visible to every user. | 1440__candidates_drawer_inv_0d33cdf0bc7aeebb.png · `aside#drawer` | Remove the summary sentence; hide Copy JSON outside dev. `_cand_drawer.html`, `_c_drawer.html`. | S | 2 |

### Inbox (`/console/inbox`)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-030 | Low | Only reachable through the envelope icon in the top bar; always empty in this data. Overlaps with Cases & alerts. Table with 4 headers shown for "No notices". | 1440__inbox.png · `div.tablewrap > table > tbody > tr > td.empty` | Hide the table when empty or fold Inbox into the Cases & alerts tab strip. `inbox.html`, `_inbox_rows.html`. | S | 2 |

### Governance overview (`/console/governance`)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-040 | High | Contradicts Home: Home shows "21 Tasks overdue" and a risk-assessment table; this page shows "Overdue tasks - Controls are off" and "Not measured" and the KPI list says "Overdue tasks: not available". Same product, same data, opposite message. | 1440__governance.png · `div#numbers > div.g1-tile > b.g1-nm` (tile 4), `section.card > h2.sec` (Governance KPIs); 1440__console.png · KPI 5 | Read both from the same task source, or remove the tile when the Controls flag is off. `overview_v3.py`, `ov_governance.html`, `_ov_gov_kpis.html`. | M | 1 |
| UI-041 | Medium | 5 of 9 blocks are empty or switched off in the deployed config: 2 "Not measured" tiles, "Risk posture", "Control readiness by system" (with a "View all" that leads to a page that is off), "Policy implementation by system". | 1440__governance.png · `.u5-panel` | Do not render a block whose feature flag is off. `ov_governance.html`, `ov_gov_systems_ux5.html`. | M | 1 |
| UI-042 | Medium | Raw debug text for users: flag names "(RISK_REGISTER_ENABLED)", "(CONTROLS_ENABLED)"; "The same figures as GET /v1/kpis and the MCP tool kpis"; enum dumps "agent: 152 · dataset: 28 · genie_space: 8 · ..."; "not available The risk register is off" with no separator. | 1440__governance.png · `section.card table.list tbody tr td` | Remove flag names and API text from the page; render enum labels; add separator. `i18n.py` (line ~4247), `_ov_gov_kpis.html`. | S | 3 |
| UI-043 | Medium | Duplicate figures: "Systems by stage" table and KPI row "Systems by stage"; "Classification rate 90%" tile and KPI row; "Systems in scope 300" tile and subtitle "Showing 300 of 300"; risk levels again on Home. | 1440__governance.png · `div.g1-two > section.u5-panel`, `section.card table.list` | Keep the KPI list as a collapsed "all figures" block or delete the repeated rows. `_ov_gov_kpis.html`. | S | 2 |
| UI-044 | Low | Stage table: columns "Pending approval" and "Open required tasks" are "-" in 12 of 14 cells. | 1440__governance.png · `div.g1-two > section.u5-panel table` | Show the columns only when any row has a value. | S | 2 |

### Systems list (`/console/systems`)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-050 | Medium | KPI tiles ("300 All systems", "284 Active", "46 High risk or more") are filters and also stats, and the Status and Risk selects under them filter the same fields. | 1440__systems.png · `.tiles`, `.fbar` | Keep tiles as stats (non-clickable) or remove them. `systems.html`, `_systems_list.html`. | S | 2 |
| UI-051 | Low | "from parts" sits next to the risk chip with no explanation. Owner team values already end with "team" under a column named "Owner team". | 1440__systems.png · `table.systems-tbl tbody#rows td > span.muted` | Add tooltip "inherited from components"; trim suffix in the label. `_systems_list.html`. | S | 3 |
| UI-052 | Medium | Four labels "Systems" on the first screen (strip title, tab, h1, sidebar) and 5 entry points to register something (+Register, My drafts, Onboard tab, Agents > Onboard, Candidates > Register). | 1440__systems.png · `.sec-tabs-t`, `h1` | See cross-page sections B and C. | M | 2 |

### System detail (`/console/systems/<id>`, 13 tabs)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-060 | High | Overview: the three cards are 330 px wide with a 150 px label column, so values break one word per line ("Chooses / the / contact / ...") and mid-word ("Deployme/nt", "bizowner.c/ontact-", "classificati/on"). At 1280 px vi the value column is 1 to 3 characters wide. | 1440__systems_shw_sys_0081_tab_overview.png; 1280dark_vi__systems_shw_sys_0081_tab_overview.png · `div#tab-body > div.g2-cols > section.card > dl.u5-kv` | `.u5-kv` uses `minmax(120px,220px) 1fr` with `overflow-wrap:anywhere` on dd (`ux5.css:125-126`) inside cards of about 330 px (`.g2-cols` minmax(300px,1fr), `ux5_g2.css:77`). Stack dt over dd below 420 px, use `overflow-wrap:break-word`, raise the `.g2-cols` minimum to 420 px. | S | 4 |
| UI-061 | High | Tabs "Risks" and "Controls" open a page that shows only a grey chip "not available". Their flags are off in the deployed config, but the tabs are still in the strip. | 1440__systems_shw_sys_0081_tab_risks.png, ..._tab_controls.png · `div#tab-body > p.hint.nv3-na > span.u5-chip.na` | Do not add a tab whose feature flag is off. `systems_tabs.py`. | S | 1 |
| UI-062 | High | Duty counts do not add up: "18% of 27 duties closed", Open 22 + Closed 5 + Waived 1 = 28, "All 30", tab badge "Duties 22"; Tasks tab badge says "1" while the page lists 2 open + 1 in progress. | 1440__systems_shw_sys_0081_tab_duties.png · `section.u5-strip.g2-score`, filter chip row under it; ..._tab_tasks.png · tab `.k` | Define the badge as open duties/tasks and say what "All" contains (add "incl. needs answer"). `systems_duties.py`, `systems_tabs.py`, `_system_duties_ux5.html`. | M | 1 |
| UI-063 | High | Risk assessment says "No run yet." while the table below shows Pass / In progress / Not applicable for every dimension and the chips say "Pass 5". | 1440__systems_shw_sys_0081_tab_riskdim.png · `div#orch-panel > div.g2-run > span.muted`, `p.g2-counts > span.u5-chip` | Show "No run yet" only when no status exists; else show the date of the last change. `systems_riskdim.py`, `_system_riskdim_ux5.html`. | S | 1 |
| UI-064 | Medium | Header chips (Active, High, Deployment, Duties closed 18%) are repeated inside the Overview cards (Stage, Status, Risk level) and in the Duties KPI; owner team and owner appear in the subtitle, the Identity card and the Team table. Risk level reads "High (set by a person: High; inherited: High)" (one value three times) and "[demo:showcase] Set from the approved classification" leaks a seed tag. | 1440__systems_shw_sys_0081_tab_overview.png · `header.g2-syshead .u5-title span.u5-chip`, `div.g2-cols dl.u5-kv` | Remove Stage, Status and Owner team from Identity; one risk value with a source tooltip. `_system_facts_ux5.html`. | S | 2 |
| UI-065 | Medium | Duties: KPI strip (22 / 5 / 1 / 2) and filter chips (Open 22, Closed 5, Waived 1, Needs answer 2) repeat the same numbers; a bulk bar "Waive selected / Close selected" plus a per-row "Actions" menu plus "Re-evaluate" and "Refresh evidence" repeat actions; "0 rows" chip on every duty. | 1440__systems_shw_sys_0081_tab_duties.png · `section.u5-strip.g2-score`, `table.g2-duties td.g2-c-ev span.g2-ev` | Merge KPI and chips; hide "0 rows"; keep bulk bar only when something is selected. `_system_duties_ux5.html`. | M | 2 |
| UI-066 | Medium | Rules and Guardians tabs overlap (guardian floor, assignments, "Run the rules now" vs "Propose guardians"). Rules shows raw keys `dlp_vn`, `injection_regex`, `AR-D33-HIGH`, "Matched on: decision33_class, autonomy_level" and the plural bug "2 guardian feature". The floor list appears twice (floor table and "Assigned by rules"). | 1440__systems_shw_sys_0081_tab_rules.png, ..._tab_guardians.png · `div#tab-body table > tbody > tr > td > code` | Merge the two tabs or link Rules to Guardians; map keys to catalogue names; fix plural. `_system_rules_ux5.html`, `_system_guardians_ux5.html`, `i18n_ux5_g2.py`. | M | 2 |
| UI-067 | Medium | Obligations: two stacked empty states ("not available" chip, then "No agent is linked to this system yet. Link an agent"). Reports: only the same "No agent is linked" text and "Incidents: No incidents"; no report anywhere on the tab. The "Link an agent" button is on both tabs. The "Advisory only" chip is blue here and grey ("Advisory, not legal advice") on Classification and Guardians. | 1440__systems_shw_sys_0081_tab_policies.png, ..._tab_reports.png | Show one empty state per tab; rename Reports or fill it; one disclaimer component. `_system_policies.html`, `_system_reports.html`, `_ui.html`. | S | 2 |
| UI-068 | Medium | Components: the table is followed by an unlabeled list "Risk level taken from" that repeats 3 of the 4 rows; the table lists the system itself ("Collections Strategy Selector - Pilot, Inventory item") as its own component. | 1440__systems_shw_sys_0081_tab_components.png · `div#tab-body > h3.sec` ("Risk level taken from") | Fold the risk level into a column; drop the self row. `_system_components_ux5.html`. | S | 2 |
| UI-069 | Low | Tasks: "Required" chip "required" on all 21 rows; "Move" button is full width; task codes in monospace under each title. Reviews: one sentence, no action ("Reviews start at the Validation stage") while the system is in Deployment. | 1440__systems_shw_sys_0081_tab_tasks.png, ..._tab_reviews.png | Show "Required" only for the exceptions; hide Reviews until Validation. `_system_tasks_ux5.html`, `_system_reviews.html`, `systems_tabs.py`. | S | 2 |
| UI-070 | Low | "Regulator pack" button sits on the right for a short name and wraps below the title for a long name; the 13-tab strip wraps to a second row at 1280 px vi; the Overview tab has no group label. | 1440__systems_shw_sys_0241.png · `header.g2-syshead .u5-title`; 1280dark_vi__systems_shw_sys_0081_tab_overview.png · `.g2-tg` | Make the header a 2-column grid with `min-width:0` on the title; allow the strip to scroll. `ux5_g2.css`. | S | 4 |

### Onboard, Integration, Register (Systems strip)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-080 | Medium | Onboard: tab leads to a page whose Discover button is greyed out (flag `CONSOLE_ONBOARD_ENABLED` is off) and the help text prints the env var and a Windows command line. A dead page in the nav. | 1440__onboard.png · `div#onboard-status section.card form.startrow button.btn.primary` | Hide the tab when the flag is off. `nav_v3.py` (tab `onboard`), `onboard.html`. | S | 2 |
| UI-081 | Medium | Integration advice: empty page, "Ask an administrator to run the advisor" shown to an administrator, no action, and the text says "agents to bring under Watch" (old name). | 1440__integration.png | Show the button for admins; fix the wording. `integration.html`, `i18n_ux5_g1.py`. | S | 3 |
| UI-082 | Low | Register list: h1 "My registration drafts" under breadcrumb "Register an AI system". Register new: "This starts a registration draft for the agent credit_prequal" prints the id, the name is "Loan pre-qualification agent". | 1440__register.png, 1440__register_new_agent_credit_prequal.png | Use the agent name. `register_list.html`, `register_new.html`. | S | 3 |

### Catalogues: Agents, Models, Tools, Datasets, MCP servers, Inventory

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-090 | Medium | Models, Tools and Datasets are three tables with the same shape (Name / Status / Last seen). Models lists every model twice ("x" and "x-endpoint"). "Last seen" is the same timestamp in every row. Two pager lines ("Page 1 of 3" and "25 of 52 shown"). | 1440__catalogues_tab_models.png, ..._tab_tools.png, ..._tab_datasets.png · `div.tablewrap > table.list`, `div.u5-foot > span` ("25 of 52 shown") | One Assets page with a Kind filter; show Last seen only when it differs; one pager line. `cat_assets_ux5.html`, `tools_views.py`. | M | 2 |
| UI-091 | High | MCP servers: empty-state link "Integrations" goes to `/console/integrations`, which is OFF (HTTP 400). Agent > Attach has the same link. | 1440__catalogues_tab_mcp.png · `a[href^='/console/integrations']`; link check | Hide link when the page flag is off. `cat_assets_ux5.html`, `_agent_tab_attach_ux5.html`. | S | 1 |
| UI-092 | High | Inventory > Nodes: the Agent selector is prefilled with `shw-app-shw_sys_0001` and "Open the agent page" ends in HTTP 400 "agent shw-app-shw_sys_0001 is not registered". The select lists internal node ids, not agent names. | 1440__inventory.png · `div#inventory-body > form.filters.fbar > select` and `a.chipbtn`; link check | List registered agents by name only; disable the button for others. `inventory_views.py`, `inventory.html`. | S | 1 |
| UI-093 | Medium | Inventory: "Unmanaged items 43" duplicates Candidates; kinds shown raw (`genie_space`, `model_endpoint`); "Case" column "-" in all rows; three names for one page (strip "Inventory", nav key "Unmanaged", block "Unmanaged items"). | 1440__inventory.png | See UI-022. | M | 2 |
| UI-094 | Medium | Catalogues > Agents: " agent" is appended to every name, the id is on a second line, Coverage is "-" in all rows, header "risk" is lowercase; `/console/catalogues` renders the same page as `/console/agents`. | 1440__agents.png, 1440__catalogues.png (same 2140 px page) | Remove suffix; hide empty column; make `/console/catalogues` redirect to the first tab. `agents_list.py`, `_agents_table.html`. | S | 2 |

### Agent detail (`/console/agents/<id>`, 11 tabs)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-100 | Medium | State is repeated three times: header chips (SHADOW, risk: high, Decision 33 high-risk), Overview card (id again, "SHADOW · shadow", Owner, "risk: high", "Decision 33 high-risk") and Register tab (Registry row + AI system card, "risk" twice). | 1440__agents_shw_ag_0031.png, 1440__agents_shw_ag_0031_tab_register.png | Keep header chips; delete the status line and one of the two Register cards. `_agent_tab_overview_ux5.html`, `_agent_tab_register_ux5.html`. | S | 2 |
| UI-101 | Medium | "Move to RUNNING" form (Overview) and "Recommended action: Move to Running" button (Register tab) do the same thing; RUNNING vs Running spelling. Footer line "Audit trail: 0 entries · not verified yet · Evidence · Register" links to tabs that are in the strip. | 1440__agents_shw_ag_0031.png · `section.mode-panel > h5` ("Move to RUNNING"), `div.g4-stack > p.g4-line` (Audit trail) | One action location; delete footer links. `_agent_tab_overview_ux5.html`. | S | 2 |
| UI-102 | Medium | Overview has a vertical rule and an empty right half (dead space beside the Pause / Move forms). | 1440__agents_shw_ag_0031.png · `div#agents-table > article.card.agent.g4 > div.side` | Remove the empty column or use it for the gate KPIs. `_agent_tab_overview_ux5.html`, `ux5_g4.css`. | S | 2 |
| UI-103 | Medium | Guardians tab: raw feature keys (`dlp_vn`, `guard_model`, `injection_regex`) where the catalogue has names; "Switched off by the platform team" 4x and "Not enabled in this environment" 6x; a 630 px inner scroll box with its own scroll bar (`.g4-scroll`, `max-height:70vh`) inside a page that scrolls; "Results (all zero): show" and an empty "Cases" heading. | 1440__agents_shw_ag_0173_tab_guardians.png · `div.g4-stack > section > div.tablewrap.flat.g4-scroll` | CSS part (batch 4): remove `max-height` from `.g4-scroll` (`ux5_g4.css:48`). Template part (batch 2): show the reason once as a legend, hide zero blocks, map keys to names in batch 3. `_agent_tab_guardians_ux5.html`. | M | 4 |
| UI-104 | Medium | Source, Facts, Pre-deploy, Attach, Post-deploy tabs are shown for a registered agent that was never onboarded. They show "Source 0", "Facts 0", "Timeline 0", "Agent log 0" with "No ... yet" under each; Source has two upload buttons ("Upload zip" and "Take in"); Post-deploy shows "Gate mode: SHADOW" a third time. | 1440__agents_shw_ag_0031_tab_source.png, ..._tab_facts.png, ..._tab_postdeploy.png | Group these under one "Onboarding" tab or hide until a source exists; drop zero counts. `agent_detail.py`, `_agent_tab_source.html`, `_agent_tab_facts.html`, `_agent_tab_postdeploy.html`. | M | 2 |
| UI-105 | Medium | Compliance tab empty state: the button is labelled "Compliance" (same as the tab) under "Build one with the advisor command". Policy tab: count "Rules in scope 0" plus two statements that say the same ("No rules apply...", "No deployed rule names this agent"); Approved tools 0 plus "No approved tools listed". | 1440__agents_shw_ag_0031_tab_compliance.png, ..._tab_policy.png | Name the button for the action ("Open compliance advisor"); show count or sentence, not both. `_agent_tab_compliance.html`, `_agent_tab_policy.html`. | S | 2 |
| UI-106 | Low | Attach tab says "Attach 0/16" and "Guardian list (16)"; Guardians tab says 15 features. Cases tab has an "Agent" column on a single-agent page; "More" menu holds 5 tabs. | 1440__agents_shw_ag_0031_tab_attach.png, ..._tab_cases.png | Use one feature count. `agent_guardians.py`, `_agent_tab_cases.html`. | S | 2 |

### Risks & controls: Compliance (list, agent, D33, all duties, obligation)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-110 | High | Limits table on the Decision 33 tab lists "PAY-03 daily total 150,000,000 VND" twice (rows 2 and 4, identical) and two rows named by raw rule keys ("daily transfer max minor · daily total", "transfer max minor · single transfer"). | 1440__compliance_payments_tab_d33.png · `section.card table` under `div.g3-ph > h3` "Limits above the legal cap" | Dedupe by (rule, limit) and map keys to PAY-xx labels. `compliance_view.py`, `compliance_agent_ux5.html`. | M | 1 |
| UI-111 | Medium | `/console/compliance` and `/console/risks-controls` are the same page. Four names: strip "Risks & controls", tab "Compliance", h1 "Compliance advisor", gear key "Policies". The section named "Risks & controls" holds no risks and no controls in this config. | 1440__risks_controls.png, 1440__compliance.png (identical) | Rename the label (`nv3_risks_controls`) in i18n; the redirect is UI-310. `i18n.py`, `i18n_ux5_g4.py`. | S | 3 |
| UI-112 | Medium | Agent row text "479 duties apply · 139 need an answer · 6 open questions · 1 limit gap" repeats the Gaps and Questions columns and the caption under the bar ("Gap 40 · Partial 377 ..."); "+419 more" next to the bar has no explanation; chip "demo" on each agent. | 1440__compliance.png · `table.g3-tbl td > div.hint`, `span.u5-ticks > span.more` | Keep one summary line. `compliance_ux5.html`. | S | 2 |
| UI-113 | Medium | Agent Summary: tile "479 Duties apply" and the sentence under it say the same; the Decision 33 card is shown again, expanded, on the D33 tab; per-question counts (90+86+23+18+15+7 = 239) exceed "139 duties blocked" without a note; tab says "All duties, 618" next to 479. | 1440__compliance_payments_tab_summary.png, ..._tab_d33.png | Remove the duplicate card from Summary (link to tab); note overlap. `compliance_agent_ux5.html`. | M | 2 |
| UI-114 | Medium | Control text "Missing: groundedness (not switched on), fairness (not switched on), fairness slice (not switched on)": the suffix is repeated up to 4 times per row and near-duplicate names appear (fairness / fairness slice / fairness slices). All-duties tab renders 618 rows at once (9301 px page). | 1440__compliance_payments_tab_summary.png, ..._tab_all.png · `section.card > table.g3-tbl > tbody > tr > td` | State "not switched on" once per row; dedupe names; paginate by instrument. `compliance_view.py`, `compliance_agent_ux5.html`. | M | 2 |
| UI-115 | Low | Disclaimer chip is cut ("Advisory only. Not legal ...", "Not legal advice. Bank co..."), with three wordings across pages; breadcrumb on obligation page is the raw id "payments"; obligation page says "This product" (agent elsewhere) and kinds in two cases ("catalogue", "Bank process"). | 1440__compliance.png, 1440__compliance_payments_obligation_INTL_ATLAS_T0070_01.png · disclaimer chip in the page header | One short disclaimer with a tooltip; use agent name. `_compliance_note.html`, `compliance_obligation_ux5.html`. | S | 3 |
| UI-116 | Low | Obligation "Text (Vietnamese)" block says "No Vietnamese text stored for this duty" before the English summary. | 1440__compliance_payments_obligation_INTL_ATLAS_T0070_01.png | Hide the block when empty. `compliance_obligation_ux5.html`. | S | 2 |

### Risks & controls: Internal documents, Regulation watch, Law changes

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-120 | Medium | Regulation watch: three headings with a count and an empty sentence each ("Runs 0 / No run yet", "Watch reports 0 / No report yet", "Imported packages 0 / No package imported yet"); text prints `POST /v1/regkb/import`; breadcrumb "Regulations /" is hard-coded English and not a nav item; disclaimer is a bullet line here and a chip on the other two tabs. | 1440__regkb_watch.png | One empty state for the whole page; remove API text; use the shared crumb and chip. `regkb_watch.html`. | S | 2 |
| UI-121 | Low | Internal documents: a red "Upload a document" heading button and a second red "Upload" submit button; Title / Owner group / Version label inputs have no width and sit in one loose row. Law changes: empty-state paragraph only. | 1440__regkb_internal.png, 1440__regkb_changes.png | One button; grid the form. `regkb_internal.html`, `_regkb_internal_panel.html`. | S | 2 |

### Factory (Agent factory list and editor)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-130 | Medium | "The eight dimensions" cards say "No agent yet" and, one line below, "1 agents" (contradiction and plural bug). The 8 cards wrap 7 + 1 (orphan "Reputation"). | 1440__factory.png · `section.card > div.portfolio-strip > div.card.flat > span.u5-chip.na` | Count live agents separately from drafts; use plural rule; grid `repeat(4,1fr)`. `factory_view.py`, `factory.html`. | S | 2 |
| UI-131 | Medium | Kicker "Agent factory" above h1 "Agent factory"; Agent column shows the owner group in monospace under the name (a second "dimension" column); "(starter)" vs "(TEMPLATE)" suffixes; "New agent from a template" is both heading and summary; filters use lowercase "all" and a Filter button. | 1440__factory.png | Drop kicker; one suffix rule; auto-apply filters. `factory.html`, `_factory_ui.html`. | S | 2 |
| UI-132 | Medium | Editor: Dimension and Owner group (both "Model risk") are shown in the header strip and again in the Template card; "Reason + Retire" is a destructive action with no heading; breadcrumb shows the slug `model-risk-assessor`; step bar mixes check icons with numbers ("10", "8"). | 1440__factory_model_risk_assessor.png | Remove duplicates; add a "Retire" heading; show the name in the crumb. `factory_editor.html`, `_factory_step_template.html`. | S | 2 |

### Workflows (`/console/workflows`)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-140 | Medium | "Scheduled jobs" table has one pseudo row ("Scheduler not running in this process, so job state is not available", chip off, two "-"). Status words "on / off" in lowercase here, "On / Off" on Guardians, "On · mock" elsewhere. | 1440__workflows.png · `.u5-panel table` | Replace the table with a single notice. `workflows.html`. | S | 2 |
| UI-141 | Low | No info icon or "About this page" (most list pages have one). | 1440__workflows.png | Add `ui.purpose`. `workflows.html`. | S | 2 |

### Supervisor overview (`/console/supervisor`)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-150 | Medium | Evidence strip repeats itself: chip "not verified yet" + sentence "Evidence chain not verified yet for 152 agents" + Verify button. The same Verify action is on Analytics > Oversight metrics, Evidence and Case detail. | 1440__supervisor.png · `div.g1 > div.g1-banner > span.u5-chip.warn` (strip); 1440__analytics_tab_metrics.png; 1440__evidence.png; 1440__cases_shw_case_001.png | One Verify location (Evidence). Others show the status only. `ov_supervisor_ux5.html`, `_verify_result.html`. | S | 2 |
| UI-151 | Medium | "Agents with stops or gaps" shows "No agent has stops or coverage gaps" and, on the next line, "152 agents with no blocks and full coverage (not listed)"; KPI "Guardian coverage 152/152" repeats Home; "Stopped by a rule · 0 blocked · 0 paused" prints three zeros in a tile; "Alerts fired 7 d" heading plus "No alert fired in 7 days". | 1440__supervisor.png | One sentence per block; no zero-chain tiles. `ov_supervisor_ux5.html`. | S | 2 |
| UI-152 | Low | "Judges and packs": chips for "On" and "mock", plain text for "no run yet" and "off" in the same column. Page is named "Supervisor overview" but nav says AI guardian > Overview. | 1440__supervisor.png | Use `state_pill` for all rows; rename h1. `ov_supervisor_ux5.html`. | S | 3 |

### Guardians (Library, Detectors, Judges, Monitors)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-160 | Medium | Detectors, Judges and Monitors tabs are the same page as Library with one category pre-selected; h1 stays "Guardian catalog" and a second chip row (All 27 / Gateway controls 5 / Detectors 6 / ...) repeats the tab strip. `/console/guardians` and `/console/catalog` are the same page. | 1440__guardians.png, 1440__catalog.png, 1440__guardians_tab_detectors.png | Keep either the tabs or the category chips. `nav_v3.py` (tabs `detectors\|judges\|monitors`), `guardians_view.py`, `_catalog_ux5.html`. | M | 2 |
| UI-161 | Medium | "Off. Ask the platform team to turn it on." is printed 17 times, next to an "Off" chip. | 1440__guardians.png · `section.g5-panel div.g5-row.off p.g5-sub` | Print once in the page header. `_catalog_ux5.html`, `i18n_ux5_g5.py:107`. | S | 2 |
| UI-162 | Low | "10 of 27 on" chip next to "On 10 / Off 17" filter chips; "Open" button on 10 of 27 rows only; "Show for system" input + "Show switches" button. | 1440__guardians.png | Remove the chip; add "Open" to every row or none. | S | 2 |

### Guardian factory (list and New guardian)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-170 | Medium | "All 0" chip, three filters and a header row above "No guardian definitions match." (nothing exists, nothing to match). No tab strip. | 1440__guardian_factory.png | Empty state with one "New guardian" button. `_gf_list_ux5.html`. | S | 2 |
| UI-171 | Medium | New guardian: dropdowns show raw values (`model_risk`, `regex`, `input`); two draft buttons ("Draft the artifact", "Create draft"); "Agents (comma list or *)" fields. | 1440__guardian_factory_new.png | Use labels from i18n; one primary action. `_gf_editor_ux5.html`, `i18n_guardian_factory.py`. | S | 3 |

### Cases (list, drawer, detail, case file)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-180 | Medium | List: Agent column shows raw ids (`shw_ag_0212`) although names exist; a mono line "person" under every row; Report due "-" in all rows; assignee raw usernames; status chips in lowercase ("open") while Incidents uses "Investigating"; segmented control "Open / Archive 0 / All" and the Status chip both express status. | 1440__cases.png · `table.cases-tbl tbody tr td`, `.idline` | Show agent name with id as tooltip; hide empty column and "person" line. `_cases_table.html`, `cases_list.py`. | S | 3 |
| UI-181 | Medium | Drawer: label "rule" in lowercase with "-"; title is the id (`shw_case_001`) not the summary; "Open the case" plus a row "Details" button; "Copy JSON". | 1440__cases_status_open_sort_severity_dir_desc_drawer_shw_case_001.png | `_case_drawer.html`. | S | 2 |
| UI-182 | Medium | Detail: h1 "Case shw_case_001" (id), the headline sentence is printed twice (title and grey line), seed tag "[demo:showcase]"; the side panel has buttons Verify now / Evidence / Case file that duplicate the Evidence and Case file tabs; the "What happened" card has links to Rules and Transcript tabs. | 1440__cases_shw_case_001.png · `section.case-head`, `section.card.g6-evid > div.btnrow > button.btn` | Remove duplicate buttons and links. `case.html`, `_case_body.html`, `_tab_story.html`. | S | 2 |
| UI-183 | Medium | Tabs disagree: Story "1 stops by hard rules on this case", Rules tab "No rule or judge verdict linked yet", Case file "Rules broken 0". Header "Preliminary report due 2026-10-28" vs case file "Report due (24 h) 2026-10-26" (two clocks, one label). | 1440__cases_shw_case_001.png, ..._tab_rules.png, ..._tab_casefile.png, 1440__cases_shw_case_001_casefile_html.png | Count from the same rule-link query; name the two clocks. `case_ux5.py`, `evidence/casefile/builder.py`. | M | 1 |
| UI-184 | High | Case file (HTML) prints "FILL-ME: Decision 33 classification (bank counsel to supply the Appendix wording)" because `CASEFILE_DECISION33_TEXT` is not set in `app.yaml`; also prints raw token "(calendar_days)" (here and in the case-file tab). | 1440__cases_shw_case_001_casefile_html.png; 1440__cases_shw_case_001_tab_casefile.png | Set a non-placeholder default or hide the section when unset; map `calendar_days` to "calendar days". `config.py:285-288`, `app.yaml`, `evidence/casefile/builder.py`. | S | 1 |

### Alerts, Approvals (Sign-off), Incidents

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-190 | High | Incidents: every "Details" button (12 of 12) ends with "incident shw_inc_0xx does not exist" (HTTP 400, also the `?drawer=` fallback URL). The list shows rows that `incidents.get(id, me)` refuses. Likely cause: list ignores the scope that `visible()` applies (`governance/incidents.py:161-173, 231-234`). | 1440__incidents.png · `td a.chipbtn`; link check output | Use the same scope in list and get, or list only what get allows. `incidents_views.py:109-116`, `governance/incidents.py`. | M | 1 |
| UI-191 | Medium | Incidents: Agent and System columns both show raw ids (`shw_ag_0036`, `shw_sys_0036`); case shown as "Case 009" here and `shw_case_009` elsewhere; "by reviewer.retail.1" monospace; no info icon. | 1440__incidents.png · `td` | Show names; one id format. `_incidents_list.html`, `incidents_views.py`. | S | 3 |
| UI-192 | Medium | Alerts is an empty page reached 4 ways: tab Cases & alerts > Alerts, Analytics header button "Alerts", Oversight tile "Alerts 0 ... see all", Guardians > Alerts "Open". Empty state is two lines ("No alerts", "All clear"). | 1440__alerts.png, 1440__analytics.png, 1440__analytics_tab_metrics.png | Remove Analytics button and Oversight tile. `analytics.html`, `_analytics_tab_metrics_ux5.html`. | S | 2 |
| UI-193 | Low | Sign-off page: tab says "Approvals", h1 says "Sign-off"; empty state two lines. | 1440__signoff.png | Rename to one word. `signoff_list.html`, `i18n_ux5_g4.py`. | S | 3 |

### Analytics (Gate, Oversight metrics, Latency) and Evidence

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-200 | Medium | Strip title "Analytics", tab "Analytics", h1 "Analytics" and sidebar "Analytics"; sub-tabs Gate / Oversight metrics / Latency are a third tab style (pill segmented); Gate shows 4 zero tiles plus "No gate decision in this range". | 1440__analytics.png · `#gate-totals`, pill segmented control under the header | Hide tiles when no data. `_analytics_tab_gate_ux5.html`. | S | 2 |
| UI-201 | Medium | Oversight metrics repeats other pages: an "Evidence chain" block (0 lanes, "Open the evidence chain", "not verified in this session", Verify now), an Alerts tile, and the same empty text twice ("No data yet. Metrics appear after the first daily run." in Monitor status and Oversight metrics). | 1440__analytics_tab_metrics.png · `#tab-body .card` | Remove Evidence block and Alerts tile; one empty state. `_analytics_tab_metrics_ux5.html`. | S | 2 |
| UI-202 | Medium | Evidence: h1 "Evidence" vs tab "Evidence chain"; 4 near-empty blocks (Chain status "Entries 0", "Download: No export yet", Lanes with a search box and "The chain is empty", legend for an empty chain) plus a "Page 1 of 1" pager. | 1440__evidence.png | Collapse to one empty state until the chain has entries. `evidence.html`. | S | 2 |

### Settings gear and Health

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-210 | Low | Settings button opens a drawer with one item (Health). The mode "laptop" is shown in the top bar, the footer, the sidebar foot and Health. | 1440__health.png; `.gear-drawer .gear-list` | Link Health directly or add the other pages when flags allow. `nav_v3.py` (`GEAR`), `_c_sidebar_v3.html`. | S | 2 |
| UI-211 | Low | Health shows "Developer checks" (preflight, technical details) and "Onboard from the console: off" (duplicate of the Onboard page state) to every admin. | 1440__health.png | Fold under one "Technical" disclosure. `health.html`. | S | 2 |

## 5. Cross-page issues

### A. Naming

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-300 | High | Old group names leak into the new nav: sidebar tagline "Onboard · Watch · Prove" on all 82 pages (vi: "Tiếp nhận · Giám sát · Chứng minh"); breadcrumbs "Act / Cases", "Act / Sign-off", "Act / Incidents", "Act / Case" (case detail), "Watch / Alerts", "Prove / Evidence"; Integration text "bring under Watch". | 1440__console.png (tagline); 1440__cases.png, 1440__alerts.png, 1440__evidence.png, 1440__incidents.png, 1440__signoff.png · `.crumbs` | `i18n.py:167` (`tagline`) -> "AI management · AI guardian"; crumbs in `queue.html`, `alerts.html`, `incidents.html`, `signoff_list.html`, `case.html`, `evidence.html` use `nv3_*` keys (as `cat_assets_ux5.html` does). | S | 3 |
| UI-301 | Medium | One page, several names: Overview x3 (sidebar twice, My overview strip tab); Guardians / "Guardian catalog" / "Library"; "Governance overview" / "Supervisor overview" vs "AI management / AI guardian > Overview"; Sign-off / Approvals; Evidence / Evidence chain; Inventory / Unmanaged / Unmanaged items; Compliance / Compliance advisor / Policies; Candidates / Candidates to register; Cases & alerts vs Cases. | 1440__guardians.png, 1440__governance.png, 1440__supervisor.png, 1440__signoff.png, 1440__inventory.png | Rename h1 to equal the nav label; sidebar items "Overview" -> "Governance overview" / "Guardian overview" or keep "Overview" and drop the word from h1. `i18n.py` (`nv3_*`), `i18n_ux5_g4.py` (`nv3_t_unmanaged` is defined twice with different text). | M | 3 |
| UI-302 | Medium | Same object, three words: agent / product / system / asset ("This product: payments", "Registry row", "AI system"); "Risk level" / "risk" / "Decision 33 class"; strip label repeats the tab ("Systems" strip title + "Systems" tab; "Analytics" + "Analytics"). | 1440__compliance_payments_obligation_INTL_ATLAS_T0070_01.png, 1440__systems.png, 1440__analytics.png | Drop the strip title when it equals the first tab. `_c_section_tabs.html`, `i18n*.py`. | S | 3 |

### B. Same data under two URLs or two nav entries

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-310 | Medium | Section root equals first tab: `/console/compliance` = `/console/risks-controls`; `/console/guardians` = `/console/catalog`; `/console/catalogues` = `/console/agents`; `/console/systems` = Systems tab. Each is a second URL for one page. | 1440__risks_controls.png vs 1440__compliance.png; 1440__guardians.png vs 1440__catalog.png; 1440__catalogues.png vs 1440__agents.png | Redirect section roots (HTTP 302) to the first visible tab. `nav_v3.py`, route files `routes.py`. | S | 2 |
| UI-311 | Medium | Pairs that show the same records: My agents / Agents / Systems (same ~150 names), Candidates / Inventory (43), Detectors+Judges+Monitors / Library (same 27), Models+Tools+Datasets / Inventory Nodes, Cases tab / Inbox (case notices), Compliance (agent) Summary / D33 tab. | see rows UI-011, UI-022, UI-160, UI-090 | Pick one owner page per record set. | L | 2 |
| UI-312 | Medium | Same action in several places: Verify chain x4 (Supervisor overview, Analytics > Oversight, Evidence, Case detail); register entry x5; Move to Running x2 on one agent; Alerts x4; Case file / Evidence buttons next to tabs of the same name. | UI-150, UI-052, UI-101, UI-192, UI-182 | One home per action. | M | 2 |

### C. Component consistency

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-320 | Medium | Two chip components in use: `.pill` (276 uses) and `.u5-chip` (237 uses) plus `.chipbtn` for link buttons. Case rules differ: SHADOW / RUNNING (upper), high / low (lower), Investigating (title), on / off vs On / Off. | findings.json `chipClasses`; 1440__my_agents.png, 1440__incidents.png, 1440__workflows.png | One chip macro with a kind and a case rule. `_ui.html` (`pill`, `state_pill`, `sev`), `ux5.css:59`. | M | 4 |
| UI-321 | Medium | Five tab patterns: sidebar section strip (`.sec-tabs`), in-page grouped tabs with group labels (`.g2-tg`), pill segmented control (Analytics, Case), count tiles that filter (Systems, Incidents), "More ▾" menu (Agent). Filter bars: auto-apply + Reset (Systems), Search button (Catalogues), Filter button (Factory, Compliance), Apply (Duties). | 1440__analytics.png, 1440__cases_shw_case_001.png, 1440__agents_shw_ag_0031.png, 1440__catalogues_tab_models.png | Document one tab and one filter pattern; migrate. `_ui.html` (`tabs`, `filterbar`, `tiles`). | L | 4 |
| UI-322 | Medium | Seven table classes (`queue`, `queue systems-tbl`, `list cand-tbl`, `g3-tbl`, `g2-duties`, `g1-grid`, `incidents`) and 19 tables without a class. KPI tile has two layouts (number above label on Home, label above number on Analytics, Agent detail). | findings.json `tables`; 1440__console.png vs 1440__analytics.png | One table class with modifiers; one `stat` macro. `_c_table.html`, `_ui.html` `stat`, `ux5.css`. | L | 4 |
| UI-323 | Low | Breadcrumbs: three styles ("Act / Cases" grey group, "AI management / Systems / Name", "Compliance /name" without spaces) and absent on 40+ pages; info icon plus "About this page" only on some pages. | 1440__cases.png, 1440__systems_shw_sys_0081_tab_overview.png, 1440__compliance_payments_tab_summary.png | One `crumbs` macro, always on detail pages. `_ui.html` `crumbs`. | M | 4 |
| UI-324 | Medium | Empty states in 6 forms: `ui.empty` card (two lines), plain muted line, dashed box (MCP), count + line ("Runs 0 / No run yet"), grey chip "not available" (Risks, Controls, Obligations), table with a pseudo row (Workflows). Zero-count headings ("Source 0", "Facts 0", "Timeline 0") repeat the empty sentence. | 1440__catalogues_tab_mcp.png, 1440__regkb_watch.png, 1440__systems_shw_sys_0081_tab_risks.png, 1440__workflows.png | Use `ui.empty` only; no count when 0. `_ui.html`, templates listed per page. | M | 2 |
| UI-325 | Low | Pager text: "Page 1 of N" alone (Systems), plus "25 of 52 shown" (Catalogues), plus "Page 1 of 1" on empty lists (Inbox, Evidence). | 1440__catalogues_tab_models.png, 1440__inbox.png | `_c_table.html` `pager`. | S | 4 |

### D. Raw ids, keys and debug text where a name exists

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-330 | Medium | Agent ids as the only label: Cases, Incidents, Case drawer, Case file. System ids: Incidents, Home table sub-line. Guardian keys (`dlp_vn`, `injection_regex`, `guard_model`) on Rules and Guardians tabs and in My agents "Recommended action". Snake-case kinds (`genie_space`, `model_endpoint`). Usernames (`reviewer.retail.1`) in Cases, Incidents, Team. Rule id `AR-D33-HIGH`. Task codes `DEP-D33`. | 1440__cases.png, 1440__incidents.png, 1440__systems_shw_sys_0081_tab_rules.png, 1440__inventory.png | A shared `label_for(kind,id)` helper in the view layer; id in a tooltip. `readmodels.py`, `listing.py`, templates per page. | L | 3 |
| UI-331 | Medium | Debug or developer text in user pages: flag names (`CONSOLE_ONBOARD_ENABLED`, `RISK_REGISTER_ENABLED`, `CONTROLS_ENABLED`), `GET /v1/kpis`, `POST /v1/regkb/import`, Windows command lines on Onboard, "Copy JSON" in drawers, "calendar_days", "[demo:showcase]" seed tag, "FILL-ME" placeholder. | 1440__onboard.png, 1440__governance.png, 1440__regkb_watch.png, 1440__cases_shw_case_001_casefile_html.png | Move to a dev-only `Technical details` disclosure. `i18n.py`, `i18n_ux5_g1.py`, templates per page. | M | 3 |

### E. Language (en / vi)

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-340 | Medium | vi pages keep English text from data: task title on Home, case summaries on Cases ("Several calls were stopped by the money rule in one hour."), case-file text on the Overview tab ("Chooses the contact strategy ..."), Governance "agent: 152 · dataset: 28" keys and "GET /v1/kpis". Names such as "Lenh Dinh ky" are data, not UI. | 1280dark_vi__console.png, 1280dark_vi__cases.png, 1280dark_vi__governance.png | Translate system-generated case and task text through i18n keys; keep user-entered text as is. `case_ux5.py`, `overview_v4.py`, `_ov_gov_kpis.html`. | M | 3 |
| UI-341 | Low | Odd or machine-like labels: "Take in" (upload button), "Re-read", "Run the rules now", lowercase "rule", "risk", "all"; "1 agents", "2 guardian feature". | 1440__agents_shw_ag_0031_tab_source.png, 1440__factory.png | Plural helper in i18n; review wording. `i18n*.py`. | S | 3 |

### F. Counts that disagree

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-350 | High | Same quantity, different totals on neighbouring pages: Agents 152 (Home, Agents) vs 192 "All, with candidates" and 150 running (My agents) vs 147 running; overdue 10 vs 21 vs "Controls are off"; duties 27 / 28 / 30; guardian features 15 (Guardians tab) vs 16 (Attach); Tasks badge 1 vs 3 open. | 1440__console.png, 1440__my_agents.png, 1440__agents.png, 1440__governance.png, 1440__systems_shw_sys_0081_tab_duties.png, 1440__agents_shw_ag_0031_tab_attach.png | Define each number once in the read model and reuse it. `readmodels.py`, `overview_v4.py`, `agent_guardians.py`, `systems_tabs.py`. | L | 1 |

### G. Scroll bars and overflow

| Id | Sev | Finding | Evidence | Fix | Est | Batch |
|---|---|---|---|---|---|---|
| UI-360 | Medium | Stray scroll areas: agent Guardians table (`.g4-scroll`, 630 px box inside a scrolling page), Candidate drawer (3 nested horizontal boxes), My agents at 1280 px (page-level box 1336 > 950), Home risk table at 1280 px vi. No page has horizontal page overflow at 1440 or 1280 px. The factory description textarea scroll is intended. | findings.json `scrollers`; 1440__agents_shw_ag_0173_tab_guardians.png; 1440__candidates_drawer_inv_0d33cdf0bc7aeebb.png; 1280dark_vi__my_agents.png | See UI-004, UI-013, UI-023, UI-103. | M | 4 |

### Reference: names used for the same page

| Sidebar item | Strip title | Tab | h1 | Breadcrumb |
|---|---|---|---|---|
| AI management > Overview | - | - | Governance overview | - |
| AI guardian > Overview | - | - | Supervisor overview | - |
| My overview | My overview | Overview | Good evening, <name> | - |
| Systems | Systems | Systems | Systems | AI management / Systems (detail only) |
| Catalogues | Catalogues | Inventory | Inventory (block: Unmanaged items) | Catalogues / Inventory |
| Risks & controls | Risks & controls | Compliance | Compliance advisor | Compliance / <agent id> |
| Guardians | Guardians | Library | Guardian catalog | - |
| Cases & alerts | Cases & alerts | Approvals | Sign-off | Act / Sign-off |
| Cases & alerts | Cases & alerts | Alerts | Alerts | Watch / Alerts |
| Analytics | Analytics | Evidence chain | Evidence | Prove / Evidence |
| Analytics | Analytics | Analytics | Analytics | - |

## 6. 1280 px dark vi pass

Pages: Home, My agents, Candidates, Governance, Systems, Agents, Guardians, Supervisor, Cases, System detail Overview, Compliance. Dark theme: no unreadable text or lost borders on the 5 pages viewed in full (Home, Governance, System detail, Cases, Guardians); the other 6 had only the automatic checks plus a look at the PNG. Findings from this pass are in UI-004, UI-005, UI-013, UI-060, UI-070, UI-340 and UI-360. Vietnamese strings are 15 to 25 percent longer; the tab strip of System detail wraps (UI-070) and the KPI list of Governance wraps to 5 lines per cell.

## 7. Fix plan (4 batches, batch 1 first, then 2, 3, 4 in parallel)

### Batch 1: Broken links, wrong numbers, contradictions (views + the templates named in these rows)

- Findings: UI-001 UI-002 UI-040 UI-041 UI-061 UI-062 UI-063 UI-091 UI-092 UI-110 UI-183 UI-184 UI-190 UI-350
- Estimate mix: L x 1, M x 7, S x 6
- Files owned by this batch: `incidents_views.py`, `governance/incidents.py`, `inventory_views.py`, `inventory.html`, `systems_tabs.py`, `systems_duties.py`, `systems_riskdim.py`, `_system_duties_ux5.html`, `_system_riskdim_ux5.html`, `compliance_view.py`, `compliance_agent_ux5.html`, `config.py`, `app.yaml`, `evidence/casefile/builder.py`, `case_ux5.py`, `overview_v3.py`, `overview_v4.py`, `ov_governance.html`, `ov_gov_systems_ux5.html`, `_ov4.html`, `_ov4_portfolio.html`, `cat_assets_ux5.html`, `_agent_tab_attach_ux5.html`, `readmodels.py`, `agent_guardians.py`
- Note: Must go first: these are the High findings. Add a link-check test (every `href` on a page returns 200 for admin) and a test that the same count is read from one function.

### Batch 2: Remove redundancy and dead blocks (templates only)

- Findings: UI-003 UI-010 UI-011 UI-012 UI-020 UI-021 UI-022 UI-024 UI-030 UI-043 UI-044 UI-050 UI-052 UI-064 UI-065 UI-066 UI-067 UI-068 UI-069 UI-080 UI-090 UI-093 UI-094 UI-100 UI-101 UI-102 UI-104 UI-105 UI-106 UI-112 UI-113 UI-114 UI-116 UI-120 UI-121 UI-130 UI-131 UI-132 UI-140 UI-141 UI-150 UI-151 UI-160 UI-161 UI-162 UI-170 UI-181 UI-182 UI-192 UI-200 UI-201 UI-202 UI-210 UI-211 UI-310 UI-311 UI-312 UI-324
- Estimate mix: L x 2, M x 12, S x 44
- Files owned by this batch: `ov_my_v4_ux5.html`, `_c_sidebar_v3.html`, `_my_agents_list.html`, `_cand_rows_ux5.html`, `_cand_drawer.html`, `inbox.html`, `_ov_gov_kpis.html`, `systems.html`, `_systems_list.html`, `_system_facts_ux5.html`, `_system_rules_ux5.html`, `_system_guardians_ux5.html`, `_system_policies.html`, `_system_reports.html`, `_system_components_ux5.html`, `_system_tasks_ux5.html`, `_system_reviews.html`, `onboard.html`, `_agents_table.html`, `agent_detail.py`, `_agent_tab_*` (except attach), `compliance_ux5.html`, `compliance_obligation_ux5.html`, `regkb_*.html`, `factory.html`, `factory_editor.html`, `workflows.html`, `ov_supervisor_ux5.html`, `_catalog_ux5.html`, `_gf_list_ux5.html`, `_case_drawer.html`, `case.html`, `_case_body.html`, `_tab_story.html`, `analytics.html`, `_analytics_tab_*_ux5.html`, `evidence.html`, `health.html`, `nav_v3.py`, `routes.py` (302 redirects)
- Note: Depends on batch 1 only for `nav_v3.py` flag helpers. No i18n and no CSS in this batch.

### Batch 3: Names, labels, raw ids, language (i18n and label helpers)

- Findings: UI-005 UI-014 UI-042 UI-051 UI-081 UI-082 UI-111 UI-115 UI-152 UI-171 UI-180 UI-191 UI-193 UI-300 UI-301 UI-302 UI-330 UI-331 UI-340 UI-341
- Estimate mix: L x 1, M x 4, S x 15
- Files owned by this batch: `i18n.py`, `i18n_ux5_g1.py`, `i18n_ux5_g2.py`, `i18n_ux5_g4.py`, `i18n_ux5_g5.py`, `i18n_guardian_factory.py`, breadcrumb lines in `queue.html`, `alerts.html`, `incidents.html`, `signoff_list.html`, `case.html`, `evidence.html`, `_cases_table.html`, `_incidents_list.html`, `_gf_editor_ux5.html`, `integration.html`, `register_list.html`, `register_new.html`, `compliance_*.html` (label lines only), `_c_section_tabs.html`, `listing.py`
- Note: Add a `label_for()` helper first, then convert pages. Batch 2 must be merged first for the files that both touch (`case.html`, `compliance_*`): rebase, do not edit the same lines.

### Batch 4: Components and CSS (no template edits)

- Findings: UI-004 UI-006 UI-013 UI-023 UI-060 UI-070 UI-103 (CSS part) UI-320 UI-321 UI-322 UI-323 UI-325 UI-360
- Estimate mix: L x 2, M x 6, S x 5
- Files owned by this batch: `console/static/console.css`, `ux5.css`, `ux5_g1.css`, `ux5_g2.css`, `ux5_g4.css`, `_ui.html`, `_c_table.html`
- Note: Fixes the visible layout bugs (UI-060 first: `.kv` stacking). Component unification (UI-320 to 323) is the large part; do it behind the macro so templates do not change.

Order: merge batch 1 first (High findings, plus a link-check test). Then run batches 2, 3 and 4 in parallel on separate branches. Batch 4 edits only CSS, `_ui.html` and `_c_table.html`, no other template. Batch 2 must not add CSS and must not edit i18n files.

Files that more than one batch needs (the file lists above are not perfectly disjoint, so use this order):

| File | Batches | Rule |
|---|---|---|
| `cat_assets_ux5.html`, `inventory_views.py`, `_system_duties_ux5.html`, `systems_tabs.py` | 1 and 2 | batch 1 merges first; batch 2 rebases |
| `_ov_gov_kpis.html` | 2 (UI-043) and 3 (UI-042) | batch 2 first; batch 3 changes only the label and text lines |
| `case.html`, `compliance_agent_ux5.html`, `compliance_obligation_ux5.html` | 1 or 2, and 3 | batch 3 edits only breadcrumb and label lines; merge batch 1 and 2 first |
| `i18n_ux5_g2.py`, `i18n_ux5_g4.py` | 3 only | batch 2 asks batch 3 for new keys instead of editing them |

## 8. Decisions needed from the owner

| # | Decision | Recommendation |
|---|---|---|
| 1 | UI-011: one Agents page (scopes Mine / Team / All) or keep My agents and Catalogues > Agents | One page. My agents is the same registry with a scope filter. |
| 2 | UI-160: Detectors / Judges / Monitors as tabs or as category chips | Keep the chips, remove the 3 tabs (the page always shows the same list). |
| 3 | UI-022: Candidates and Inventory > Unmanaged are the same 43 objects | Keep Candidates, make Inventory registered-only. |
| 4 | UI-104: agent tabs for onboarding (Source, Facts, Pre-deploy, Attach, Post-deploy) | One "Onboarding" tab, shown only while a source or run exists. |
| 5 | UI-061 and UI-041: show a tab or block whose feature is off | Never show it; show the feature in Settings > Health as off. |
