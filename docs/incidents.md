# Incidents (WP-G5)

Off by default (`GOVERNANCE_ACTIONS_ENABLED=1` with `GOVERNANCE_ENABLED=1`). How an incident is
made: `docs/governance-actions.md`.

An incident is the record that a governance event needed a person. It is **made by the
governance action job and by nothing else**: there is no route, no console form and no service
method that creates one from input. A judge cannot make one. A person **moves it on and closes
it**; nothing automatic can.

## 1. Table `incident`

| Column | Meaning |
|---|---|
| `incident_id` | `inc_` + 24 hex characters of the event key. The same event gives the same id, so a repeat is a no-op |
| `system_id` | The AI system, or empty when the agent is on no system |
| `agent_id` | The agent, or `-` for an event with no agent (a chain break) |
| `kind` | `alert`, `gate_stop`, `detector_failed`, `monitor_failing`, `pack_no_go`, `chain_break`, `model_version_change`, `judge_escalation` |
| `severity` | `low`, `medium`, `high`, `critical` (from the event) |
| `title` | From a template per kind (for an alert, the alert rule id is filled in). Never text from an event |
| `event_ref` | Ids only, for example `alert:al_8c1`, `verdict:v_77`, `case:CASE-drift-3` |
| `root_cause`, `affected_scope` | Typed by the person who moves the incident (up to 1000 characters) |
| `status` | `open`, `investigating`, `resolved`, `closed` |
| `opened_at`, `closed_at`, `closed_by` | Times and the person who closed it |
| `case_id` | The case of the source (an alert's case, the drift case...) when there is one |

## 2. States

```
 open --> investigating --> resolved --> closed        closed is final
   |            |               |  ^
   |            |               +--+  resolved --> investigating (the fix did not hold)
   +------------+---------------+--> closed           (a person, from any state)
 open --> resolved
```

## 3. Who can do what

| Permission | Roles | Use |
|---|---|---|
| `incidents.view` | all roles | List and read incidents in your scope |
| `incidents.transition` | `reviewer`, `owner`, `admin` | Move on and close. These are the holders of `case.transition` or `systems.edit` |

The caller must be a signed-in person (`kind` is `user`); a service principal is refused. **Scope**
follows the AI systems (`docs/governance.md` section 4): `admin`, `auditor`, `reviewer` and
`approver` see every incident; `owner`, `viewer` and `operator` see the incidents of the systems
they are on, own, or that their team owns, and the incidents with no system for agents in their
scope. An incident out of scope answers 404, like one that does not exist.

## 4. API

| Route | Permission | Purpose |
|---|---|---|
| `GET /v1/incidents` | `incidents.view` | List. Filters `status` (`open`, `investigating`, `resolved`, `closed`, `active` = not closed (default), `all`), `severity`, `kind`, `system`, `agent`, `q` |
| `GET /v1/incidents/{id}` | `incidents.view` | One incident, with `next` (the states it can move to) |
| `POST /v1/incidents/{id}/transition` | `incidents.transition` | Body `status`, optional `root_cause`, `affected_scope`, `row_version` |

A bad input is HTTP 400 with a message, never 500. Every transition makes two `console_action`
rows (`attempted`, then `ok` with the row hash before and after; target kind `incident`).

## 5. Console

**Cases & alerts** gets a tab **Incidents** (`/console/incidents`, with `CONSOLE_NAV_V3`; in the
old sidebar an item next to Inbox): tiles by status, filter bar (severity, kind, agent), sortable
paged table, row drawer with the facts and, for a person who may move it, the form to move it.
The **Reports** tab of the AI system page (`/console/systems/<id>?tab=reports`, shown with the
flag on) lists the incidents of that system, read only. The slot is a partial,
`_system_incidents.html`, that the full Reports tab of WP-UX4b includes. EN and VI.

## 6. Chain record `incident_change`

Ref `incident:<id>`, root lane. Actions `create` and `transition`. Fields: `incident_id`,
`action`, `kind`, `severity`, `status`, `system_id`, `agent`, `event_ref`, `case_id`, `actor_ref`
(keyed hash of the actor), `ts`, and for a transition `from_status`, `root_cause_hash`,
`affected_hash`. No title, no typed text, no user id, no float. The actor of `create` is
`system:governance_actions`.
