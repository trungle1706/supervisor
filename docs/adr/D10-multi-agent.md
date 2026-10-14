# D10 - Multi-agent

Status: Accepted (plan v2, 2026-10-14)

## Context

Agents call other agents. No bus exists that shows who called whom. A split payment can pass every single-call limit.

## Decision

- The stream is derived from gateway events. No new bus.
- The `caller_agent_id` header is mandatory on gateway calls. A call without it is treated as unknown (fail closed for money tools, see D03).
- Phase 1 has one pattern: split-payment aggregate limit. It is a stateful rule in gateway code over a window.
- The pattern job runs in the in-process scheduler over gateway events (WP7).
- Other patterns (loops, privilege chaining) are design only.

## Consequences

- Agents must send the header. The SDK decorator sets it. Agents that call the proxy directly need a change.
- A caller can lie in the header. Identity binding is in the schema (`identity_binding`) but strong proof needs bank identity work.
- One pattern is a demo of the method. It is not full coverage. Coverage is shown in the console (`coverage` table).

## Changes from 06 section 3

- None. 06 puts multi-agent code in WON'T for the competition build. Plan v2 lists one pattern in WP7.
