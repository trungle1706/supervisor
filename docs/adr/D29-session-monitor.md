# D29: Session monitor

Status: accepted for WP27 (phase 3, wave 2). Flag `SESSION_MONITOR_ENABLED`, off by default.
(D24 to D28 belong to other packages; D23 was the highest on this branch.)

## Context

Per-call checks miss a conversation that is steered over many turns (Echo Chamber, Crescendo,
payload splitting, a planted fact used later). The drift monitor works on daily bands per agent, not
on one conversation. Judges and detectors score single calls.

## Decision

1. **Session identity on every decision.** `session_id` from the context, else a derived id (agent
   + consumer + day, `session_source=derived`). Stored on `agent_event` (nullable columns), on the
   answer and as `session_sha256` on the chain.
2. **One pure engine** (`monitors/session.py`) used by the gate (in-request) and by a batch job
   that replays `agent_event`. Nine integer signals, policy weights that sum to 10000, a score in bp.
   No model. Turn text is read in memory and dropped; only flags, a keyed bottom-k sketch and
   keyed hashes are stored (R2).
3. **R1.** The only effects are a case and, if the policy lists a tool class in `pause_scope`, a
   session-scoped pause enforced by the built-in rule `GATE-SESSION-PAUSE`. Findings and judge
   output are counters. Default: case only, pause off.
4. **PII-shaped findings do not count** as an attack signal (WP28 false alarms came from them). A
   detector that timed out is not a finding, and a `GATE-DETECTOR-FAILED` block is not a refusal.
5. **State signal `memory`** (authority fact asserted early, used by a later money or credit call)
   because counters see almost none of that pattern (WP28: 4 percent). It may open a case alone
   (`solo_signals`); the harness shows its false alarm rate.
6. **Pause lifetime.** Ends by the two-person resume (owner + reviewer, same role rule as the agent
   resume; also when the agent itself gets its resume) or by cool-down, both on the chain.
7. **Operating point** K=3, case threshold 2500 bp, pause threshold 4000 bp, window 1800 s,
   cool-down 3600 s: chosen on the dev split only (no false alarm); ILLUSTRATIVE until the bank sets
   them.

## Consequences

* New table `session_control`, three nullable `agent_event` columns, permission `session.view`,
  alert rule `AL-SESSION-ESCALATION`, `case_type` as an alert field of the `case` source.
* The in-request path adds about 0.2 ms p95 to a decision (harness) and one state read every 2 s
  (background thread).
* Known limits (BACKLOG): slow attacks beyond the window, session id churn, obfuscated phrases,
  paraphrased memory poison, two consumers for one actor.
* The pause is per session id: an attacker who rotates the id escapes it; the cross-agent and
  consumer signals are the only bridge.
