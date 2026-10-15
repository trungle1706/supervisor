# D03 - Agent states and fail mode

Status: Accepted (plan v2, 2026-10-14)

## Context

No rule exists today for what happens when the gateway cannot decide. No rule exists for the state of an agent.

## Decision

Each agent has one state.

| State | Meaning |
|---|---|
| RUNNING | Rules enforce. Calls pass if allowed. |
| SHADOW | Rules evaluate and log. They do not block. |
| PAUSED | All calls are blocked until resume (see D04). |
| QUARANTINED | Blocked. Only a reviewer can inspect. Used after a confirmed incident. |

Each rule has a fail mode:

| Tool class | Fail mode |
|---|---|
| Money, credit, PII export | Closed: block if the gateway cannot decide |
| Read-only, chat | Open plus alert |
| Unknown tool or unknown agent | Closed |

The hard timeout for a check is 2 s. After 2 s the fail mode applies.

Mutable state (agent state, counters) lives in SQLite on the laptop. On Databricks it lives in Delta with `row_version` optimistic concurrency. A state change that loses the race is retried or rejected, never merged silently.

## Consequences

- WP3 test: make the policy store unavailable mid-test. Money tools must block.
- A fail-closed outage stops real work. The owner must accept this per tool class.
- Delta state has higher latency than SQLite. Counters for 0a use an in-process cache with write-through.

## Changes from 06 section 3

- None in the rules. Storage changes: no Lakebase. BACKLOG.md item: "Lakebase for mutable state".


## Amendment WP19: RETIRED

A fifth state ends the life of an agent.

| State | Meaning |
|---|---|
| RETIRED | Out of service for good. The gateway blocks every call, read-only tools too (builtin rule `GATE-RETIRED`, reason "agent retired"). `agent.status` shows `retired`. |

Transition rule (one way):

| From | To RETIRED |
|---|---|
| PAUSED | allowed |
| SHADOW | allowed |
| RUNNING | refused: pause it first |
| QUARANTINED | refused: an admin releases it to PAUSED first |
| RETIRED | no-op (already retired); no transition leaves RETIRED |

Resume, `set_mode`, pause, quarantine and release refuse a RETIRED agent. Authority: an admin
listed in the policy `admins` (same check as a quarantine release, D04). Entry point:
`AgentStateMachine.retire`; the Onboard stage `python -m supervisor.onboard --retire AGENT_ID`
also closes the open cases, writes the `agent_retired` chain entry, builds the audit pack and
renders the retirement note.
