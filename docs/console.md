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

| Role | Can do |
|---|---|
| reviewer | Assign, triage, contain, close, comment, ITSM ref, sign off, pause, resume (as the reviewer half) |
| approver | Sign off (the approver half), comment, pause |
| owner | Resume (as the owner half), comment, pause |
| auditor | Read everything, build and download audit packs |
| admin | Reviewer rights, quarantine, release a quarantine |

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

## Errors

Every user error (bad transition, missing role, the same person approving twice, a stale page,
an unknown user) is HTTP 400 with a short message that appears at the top of the page. Every
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
| `CONSOLE_EXPORT_DIR` | `<DATA_DIR>\exports` | Audit packs. On the App this is ephemeral: download the zip at once. |
| `NOTIFY_WEBHOOK_ENABLED` | `0` | Webhook stub: queues notices (`status=queued`), never sends |

Case intake as a job (only when the app is not running, single chain writer):
`python -m supervisor.jobs.case_intake`.
