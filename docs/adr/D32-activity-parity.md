# D32: Activity and analytics parity, nine alert use cases

Status: accepted for WP39 (phase 3, wave 2). Flag `CONSOLE_DECISIONS_V2`, off by default.
Highest ADR on the branch before this one was D23 (WP37); D24 to D31 belong to other packages.

## Context

WP37 made every gate decision carry a verdict (`status`, findings, `not_executed`, coverage,
`correlation_id`). The console still showed the old decision: no findings, no coverage, no latency
split, no way to follow one id from the decision to the trace and the alert. A SOC analyst on call
and a data protection officer need three things the old pages cannot give: triage from one drawer,
proof that no raw personal data is on any page, and alerts that mean something on a bank SOC
(bypass, detector outage, secrets and personal data in outputs, spikes, latency, errors, auth
anomalies).

## Decisions

1. **One flag, one switch back.** `CONSOLE_DECISIONS_V2=0` (default) leaves the Decisions list and
   drawer, the Traces pages and the Analytics tabs as in v0.3.0. With it on: four-tab drawer,
   six new filters, masked CSV export, deep links, correlation id in Traces, Gate tables and the
   Detectors tab in Analytics, the rollup job. The nine alert rules and the alert correlation id
   do not need the flag (they need `ALERTS_ENABLED` and, for the verdict signals,
   `DETECTORS_ENABLED`).
2. **Masked text only; the gate stores no arguments.** The gate keeps a keyed hash of the
   arguments (R2), so the Request tab is rebuilt from the recorder events of the same trace and
   passed through the masker again. A fragment is located on that text by its offsets, else by its
   token, else listed as "not located". Every finding text, entity token and reason is masked
   again on the way out, so a buggy detector row cannot leak. With no masker, or at capture level
   `digest`, no text is shown. The transformed payload is not stored by the gate; the Response tab
   shows it rebuilt from the masked record and says so. A gate that stores the masked payload
   itself is in BACKLOG.
3. **Additive facts, nullable, only with detectors on.** `agent_event` gets `request_id`,
   `consumer_id` (from `context.consumer_id`, a plain id), `latency_rules_us`,
   `latency_detectors_us` and `detector_latency_json`; `alert` gets `correlation_id`. Overhead is
   `latency_us - rules - detectors`. The fingerprint test of WP37 (flag off, byte for byte) is
   unchanged except for the new null columns it already ignores.
4. **A rollup table for Analytics.** `decision_daily` (per UTC day, dimension, key, key2) is
   filled by `python -m supervisor.jobs.decision_rollup` with grouped SQL (SQLite and Delta
   dialects). Pages read it and never scan the raw tables on load. Percentiles per detector are
   exact per day; over several days p50 is the weighted mean and p95 the highest daily p95.
5. **CSV export: allow-list, cap, audit, no GET with side effects.** 18 columns, all ids, codes,
   enums and integers. `CONSOLE_EXPORT_MAX_ROWS` (default 5000) cuts the file and the answer says
   `truncated: N of M rows`. The action is a POST with the two `console_action` rows (permission
   `decisions.export`, auditor and admin); the file is read by a GET with the same permission.
   Cells that start with `=`, `+`, `-` or `@` get a leading quote.
6. **Alert engine: two optional keys, no code.** `where_min` (a numeric floor) and `rate`
   (`min_bp`, optional `of`): the rule fires when matching signals are at least that share of the
   signals of the source and group in the window, and at least `threshold` of them. p95 above a
   budget is written as "more than 500 bp of calls above the budget". Rule hashes of old rules are
   unchanged (the keys enter the hash only when used).
7. **New signals are derived, not stored.** `gate_finding` (from `finding`), `gate_request`
   (decisions and ingress rejections), `coverage_gap` (agents seen in traces or the inventory with
   no decision in the window). They are not counted in `judged`. HTTP statuses of the gate routes
   are not stored, so AL-ERROR-RATE counts what is stored; persisting route status is in BACKLOG.
8. **Findings are advice (R1).** AL-THREAT-NOT-ENFORCED reports a hint of `pause` or `block` on an
   agent in SHADOW. No finding changes a decision here.

## Consequences

* The drawer needs the recorder to have stored masked text for a call; a gate-only client sees the
  findings and the masked fragments but not the text around them.
* The coverage gap check treats an agent seen under a second id as a gap for the id the gate never
  saw. That is a feature (it shows the naming problem) and a source of one extra alert.
* Thresholds of the nine rules are ILLUSTRATIVE until the bank SOC sets them.

## Review addendum (WP39 Opus review, 2026-10-20)

* **Caller ids are not trusted to be ids.** The plain-id pattern accepts `@`, `.` and digits, so
  an e-mail or a phone number passes it. The gate (one choke point, `Gateway._req`) replaces a
  correlation or request id that the Vietnamese masker finds personal data in with a new id,
  and drops such a consumer id; the alert row drops such a correlation id; every console page,
  the export and the rollup show older rows of that kind as `<id-hidden>`. Cost: about 1 in
  4000 random hex ids and ids with a 9 to 19 digit run look like a number to the masker.
* **Export download.** One-time link, bound to the user who built it and to 15 minutes, signed
  with a key held in the process; the file is deleted when served; stale files are removed on
  every export; the audit note carries a hash of the filters.
* **AL-THREAT-NOT-ENFORCED.** `enforcement` is read from the decision: `enforced` only when a
  rule stopped the call (block or pause), `shadow` in SHADOW, `observe` for an observe verdict
  row, else `not_enforced` (findings never stop a call, R1). The rule fires on `shadow`,
  `observe` and `not_enforced`.
* **AL-COVERAGE-GAP.** Only `tool_call` events count (LLM calls and messages never pass the
  gate); the inventory counts only for systems not in the registry; a RETIRED agent that still
  calls tools is a gap (the gate records a block for each call of a retired agent).

