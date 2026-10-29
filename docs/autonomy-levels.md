# Autonomy levels (WP-G2)

Field `ai_system.autonomy_level`. It segments AI systems by how much the model decides and where
the person stands. Off with the rest of governance (`GOVERNANCE_ENABLED`). ILLUSTRATIVE: the bank
sets the real mapping.

| Level | What the model does | Human role |
|---|---|---|
| `unspecified` | not a level; default for a new system. Blocks "apply" of a Decision 33 classification until set. Never matches `gte` | - |
| `l0_rule_based` | no model takes a decision (rules, RPA, scripted bots) | none needed |
| `l1_assistive` | produces text or answers; a person acts on it (knowledge chatbot, copilot, summariser) | in the loop |
| `l2_workflow_step` | a fixed workflow calls a model for one step (classify, extract, draft); the model calls no tools; rules or a person act on the output | in the loop |
| `l3_tool_using_supervised` | chooses and calls tools from a bounded set; a person approves consequential actions before they run | in the loop |
| `l4_autonomous_bounded` | plans and runs a multi-step workflow end to end inside an authority boundary; a person monitors and can pause or roll back | on the loop |
| `l5_self_directed` | sets sub-goals, spawns agents or changes its own tools; no person in the flow | out of the loop. Prohibited at the bank by default |

## Why this ladder

ISO/IEC 22989 (AI concepts and terminology) describes degrees of supervision of an AI system by a
person. The L0 to L5 ladder follows the autonomy levels of the data-agent survey (arXiv
2510.23587). The three human positions are the usual in-the-loop (a person acts on each output),
on-the-loop (a person watches and can stop it) and out-of-the-loop (no person in the flow). The
ladder is a classification of the system, not a test of the model. Higher levels need stronger
controls because less depends on a person catching an error before it acts.

## How a level maps to the guardian floor and the task set

Rules in `config/assignment_rules.yaml` (see `docs/assignment-rules.md`). `autonomy_level` is an
ordered field: `gte` compares in the order above, and `unspecified` never matches. The explain
output (`python -m supervisor.governance.rules explain --system ID`) shows the level that fired.

| Rule | Fires at | Guardian floor | Controls and tasks | Risk |
|---|---|---|---|---|
| `AR-AUTONOMY-L3` | l3 and above | `policy_rules`, `dlp_vn` | - | - |
| `AR-AUTONOMY-L4` | l4 and above | `session_monitor` | control `CTL-BANK-PAUSETEST` (pause switch tested; the file is `config/controls_pending/autonomy.yaml`, imported when the bank wants it), task `OPS-RESUME-2P` (two-person resume approved; assigned by rule only, sizing never picks it) | - |
| `AR-AUTONOMY-L5` | l5 | - | the five initiation tasks are added (`INI-REGISTER`, `INI-PURPOSE`, `INI-RISKS`, `INI-D33`) so the decision is documented. Task sizing is not limited to them: it still follows the agent's band and class (see open question 1) | `RSK-SHR-003` unbounded autonomy (status draft: needs governing-body approval; the file is `config/risks_pending/autonomy.yaml`, outside the register until the risk team imports it) |

## Interaction with Decision 33 (`docs/decision33.md`)

The level never lowers a class. A system at l4 or l5 with money movement or a credit decision and
`human_control` other than `pre_approval` is `high_risk`, as for any level. Level l5 also sets the
classifier floor of the risk level to `prohibited`: applying a classification raises `risk_level`
to `prohibited` (source `classifier`), and the effective risk level is at least `prohibited` while
the level is l5.

## Open questions

1. Should a prohibited system carry the initiation tasks only? The rule adds them, but sizing
   (`config/tasks.yaml`, per agent band) is unchanged, so the later stages are still planned.
2. A scan (workspace auto-register) never sets the level. It keeps its proposal in
   `tags.autonomy_level_proposal` (and `tags.autonomy_level_proposal_ref`); a person sets
   `autonomy_level`. The Classification tab shows the proposal.
3. The stored risk level is never lowered by applying a classification. Lowering (for example
   after a system leaves l5) is `POST /v1/systems/{id}/risk-level/lower` with a reason, by a person
   who is not the owner.

## The cap at the gate (WP-B1)

An accepted smart guardian line `max_level` is stored in the system tag `autonomy_limits`. With
`SMART_GUARDIAN=1` and `GOVERNANCE_ENABLED=1` the gateway reads that tag for every agent linked to
the system (an agent on several systems gets the strictest limit) and applies one deterministic
rule, `GATE-AUTONOMY-CAP`. A matching call is paused for approval: the agent is paused and a person
resumes it, as for the other pause rules. Source: `src/supervisor/gateway/autonomy_cap.py`.

| Check | Pause when |
|---|---|
| Level | the level the tool risk class needs is above `max_level`. `read_only` needs L3; `money`, `credit`, `pii_export` need L4 (illustrative; the bank sets the real mapping) |
| Amount | a `money` call has an integer `amount_minor` above `approval_above_vnd`; a `credit` call above `credit_approval_above_vnd` (VND has no minor unit) |

Observe mode lifts the pause like the other rules (`observed_decision`; on money, credit and
pii_export tools it needs the two `observe_approvals`). Output checks are not tool calls and are not
checked. The tag is cached for 5 seconds. With the flags off, no source exists and nothing changes.
The other limits of the tag (`daily_total_vnd`, `session_max_*`) are not enforced by this rule.
