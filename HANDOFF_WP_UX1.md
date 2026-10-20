# HANDOFF WP-UX1: console shell and components

Branch `wp-ux1-shell` (from `phase3-wave1` eacb549). Not pushed, not merged.
Spec: `/home/trung/supervisor-testbed/phase3/CONSOLE_DESIGN_SPEC.md` sections 2.1, 3.2, 4, 6.

## What was built

| Item | Result |
|---|---|
| Shell | `base.html` has a left sidebar (Overview; Watch, Act, Prove, Onboard, Analytics, Settings: 22 items) and a reduced top bar: env and demo badge, global search, inbox count, EN/VI switch, theme button, role pill, user menu with "Switch user" in `dev_header` mode. Sidebar: collapsible to one letter per item (kept in `localStorage`), menu button under 1100 px, arrow keys, count badges (agents, cases red when critical, alerts open, sign-off waiting, unread, inventory unmanaged), `aria-current="page"` on the active item, flagged items hidden as before. |
| Rollback | `CONSOLE_NAV=sidebar` (default) or `top`. `top` renders the old pill header (`_c_header_top.html`, same markup as before). Documented in `docs/console.md` and README. |
| Placeholders | `/console/soon/<page>` for Gate decisions, Traces, Policies, Credentials, Users and roles, Audit log, Integrations: "coming in WP-UX3". Hidden unless `CONSOLE_NAV_PLACEHOLDERS=1` (new flag, default off). Flag off: link hidden and the URL answers 400 with a message. |
| Search | `GET /console/search?q=` (permission `console.view`, in `rbac.ROUTES`). Agents and cases by substring on id and name, traces by exact trace id, 5 hits per kind, 2 to 64 characters, `[A-Za-z0-9_.:@ -]` only (else 400). htmx gets a popover partial; without JS a full page. |
| Components | Macros in `_ui.html`: `crumbs`, `pagehead` (call block for actions), `tiles`, `filterbar`, `tabs`, `kv`, `empty`, `stat`, `barcell`, `action_pill`, `timeline`, `toast`. `_c_table.html` (`th` sortable header with `aria-sort`, `pager`), `_c_drawer.html` (drawer macro), `_c_sidebar.html`, `_c_topbar.html`, `_c_who.html`. Python: `console/listing.py` (`paginate`, `parse_sort` allow-list, `sort_rows`, `ListingError` = 400), `console/nav.py`, `console/search.py`, `console/agents_list.py`. CSS appended to `static/console.css` (existing tokens, no new colour). JS: about 60 lines in `static/console.js` (sidebar, drawer open / Esc / focus return / Copy JSON, arrow keys); no inline script. |
| Migrated pages | Overview (stat tiles, empty state, "see all" link) and Agents list (breadcrumb, page header, state tiles as filter, filter bar, sortable paged table, row drawer with tabs Overview / Policy / Cases, prev / next row, no-JS fallback `?drawer=<id>&dtab=`). Other pages render in the new shell unchanged. |
| i18n | 60 new keys, EN and VI (`console/i18n.py`). |
| Accessibility | Skip link, `aria-current`, `aria-sort`, `aria-live` on search results, `role=tablist`, focus to drawer title and back to the row link, visible focus ring (existing), our colour tokens only (checked in light, dark and VI screenshots). |

Decisions to flag:

1. The Agents page keeps the old cards under the table in a section "Lifecycle and controls".
   Existing tests (and the Pause / Resume / Quarantine forms) live in the cards; moving the
   controls is WP-UX2 (agent detail page). Action answers also refresh the table by an
   out-of-band swap (default filters).
2. Table rows use `data-row="<id>"`, not `data-agent`, so `test_agents_screen.py` selectors stay valid.
3. "Alerts" links to `/console/metrics#alerts`; "Sign-off" links to `/console/cases?status=open` (no own pages yet). The Playground item is not in the sidebar (your list omits it).
4. Filter, sort and page links do not push the URL (`hx-push-url=false`, same as the queue page); the plain `href` still works without JS.
5. `readmodels.shell()` gained `alerts_n`, `signoff_n`, `placeholders` (additive). `signoff_n` reads `ctx.cases._approvals` (private, read-only, `noqa: SLF001`); a public accessor in `cases/service.py` would be cleaner.
6. Added `section="metrics"` and `section="inbox"` to those two routes so the sidebar marks them active.

## Flags and commands

| Setting | Default | Effect |
|---|---|---|
| `CONSOLE_NAV` | `sidebar` | `top` = phase 2 header |
| `CONSOLE_NAV_PLACEHOLDERS` | `0` | show the seven "coming in WP-UX3" links |

```
python -m pytest tests/console/test_shell.py tests/console/test_components.py -q
python tools/console_screenshots.py --reseed --out <dir> [--nav top]
```

## Tests

| | Count |
|---|---|
| Before (phase3-wave1) | 3426 passed |
| After | 3455 passed, 29 skipped (same skips as before), ruff check and format clean |
| New | `tests/console/test_shell.py` (16), `tests/console/test_components.py` (13) |

Covered: shell in both nav modes and both languages on 8 pages; one active item with `aria-current`; flagged items absent / present per flag; counts equal `shell()`; placeholders per flag; `Switch user` kept; search (agents, cases, trace id, too short, too long, bad characters); agents list filter, sort (unknown column falls back), page out of range or not a number = 400, drawer tabs, no-JS fallback; action POST still works; macros render in EN and VI; pager math; no external URL in any template, CSS, JS or rendered page; no inline script or event handler. Existing console tests, `test_rbac.py::test_every_route_permission_exists`, `test_rbac_matrix.py`, `test_i18n.py`, `test_static_assets.py` all green and unchanged.

## Screenshots

The existing tool `tools/console_screenshots.py` was used (Playwright from `PLAYWRIGHT_PYTHON`). It now has `--nav` and two new shots (agents with drawer open, agents with collapsed sidebar); it starts the console with `CONSOLE_NAV_PLACEHOLDERS=1`. Five PNGs in `/home/trung/supervisor-testbed/phase3/ux1-shots/`:
`overview-vi.png`, `agents-drawer-en.png`, `agents-collapsed-en.png`, `overview-en-dark.png`, `agents-vi.png`.
The demo store had one agent (`onboarding_agent`), so the table shows one row. PNGs are not committed to `docs/design/screens/` (the old ones there show the pill header).

## Not done (BACKLOG rows added)

- WP-UX2: agent detail page, Analytics page, Alerts page, Sign-off list, old-URL 303 redirects, other pages switched to the components, span tree partial.
- WP-UX3: the seven placeholder pages (each with its flag and permissions), Playground.
- `console.js` is about 60 lines added (spec said 40 max).
- No browser test of the drawer focus behaviour (only the server HTML is tested); I checked the render in screenshots only.

## Open questions for the owner

1. Is a placeholder flag (one flag for seven links) acceptable until WP-UX3 gives each page its own?
2. Should "Sign-off" get its own list page in WP-UX2 first, since the badge counts waiting cases?
3. Letters in the collapsed sidebar are ambiguous (many items start with A, C, I). Use short codes or hide labels completely?

## Review notes

- Search runs `agent_event` by exact `trace_id` on each keystroke after 300 ms (2+ characters); on Delta that is a SQL call per search. Bounded by `limit=50`. A `trace_id` index or a minimum of 8 characters for the trace lookup may be wanted.
- The drawer endpoint rebuilds `agent_cards` (one `agent_event` query per agent). Fine for a few agents; WP-UX2 should cache or narrow it.
- No secrets, no network, no `exec`, no 500 path found: bad input is `ListingError` or `ConsoleInputError` (400). R1 to R3 not touched.

## Files touched

New: `src/supervisor/console/{listing,nav,search,agents_list}.py`; templates `_c_sidebar`, `_c_topbar`, `_c_who`, `_c_header_top`, `_c_table`, `_c_drawer`, `_agents_list`, `_agent_drawer`, `_search_results`, `search`, `soon` (all `.html`); `tests/console/test_shell.py`, `tests/console/test_components.py`; `HANDOFF_WP_UX1.md`.
Shared files, additive edits only: `config.py` (block `# --- WP-UX1 ---` at the end of the class), `core/rbac.py` (4 `ROUTES` rows), `console/routes.py` (`render()` passes `side_nav` and `nav_groups`; agents routes; search and soon routes; `section` on metrics and inbox), `console/readmodels.py` (`shell()` additions, `signoff_waiting`), `console/i18n.py` (block at the end), `templates/base.html` (rewritten, old header moved to `_c_header_top.html`), `templates/_ui.html` (macros appended), `templates/overview.html`, `templates/agents.html`, `static/console.css` and `static/console.js` (appended), `tools/console_screenshots.py`, `docs/console.md`, `README.md`, `CHANGELOG.md`, `BACKLOG.md`.
Merge hint: WP-UX2 and WP-UX3 will both touch `routes.py`, `i18n.py`, `rbac.py`; merge one at a time as the spec says.
