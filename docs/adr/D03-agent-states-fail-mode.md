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
