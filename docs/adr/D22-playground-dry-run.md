# D22: Playground dry run (`Gateway.evaluate_only`)

Status: accepted for WP-UX3 (phase 3). Flag `CONSOLE_PLAYGROUND_ENABLED`, off by default.

## Context

The Playground lets a person ask the gate what it would decide for a call, without making the
call. The gate's normal path (`Gateway.check`) writes verdict rows, an event row and a chain
record, adds the call to the sliding windows, may pause the agent and counts in the metrics.
A Playground that used it would pollute the evidence, could pause a production agent, and would
distort the numbers. The first design note in the console spec proposed a fresh `WindowStore`
and a null recorder.

## Decision

1. A new entry `Gateway.evaluate_only(agent, version, tool, args, context)` returns the same
   result shape as `check` plus `dry_run`, `shadow`, `builtin`, `would_pause` and
   `not_evaluated`. It runs on the gateway's worker pool with the same 2 s timeout and never
   raises (`error` in the answer).
2. The decision logic is **one function**, `Gateway._evaluate`, that both `_decide` (real) and
   `_dry` (dry run) call. It reads a policy snapshot and returns the decision; it writes
   nothing. So a dry run cannot drift from the real gate. `_decide` keeps everything with a side
   effect (windows, pause, recording, metrics, Tier 0b).
3. Rules that need history (`aggregate`, `prior`) are **not evaluated** in a dry run. The live
   windows must not be read for a rehearsal, and an empty window would give a wrong answer
   (a "prior call absent" rule would always match). They are listed in `not_evaluated` when
   their tool and predicates match, and the page says so.
4. A pause rule sets `would_pause`; the agent state is never touched. An agent that is already
   paused, quarantined or retired gives the built-in block, as in the real gate.
5. Inline redaction runs (it is a pure function of the arguments) but the redaction hint cache
   of the gateway is left alone.
6. The Playground route is audited like every POST (two `console_action` rows). The `ok` row's
   `detail` holds `in:<24 hex>` of the **keyed HMAC** of the arguments (same key as the gate's
   `args_hash`), never the arguments. A route may set `request.state.audit_detail` for this; the
   audit decorator copies it into the outcome row only.
7. The typed arguments may hold personal data. They are used for the evaluation only; the
   answer shows a masked preview and counts, never the typed values.
8. In `databricks_app` mode the page also needs `PLAYGROUND_ALLOW_APP=1` (owner decision
   pending): a shared App has more users and no local-only guarantee.

## Consequences

* Proof: `tests/gateway/test_evaluate_only.py` and `tests/console/test_ux3_playground.py`
  compare a SHA-256 over every row of every table, the chain heads, the agent states, the window
  store, the evidence sink and the metrics before and after dry runs (pause, block, unknown
  agent, unknown tool, personal data in the arguments); a guard test shows the same fingerprint
  does change after a real check.
* `_decide` was split. The 447 gateway tests passed unchanged. A change to rule matching is now
  one change, in one place.
* A dry run is not a prediction for window rules; the page lists them.
