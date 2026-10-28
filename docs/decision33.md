# Decision 33 classification (WP-G2)

Off by default. Needs `GOVERNANCE_ENABLED=1` (the tab also needs `CONSOLE_SYSTEMS_ENABLED=1`).
Illustrative and not legal advice: counsel confirms. Plan: `docs/phase4/BUILD_PLAN_PHASE4.md`
section 4.2; the rule text is in `docs/onboard.md`, section "Decision 33".

## 1. The rule that is encoded

A banking system is high risk under Decision 33 (Appendix IV) when it moves money, or decides
credit, "without human inspection, approval or control before execution". A human step counts only
when it is in code; a sentence in a README does not. The Supervisor pause acts after the agent; it
is not approval before execution and does not move a system out of the list.

`config/decision33.yaml` holds an ordered question flow:

| Question | Answered from | Meaning |
|---|---|---|
| `Q-MONEY` | `money_movement` | the system can create, change, confirm or approve a transaction |
| `Q-CREDIT` | `credit_decision` | the system makes the final credit decision |
| `Q-PRE-APPROVAL` | `human_control = pre_approval` | a person approves before execution, in code |
| `Q-OTHER` | a person (or the AI pre-fill) | any other Appendix IV entry, or the Art. 2 high-risk test |

| Outcome rule | Condition | Class |
|---|---|---|
| `D33-TRANSACTION` | `Q-MONEY` yes and `Q-PRE-APPROVAL` no | `high_risk` |
| `D33-CREDIT` | `Q-CREDIT` yes and `Q-PRE-APPROVAL` no | `high_risk` |
| `D33-OTHER` | `Q-OTHER` yes | `high_risk` |
| default | every question answered | `not_high_risk` |
| default | some question open | `unclassified` |

So a system is never `not_high_risk` until a person (or a person-checked pre-fill) has answered
`Q-OTHER`. The schema is strict (unknown keys stop the load). In `when`, write `"yes"` and `"no"`
in quotes; a bare `yes` is read by YAML as true, and the loader turns it back into text. Each
question has an optional `derive`: a condition over the system fields (same syntax as
`docs/assignment-rules.md`), yes when true.

## 2. Steps. Only the last one changes the system

```
 draft (from fields, source rules)  -->  edit (a person, source person)  -->  apply (a person)
        |  optional AI pre-fill, tagged ai_prefill                              sets class + floor
        +--- never changes the system                                           chain: classification_change
```

Table `classification`: `classification_id`, `system_id`, `outcome`, `answers` (JSON: per question
`answer` yes / no / null, `source` rules / ai_prefill / person, `justification`), `flow_sha256`,
`status` (draft or applied), `created_by`, `created_at`, `applied_by`, `applied_at`. One draft is
open at a time; a new draft replaces it and goes back to what the fields say. Applied rows stay as
history.

**Apply** needs `systems.edit` and refuses (HTTP 400, message starts `segregation of duties:`)
when the caller is the `reviewer` or `oversight_manager` of the system. It also refuses a draft
that is not complete, and a draft with AI pre-filled answers unless the body has
`confirm_ai_prefill: true` (the console shows a check box). Applying:

* sets `decision33_class` to the outcome;
* is the classifier floor of the risk level: `high_risk` raises `risk_level` to at least `high` (apply never lowers the stored level; `POST /v1/systems/{id}/risk-level/lower` does, with a reason, by a non-owner)
  (source `classifier`; a higher manual level, for example `prohibited`, is kept). The effective
  risk level also uses the floor on read: a system with class `high_risk` is at least `high`
  whatever the manual level says. With GOVERNANCE_ENABLED on, `decision33_class` can no longer be set by PATCH or at registration: only applying a classification sets it. Apply re-derives the rules-sourced answers from the system as it is now and refuses a stale draft ("the system changed since the draft; remake it");
* updates the system like any change, so the assignment rules run again (rule `AR-D33-HIGH` fires
  for `high_risk`) and the task sizing sees the class.

## 3. Optional AI pre-fill

`CLASSIFIER_AI_PREFILL=1` (default 0). When a draft is made, the questions no field can answer may
be sent to the LLM adapter (`make_chat_model`: the real endpoint, or the mock when no endpoint is
set). Only a few enums and the purpose are sent, the purpose after the secret scrubber and the repo masker (names, phone, CCCD, accounts); the system name is not sent, and with `MASKER_KIND=none` no purpose is sent. The reply is checked
against a schema and only yes or no for an open question is kept. Every such answer has
`source: ai_prefill`, the model id, and `mock: true` with the justification starting `[mock]` when
the model is the mock. A model failure leaves the draft without a pre-fill. The service never
applies a classification; the console shows the label and the check box.

## 4. Chain record `classification_change`

Ref `system:<id>`. Actions `draft`, `edit`, `apply`. Payload: system and classification ids, enums,
integer counts (`questions_n`, `answered_n`, `answers_by_source`), `flow_sha256`, `answers_hash`,
`justifications_hash`, booleans `ai_prefill` and `mock`, a keyed hash of the actor. No justification
text, no user id, no float.

## 5. API (with `/v1/systems`)

| Route | Permission | Purpose |
|---|---|---|
| `GET /v1/systems/{id}/classification` | `systems.view` | the open draft, the applied class, the history count |
| `POST /v1/systems/{id}/classification` | `systems.edit` | make (or remake) a draft from the rules; 201 |
| `PATCH /v1/systems/{id}/classification` | `systems.edit` | body `{"answers": {"Q-OTHER": {"answer": "no", "justification": "..."}}}` (the `answers` wrapper is optional) |
| `POST /v1/systems/{id}/classification/apply` | `systems.edit` | a person applies; optional `confirm_ai_prefill` |

A system outside the scope answers 404; a bad input is HTTP 400 with a message.

## 6. Console

System page, tab Classification: the applied class, the open draft with its outcome and the rule
that decided it, a table of questions with answer, source and justification (editable for
`systems.edit`), and buttons Make a draft, Save answers, Apply. AI answers carry the label "AI
pre-fill" and "mock model". EN and VI.

## 7. Open questions

1. The flow has no "high value" test (Circular 53 Art. 4(2)); the first version follows the plan
   text. The WP14 matrix has the lines (`advisory/compliance/decision33.py`). Should the flow ask
   for the amounts?
2. A system has no per-component class; the agent's own `decision33_class` is separate from the
   system's. Should applying also set the class of the linked agents?
3. Who is "the system's reviewer": only the team role `reviewer`, or also `oversight_manager`
   (both are refused now)?

## Cross-check of `human_control` with the define profile (WP-P2)

`Q-PRE-APPROVAL` is answered from the declared field `human_control`. When the field says `pre_approval` and a linked agent has a define profile (`<DATA_DIR>/onboard/<agent_id>/profile.json` and `inventory.json`, written by `python -m supervisor.onboard` or `python -m supervisor.onboard.define`) with a money or credit tool, the draft checks the declaration against the code:

| Profile of the linked agent | Answer in the draft |
|---|---|
| `human_gate_in_code` true (for example a LangGraph `interrupt_before` or an approval step) | `yes`, source rules; the justification adds the `file:line` of the gate |
| `human_gate_in_code` false | not answered, source person: "unknown, a person confirms (declared, not found in code)". The outcome is `unclassified` until a person answers. |
| no profile, or no money or credit tool | unchanged: `yes` from the declared field |

## Separation of duties (WP-P2, phase 8, `CONSOLE_STATE_ACTIONS`)

With the flag on: the system owner (`owner_user` or an active `system_owner` of the team) cannot apply the class on the own system (HTTP 400 `owner_cannot_apply`), and every answer a person gives needs a justification of at least 20 characters (HTTP 400 `justification_too_short`; the check runs on edit and again on apply for answers a person gave). The reviewer and oversight-manager rule is unchanged. Off = as before.

## The classification tree uses this flow as a sub-flow (WP-C1, phase 12, `CLASSIFICATION_V2`)

With `CLASSIFICATION_V2=1` the node "on the Prime Minister's list" of the classification tree
(`docs/classification.md`) is answered by the four questions of this page and by the outcomes
`high_risk` and `not_high_risk`. The tree does not repeat them. When a second person approves a tree
record, the service makes the Decision 33 draft from the sub-flow answers and calls the `apply`
step of this page, so the rules of `apply` hold (autonomy level set, the owner rule of
`CONSOLE_STATE_ACTIONS`, the floor of the risk level that never goes down). It does not call `apply`
when the tree overrules the list (high in the list, SBV threshold not met). With the flag off
nothing here changes. The routes `/v1/systems/{id}/classification` stay this flow; the tree has its
own routes under `/classification-v2`.

