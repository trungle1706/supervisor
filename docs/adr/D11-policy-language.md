# D11 - Policy language

Status: Accepted (plan v2, 2026-10-14)

## Context

Risk staff and the Onboarding Agent must write policies. Policies must be testable now and analysable later.

## Decision

- Policies are YAML files with a typed schema and a loader. Each policy has a hash (`policy_hash`).
- Stateful limits (windows, aggregates) live in gateway code. YAML names them and sets parameters.
- A policy suite runs as tests. A prompt change triggers a re-run of the suite.
- Cedar is the intent for later (H1 2027). The YAML schema is chosen so it can compile to Cedar. Cedar is not built in plan v2.

## Consequences

- No new language runtime. Pure Python, YAML parse only.
- YAML cannot express everything. Complex rules need code and a code review.
- Cedar later gives formal analysis. The compiler is future work, so migration cost is not yet known.
- Policy files are data. The loader treats them as untrusted input: schema check, size limit, no code.

## Changes from 06 section 3

- Same choice. The Cedar step is kept as an intent only, with no work package. Add a BACKLOG.md line for "Cedar compiler" when the lead updates the backlog (it is not in BACKLOG.md today).
