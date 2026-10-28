# Register workflow v2 (WP-N3)

A six-step registration of an AI system with a stored draft. Spec: `docs/phase7/BUILD_PLAN_PHASE7.md`
section 3. The two-step wizard at `/console/systems/new` stays and is used while the flag is off.

## Flags

| Flag | Role |
|---|---|
| `CONSOLE_REGISTER_V2=1` | turns the workflow on (default off; off: every URL below answers HTTP 400 naming the flag) |
| `GOVERNANCE_ENABLED=1`, `CONSOLE_SYSTEMS_ENABLED=1` | needed (the routes are mounted with the Systems pages) |
| `CONSOLE_REGISTER_DUTIES=1` | adds the **Duties** step (seven steps; default off; needs `CONSOLE_REGISTER_V2` and `GOVERNANCE_ENABLED`; see "Duties step") |
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

## Duties step (WP-L2, `CONSOLE_REGISTER_DUTIES=1`)

> **Not legal advice. Bank counsel must confirm.** The step is an advisory aid. It does not decide
> compliance. An unknown fact is an open question, never a guess.

With the flag on, the workflow has seven steps. The Duties step is step 4: after the
pre-deployment check and before Decision 33. Steps 5, 6 and 7 are Decision 33, Guardian tools and
Review and submit. With the flag off the workflow keeps six steps and every URL as above. The step
numbers come from `register_v2/model.py` (`STEP_KEYS`, `STEP_KEYS_DUTIES`, `step_keys()`); the flag
only chooses the list. A draft that is already open keeps its answers; the "furthest step" mark
follows the list in use.

**What the step does.** It builds a product profile from the draft answers (purpose, user segment,
personal data, role, autonomy, human control, money movement, credit decision) and from the
policy rules that name the agent. It runs the compliance matrix (`docs/compliance-advisor.md`) on
it. The profile marks what the person said as known and leaves the rest unknown: data classes are
a lower bound (financial data is never asked), cross border and model hosting are unknown, and the
controls are those of a system registered with Supervisor (`planned`) plus the gate rules of the
policy. The model family, the host kind and the data sources text do not map to a matrix fact and
are not used. If the table `onboard_facts` (WP-O2) exists and the draft came from a scanned node,
the step shows how many facts rows it saw; it reads that table by name only and works without it.

**The page.** A banner with the sentence above; counts (duties checked, apply, do not apply, need an
answer; of those that apply, full, partial and none coverage); the Decision 33 suggestion; the open
questions; the rows. A row has the instrument, the article, the duty, applies (`yes`, `no`, `needs
answer`), coverage and the effective date of the instrument when RegKB knows it. Coverage comes
from the matrix status: `met` is full, `partial` is partial, `gap` and `bank_process` are none.
The filter `?f=` is `gaps` (default: apply and not fully covered), `yes`, `needs_answer`, `no` or
`all`; the page size is 100 rows (`?p=`). A bad filter or page is HTTP 400.

**The questions.** Each open question of the matrix is a form field named by its question id
(`Q-<fact>`, for example `Q-data_classes`, `Q-model_hosting`, `Q-cross_border`,
`Q-in_operation_since`). Yes/no questions are a select, vocabulary questions are a select or a
comma list (`none` means an empty list), money is a whole number of VND, a date is `YYYY-MM-DD`.
A blank field means unknown. The button **Run again** saves the answers and stays on the step,
so the matrix runs again on them. **Continue** saves and goes to the next step. The answers are
stored in the draft `data` under `duties_answers` (`{"Q-cross_border": false, ...}`). A question
that the answers have settled stays on the page, marked answered, so the person can change it; the
person can also go back to any earlier step and return. A bad value is HTTP 400 with the field name
and the page shows what was typed.

**On submit** (after the system exists; a failure here is shown on the result page and does not
undo the system):

| Write | Detail |
|---|---|
| table `obligation_status` | one row per duty that applies (`applies = yes`) to the new AI system: `coverage` full, partial or none; `status` open; `owner_user` the system owner; `due_date` the effective date of the instrument when known; `closing_control` empty (WP-L3 sets it); `note` starts with the banner. A repeat is a no-op (the id is a hash of system and obligation) |
| one task per applying duty with coverage partial or none | template `DUTY-<obligation id>`, title `Close duty <obligation id>`, stage initiation, owner role owner, not required (it does not block a stage move), due date the effective date of the instrument when it is in the future, else 14 days; the banner and the article are in the task note (the evidence field) |

Rows with `needs answer` and `no` are not written. Expect many tasks: a typical internal assistant
has about 330 applying duties, all partial or none (no duty is fully covered by a Supervisor
control today). The matrix takes about two seconds; the last eight results are kept in memory by
profile, so the page, the review and the submit of one draft run it once.
