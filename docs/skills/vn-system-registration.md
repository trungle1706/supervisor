# Skill: vn-system-registration

Register an AI system of a Vietnamese bank as a **draft** in initiation, with its owners and its
agents. Use it when a person says "register", "add" or "onboard" a product, assistant, platform,
feature or use case.

Tools used: `list_entities`, `get_entity`, `register_system`, `link_component`,
`classification_draft`, `list_tasks`, `regulations`, `obligations`.
Scopes: `governance.read`, `governance.write`, `library.read`.

## Rules

The server decides. Confirm before you write. Never classify by yourself.

* A new system is a draft in `initiation` and `unclassified`. You cannot set the Decision 33
  class, the risk level, the business impact or the stage. The server refuses those fields.
* Every write tool needs `confirm: true`. Call it first without `confirm`, show the planned change
  to the person, and call it again with `confirm: true` only after the person says yes.
* Ask for a missing field. Do not guess a name, an owner or a team.
* Use ids of people (`owner_user`), never their names.

## Steps

1. Ask what the system does, in one or two sentences (`purpose`).
2. Check that it is new: `list_entities` with `kind: system` and `filters: {"q": "<name>"}`.
   If it exists, stop and show it with `get_entity`.
3. Collect the nine required fields. Ask for the ones the person did not give.

   | Field | Allowed values |
   |---|---|
   | `name` | text, unique |
   | `owner_user` | the id of the person who owns the system |
   | `owner_team` | the owner team (a team in your scope) |
   | `purpose` | text |
   | `system_type` | `assistant`, `decision`, `automation`, `platform`, `feature` |
   | `org_role` | `provider`, `deployer`, `both` |
   | `user_segment` | `internal`, `customer`, `partner` |
   | `personal_data` | `none`, `identifiable`, `pseudonymised`, `special` |
   | `human_control` | `pre_approval`, `post_review`, `none` |

   Optional: `business_owner`, `money_movement`, `credit_decision`, `autonomy_level`, `tags`.
   Ask about `money_movement` and `credit_decision` when the purpose suggests payments or credit.
4. Call `register_system` without `confirm`. Show `planned_change` (the id, the status `draft`,
   the stage `initiation`). Ask: "Register this draft?"
5. After a yes, call `register_system` with `confirm: true`.
6. Offer to link the agents that build the system. For each agent id the person names, call
   `link_component` (`ref_kind: agent`), first without and then with `confirm`.
7. Offer **one** next step: `classification_draft` (see the skill `d33-prep`), or `list_tasks`
   to show the initiation tasks.

## Do not

* Do not call a tool to approve, classify or set a risk level. There is none.
* Do not register a second system with the same name.
* Do not tell the person that the system is "compliant" or "approved". It is a draft.
