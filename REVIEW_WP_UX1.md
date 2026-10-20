# REVIEW WP-UX1: console shell and components

Reviewer: Opus (front-end, accessibility, security; senior Python). Branch `wp-ux1-shell`,
base `phase3-wave1` eacb549. Reviewed commit 68de302 (full diff `eacb549...68de302`).
Review commits: ae96edf, d74d60a, 2428334 (plus this file). No history rewrite, no merge, no push.
The uvicorn process on 127.0.0.1:8130 was not touched (it serves another store; I used port 8771).

## Verdict

**GO for merge** after the review commits. The work is clean: strict CSP kept, every new route in
`rbac.ROUTES`, autoescape on, no `|safe`, no external URL, all bad input is 400. I found no
security defect. I fixed the accessibility, performance and scope findings below on the branch.

## Findings

| # | Sev | File:line (68de302) | Issue | Action |
|---|---|---|---|---|
| 1 | Medium | `templates/_c_sidebar.html:19` | Collapsed sidebar shows one letter (`t(label)[:1]`). Many items share a letter (Agents, Alerts, Assurance, Audit; Cases, Compliance, Credentials; Inbox, Integration, Inventory, Integrations). In VI it is worse (Tác tử, Tiếp nhận, Tích hợp). | Fixed (ae96edf). Two-letter codes in `nav.CODES` (OV AG GD TR AL CS SO IB EV AS CO ON IV IG TL MT PO CR US AU IS HL). The codes are the same in EN and VI. The `title` tooltip and the accessible name stay the full label. I did not use icons because the console has no icon set (only the inbox SVG), and the spec says "icons-free". Test: the codes are unique and 2-3 capital letters, and every nav item has a code. |
| 2 | Medium | `static/console.css:451,457` | The count badge and the code chip on the active (brand red) item use `rgba(255,255,255,.24)` with white text. The ratio is 3.9:1 at 10-11 px, which fails AA (4.5:1). | Fixed (ae96edf). Changed to `rgba(0,0,0,.22)`, which gives about 7:1. I checked the other new pairs with our tokens: active item white on `--brand` 4.8:1; `.k.hot` light 5.1:1, dark 5.3:1; tiles, crumbs and `.sres-h` are 6:1 or more. |
| 3 | Medium | `console/routes.py:696` | The drawer endpoint built `agent_cards` for **all** agents. Each card does several queries (events up to 2000, coverage, judge, d33). The cost was N times higher than needed for each row click and each prev/next click. | Fixed (ae96edf). Added `agent_cards(..., only=id)`. `agents_list.order_rows` makes light rows for the prev/next order (agent row, gate state, open count). It uses all the cards only when the list is sorted by coverage. The no-JS fallback uses the cards that the page already has. Test: a spy shows that one card is built and that prev/next still follow the list order. |
| 4 | Medium | `console/search.py:48` | The search ran an exact `agent_event.trace_id` lookup on each keystroke from 2 characters. On Delta that is one SQL call for each keystroke, with no index. | Fixed (ae96edf). Added `TRACE_MIN = 8`. Test: 7 characters give no `agent_event` query, and 8 characters give one. |
| 5 | Low | `console/readmodels.py:118,917` | It read the private `ctx.cases._approvals` (one new use with `noqa: SLF001`, one old use). | Fixed (ae96edf). Added the public read-only `CaseService.approvals()` and used it in both places. |
| 6 | Medium (scope) | spec 6 / WP-UX1, `BACKLOG.md:99` | The spec puts the span tree partial (`_c_spantree.html`, `readmodels.span_tree`, `test_span_tree`) in WP-UX1. The branch moved it to the backlog. | Fixed (d74d60a). It has one node per span, a `<details>` for each parent (works without JS), orphans and loop spans under "Spans without a parent" (a loop is marked "loop cut"), a cap of 500 spans, and chains deeper than 48 move to the orphan list (no deep Jinja recursion). Tests cover orphans, cycles, self-parent, the cap, the depth, escaping, the empty state, and EN and VI. It uses plain nested lists, not `role=tree` (see residual risk 4). No page uses it yet. |
| 7 | Low | `templates/_ui.html` tabs, `_c_drawer.html` | Tabs had no `aria-controls` and no `role=tabpanel`, and Home and End did nothing. After an htmx tab swap, focus jumped to the drawer title, so keyboard users lost their place. | Fixed (ae96edf). Added `panel=` to `ui.tabs`, `aria-controls`, `role=tabpanel` on `#tab-body`, and Home and End keys. Focus now goes back to the selected tab after the swap. |
| 8 | Low | `test_components.py` | The i18n test checked only 6 of the 60+ new keys. | Fixed (ae96edf). The test reads every key in the `# --- WP-UX1` block of `i18n.py` and checks that EN and VI are not empty. It also checks every nav label and group key. |
| 9 | Low (tool) | `tools/console_screenshots.py:121` | `--reseed` with `--data-dir` seeded `data/local/demo`, because the demo harness reads `--data-dir`, not `DATA_DIR`. The server then served the other directory. The result was screenshots with one agent and no case (this matches the handoff note). | Fixed (2428334). The tool now passes `--data-dir` to `demo seed` and `demo inject`. |
| 10 | Info | tests | There was no test for `shell()` on an empty store, and no test of the new routes in `databricks_app` mode. | Added (ae96edf). The empty-store test checks that all counts are 0, the pages give 200, the drawer gives 400 and the pager shows "Showing 0-0 of 0". The SSO-mode test covers the sidebar, search, rows and drawer, checks that there is no `dev-user` and no `/console/dev/user`, and checks that the token is not in the output. |

Checked and found correct (no action):

| Area | Result |
|---|---|
| CSP | `ops/middleware.py` is not changed. No inline `<script>` and no `on*=` handler (a test checks the rendered pages). The `style=` width on `bar`/`barcell` was already allowed (`style-src 'self' 'unsafe-inline'`, as before). |
| RBAC | 4 new `ROUTES` rows, all `console.view` (read-only GETs). `test_every_route_permission_exists` and `test_rbac_matrix` pass. Drawer and tab GETs write nothing. |
| Search input | `.strip()`, at most 64 characters, `[A-Za-z0-9_.:@ -]` only, else 400 (`ListingError`). An empty or 1-character query gives a hint, not a query. |
| Reflected HTML | Autoescape is on for `.html`. There is no `|safe` and no `Markup` in the diff. `q`, ids and JSON go through autoescape. The `sort`/`dir` raw values only reach `urlencode` (`query_string`). |
| Open redirect | `?drawer=` passes `_check_id`, renders in place, and does not redirect. "See all" is a fixed path. |
| `soon` route | An unknown page gives 400. With the flag off, every page gives 400 with a message. |
| localStorage | Only `sv_theme` (existing) and `sv_side` (collapse). Every access is in try/catch. |
| User menu | `known_users` is empty for `databricks_app` (`adapters/auth/databricks_app.py:134`), so there is no picker and no user list. In `dev_header` mode it shows only the picker that was there before. |
| Sort / pages | Allow-listed columns. An unknown column or direction gives the default. The page number must be digits, fewer than 8 characters, and inside 1..N, else 400. Page 1 of an empty list is valid. |
| OOB refresh after pause/resume | The POST path, its permission check and the two `console_action` audit rows did not change. The out-of-band `#list` uses the default filters, so the user loses the filter (this is documented). |
| Rollback | `CONSOLE_NAV=top` renders `_c_header_top.html` (the same markup as phase 2). Tested on 8 pages in EN and VI. |

## Tests

| | Count |
|---|---|
| Base `phase3-wave1` (handoff) | 3426 passed |
| After 68de302 (handoff) | 3455 passed, 29 skipped |
| After the review commits | **3464 passed, 29 skipped** (`uv run python -m pytest -q -x`), `ruff check` and `ruff format --check` clean |
| New in review | `test_shell.py` +4 (trace minimum, one-card drawer, codes, empty store), `test_components.py` +4 (i18n block, tab panel, span tree x2), `test_databricks_mode.py` +1 |

Screenshots: `tools/console_screenshots.py --reseed --data-dir <scratch> --port 8771`. All 21
screens were OK. The five that were asked for are replaced in
`/home/trung/supervisor-testbed/phase3/ux1-shots/` (`overview-vi`, `agents-drawer-en`,
`agents-collapsed-en`, `overview-en-dark`, `agents-vi`). They now show the real demo store (4
agents, 4 cases). `sheet.png` in that directory is from before and is now out of date. The
`--reseed` run also re-created the synthetic demo store `data/local/demo` in this worktree
(before the tool fix). That directory is gitignored and marked "safe to delete", and the 8130
server does not use it.

## Residual risks

1. **The drawer beside the list at 1360 px.** The spec breakpoint (beside at 1280 px or more)
   was set before the 248 px sidebar existed. With the drawer open, the table has about 630 px,
   and the Coverage and Cases columns scroll inside `.tablewrap` (the page does not scroll).
   Option for the owner or WP-UX2: move the breakpoint to about 1600 px, or hide the low-value
   columns while the drawer is open.
2. **The collapsed tooltip is mouse-only.** The full label is a native `title` and the
   accessible name, so screen readers are correct. A sighted keyboard user sees only the code.
   A CSS tooltip is clipped by the sidebar's `overflow-y: auto`. A fix needs a different
   scroll container or a small JS tooltip.
3. **The search still loads all cases on each query** (`ctx.cases.list_cases()`, then a
   substring filter). This is fine at bank-pilot volume. WP-UX3 Traces/Decisions should use
   a SQL `LIKE` with a limit.
4. **The span tree is not an ARIA tree.** This was my choice: the spec says `role="tree"`, but a
   real tree needs roving tabindex and arrow keys. Native `<details>` is accessible today.
   WP-UX3 can add the full pattern if the selection is needed.
5. **The sign-off badge does N+1 queries** (one `signoff` query for each open high/critical
   case on each full page). This is bounded by the open cases. Cache it if Delta latency shows.
6. **Old code, not touched:** the phase-2 top header `.nav a.active .k` (`console.css:108`)
   has the same 3.9:1 chip. It is visible only with `CONSOLE_NAV=top`.
7. **Landmarks:** the `<aside>` and the `<nav>` inside it have the same `aria-label`, so screen
   readers announce two landmarks with the same name. This is cosmetic. The fix is to drop one
   label (tests split on `<aside class="side"`).
8. **No browser test of JS behaviour** (Esc, focus return, arrow keys, Home and End). I checked
   only the server HTML and the screenshots.
9. `console.js` added about 75 lines (the spec allows 40 or fewer).

## Merge notes

Merge WP-UX1 first, then WP-UX2 and WP-UX3 one at a time (spec section 6).

| File | Why it conflicts | Hint |
|---|---|---|
| `console/routes.py` | `render()` gained `side_nav` and `nav_groups`; agents, rows, drawer, search and soon routes; `section=` on metrics and inbox | WP-UX2/3 add routes: append below `# ---- search, soon` and remove each `soon` entry as its page lands |
| `console/i18n.py` | Block `# --- WP-UX1` at the end of `_T` (65 keys including span tree) | Add your own `# --- WP-UX2/3` block after it; the new completeness test reads only the WP-UX1 block |
| `core/rbac.py` | 4 `ROUTES` rows after `/console/exports/{name}` | Append; WP-UX3 adds new permissions to the matrix first, then regenerates `docs/console.md` |
| `console/nav.py` | `PLACEHOLDERS`, `GROUPS`, `CODES` | When WP-UX3 replaces a placeholder, keep its `CODES` key in step (the test checks that every item has a code) |
| `templates/base.html` | Rewritten (shell; the old header is in `_c_header_top.html`) | Change content blocks only; do not re-add the header |
| `static/console.css` | WP-UX1 section at the end (shell, drawer, tree) | Append after it; use tokens only |
| `static/console.js` | WP-UX1 block at the end of the IIFE | Keep additions inside the IIFE; no inline scripts |
| `console/readmodels.py` | `shell()` keys, `signoff_waiting`, `agent_cards(only=)`, `span_tree` at the end | Additive |
| `cases/service.py` | `approvals()` accessor before `_approvals` | Additive |
