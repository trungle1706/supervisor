# Governance shared core: the AI system (WP-G0)

Off by default (`GOVERNANCE_ENABLED=1`; pages need `CONSOLE_SYSTEMS_ENABLED=1` too). Plan and
reasons: `docs/phase4/BUILD_PLAN_PHASE4.md` section 2 and the Saidot adoption plan (object model,
section 3). Built on the inventory graph (`docs/inventory.md`, ADR D16), the same pattern as the
risk register (`docs/risk-register.md`) and the control catalogue (`docs/controls.md`).

## 1. What it is

A bank governs *AI systems* (a product, a platform, a feature, a use case), not single agents. An
agent or a model is a part of a system. The system has named owners and a small set of intake
fields. Everything else comes from its parts or is set by rules later.

```
 person (role)  --scope_for-->  systems they are on / own / their team owns
                                       |
   ai_system  <--- system_team --- (user, team role)
       |
       +--- system_component --- agent        (ref_kind agent)
       |                    +--- inventory node (ref_kind node: model, tool, dataset, ...)
       |
       +--- effective risk level = max( manual level , level inherited over the parts )
```

## 2. Tables (`schema/model.yaml`)

| Table | Key | Content |
|---|---|---|
| `ai_system` | `system_id` | Intake fields, lifecycle stage, manual risk level and its source, Decision 33 class (human-set), status, tags |
| `system_team` | `system_id`, `user_id` | Team role (`system_owner`, `business_owner`, `technical_specialist`, `data_steward`, `compliance_specialist`, `reviewer`, `oversight_manager`); `active` is false after a removal (the state port has no delete) |
| `system_component` | `component_id` | Link to an agent or an inventory node; role `component_of`, `built_on`, `depends_on`; source and evidence reference; `active` is false after an unlink |

WP-G1 adds three more tables, described in sections 13 to 15: `stage_approval` (a request to move a
system into a stage and its answer), `review` (a review with scope, window and reports; locked when
completed) and `outbound_event` (events for other systems; ids and enums only).

`system_id` is `sys_` plus a hash of the canonical name, so a repeat registration is a duplicate.
`component_id` is a hash of (system, ref kind, ref id, role): a repeat link is a no-op.

Intake fields (all required at registration): name, owner user, owner team, purpose, system type
(`assistant`, `decision`, `automation`, `platform`, `feature`), org role (`provider`, `deployer`,
`both`), user segment (`internal`, `customer`, `partner`), personal data (`none`, `identifiable`,
`pseudonymised`, `special`), human control (`pre_approval`, `post_review`, `none`). Defaults:
status `draft`, stage `initiation`, risk `unspecified`, Decision 33 class `unclassified`, business
impact `unspecified`, money movement and credit decision false.

## 3. Risk level

`effective_risk_level(system_id)` returns the level, which side won (`source`), the manual level,
the inherited level and the parts the inherited level came from. Computed on read, never stored.

* Manual level: `unspecified < low < medium < high < prohibited`. A person sets it, with source
  `manual` or `classifier`. The governance action `raise_risk_level` (WP-G5) can raise it one step,
  with source `event`, never down and never above `high` (`docs/governance-actions.md`).
* Inherited level: for each active part, its effective level in the inventory graph (`uses` edges,
  cycle safe; WP24). An agent with no node in the inventory (inventory off or not filled) uses the
  `risk_tier` of its registry row. The inventory scale has `critical`; at the system it counts as
  `high`. `prohibited` is never inherited: it is a legal finding.
* The higher level wins. On a tie the manual level wins, so the source stays `manual`.

## 4. Who sees what

`scope_for(user)` returns `ALL` or the set of system ids.

| Roles | Scope |
|---|---|
| `admin`, `auditor`, `reviewer`, `approver` | all systems |
| `owner`, `viewer`, `operator` (`SCOPED_ROLES`) | systems they are on in `system_team`, systems they own, systems owned by their team |

A person with both kinds of role sees everything. A person with no role sees nothing.
`agents_in_scope(user)`: agents linked to a system in scope, plus agents with no active system link
whose `owner_team` is the person's team. An agent linked only to systems out of scope stays hidden.

A person's team is not a field of the login. It is taken from the facts we have: the owner team of
the agents they own, and of the systems where they are an active `system_owner` (a role somebody
with edit rights gave them). Systems a person registered themselves do not widen it. A scoped
person can register a system with, or change `owner_team` to, only a team already in their scope
(HTTP 400 otherwise), and can link only agents in `agents_in_scope` (and inventory nodes those
agents reach); anything else answers 404 like a missing item (open question 1). When the owner of
a system changes, the old owner becomes `technical_specialist`.

## 5. Segregation of duties

The owner of a system (`owner_user`, or a member with team role `system_owner`) cannot be the
`reviewer` or `oversight_manager` of the same system, and a reviewer or oversight manager cannot
become owner (by team change or by changing `owner_user`). The refusal is HTTP 400 and the message
starts with `segregation of duties:`. The owner cannot be removed; change the owner first.

## 6. API (`/v1/systems`, only when `GOVERNANCE_ENABLED=1`)

| Route | Permission | Purpose |
|---|---|---|
| `GET /v1/systems` | `systems.view` | list, scoped; filters `status`, `owner_team`, `lifecycle_stage`, `risk`, `system_type`, `q` |
| `POST /v1/systems` | `systems.edit` | register (status draft); a scoped person registers only with themselves as owner |
| `GET /v1/systems/{id}` | `systems.view` | one system with team, parts and effective risk |
| `PATCH /v1/systems/{id}` | `systems.edit` | change fields; optional `row_version`. `lifecycle_stage` changes only with `POST .../stage` (section 13) |
| `POST /v1/systems/{id}/team` | `systems.edit` | body `user_id`, `team_role` (add or change) |
| `DELETE /v1/systems/{id}/team/{user}` | `systems.edit` | remove a member |
| `POST /v1/systems/{id}/links` | `systems.edit` | body `ref_kind` (`agent`, `node`), `ref_id`, optional `role` |
| `DELETE /v1/systems/{id}/links/{component_id}` | `systems.edit` | remove a link |
| `POST /v1/systems/{id}/archive` | `systems.edit` | archive (final) |

`systems.view` is held by every role. `systems.edit` by `reviewer`, `owner`, `admin`. A scoped
person changes only systems in their scope. A system outside the scope answers 404, like one that
does not exist. A bad input is HTTP 400 with a message; never 500. Every write makes two
`console_action` audit rows (attempted, outcome) with target kind `system`.

## 7. Console (`CONSOLE_SYSTEMS_ENABLED=1`, old navigation)

`/console/systems`: tiles, filter bar, sortable paged list, row drawer (Details, Team, Components),
register form. `/console/systems/{id}`: tabs Overview and Components. The nav item sits under
Onboard (Governance section when `CONSOLE_NAV_SECTIONS=1`). EN and VI. Read-only apart from
registering; edits go through the API until the governance pages (UX4b) land.

## 8. Chain record `system_change`

One record per change, ref `system:<id>`. Actions `create`, `update`, `archive`, `team_add`,
`team_remove`, `link`, `unlink`. The payload holds ids, enums, integers (`team_n`, `components_n`),
hashes (`row_hash`, `team_hash`, `links_hash`) and a keyed hash of the actor (`actor_ref`; for
team changes also `member_ref`). No name, no purpose, no user id, no float.

## 9. For other modules

`SystemService` (`supervisor.governance.systems`): `register`, `update_fields`, `archive`,
`add_member`, `remove_member`, `link`, `unlink`, `effective_risk_level`, `scope_for`, `can_view`,
`agents_in_scope`, `list_systems`, `get`, constants `ALL`, `SCOPED_ROLES`, `ALL_ROLES`.
Console context: `ctx.systems`, and from WP-G1 `ctx.lifecycle` (`LifecycleService`: `request`, `decide`, `move`, `approvals`, `status`, `can_decide`) and `ctx.reviews` (`ReviewService`: `create`, `update`, `complete`, `reopen`, `list_reviews`, `get`). Sizing: `supervisor.governance.sizing.linked_sizing`. Events: `supervisor.governance.events.emit`, `deliver_pending`.

## 10. Off path

With both flags off no `/v1/systems` or `/console/systems` route is mounted (`app.py` reads the
flags once at start), the nav is unchanged, and the three tables stay empty.
`tests/governance/test_off_path.py`. WP-G1 adds no route of its own: its routes are on the same router, so with
`GOVERNANCE_ENABLED` off none exists, the tables `stage_approval`, `review` and `outbound_event` stay empty,
`WEBHOOKS_ENABLED` does nothing, and the task sizing of every agent is as before
(`tests/governance/test_g1_off_path.py`).

## 12. Task sizing by the risk level of the system (WP-G1)

An agent that is linked to at least one system (active link, system not archived) is sized from the
system and, when higher, from its WP29 register band:

```
 band  = higher of (effective risk level of the system, WP29 register band of the agent)
         (the highest system level if the agent is on several systems)
         low -> low, medium -> medium, high -> high, prohibited -> critical (top of the task scale)
 level = higher of (band, floor of the Decision 33 class of the agent)      [tasks.model.effective_level]
 unspecified system level and the final level still low -> the initiation set ONLY: no move
         to the next stage until a person sets the level of the system. A Decision 33 floor or a
         higher register band gives the full set and the move task
```

An agent with no link keeps the computation of `docs/controls.md` section 5, byte for byte (test
`tests/governance/test_g1_off_path.py` pins the plan of every class and band). The list never gets
lighter (existing rule): a system level that goes down keeps the tasks and the level the list had.
After a change of the system level run `python -m supervisor.tasks generate --agent <id>` (or the
Generate call) so the list is sized again; it only adds or makes tasks required.

`config/tasks.yaml` templates may state their size on the scale of a system with `min_risk_level`
and `required_from_level` (`low`, `medium`, `high`, `prohibited`). They mean the same as `min_level`
and `required_from` (`prohibited` = `critical`); give one name or the other, not both.
`tasks.service.TaskService.agent_inputs` adds `system_level`, `system_ids` (and `initiation_only`)
for a linked agent; the keys are absent for an unlinked one.

## 13. Stage approvals and the lifecycle move (WP-G1)

```
 POST /approvals {to_stage}            pending
        |                                 |
        |   POST /approvals/{id}/decide   v
        +--------------------------->  approved | rejected
                                          |
 POST /stage {to_stage}  <---- needs an approved row made from the current stage, not used yet
```

Table `stage_approval` (`approval_id`, `system_id`, `from_stage`, `to_stage`, `requested_by`,
`status` pending, approved or rejected, `decided_by`, `reason`, `created_at`, `decided_at`, plus
`applied_at`, set when a move used the approval).

* **Which stages need an approval.** `config/tasks.yaml`, block `stages:` (`deployment` and
  `operation` have `approval: true`; without the block the default is the same). Other moves go
  with `POST /stage` alone. A system in `retirement` does not move; an archived one does not move.
* **Who answers.** A person who is a `reviewer` or `oversight_manager` on the team of the system,
  or who holds the `approver` role. An `admin` has no standing by role alone (add the person to
  the team). Route permission `systems.approve` (`approver`, `reviewer`, `owner`, `admin`) is the
  first gate, the rule above is the second.
* **Segregation of duties.** The answering person is not the requester and is not the owner
  (`owner_user` or an active `system_owner`), compared without letter case. The refusal is HTTP 400
  and starts `segregation of duties:`.
* **Rules.** One pending request per target stage. A reject needs a reason. The request must still
  be valid (the system is in `from_stage`). An approval is used once: after the move the row has
  `applied_at`, and a later move needs a new approval.
* **Stage change by `PATCH` or at registration** is refused (HTTP 400): it would skip the approval. A new
  system starts in `initiation`; ask with `POST .../approvals`, then `POST .../stage`.
* **Route permission is not standing.** `systems.approve` (kept for `approver`, `reviewer`, `owner`,
  `admin`) only lets the call reach the service. An `admin`, an `owner` or a `reviewer` decides only
  if the person is also a team `reviewer` or `oversight_manager` of this system, or holds the
  `approver` role. Otherwise the answer is HTTP 400 ("only a reviewer or oversight manager...").
* **No stage order rule.** Any stage other than the current one is a valid target, forward or
  backward, except out of `retirement`. Only the approval stages are gated (open question 5).
* **Claim first.** A move marks the approval as used before it changes the system, so a lost race
  leaves the system as it was.

## 14. Reviews (WP-G1)

Table `review`: `review_id`, `system_id`, `kind` (`internal`, `external`, `conformity`,
`classification_audit`), `title`, `scope` (list of `{kind: agent|node|system, id}`), `reviewer_user`,
`status` (`planned`, `in_progress`, `completed`, `reopened`), `window_start`, `window_end`
(RFC 3339), `reports` (list of `{kind: file|link|note, ref, sha256}`), `completed_at`,
`completed_by`, `locked`, `reopen_reason`, `reopen_count`.

* A file report needs the SHA-256 of the file; a note gets the hash of its text; a link must start
  `http://` or `https://`. Nothing is fetched.
* `complete` (the named reviewer, or an admin) sets `completed` and locks the review. A locked review
  cannot be changed (HTTP 400). `reopen` (the reviewer, an approver or an admin) needs a reason,
  unlocks it, sets `reopened`, counts the reopen and keeps the reason in the row; the chain holds a
  hash of the reason.
* The owner of the system cannot be the reviewer of its review (`segregation of duties:`).
* Permission `systems.review` (`reviewer`, `approver`, `admin`) for writes; `systems.view` reads.

## 15. Outbound events and the webhook stub (WP-G1)

Table `outbound_event` (`event_id`, `kind`, `system_id`, `payload`, `created_at`, `delivered`,
`delivered_at`). The services write a row when a stage is approved (`stage_approved`), a review is
completed (`review_completed`), a system is registered (`system_registered`) or archived
(`system_archived`). The payload holds ids and enums only (`system_id`, `approval_id`, `review_id`,
stage names, review kind, system type); anything else is refused. A failed write is logged and never
stops the change.

`WEBHOOKS_ENABLED=1` (default off): after the write the stub (`adapters/notify/outbound_webhook.py`)
logs the event and marks it delivered. It sends nothing; the real HTTP sender is later work (G5).
`supervisor.governance.events.deliver_pending` sends the backlog through the stub when the flag is
turned on later. Nothing else reads the table yet.

## 16. API added by WP-G1 (same router, same flag)

| Route | Permission | Purpose |
|---|---|---|
| `GET /v1/systems/{id}/approvals` | `systems.view` | list stage approvals |
| `POST /v1/systems/{id}/approvals` | `systems.edit` | body `to_stage`: ask for a move |
| `POST /v1/systems/{id}/approvals/{aid}/decide` | `systems.approve` | body `decision` (`approve`, `reject`), `reason` |
| `POST /v1/systems/{id}/stage` | `systems.edit` | body `to_stage`: do the move |
| `GET /v1/systems/{id}/reviews` | `systems.view` | list reviews |
| `POST /v1/systems/{id}/reviews` | `systems.review` | plan a review (status `planned`) |
| `PATCH /v1/systems/{id}/reviews/{rid}` | `systems.review` | change fields; optional `row_version` |
| `POST /v1/systems/{id}/reviews/{rid}/complete` | `systems.review` | complete and lock |
| `POST /v1/systems/{id}/reviews/{rid}/reopen` | `systems.review` | body `reason` |

Scope, 404 for a system out of scope, HTTP 400 for bad input and the two `console_action` audit rows
work as in section 6.

## 17. Chain records added by WP-G1

Ref `system:<id>`. Canonical JSON, ids, enums, integers, hashes and keyed actor hashes; no title, no
reason, no report text, no user id, no float.

| Type | Actions | Fields |
|---|---|---|
| `stage_change` | `request`, `approve`, `reject`, `move` | `approval_id`, `from_stage`, `to_stage`, `status`, `actor_ref`, `requester_ref` or `approver_ref`, `reason_hash`, `lifecycle_stage`, `ts` |
| `review_change` | `create`, `update`, `complete`, `reopen` | `review_id`, `kind`, `status`, `locked` (0 or 1), `scope_n`, `reports_n`, `scope_hash`, `reports_hash`, `reopen_count`, `reason_hash`, `actor_ref`, `reviewer_ref`, `ts` |

## 18. Console tabs added by WP-G1 (`CONSOLE_SYSTEMS_ENABLED=1`)

The system page `/console/systems/<id>` has the tabs Overview, Components, **Tasks** and **Reviews**.
Tasks: the stage of the system, the stages that need an approval, the stage approvals, and the task
list of every linked agent (needs `CONTROLS_ENABLED=1`; a note says so when it is off). Reviews: the
reviews with kind, status, lock, reviewer, window and report count. Both are read only; changes go
through the API. EN and VI strings sit in one block marked WP-G1 in `console/i18n.py`.

## 19. Open questions

1. A login has no team. Is `owner_team` of the agents and systems a person owns the right proxy, or
   should `config/users.yaml` and the SSO group lookup carry a team?
2. `systems.edit` is held by `reviewer`, `owner`, `admin` (like the control catalogue). Should a
   reviewer be able to register systems, or only the owner role?
3. Archive is final. Should an archived system come back (needs a reviewer)?
4. (WP-G1) Should an `admin` be allowed to answer a stage approval, as an admin may approve a task
   move? The plan says a team reviewer, an oversight manager or the `approver` role; admin is out.
5. (WP-G1) Stage moves other than into `deployment` and `operation` need no approval, and a move may
   go back (for example operation to design). Should the bank forbid backward moves?

## 14. Draft systems from the workspace scan (WP-G3)

With `INVENTORY_AUTOREGISTER=1` the inventory scan registers a draft system (status draft, risk `unspecified`, tag `source=workspace_scan`) for each unmanaged App, agent endpoint or Genie space, with a default owner from `config/governance.yaml`, and opens the task "Confirm context". See `docs/inventory.md`, "Draft registration from the scan".


## 20. Governance loop and incidents (WP-G5)

Off by default (`GOVERNANCE_ACTIONS_ENABLED=1`, needs `GOVERNANCE_ENABLED=1`). Events from the
runtime evidence (alerts, gate stops on risky tools, failed detectors, failing monitors, assurance
NO-GO, chain break, new model version, judge escalation) are matched to
`config/governance_actions.yaml` and run seven actions: create an incident, notify the owner,
raise the risk level, move to re-evaluation, create a review, fire a webhook event, reopen a
control. The loop never pauses or blocks an agent. New tables `incident` and `governance_event`
(the marker that an event was processed), chain records `incident_change` and `governance_action`,
routes `/v1/incidents`, the Incidents tab on Cases & alerts and the Reports tab of the system
page. Details: `docs/governance-actions.md` and `docs/incidents.md`.

Changes to the G0 and G1 code that the loop needs, all additive: `SystemService.raise_risk_from_event`
and the risk source `event`; the outbound event kind `governance_action`; the review scope kind
`event`. Console context: `ctx.incidents` (`IncidentService`).
