# D19: Per-agent monitor bindings and explicit monitor status (WP1b-B)

Status: accepted for phase 3 wave 1b. Source: credit-memo benchmark defect D06
(`quality`, `fairness`, `drift` and `multiagent` silent for a non-demo agent).

## Context

`monitors/quality.py` read the tool `reply`, `monitors/fairness.py` read `decide_prequal`,
`monitors/multiagent.py` read `transfer`, and drift needed seven whole day windows. An agent
with other tool names produced no rows and no warning. A monitor that is on but silent looks
like a monitor that found nothing.

## Decision

1. **Bindings are data, per agent**: `monitors:` in the manifest and in the `agents:` section
   of `policies/*.yaml` (strict pydantic model in `core/monitor_bindings.py`; policy wins).
2. **Defaults come from tool classes** (`credit` tool = fairness decision, single `money` tool
   = payment, reply-like name on a non-money tool = output). Ambiguity is never guessed: two
   `credit` tools give `not_applicable` with the tool names in the reason.
3. **Silence is a state**: each monitor writes `ok`, `not_applicable` or `no_data` per agent
   and day into one JSON column `oversight_metric.monitor_status` (additive, both DDL files).
   A JSON column instead of a new table: the Metrics page already reads that row, and the
   status is small, derived and recomputed each run.
4. **Flags unchanged**: `QUALITY_ENABLED` etc. still switch the jobs. Without a resolver (old
   call sites, tests) each monitor behaves as before.
5. **Protected attributes may come from the decision call arguments** through
   `protected_attribute_keys`; forbidden attributes are rejected at load.

## Consequences

- A tool-name collision is possible: a non-money tool called `message_*` that is not the output
  becomes the quality tool. The reply binding overrides it; the status `n` shows what was read.
- Statuses are not on the evidence chain (derived, recomputable). If the bank wants an audit
  trail of "monitor was not applicable", record the status change on the chain later.
- Drift per-agent windows change what "baseline" means for that agent. A baseline is built once
  per agent version, so change `monitors.drift` before the baseline exists or ship a new version;
  changing it later mixes window sizes.

## Open

- Should a high-risk agent with `not_applicable` open a low-severity case? (BACKLOG)
- ADR numbering: D19 was taken here; the integrator may renumber.
