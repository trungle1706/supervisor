# D01 - Gateway

Status: Accepted (plan v2, 2026-10-14)

## Context

Agents need one place where a tool call can be allowed, blocked or paused before it runs. Today no such place exists. The scanner tools we looked at (mcp-scan) only scan. Invariant Gateway is dormant.

The bank workspace allows one Databricks App. It does not allow creation of serving endpoints. The bank laptop has no Docker.

## Decision

The gateway is an own thin FastAPI service. It is a route group in the same process as the console and the API. On Databricks it is a route in the single Databricks App. On the laptop it is a route in `python -m supervisor.cli serve`.

There are three enforcement points:

| Point | What it is | When |
|---|---|---|
| MCP proxy | Gateway sits between agent and MCP server | Phase 1 |
| `@supervised_tool` | Python SDK decorator that calls `/gate/check` | Phase 1 |
| Egress proxy | Network level control | Later |

Routes: `/gate/check`, `/gate/pause`, `/gate/resume`. The gateway reads policy from the policy store and the agent state from the state store (see D03).

## Consequences

- One process, one deploy unit. No cross-service network hop for the check.
- The gate shares CPU with the console. We publish p50/p95/p99 from `tests/perf` to prove the budget (see D02).
- If the App adds too much latency, a separate host can return. This is a backlog item.
- A crash of the App means the gateway is down. D03 fail mode covers this case.

## Changes from 06 section 3

- 06 says "hosted on Model Serving (route optimization) or as sidecar". Plan v2 drops the Model Serving pyfunc host. BACKLOG.md item: "Model Serving pyfunc host for the gateway". It returns when endpoint creation rights exist and spike B shows too much latency.
