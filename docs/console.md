# Reviewer console (WP8)

Server-rendered pages (Jinja2) with htmx 1.9.12 (vendored, see `docs/LICENSES.md`), hand-written
CSS, system fonts. No CDN, no external fonts, no network calls from the browser except to the
app itself. Labels in English and Vietnamese (`?lang=vi` or `?lang=en`; default `CONSOLE_LANG`).

Start on the laptop (Windows cmd):

```
set PYTHONPATH=src
python -m supervisor.demo.replay --gate
python -m uvicorn supervisor.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` (it redirects to `/console/`).

## Screens

| Screen | URL | What it shows | Actions |
|---|---|---|---|
| Queue | `/console/` | Open cases sorted by severity, then age. Source badge (gate / judge / monitor). SBV 24 h report countdown, colour at 50 / 80 / 100 % of the window. Filters: status, severity, agent. Refreshes every 30 s. | Opening the queue runs the case intake: every gate block / pause that has no case gets one (a second stop by the same rule joins the open case). |
| Case | `/console/cases/<id>` | "What happened / Why it matters / What you can do" box, SBV report and 5-day remediation clocks, rules broken (Tier 0), judge findings (advisory, `MOCK` badge for mock judges), masked transcript excerpts, timeline (case events, verdicts, sign-offs, with actor and auth method), evidence-chain range of the case and its verify status. | Assign, triage, contain, close, comment (masked), ITSM ref, verify the agent lane now. |
| Sign-off | `/console/cases/<id>/signoff` | Sign-offs so far with the statement text verbatim. | Approve or reject with a statement; the signer ticks "I sign this statement as myself". |
| Agents | `/console/agents` | Registry: gate state, owner, risk tier, coverage score, open cases, pending resume approvals. | Pause (one click), resume (two people), quarantine and release (admin). These call the gateway state machine in-process. |
| Metrics | `/console/metrics` | Oversight metrics per agent (every column of `oversight_metric`, including columns WP7 adds later) with an inline SVG sparkline per column; chain lanes and heads; gateway latency counters. | Verify the whole chain now. |
| Audit pack | `/console/export` | Earlier packs. | Build a zip: chain export + offline verify report + case files (JSON + HTML) + judge eval report (or a NOT_RUN note) + manifest with SHA-256. Download link. |
| Inbox | `/console/inbox` | Notices from the case workflow (new case, sign-off needed, case closed). | Mark read. |

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
| `CONSOLE_EXPORT_DIR` | `<DATA_DIR>\exports` | Audit packs. On the App this is ephemeral: download the zip at once. |
| `NOTIFY_WEBHOOK_ENABLED` | `0` | Webhook stub: queues notices (`status=queued`), never sends |

Case intake as a job (only when the app is not running, single chain writer):
`python -m supervisor.jobs.case_intake`.
