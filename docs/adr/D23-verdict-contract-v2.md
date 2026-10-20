# D23: Verdict contract v2 and the detector framework

Status: accepted for WP37 (phase 3, wave 2). Flag `DETECTORS_ENABLED`, off by default.
Owner decision of 2026-10-20: verdict contract v2 on `/v1/gate/check`, old fields kept.

## Context

The gate answers with a decision (`allow`, `action`, `rule_id`) and, for the WP24b redaction,
`transformed_args`. Three other capabilities look at the same call but are wired one by one: the
masker (inline redaction), the Tier 0b regex classifier (after the call) and the judges (after the
trace). A reader of a decision cannot see what was looked at, what was found, what could not run,
or which payload parts were never inspected. A classifier planned for WP25 and a tool-description
scan planned for WP26 would each add another private shape.

## Decision

1. **One contract.** `core/detectors.py` defines `Detector` (slug, sides, protocols, settings
   schema, presets, `evaluate`), `Finding`, `DetectorRegistry`. The registry lists the catalogue
   from code, validates settings against a declarative schema, and runs the detectors whose `sides`
   include the direction. No weights and no network in the contract.
2. **Wrap, do not rewrite.** `dlp_vn` (the masker), `injection_regex` (the Tier 0b patterns) and
   `judge_advisory` (the Tier 1 judge) are detectors. Their old uses are unchanged.
3. **Verdict v2 is additive.** `status`, `findings[]`, `not_executed[]`, `coverage`,
   `transformed_payload`, `request_id`, `correlation_id`. Every old field keeps its name and
   meaning, so the SDK, the MCP proxy and the benchmark harness keep working. With the flag off
   the answer is byte for byte the old one.
4. **Precedence, explicit:** `block > pause > transform > report > allow`; `skip` only from a
   policy value. The old `action` keeps the gate order (pause rule before block rule); `status`
   says `block` when a block rule matched too.
5. **R1 holds.** A finding never blocks or pauses. A `pause` or `block` hint counts as `report`
   until a later package (WP25) is allowed to use it after model-risk validation. Two things act:
   the `dlp_vn` transform, and `GATE-DETECTOR-FAILED`.
6. **Fail closed where money moves.** A detector set `fail_closed` that cannot run on a money,
   credit or pii_export tool blocks the call with rule `GATE-DETECTOR-FAILED`. On any other tool
   the failure is an entry in `not_executed`. `judge_advisory` is never fail-closed: a judge outage
   must not stop payments (R1).
7. **Masked text only (R2).** Entities carry pseudonym tokens; fragments carry masked excerpts with
   offsets into the masked leaf. The chain gets hashes (`finding_hashes`), codes and counts, never
   text, tokens or paths. Dict keys that are not plain identifiers show as `*` in paths.
8. **Output direction.** `direction: output` checks what a tool returned. It is not a call: no rule
   is evaluated, no window changes, no pause. The state checks still apply.
9. **Detectors run outside the gate lock.** The pass is computed before the lock (a masker pass
   costs milliseconds) and folded in after the deterministic decision exists. "After the rules"
   holds for the decision; the work itself overlaps no rule evaluation.
10. **Persistence.** New table `finding`; nullable columns `verdict_status`, `correlation_id`,
    `coverage_json` on `agent_event` (the old `status` column keeps its meaning). The brief called
    this "`gate_decision` gets columns": there is no such table, the decision row is `agent_event`
    with `event_type=gate_decision`.
11. **Settings.** `config/detectors.yaml` for defaults; `agents.<id>.detectors` in the policy file
    for a per-agent override. The key is dropped from the policy hash when unset, so existing policy
    hashes do not change. Presets are named thresholds in integer basis points, illustrative, frozen
    per detector version.
12. **Harness first.** The golden set, the adversarial probes, the metrics and the baseline ship
    with the framework (team brief section 3).

## Alternatives considered

* **A new response object and a new path (`/v2`).** Rejected: every client would have to change,
  and the owner asked for old fields to stay.
* **Let a high-scoring finding pause or block.** Rejected: R1. The ML classifier of WP25 may pause
  money and credit tools after validation; the contract already carries the hint.
* **Fail open when a detector is down.** Rejected on money, credit and pii_export tools; allowed
  elsewhere, with the failure visible in `not_executed`.
* **Run detectors inside the gate lock.** Rejected: it would delay every other agent's decision.
* **A `skip` rule action in the policy language.** Deferred: `skip_tools` in the agent override is
  a deterministic policy value and needs no change of the rule schema.

## Consequences

* Proof: `tests/detectors/` (about 110 tests): contract, precedence table, flag-off fingerprint
  against the v0.3.0 value, GATE-DETECTOR-FAILED on money / pii_export and not elsewhere, skip,
  output direction, correlation id in decision / finding / chain, no raw personal data in rows or
  chain, HTTP contract, both modes (SQLite laptop and `databricks_app`, plus the Delta statements on
  the fake executor), SIEM attributes, harness regression.
* The `agent_event` table gets three nullable columns; older rows and the flag-off path leave them
  NULL.
* A timeout is checked after the detector returns; it does not interrupt a hung detector. The
  gateway's own 2 s timeout still protects the call.
* A wrong detector config stops start-up, not the gate at run time.
* WP25, WP26 and WP27 emit findings through this contract; WP39 reads `finding` and the new
  columns for the decisions drawer.
