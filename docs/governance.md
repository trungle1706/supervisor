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
  `manual` or `classifier`.
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
| `PATCH /v1/systems/{id}` | `systems.edit` | change fields; optional `row_version` |
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
Console context: `ctx.systems`.

## 10. Off path

With both flags off no `/v1/systems` or `/console/systems` route is mounted (`app.py` reads the
flags once at start), the nav is unchanged, and the three tables stay empty.
`tests/governance/test_off_path.py`.

## 11. Open questions

1. A login has no team. Is `owner_team` of the agents and systems a person owns the right proxy, or
   should `config/users.yaml` and the SSO group lookup carry a team?
2. `systems.edit` is held by `reviewer`, `owner`, `admin` (like the control catalogue). Should a
   reviewer be able to register systems, or only the owner role?
3. Archive is final. Should an archived system come back (needs a reviewer)?
