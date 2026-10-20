# HANDOFF WP-UX3: new console pages and the Playground

Branch `wp-ux3-new-pages` (worktree `agent-a9196be3bbd0ef7b0`), from `wp-ux1-shell`. `wp-ux1-shell`
(with the Opus review commits, tip 7e55d89) is merged in (commit 3c008da). Not pushed, not merged
to main. Spec: `/home/trung/supervisor-testbed/phase3/CONSOLE_DESIGN_SPEC.md` (2.2, 2.5, 3.4, 4, 6).

## What was built

Eight pages replace the WP-UX1 placeholders. Each has its own flag (default off: HTTP 400 with a
message and no sidebar link) and its own permission. All are read-only except the Playground
POST, which still writes nothing but its two audit rows.

| Page | URL | Flag | Permission (roles) |
|---|---|---|---|
| Gate decisions | `/console/decisions` | `CONSOLE_DECISIONS_ENABLED` | `decisions.view` (all) |
| Traces, span viewer | `/console/traces`, `/console/traces/<trace_id>` | `CONSOLE_TRACES_ENABLED` | `traces.view` (all) |
| Playground | `/console/playground`, `POST .../run` | `CONSOLE_PLAYGROUND_ENABLED` (+ `PLAYGROUND_ALLOW_APP=1` in `databricks_app`) | `playground.run` (reviewer, approver, owner, admin, operator) |
| Policies | `/console/policies` | `CONSOLE_POLICIES_ENABLED` | `policies.view` (all) |
| Credentials | `/console/credentials` | `CONSOLE_CREDENTIALS_ENABLED` | `credentials.view` (owner, admin) |
| Users and roles | `/console/users` | `CONSOLE_USERS_ENABLED` | `users.view` (admin) |
| Audit log | `/console/audit` | `CONSOLE_AUDITLOG_ENABLED` (see decision 1) | `audit.view` (auditor, admin) |
| Integrations | `/console/integrations` | `CONSOLE_INTEGRATIONS_ENABLED` | `integrations.view` (all) |

| Item | Result |
|---|---|
| Gate decisions | `agent_event` (gate_decision) joined to tier-0 `verdict` rows by event id, `case_link`, `chain_entry`. Count tiles are the action filter; filters agent, action, rule, tool, time range, trace; 6 sortable columns; 25 per page; drawer tabs Details / Rules / Evidence with Copy JSON, prev / next, links to the case and the trace; no-JS fallback `?drawer=&dtab=`. Shows the keyed args hash and hashed key names only, never arguments. |
| Traces | List (agent, start, spans, verdict labels, status; filters agent, status, range, id). Viewer: span tree built from `span_id` / `parent_span_id` (events sharing a span id form one node; cycles, missing parents and a 500-span cap are handled), detail panel by htmx partial `/console/traces/<id>/span/<span>` or `?span=`, marks P / B / A / J, gate rule hits, Tier 0b findings and judge verdicts (mock and advisory labelled) attached to spans. Capture level decides text: `digest` none; `masked` and `raw` show the masked column only (the raw table is never read), re-masked on display; no masker means no text. Opens on the most severe stop. |
| Playground | New `Gateway.evaluate_only` (ADR D22). The decision logic moved into one function `Gateway._evaluate` that both `_decide` and the dry run use. A dry run writes no verdict, event or chain record, changes no agent state (`would_pause`), adds nothing to the windows, does not count in metrics, never raises, has the gate's 2 s timeout. Window rules (aggregate, prior) are not evaluated and are listed in `not_evaluated`. The answer shows decision, rule hits, masked preview of the arguments (or `transformed_args`); typed arguments are not echoed. Audit: the standard two `console_action` rows; the `ok` row `detail` is `in:<24 hex keyed HMAC of the arguments>`. |
| Policies | Deployed versions (hash, in force, from, git sha, rule count), tool and risk table, rules in force with filters (agent scope, action, severity, risk class, text) and sort; drawer tabs Details / YAML / Versions with regulation refs and the catalogue gate-rule capabilities for the risk class. |
| Credentials | WP20 key metadata (key id, state, issued from `k-<time>`, expiry, valid now), agents without a key, identity map (principals shortened), rotate CLI line, banner when `INGRESS_AUTH_ENABLED` is off. Reads `key_id`, `state`, `expires_at` and `valid_at()` only; a store error shows the class name, not message or path. |
| Users and roles | Users file (laptop) or `auth.yaml` role map (App), holders per role, role x permission matrix from `core/rbac.py`. |
| Audit log | `console_action` rows, filters actor, permission, outcome, target, range, sort, 25 per page, drawer with hashes before / after, request id, same-request rows. |
| Integrations | SIEM, webhook, pager, ITSM, SCIM: configured, enabled, last delivery, dead-letter count (files counted, never read), host name only; stubs labelled. |
| Both backends | Read models use only `ctx.tables.query` / `ctx.state.query`. `tests/console/test_ux3_delta.py` runs them through the real `DatabricksRestExecutor` + `SqlTableStore` / `SqlStateStore` on a `FakeStatementExecution` subclass that answers each Delta statement from the SQLite store as strings; results must equal the SQLite results. |
| Nav | `console/nav.py`: item `page=` key; flag on opens the real page, flag off shows the old placeholder only with `CONSOLE_NAV_PLACEHOLDERS=1`. Playground sits in Onboard. `CODES` extended (`PG`). `readmodels.shell()` gained `pages`. |
| i18n | About 190 new keys, EN and VI, in a `# --- WP-UX3` block. |
| Accessibility | As WP-UX1: skip link, `aria-sort`, `aria-live` result panels, labels on every control, tree items with `aria-level` and `aria-current`, words in pills not colour alone, tokens only. |
| CSP | No inline script, no external URL (the existing template scans cover the new files). |
| Docs | `docs/console.md` (section "New pages (WP-UX3)", flag rows, role matrix regenerated), README flags and Console row, CHANGELOG v0.3.0-pre row, BACKLOG rows, `docs/threat-model.md` 3.9, ADR `docs/adr/D22-playground-dry-run.md`, `docs/index.md`. |

Decisions to flag:

1. **Flag name.** The brief says `CONSOLE_AUDIT_ENABLED` for the audit page, but that name already
   exists (WP18: "write `console_action` rows", default on). I used `CONSOLE_AUDITLOG_ENABLED`.
2. **Permissions.** Brief wins over the spec where they differ: `audit.view` = auditor, admin
   (spec: also approver, reviewer); `credentials.view` = owner, admin (spec: admin, operator,
   auditor). `playground.run` = "operator and up" read as reviewer, approver, owner, admin,
   operator (not viewer, not auditor). The four read-only pages are open to all roles.
   Service principals (`NON_USER_OK`) do not get the new permissions.
3. **Own span tree.** The review added `_c_spantree.html` / `readmodels.span_tree` (nested
   `<details>`, no selection). The trace viewer needs selection, marks and verdicts, so it has its
   own tree (`console/traces.py`). Both exist now; see BACKLOG for the choice.
4. **Shared-file edits** (all small, labelled `# --- WP-UX3 ---`): `core/rbac.py` (8 permissions,
   17 routes), `console/routes.py` (imports; one block of routes before Health; the `audited`
   decorator copies `request.state.audit_detail` into the **outcome** row only), `console/i18n.py`,
   `config.py` (9 settings), `console/nav.py`, `console/readmodels.py` (`ux3_pages`, `shell()["pages"]`),
   `static/console.css` (appended), `adapters/auth/agent_creds_identity.py` (read-only
   `AgentIdentityMap.entries()`), `gateway/engine.py` (the `_evaluate` split). Two existing tests
   were changed on purpose: `tests/test_rbac.py::test_new_roles` (viewer and operator sets) and
   `tests/console/test_rbac_matrix.py::test_every_post_route_is_covered_by_an_audit_test`
   (adds `playground.run`, covered by `test_ux3_playground.py`).
5. **`traces.py` imports `readmodels._verdict_row`** (module-private, same package) to reuse the
   verdict classification.
6. **Spec items not built:** CSV export of the visible page (not in the brief; BACKLOG).

## Flags and commands

```
set CONSOLE_DECISIONS_ENABLED=1       (and TRACES, PLAYGROUND, POLICIES, CREDENTIALS, USERS,
                                       AUDITLOG, INTEGRATIONS; PLAYGROUND_ALLOW_APP=1 on the App)
python -m pytest tests/gateway/test_evaluate_only.py tests/console/test_ux3_pages.py ^
    tests/console/test_ux3_playground.py tests/console/test_ux3_more.py tests/console/test_ux3_delta.py -q
python tools/console_screenshots.py --ux3 --reseed --data-dir <scratch> --out <dir> --port <free port>
```

## Tests

| | Count |
|---|---|
| `wp-ux1-shell` tip (7e55d89), reviewer's count | 3464 passed, 29 skipped |
| After WP-UX3 and the merge | **3589 passed, 29 skipped** (`uv run python -m pytest -q`, 6 min), `ruff check` and `ruff format --check` clean |
| New | `tests/gateway/test_evaluate_only.py` (7), `test_ux3_pages.py` (53), `test_ux3_playground.py` (19), `test_ux3_more.py` (23), `test_ux3_delta.py` (5) |

Covered: dry run leaves a SHA-256 over every table, the chain heads, agent states, window store,
evidence sink and metrics unchanged (and a guard shows a real check does change it); decision
equals `check`; pause shows "would pause" and the agent stays RUNNING; window rules listed as not
evaluated and not counted; flag off = 400 and no nav entry, per page and independent; viewer 403
on the Playground, role checks per page; render of all 8 pages in EN and VI with one active
sidebar item; filters, sort, paging, bad input = 400 (never 500) per list page; drawers and
no-JS fallback; planted phone number absent from decisions, drawers, traces and Playground answer
and audit rows; planted key secret absent from the Credentials page and headers; loose key file
mode and unreadable store give a message without the path; digest, masked and raw capture levels,
no masker; tree shape with cycle, orphan and cap; Playground POST: two audit rows with the keyed
input hash and no args, htmx-only, bad JSON, size and depth limits, policy error shown as a
message; users page for the dev file and the App role map (FILL-ME never shown, SP shortened);
audit filters, drawer, paging, GET writes nothing; integrations with SIEM env (URL and token never
shown, dead letters counted); SQLite equals Delta results for decisions, traces, policies, audit;
RBAC coverage (`test_rbac_matrix`, `test_rbac`, docs matrix test) green.

## Screenshots

`/home/trung/supervisor-testbed/phase3/ux3-shots/` (25 PNG plus `-full` variants, port 18765,
store seeded in the scratchpad): decisions, decisions-drawer, traces, trace (viewer on a paused
trace with a Tier 0b finding), playground, policies, policies-drawer, credentials, users, audit,
audit-drawer, integrations in EN and VI (each as the role it needs), and `decisions-en-dark`.
Not committed to `docs/design/screens/`. Audit rows in the shots were written by a local seeding
script (synthetic). Credentials shows its empty state (no key file in the demo store).

## Not done (BACKLOG rows added)

CSV export; time and rule filters in Python over the newest 20,000 rows (needs store range
filters and indexes on Delta); the gate span has no parent span id (SDK should pass span ids);
after an htmx span swap the tree keeps the old highlight; Playground cannot evaluate window rules;
Credentials "last used" is not tracked by WP20; Policies has no link to the catalogue manifest
(a rule has no manifest id); Integrations pager, ITSM, SCIM are fakes; two tree components.

## Open questions for the owner

1. Is `CONSOLE_AUDITLOG_ENABLED` acceptable, or should the old `CONSOLE_AUDIT_ENABLED` be renamed?
2. `PLAYGROUND_ALLOW_APP=1`: allow the Playground on the shared App at all?
3. Should Credentials and Audit log be visible to more roles (spec: operator, auditor for
   credentials; reviewer, approver for audit)?
4. CSV export: wanted? It would need its own permission and audit row.
5. Remove `CONSOLE_NAV_PLACEHOLDERS` now that every placeholder has a page?

## Review notes (self-review of the diff)

* R1: nothing here blocks or pauses; the dry run only reports. R2: no raw argument is stored or
  shown; audit rows hold a keyed hash; traces re-mask text. R3: no network call added (the
  credentials page may read the configured Databricks secret scope when `INGRESS_KEY_STORE` says
  so, as the gate itself does).
* No `exec`, `eval`, `subprocess`; all ids and filters pass allow-lists or patterns; no 500 path
  found (every bad value is `ListingError` / `ConsoleInputError`); output ASCII only for CLI.
* `load_integration_settings()` reads the environment and the `.env` file in process (as the
  jobs do); nothing from it is shown except booleans and a host name.
* Cost: Gate decisions and the Traces list each run up to 5 or 2 large scans per request
  (5 verdict queries by action, 1 event query). Fine for a pilot; see BACKLOG for Delta.

## Files touched

New: `console/{decisions,traces,playground,policies_view,credentials_view,users_view,audit_view,integrations_view,ux3}.py`; templates `decisions`, `_decisions_list`, `_decision_drawer`, `traces`, `_traces_list`, `trace`, `_span_detail`, `playground`, `_playground_result`, `policies`, `_policies_list`, `_policy_drawer`, `credentials`, `users`, `audit`, `_audit_list`, `_audit_drawer`, `integrations` (`.html`); `docs/adr/D22-playground-dry-run.md`; tests `tests/gateway/test_evaluate_only.py`, `tests/console/test_ux3_{pages,playground,more,delta}.py`; `HANDOFF_WP_UX3.md`.
Shared, additive: `config.py`, `core/rbac.py`, `console/{routes,i18n,nav,readmodels}.py`, `static/console.css`, `gateway/engine.py`, `adapters/auth/agent_creds_identity.py`, `tools/console_screenshots.py` (`--ux3`, per-shot user cookie), `tests/test_rbac.py`, `tests/console/test_rbac_matrix.py`, `docs/{console,index,threat-model}.md`, `README.md`, `CHANGELOG.md`, `BACKLOG.md`.
Merge hint: with WP-UX2 merge one at a time; conflicts are in `routes.py`, `i18n.py`, `rbac.py` (append-only blocks), `nav.py` (`GROUPS`, `CODES`), `console.css`, `docs/console.md`.
