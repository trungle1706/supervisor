# REVIEW WP-UX2: console page migrations

Reviewer: Opus (front end, accessibility, security; senior Python). Branch `wp-ux2-pages`,
base `wp-ux1-shell` at 7e55d89, reviewed head a7ad34e, head after review fixes: see the
commit list below. Not pushed, not merged, no history rewrite.

## Verdict

**APPROVE. The branch is ready to merge after the fixes below.** Security, RBAC and audit
are correct. The `?tab=` full page and the htmx partial give the same body, and tests prove
it. I found and fixed six significant problems: the redirect query string, a toolbar bug,
the drawer squeeze, card cost, a 400 after a successful write, and labels. The residual
items are minor.

## Review commits (each ends with the Fable 5.1 and Claude-Session lines)

| Commit | What |
|---|---|
| 06018fe | 303 redirects pass only known query keys; the redirect's own `tab` wins |
| 9e25ce4 | `card_of()` builds one card (`only=agent_id`); public `readmodels.allowed_tools()` |
| f44aea1 | Analytics toolbar shows the effective window; tab click swaps `#main` so the toolbar follows the tab; tab ids + `aria-controls` |
| f1f26ef | i18n keys (window line, "Signatures (of 2)" / "0/2 signatures", alert window in VI); drawer beside the list only from 1600 px; `test_ux2_review.py` |
| f4b1574 | List answer after ack / mark read falls back to the new last page (it gave a 400 after a successful write); databricks_app-mode test |
| b271940 | Redirect keeps a bad *known* value (URL-encoded) so the target page still answers 400, as it did before |

## Findings

| # | Area | Severity | Finding | Status |
|---|---|---|---|---|
| 1 | Security | Significant | `_moved()` copied the whole caller query string into `Location`, and the caller's `tab` overrode the redirect's tab. The path is fixed, so this was not an open redirect to another host. But unknown keys passed through. | Fixed: only `lang, days, agent, sort, dir` pass (`agent_id` is renamed to `agent`). Values are URL-encoded (no CR/LF in the header) and capped at 256 chars. The redirect's `tab` always wins. Test: `test_redirect_passes_only_known_keys_and_keeps_its_tab` |
| 2 | Security | OK | Every new GET is in `rbac.ROUTES` with the right permission. `test_rbac_matrix` passes in both directions. | No change |
| 3 | Security | OK | The lifecycle POST still has RBAC and the two `console_action` rows (`test_lifecycle_controls_moved_here_with_their_rbac`, `test_audit_two_rows`). Alert ack still has `alert.ack`, the two rows and the `alert_ack` record (`test_alerts_panel`, `test_viewer_cannot_ack_from_the_page`). | No change |
| 4 | Security | OK | Autoescape is on. There is no `\|safe`, no inline script or handler, and no external URL in the changed templates (grep + tests on every new page in EN and VI). Messages are escaped (`message_html`). Template names come from allow-listed tabs only. | No change |
| 5 | Security | OK | A flag-gated tab answers 400 with the flag name and the CLI line (the spec pattern). The flag check runs before the agent lookup, so a flagged tab does not show if an agent exists. A role without the permission gets 403. | No change |
| 6 | Security | OK | The Traces tab shows trace id, time, tool names, counts and the stop action only. It shows no args or payloads. | No change |
| 7 | Correctness | OK | `?tab=` full page = htmx partial, for every agent tab and every analytics tab (tests). | No change |
| 8 | Correctness | Decision applied | `waiting_approvals()` includes cases with 0 signatures. This is correct under the four-eyes rule: a high or critical case needs 2 signatures. | Kept. The column is now "Signatures (of 2)" and the cell says "0/2 signatures" (VI "0/2 chữ ký"). Test: `test_zero_signatures_is_labelled_of_two` |
| 9 | Correctness | Significant | Analytics: a blank range means "each tab's own window", but the toolbar did not say which window that was. | Kept the semantics. `analytics.effective_window()` gives a line in the toolbar: "Window: from .. to (n days, UTC) (default)", "every stored day, from .. to" (metrics) or "live counters" (latency). Test: `test_toolbar_always_names_the_effective_window` |
| 10 | Correctness | Significant (bug) | The toolbar form keeps `tab` in a hidden field. A tab click swapped only `#tab-body`, so a range or agent change after a tab click went back to the first tab. | Fixed: Analytics tabs `hx-get` the full page with `hx-target/hx-select="#main"`. The `tabs` macro has a new optional `select` argument. Test: `test_tab_click_swaps_main_so_the_toolbar_follows_the_tab` |
| 11 | Correctness | Significant | After a successful ack (filter `status=open`) or mark-read (`status=unread`) of the last row on the last page, the answer was "page N does not exist" (400). This hid a write that had succeeded. | Fixed: `_list_after_write()` shows the new last page. Test: `test_ack_of_the_last_row_on_the_last_page_answers_the_new_last_page` |
| 12 | Correctness | OK | Sort keys are allow-lists (`parse_sort` falls back to the default). `paginate` limits the page (1..pages, size ≤ 100). A bad number gives 400. The Tools sort is checked against `SORTS`. | No change |
| 13 | Performance | Significant | `card_of()` built every agent card (several queries per agent) to pick one, on every page, tab and lifecycle answer. | Fixed: `agent_cards(..., only=agent_id)`, the same fix the UX1 review made on the drawer. Test: `test_agent_page_builds_only_its_own_card` |
| 14 | Code | Minor | `_policy` read the private `readmodels._allowed_tools` (`noqa: SLF001`). | Fixed: public `readmodels.allowed_tools()` + test |
| 15 | Correctness | Minor, accepted | Trace to case mapping: the first 50 cases of the agent in service order (severity, age). Each case costs one `links()` query (at most 50). At most 2000 events and 2000 verdicts. A trace whose case is outside those 50 shows no case link. | Bounded. Not changed (see residual risks) |
| 16 | A11y / layout | Significant | At 1360 px with the drawer open, the list kept about 576 px (248 sidebar + 56 padding + 480 drawer). | Fixed: the drawer sits beside the list only from 1600 px (it needs 1544 px). Below 1600 px it lies over the list. Screenshots re-taken. Test: `test_drawer_sits_beside_the_list_only_from_1600_px` |
| 17 | A11y | Minor | The tabs had no ids and no `aria-controls`. | Fixed: with `panel`, each tab gets `id="<panel>-tab-<key>"` and `aria-controls`. The agent, case and analytics pages pass `panel='tab-body'`. The Analytics panel has `aria-labelledby` (it is re-rendered on every swap). Roles, roving `tabindex`, arrow/Home/End keys (UX1 `console.js`), `aria-sort` (`_c_table`, Tools headers), `aria-live` on lists: already present |
| 18 | i18n | Minor | Alert window text "x/y in n s" was English on VI pages. | Fixed (`alert_window_val`). New test: every WP-UX2 key has a distinct VI text, dynamic keys (`alerts_st_*`, `inbox_st_*`, `atab_*`, `an_tab_*`) exist, and 7 VI pages show no WP-UX2 English label |
| 19 | Both modes | OK | New pages render in `databricks_app` mode with SSO headers, and the service principal still cannot act (`test_ux2_pages_render_in_databricks_app_mode`). No new table, so there is no DDL. | Added test |

## Tests

| | Result |
|---|---|
| Before review (head a7ad34e, this host) | 3534 passed, 29 skipped (the handoff said 3536 / 27; the 2 extra skips depend on the environment) |
| After review | **3552 passed, 29 skipped** (+18 new: redirects 1, agent detail 2, analytics 2, sign-off 1, alerts 1, `test_ux2_review.py` 11) |
| Lint | `ruff check` and `ruff format --check` clean |
| Existing test changed | `test_redirects.py::test_tools_redirect_keeps_filters_and_sort`: it now expects `agent=payments` (renamed) in place of `agent_id=payments`. The Analytics page reads both, so the behaviour is the same |
| Screenshots | 57 shots (EN, VI, `-full`, dark), re-taken after the fixes into `/home/trung/supervisor-testbed/phase3/ux2-shots/`. Port 8771, scratch store, server stopped after. Checked by eye: alerts drawer at 1360 px (overlay, table keeps its width), analytics Tools VI (window line) |

## Residual risks (not fixed, minor)

- Trace to case link only covers the first 50 cases of an agent (finding 15). The WP-UX3 trace viewer will replace this link.
- Agent and case pages: the tab panel has no `aria-labelledby`, because htmx swaps the panel's inside and the label would go stale. The tabs have `aria-controls`. There is no browser test of focus after the Analytics `#main` swap. htmx puts focus back on an element with the same id, and the tabs now have ids, but no browser test proves this.
- Alerts drawer: Acknowledge posts without the list filters, and the drawer still shows "open" after the ack (a second click gives the usual version-conflict 400). The `<form>` sits inside a `<p>`, which is invalid HTML nesting. The button still works.
- The Gate and Tools tabs show the window twice: once in the toolbar, once in the tab's own hint.
- `/console/analytics/tab/{tab}` is still a route (RBAC and tests), but the Analytics page does not use it now. You can keep it or remove it.
- At commit f44aea1 alone, the window line shows raw key names. The i18n keys come in the next commit (f1f26ef). This does not matter after a merge.
- The pytest run shows one third-party warning (Starlette `httpx` deprecation).

## Merge notes for the integrator

- Order: UX1, then UX2 or UX3 one at a time.
- **This branch removes** `templates/tools.html` (renamed to `_tools_agents.html`), `templates/metrics.html` (renamed to `_analytics_tab_metrics.html`) and `templates/_alerts_panel.html`. If WP-UX3 links to or includes any of them, change it to `/console/analytics?tab=tools|metrics` or `/console/alerts`.
- Shared blocks that WP-UX3 also edits on its sibling branch:
  - `console/routes.py`: one `# --- WP-UX2 ---` block before `/home`. Edits in place: `_queue_data`, `queue`, `agent_action` answer, `metrics`/`tools` 303 redirects, `_moved` + `_MOVED_KEYS`, inventory/inbox rows, `alert_ack`, `_list_after_write`, and the import of `ListingError`. If UX3 adds redirects with other query keys, add those keys to `_MOVED_KEYS`.
  - `console/i18n.py`: a `_T.update` block `# --- WP-UX2` before `translator`. Put the UX3 block next to it. Do not merge the two blocks. `test_ux2_review.py` finds the WP-UX2 block by its marker up to `def translator`, so keep the UX3 block before the WP-UX2 block or give it its own `_T.update`. A UX3 block between the WP-UX2 marker and `translator` will count as WP-UX2 keys.
  - `core/rbac.py`: labelled `# --- WP-UX2 ---` block.
  - `console/nav.py`: Alerts and Sign-off hrefs, one `analytics` item (code `AN`), `tools` and `metrics` items and codes removed. If UX3 removes `soon-*` placeholders, keep `nav.CODES` the same.
  - `templates/_ui.html` `tabs` macro (owned by UX1): new optional `select` argument. With `panel` set, each tab gets `id` + `aria-controls` after `class`. Existing tests match `data-tab="x" class="on"`, so keep that order.
  - `static/console.css`: the drawer breakpoint line changed from 1280 px to 1600 px (UX1 drawer block).
  - `console/readmodels.py`: `signoff_waiting` uses `CaseService.waiting_approvals`, and there is a new public `allowed_tools()`.
- WP-UX3 trace viewer: the agent Traces tab links to it only if a route that starts with `/console/traces/` exists (`agent_detail.traces_page_exists`).
- Copy `ux2-shots/` PNGs into `docs/design/screens/` only after all UX WPs are merged (spec "Screenshot smoke").
