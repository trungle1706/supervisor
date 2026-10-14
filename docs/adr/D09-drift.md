# D09 - Drift

Status: Accepted (plan v2, 2026-10-14)

## Context

A model or prompt change can shift agent behaviour with no rule broken. Lakehouse Monitoring support for GenAI is not confirmed.

## Decision

- Drift is an in-process scheduled job: `python -m supervisor.jobs.drift`. It runs under the APScheduler inside the server process.
- Input: `agent_event` and the metrics tables. SQLite on the laptop, Delta on Databricks.
- A baseline band is kept per agent version. A value outside the band opens a case.
- Fairness slices (Fairlearn, `monitors` extra) run on configured attributes.
- Heavy runs may use the Command Execution API runner on the shared cluster. This is an optional extra.

| Seeded test | Expected |
|---|---|
| Drift week, no rule broken | A case opens |
| Fairness gap on seeded slices | Gap is computed and stored |

## Consequences

- No Databricks job is needed. This fits the "no Jobs" workspace limit.
- The job stops when the App restarts. Schedules rebuild at start. A missed run is caught up at the next start.
- Large event volumes may exceed one process. The runner extra is the first fallback.
- Lakehouse Monitoring as an extra view stays an idea.

## Changes from 06 section 3

- 06 says "scheduled Delta job". Plan v2 uses an in-process job. BACKLOG.md item: "Databricks Workflows jobs".
