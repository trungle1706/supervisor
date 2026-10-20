# REVIEW WP-UX3: new console pages and the Playground dry run

Reviewer: Opus (application security, front end, senior Python). Branch `wp-ux3-new-pages`,
worktree `agent-a9196be3bbd0ef7b0`. Base `wp-ux1-shell` 7e55d89, reviewed head ead0f49, head after
review d1d2fbd. Not pushed, not merged, no history rewrite.

## Verdict

**ACCEPT with fixes applied.** The read surfaces are sound: only masked columns, no raw table,
no secret, autoescape on, no `|safe`, every route in `rbac.ROUTES`, flags off by default.
I found two significant defects and fixed them: (1) a hung Playground dry run could take the
worker threads of the real gate; (2) a deep span chain gave HTTP 500 on the trace viewer. I also
made the scan caps settings, added the planted-raw-value and no-log tests the brief asks for, and
fixed a header role label.

## Review commits (each has the Fable 5.1 and Claude-Session trailers)

| Commit | Change |
|---|---|
| f5daa59 | Dry runs get their own 2-worker pool (`Gateway._dry_pool`); test proves that 10 hung dry runs give the timeout message and a real check still gets a worker (the test fails on the old code) |
| 3ae069f | `traces.build_tree` walks iteratively and stops at `MAX_SPANS`; test with a 1500-span chain, direct and through the page (old code: `RecursionError`, HTTP 500) |
| e82da89 | `CONSOLE_SCAN_CAP` (20000, 100-200,000) and `CONSOLE_TRACE_SCAN` (5000, 100-50,000) replace the fixed constants in decisions, audit log, traces; docs/console.md, BACKLOG |
| 8210229 | `tests/console/test_ux3_review.py`: a sentinel planted only in `agent_event_raw.args_raw` / `result_raw` is absent from all pages and drawers, and a spy proves no page queries that table; Playground POST (good and bad JSON) writes no typed value to any log record; README row |
| d1d2fbd | `readmodels.main_role` knows `operator` (+ `role_operator` EN/VI): the header showed "viewer" for an operator, which was wrong on the Playground (outside WP-UX3, one line each) |

## Findings

| # | Sev | Area | Finding | Status |
|---|---|---|---|---|
| 1 | High | Playground / gate | `evaluate_only` ran on the gate's own pool (`_pool`, 8 workers). After the 2 s timeout the future keeps its thread. A slow or hung `FactSource` in a dry run therefore took a gate worker; 8 such runs starved real `check` calls, which then timed out and took the fail mode (block for money tools). An operator could degrade production by accident. | Fixed f5daa59 |
| 2 | High | Traces | `build_tree` was recursive. A trace with more than about 1000 nested spans (span ids come from the SDK / OTLP, so a caller controls them) raised `RecursionError`: HTTP 500 on `/console/traces/<id>` and the span partial. Also the walk visited every span before the cap. | Fixed 3ae069f |
| 3 | Med | Performance | Scan caps were constants (20,000 / 5,000). | Fixed e82da89 (settings) |
| 4 | Med | Tests | The "raw" capture-level test planted the phone number in `args_masked`, not in the raw table, so it did not prove that the raw column is never read. No test on logging of Playground args. | Fixed 8210229 |
| 5 | Low | Shell | Operator shown as "viewer" in the header. | Fixed d1d2fbd |
| 6 | Low | Playground | `masked_preview` builds a masker per request when the gateway has none (`make_masker`); with `MASKER_KIND=presidio` that is slow and outside the 2 s timeout. The preview runs in the request thread. | Open (BACKLOG candidate): cache the masker on the context |
| 7 | Low | Playground | The answer echoes `error` text `"{type}: {exc}"`. Engine messages carry field names only (checked every `PredicateTypeError`), but a bank `FactSource` exception message could carry a value. Escaped, not logged, not stored. | Open, accept for pilot |
| 8 | Low | Cost | Each decisions list / drawer request: 1 event scan + 5 verdict scans + a full `case_link` scan + `rules_index`; the drawer recomputes the whole list for prev / next. Traces list: 2 scans. Fine for a pilot. | Open (BACKLOG row exists) |
| 9 | Info | Traces | Events with no `trace_id` group under the string `"None"`; its link gives 400 "not found". | Open, cosmetic |
| 10 | Info | Masker | The Playground preview and trace excerpts are only as good as the masker; the known testbed gap (names, addresses not masked) applies, e.g. a typed name can show in the preview. | Residual risk |

## What I checked and found correct

| Item | Result |
|---|---|
| `_evaluate` split, line by line | Identical logic moved; `_decide` keeps `_warm`, `prune`, `_remember`, `pause`, `_record`, metrics, Tier 0b. `_dry` calls only `policy.current()`, `states.get_state()` (read cache fill only), `risk_class`, `_now_us` (clock read), `_pre_redact` (pure), `_evaluate`. Window rules (`aggregate` / `prior`) are skipped before `_rule_matches`, so `self.windows` is never read or written. `_redact(dry=True)` leaves `_redact_hint` alone. No nonce / ingress path involved. Not under the gate lock (good: it does not delay the gate). |
| Fingerprint tests | SHA-256 over every table in `schema/model.yaml` (chain tables included) + evidence count + metrics + window sizes + agent states + hint cache, with a guard test that a real check changes it. Adequate. |
| Oracle risk | `playground.run` = reviewer, approver, owner, admin, operator. It answers only what the read-only Policies page (all roles) already shows; no per-agent RBAC exists in the product. Acceptable. |
| Audit | Two `console_action` rows; `ok` row `detail` = `in:<24 hex keyed HMAC>`; error rows carry the exception class only. `audited` change: `audit_detail` is read only when the outcome is `ok`; no other route sets it (grep), so other POSTs keep `detail=None`. Full suite (all audit tests) green. |
| Logging | No `log`/`print` call added in the diff; new test proves no typed value in log records. |
| App mode | `PLAYGROUND_ALLOW_APP=1` checked in the route and in the nav. |
| Data exposure | Decisions: keyed args hash and key names only. Traces: `digest` = no text; `masked`/`raw` = masked column re-masked; no masker = no text; raw table never read (spy test). Credentials: only `key_id`, `state`, `expires_at`, `valid_at()`; store errors show the class name; principals shortened. Integrations: host name and booleans only. Users: admin only; role map and group names, SP shortened; no more than the dev picker shows. Audit: fixed `detail` notes only. |
| Templates | Autoescape on (`select_autoescape(["html","j2"])`), no `|safe` / `Markup` in the diff, no inline script (existing CSP scans cover the new files). |
| RBAC | 18 routes in `rbac.ROUTES` with the stated permissions; `test_rbac_matrix` and the docs matrix test green. RBAC runs before the flag check, so a denied role gets 403 and learns nothing about the flag. Flag off = 400 naming only the page and its flag. |
| Input | All filters through allow-lists or `ID`/`TOKEN` patterns; sort columns allow-listed; `parse_int` bounds; `paginate` gives 400 out of range; Playground JSON size (16 KB / 4 KB) and depth (8) limits; htmx-only POST. |
| Tree | Cycles, orphans and the 500 cap handled (now also depth). |
| Delta | `test_ux3_delta.py` runs the read models through the real `DatabricksRestExecutor` + `SqlTableStore` / `SqlStateStore`; the `MirrorFake` executes the generated statement strings (only backticks and catalog prefix rewritten) and returns strings, so typed casting is exercised. Accept. |
| i18n | `(en, vi)` tuples make one-sided keys impossible; no duplicate keys (AST check); no empty value; 4 keys equal in both languages are product terms (principal, pager, ITSM, SCIM). `test_i18n.py` + the render test (no raw key) green. |
| Accessibility | As WP-UX1: labels, `aria-sort`, `aria-live`, `aria-level` / `aria-current`, words in pills. Screenshots: no horizontal scroll at 1360 px, VI labels fit, dark pills readable. |

## Decisions (as instructed)

* Keep `CONSOLE_AUDITLOG_ENABLED` (the old name means "write audit rows").
* Keep the brief's permissions (`audit.view` auditor + admin; `credentials.view` owner + admin).
* Keep `CONSOLE_NAV_PLACEHOLDERS` (WP-UX2 may still use it).
* CSV export stays in BACKLOG.
* Two span-tree components stay for now (`_c_spantree.html` / `readmodels.span_tree` from the WP-UX1
  review and `console/traces.py` for the viewer); BACKLOG row records the choice.

## Tests

| | Count |
|---|---|
| Handoff (head ead0f49) | 3589 passed, 29 skipped |
| After review (d1d2fbd), `uv run python -m pytest -q` | **3595 passed, 29 skipped** (6 min 25 s; 1 warning: APScheduler thread exception, not from this WP) |
| New in review | `test_evaluate_only.py` +1, `test_ux3_more.py` +1, `test_ux3_pages.py` +1, `test_ux3_review.py` 3 |
| `ruff check`, `ruff format --check` | clean |

## Screenshots

Re-taken after the fixes: `/home/trung/supervisor-testbed/phase3/ux3-shots/` (25 screens plus
`-full`, port 18791, store seeded in the reviewer scratchpad). The Playground shot shows the empty
form (no dry-run answer in the shot); the audit shots show the rows the screenshot run writes.

## Residual risks

1. A masker miss shows in the Playground preview and trace excerpts (finding 10).
2. Dry-run pool: 2 hung dry runs make further dry runs time out for as long as the fact source
   hangs; the real gate is not affected. A hung `FactSource` is still a real-gate risk on its own.
3. Python-side filtering over a capped scan: on a busy Delta store an old decision can fall out of
   the list (the page says "capped"). Needs range pushdown (BACKLOG).
4. Playground on the shared App is still an owner decision (`PLAYGROUND_ALLOW_APP`).

## Merge notes for the integrator

Merge WP-UX2 (`wp-ux2-pages`) and WP-UX3 one at a time. WP-UX2 removes `tools.html`,
`metrics.html`, `_alerts_panel.html` and adds its own routes, i18n, rbac and nav blocks.

| File | Expected conflict | How to resolve |
|---|---|---|
| `console/routes.py` | WP-UX3 block before "health"; import list | Keep both blocks; union the imports (alphabetical) |
| `console/i18n.py` | WP-UX3 block at the end of `_T`; review added `role_operator` after `role_service` | Keep both; run `test_i18n.py` (duplicate keys silently override: check with an AST pass) |
| `core/rbac.py` | `PERMISSIONS` and `ROUTES` appends | Keep both; regenerate the docs matrix; run `test_rbac*.py` |
| `console/nav.py` | `GROUPS`, `CODES`, `PAGES`, `_visible` | Keep `page=` items; if WP-UX2 changes Tools / Metrics items, keep the WP-UX3 Playground item in Onboard |
| `console/readmodels.py` | `shell()["pages"]`, `ux3_pages`, `main_role` | Keep all |
| `static/console.css` | appended block | Keep both |
| `config.py` | WP-UX3 block (now 11 settings) | Keep both blocks |
| `docs/console.md`, `README.md`, `CHANGELOG.md`, `BACKLOG.md` | table rows | Keep both; regenerate the role matrix |
| `tools/console_screenshots.py` | `--ux3` and per-shot user | Keep both |

After the merge run the full suite; check `test_rbac_matrix::test_every_post_route_is_covered_by_an_audit_test`.
