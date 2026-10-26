# Register workflow v2 (WP-N3)

A six-step registration of an AI system with a stored draft. Spec: `docs/phase7/BUILD_PLAN_PHASE7.md`
section 3. The two-step wizard at `/console/systems/new` stays and is used while the flag is off.

## Flags

| Flag | Role |
|---|---|
| `CONSOLE_REGISTER_V2=1` | turns the workflow on (default off; off: every URL below answers HTTP 400 naming the flag) |
| `GOVERNANCE_ENABLED=1`, `CONSOLE_SYSTEMS_ENABLED=1` | needed (the routes are mounted with the Systems pages) |
| `AGENTS_API_ENABLED=1` | needed only for the agent row; without it the task "Add the agent to the policy" opens |
| `GUARDIAN_BINDINGS_ENABLED=1` | needed only to set a guardian feature off (step 5) |
| `ONBOARD_ALLOWED_ROOTS` | folders the optional readiness check (step 3) may scan |

Permission: `systems.edit`. A scoped person registers for themselves and for a team they already work in.

## URLs

| URL | What |
|---|---|
| `GET /console/register` | my open drafts, with a resume link |
| `GET /console/register/new` | blank draft, redirect to step 1 |
| `GET /console/register/new?from=<node_id>` | draft prefilled from a scanned inventory node (candidate row link) |
| `GET /console/register/new?agent=<agent_id>` | draft prefilled from the policy manifest of a policy-only agent |
| `GET /console/register/<draft_id>/step/<1..6>` | render a step |
| `POST /console/register/<draft_id>/step/<n>` | validate and save; go to n+1. `?save=1` stays; form field `accept=<field>` or `*` takes a suggestion; `run=1` (step 3) runs the readiness check |
| `POST /console/register/<draft_id>/submit` | the writes (audited), then the result page `/result` |
| `POST /console/register/<draft_id>/abandon` | drop the draft |

Every user error is HTTP 400 with the field name (`name: is required`); a bad step value
re-renders the step with the message.

## Steps

1 Identify (name, kind, agent id, owner, team, description). 2 AI information (purpose, type, role,
segment, personal data, human control, autonomy, money, credit, model family, data sources); each field
shows a suggestion with its reason and source (`scan`, `policy`); a changed value is marked "set by
person". 3 Pre-deployment check (readiness advisor on an optional folder, policy fragment, tools
declared, service principal mapped, today's preliminary checks; each gap shows its fix). 4 Quick risk
assessment (Decision 33 questions prefilled by the rules, proposed outcome with the rule id, inherited
risk). 5 Guardian tools (floor locked on, the others on, unavailable ones show the flag they need).
6 Review and submit.

## Writes of the submit (existing services only)

`ai_system` draft and `system_team` owner (`SystemService.register`); `agent` row through
`AgentRegistry` only when the policy knows the id, the API is on and there is no row yet (else the task
"Add the agent to the policy"); `system_component` link to the agent or the scanned node; `classification`
draft (never applied) plus the answers given in step 4; `guardian_binding` rows only for a feature set
off (a floor feature cannot be); intake tasks, plus "Map the service principal identity" when the agent
id is not in `config/agent_identities.yaml`. A step after the system exists that fails is shown on the
result page and does not undo the system.

The draft is the table `registration_draft` (kind state, no evidence, nothing on the chain).
Suggestions come from `governance/register_v2/suggest.py` (inventory graph, `config/governance.yaml`
owner map, policy manifest); an LLM assist may be added later and would only advise.
