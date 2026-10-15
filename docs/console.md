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

One header row: brand mark, pill navigation with counts (agents, open cases; the case count
turns red when a case is critical), environment badge (`laptop`, `databricks_app`, plus
`demo data` when `DATA_DIR` is a demo store), inbox, language, theme, the role pill and the
avatar (the menu shows the user id, the sign-in method, the roles and, on the laptop, the
dev user switch). Every screen opens with a one-sentence purpose box and a "why" line.

Brand colour: one CSS token, `--brand` in `static/console.css` (E4002B, a placeholder for the
Techcombank brand-guide value). Gold is used only for evidence and signatures. Status is
always a word in a coloured pill.

## Screens

| Screen | URL | What it shows | Actions |
|---|---|---|---|
| Overview | `/console/` | Greeting by the ICT hour with the live counts (agents under supervision, actions stopped today, cases needing a decision, nearest SBV clock); what Supervisor is; the three pillars; four numbers from the stores (gate decisions today and median latency; stops split blocked / paused; open cases with the critical count; evidence chain entries, signed root, anchor, last verify); latest gate decisions (the newest stops always included) linked to their cases; the demo-data line on a demo store. | - |
| Agents | `/console/agents` | One card per agent, attention first: state pill with the rule or person that paused / quarantined it, owner, risk, Decision 33 class (registry, else the Onboard proposal), model and judge family (`mock` labelled), lifecycle stepper (Discover .. Operate; registered = Operate, SHADOW = Launch), coverage bar (capabilities on; else the daily metric; else gated / seen tool calls; planned capabilities named, never counted), open cases, tools (count, money-moving, fail mode). | The one relevant action with its rule under it: Pause now (one click); Approve resume (shows the pending approval, who you are, disabled after your own approval); Quarantine / Release (admin, reason required). These call the gateway state machine in-process. |
| Cases | `/console/cases` | Severity, agent, a plain headline built from the stopping rule and the stopped tool (rule id and case id under it), opened-by pill (gate / judge / monitor / person), SBV 24 h clock as a bar and text, status, assignee. Filters: severity, agent, opened by; Open / Archive / All. Refreshes every 30 s. | Refresh cases: the explicit case intake (a GET never writes). |
| Case | `/console/cases/<id>` | Header card (pills, headline, one-line explanation with amount and detect-to-stop time, SBV 24 h and 5-day clocks, Decision 33 line, regulation). Pill tabs (htmx partials at `/console/cases/<id>/tab/<name>`; `?tab=` for a full page): Story (timeline from stored rows only, rules and judges, masked transcript excerpt), Rules & judges, Transcript, Evidence, Case file. | Right column "Your decision": flow open -> triaged -> contained -> closed, the two-person rule, Assign to me, Mark triaged + note, Contain + note, Sign-off (high / critical), Close (disabled with the reason until allowed), comment, ITSM ticket. Evidence card: Verify again, Case file (`/casefile.html`, `/casefile.json`, read-only views). |
| Sign-off | `/console/cases/<id>/signoff` | Sign-offs so far with the statement text verbatim. | Approve or reject with a statement; the signer ticks "I sign this statement as myself". |
| Evidence | `/console/evidence` (`/console/export` redirects) | Entries, last signed root (key id, dev / managed key), last anchor; every lane as squares (one per entry, newest 60, "+N" for earlier ones; colour by record type; root lane gold, signed roots filled); "How to verify offline" with the cmd commands; earlier exports. | Verify now; Export chain (zip: chain export + offline verify report; recorded on the chain); Build audit pack (zip: chain export + verify report + case files + judge eval report + manifest). Auditor, reviewer, approver, admin. |
| Onboard | `/console/onboard` | Six-step wizard (stage from the artefacts of the latest run), last-run cards: profile (Decision 33 proposal, tools, money-moving, human approval step in code), plan (capabilities, rules proposed, judges), launch report (GO / NO-GO, red-team catch rate, false alarms, branch), links to the artefact files. | Start (off by default, `CONSOLE_ONBOARD_ENABLED=1`): runs `supervisor.onboard` in a background thread on the console's own store and chain writer, one run at a time, progress every 2 s. MockChat (labelled) unless the configured LLM answers the preflight probe. Reviewer, owner, admin. |
| Compliance | `/console/compliance` (off by default, `CONSOLE_COMPLIANCE_ENABLED=1`; off = 400 and no nav entry) | Advisory obligations matrix per agent (the three demo agents and onboarded products with a launch-pack matrix): counts by status, Decision 33 class, open questions, threshold findings, rows with filters (instrument, status, duty), and one page per obligation (Vietnamese text, sources, controls). Advisory only. See `docs/compliance-advisor.md`. | Read-only. |
| Integration | `/console/integration` | Off by default (`CONSOLE_INTEGRATION_ENABLED=1`). List of integration reports (agent, framework, readiness, patch count); one report shows the score per area, what was found (framework, LLM calls, tools with risk class, data access, PII fields, tracing), what Supervisor needs (semantic attributes, gate call sites, MCP proxy, catalogue, settings, test plan) and each patch as escaped text (`/console/integration/{name}/patches/{file}` serves it as `text/plain`). Read-only; a malformed report shows a message. | - (permission `onboard.view`) |
| Assurance | `/console/assurance`, `/console/assurance/<run_id>` | Off by default (`CONSOLE_ASSURANCE_ENABLED=1`; off = 404 and no nav entry). Runs newest first (time, target spec, counts, mock label); per run: pack, dimension, target, status, each metric against go / no-go, data mode, items, reasons, and the hash of the `assurance_result` chain record (links to Evidence; Evidence has no per-record page). | Read only. Run packs with `python -m supervisor.assurance run all --target demo --out out\assurance`. |
| Health | `/console/health` | A plain setup summary (mode and store, identity, judge model or mock, signing key, anchor, Databricks, Onboard start) and the local preflight checks with status pills and fix hints. Secrets are never shown. The live Databricks checks write probes, so they run only from `python -m supervisor.cli preflight`. | - |
| Metrics | `/console/metrics` (footer link) | Oversight metrics per agent with sparklines; chain lanes and heads; gateway latency counters. | Verify the whole chain now. |
| Inbox | `/console/inbox` (envelope in the header) | Notices from the case workflow (new case, sign-off needed, case closed). | Mark read. |

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
| operator | Read pages, run case intake, verify the chain |

### Role matrix

<!-- ROLE-MATRIX:BEGIN -->
| Permission | What it allows | viewer | reviewer | approver | owner | admin | auditor | operator |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `console.view` | Open console pages (queue, case, agents, evidence, case files) | x | x | x | x | x | x | x |
| `health.view` | Health page | x | x | x | x | x | x | x |
| `metrics.view` | Metrics page | x | x | x | x | x | x | x |
| `onboard.view` | Onboarding page, status and generated files | x | x | x | x | x | x | x |
| `compliance.view` | Compliance tab (advisory obligations matrix, read-only) | x | x | x | x | x | x | x |
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
| `onboard.start` | Start an onboarding run |  | x |  | x | x |  |  |
| `agent.pause` | Pause an agent (D04) |  | x | x | x | x |  |  |
| `agent.resume` | Approve a resume (D04, two people) |  | x |  | x | x |  |  |
| `agent.quarantine` | Quarantine an agent |  |  |  |  | x |  |  |
| `agent.release` | Release an agent from quarantine |  |  |  |  | x |  |  |
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

Every POST under `/console` writes one row to the append-only table `console_action`
(allowed, denied or failed), and so do the `/gate` control routes (pause, resume, quarantine,
release), also when `API_RBAC_ENABLED` is off (an unidentified caller gets one `denied` row, detail `identity_unknown`, actor_kind `unverified`). Columns: `action_id`, `ts`, `request_id`,
`actor`, `actor_kind`, `auth_method`, `roles`, `permission`, `method`, `path`, `target_kind`,
`target_id`, `outcome` (`ok`, `denied`, `error`), `before_hash` and `after_hash` (SHA-256 of
the canonical target row: the case row, the agent row with its active gate controls, or the
notice row), `detail` (an error class or a denial code, never free text typed by a user). The
rows are in the audit pack (`console_action.jsonl`, with the count in `manifest.json`). A
failed audit write is logged and shown as a WARNING in the page message; it never causes a 5xx.
`CONSOLE_AUDIT_ENABLED=0` writes nothing.

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
| `CONSOLE_ONBOARD_ENABLED` | `0` | WP12: the Onboard screen may start runs (new feature, off by default) |
| `ONBOARD_COMPLIANCE_ENABLED` | `0` | WP14: the onboarding run also writes `compliance_matrix.json`, `.md` and `.html` (advisory only) |
| `CONSOLE_COMPLIANCE_ENABLED` | `0` | WP14: the Compliance tab (`/console/compliance`, read-only, advisory only) |
| `CONSOLE_INTEGRATION_ENABLED` | `0` | WP15: the Integration tab (reads reports from `INTEGRATION_REPORTS_DIR`, default `<data_dir>/integration`; off: no nav link, routes answer HTTP 400) |
| `ONBOARD_ADVISOR_ENABLED` | `0` | WP15: `supervisor.onboard` also writes `integration_report.*` and `integration_patch_NN_*.patch` (never applied) |
| `CONSOLE_ASSURANCE_ENABLED` | `0` | WP17: the Assurance screen (`/console/assurance`, run list and per-pack results) and its nav entry; off: the paths answer 404. Windows cmd: `set CONSOLE_ASSURANCE_ENABLED=1` |
| `ASSURANCE_DATA_DIR` | (none) | WP17: bank-supplied datasets, one folder per pack: `<dir>\<pack_id>\`. Windows cmd: `set ASSURANCE_DATA_DIR=C:\supervisor\assurance-data` |
| `OSV_DB_PATH` | (none) | WP17: local OSV vulnerability dump for the `osv_offline` pack. Windows cmd: `set OSV_DB_PATH=C:\supervisor\osv\osv-db.json` |
| `ASSURANCE_LICENCE_ALLOW` | `MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,PSF-2.0,ISC,Unlicense,0BSD,MPL-2.0,MIT-0` | WP17: licences the dependency licence pack accepts (comma separated). Windows cmd: `set ASSURANCE_LICENCE_ALLOW=MIT,Apache-2.0` |
| `ASSURANCE_LAUNCH_ENABLED` | `0` | WP17: Onboard Launch runs the agent-target packs in its sandbox; a failed, errored or skipped pack with launch gate `required` makes Launch NO-GO and adds `assurance_report.md` and `.json` to the launch pack. Windows cmd: `set ASSURANCE_LAUNCH_ENABLED=1` |
| `ASSURANCE_JUDGE_GATE_ENABLED` | `1` | WP17: a non-mock judge (`JUDGE_ENABLED=1` with real models) starts only when every pack with `judge_gate` has a latest result `ok` or `warn` for `judge:<tier-1 model id>` at the current pack version; else the judge sweep stays off and the log names the missing packs. Mock judges are exempt. Windows cmd: `set ASSURANCE_JUDGE_GATE_ENABLED=0` to switch the check off |
| `CONSOLE_EXPORT_DIR` | `<DATA_DIR>\exports` | Audit packs. On the App this is ephemeral: download the zip at once. |
| `NOTIFY_WEBHOOK_ENABLED` | `0` | Webhook stub: queues notices (`status=queued`), never sends |
| `API_RBAC_ENABLED` | `0` | WP18: enforce the role matrix on the agent-facing `/gate` read routes (state, metrics). Gate control routes and console routes always enforce |
| `CONSOLE_AUDIT_ENABLED` | `1` | WP18: write one `console_action` row per mutating action (default on) |

Case intake as a job (only when the app is not running, single chain writer):
`python -m supervisor.jobs.case_intake`.
