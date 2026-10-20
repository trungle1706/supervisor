# D25: Multi-turn red team with a deterministic oracle and a labelled mock agent

Status: accepted for WP28 (phase 3, wave 2). Nightly job flag `REDTEAM_NIGHTLY_ENABLED`, off by
default. The pack `multiturn_redteam_vi` is informational for Launch (`launch_gate: advisory`).

## Context

Per-message filters miss attacks that build over many turns (the Echo Chamber and Crescendo
families, arXiv:2601.05742). Our target is not a chatbot but an agent with tools, so the harm is
a tool call: a transfer split under the limit, a fee waiver past authority, a loan file read for
a customer who did not ask. The existing red-team replay (145 + 16 cases) is single-turn and
assumes a compromised agent. Nothing measured whether a patient attacker can lead an agent, one
turn at a time, to a call that a rule should stop, or whether the rules stop it when it happens.

## Decision

1. **The oracle is deterministic.** A conversation succeeds when the agent makes a call that
   crosses a line (`oracle.py`: summed amounts in a window, counts, forbidden tools, a decision
   on an incomplete file, distinct files read, personal data in a reply). It reads calls, never
   text, never a model (R1). Judges, including the two-stage success / benign judge of the
   paper, only add evidence next to it.
2. **Success and gate decision are separate columns.** The gate runs in SHADOW on every turn:
   nothing is stopped, the answer says what WOULD be. We record the rule ids per turn and
   whether the call that crossed the line was one the gate would stop. A success the gate would
   not stop is the finding.
3. **A labelled mock agent, plus a worst case.** The sandbox agents run a scripted mock LLM, so
   "does the model give in?" has no offline answer. `agentsim.py` is a transparent susceptibility
   model (cues in the text build pressure; each call has a perceived risk; the agent partly
   tracks cumulative limits). It drives `attack_success`, which is labelled mock everywhere. The
   metric that holds for any agent is `gate_catch` in the **worst case** (the agent always makes
   the requested call), measured over objectives that a rule covers. Known holes are counted
   apart (`gap_class`), never mixed into that rate.
4. **Template attacker by default, LLM attacker optional and boxed in.** Six plain-Python
   strategies write the turns from phrase pools, seeded, offline. An LLM may only rephrase a
   turn: calls, order, ids, amounts and digit strings are protected tokens that never reach the
   model, so the oracle stays valid and no personal-data shape leaves the process (R2). It uses
   the configured endpoint only (`LLM_BASE_URL`), temperature 0, pinned model id
   (`REDTEAM_ATTACKER_MODEL`), prompt version in every row, sequential calls, hard cap of 60
   conversations per live run. The nightly job never uses it.
5. **Session signals for WP27, in the same trace.** Each turn records refusals, "expand on"
   requests, risk-topic turns and Tier 0b hits (counters after the turn), so a counter-based
   monitor can be replayed against the traces with its own K.
6. **Results are ordinary assurance results.** One `eval_result` row and one `assurance_result`
   chain record per agent and run (aggregates only: integers, cells with Wilson intervals; no
   conversation text in the chain). Traces go to files for WP27.
7. **Code lives in `src/supervisor/redteam/multiturn/`**, data in `data/eval/multiturn_redteam/`
   and `data/eval/playground_samples/`. `agents/redteam/` keeps only data, and an importable
   package must sit under `src/`.

## Consequences

* Two additive edits outside the package: `DemoAgentTarget.run_planned(..., gap_s=None)` so a
  conversation can move the sandbox clock by seconds instead of two days (default unchanged), and
  a scheduler job listed only when the flag is on. The gate and the judge are consumed, not changed.
* The first run found six plan kinds where the worst case escapes the gate (two accounts of one
  customer, a fresh payee then a large transfer, personal data in a read-only reply, bulk reads
  of loan files and credit scores, fee waivers across accounts). They are control objectives
  beyond the written rules; the owner decides which become rules.
* Attack success rates are a property of the mock model. They compare families and runs; they are
  not a rate for any real model. A real-agent run (the agent model behind the sandbox) is
  BACKLOG.
* The probes outside the templates (39: telex, no diacritics, mixed language, symbol and digit
  substitutions, homoglyphs, encodings, limit edges, benign look-alikes) found one defect on
  the first run (a tone key before the final consonant, `bajn`) and two limitations that are
  listed, not hidden (a typo defeats the lexicon; Tier 0b flags "ignore my earlier instructions"
  in a benign sentence).

## Alternatives rejected

* Judge-decided success (as in the paper): rejected for a tool-using target; a judge false
  positive would become a finding.
* A real model as the sandbox agent now: not offline, not deterministic, and it belongs to the
  agent owner; the interface (`run_planned`) allows it later.
* One pooled catch rate including the known holes: it would hide regressions behind the holes.
