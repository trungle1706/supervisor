# D15 - SIEM export and alerts

Status: Accepted (WP21, 2026-10-20). Bank decisions listed under "Open".

## Context

Phase 2 had a SIEM formatter with two sinks marked stub, a webhook notifier that never sent, and
no way to tell the SOC "something needs a human". A bank SOC works from alerts in its own SIEM
and pager. It needs events it can parse, alerts it can triage in about two minutes, and no flood.
It also needs proof that Supervisor does not hide a failed send.

## Decision

1. **Alerts are data, not code.** Rules are YAML (`config/alerts.yaml`), loaded with
   `yaml.safe_load` and validated key by key. No expression language, no `eval` (an AST test
   already bans it outside the sandbox). A rule is: source stream, equality filters, group,
   window, threshold, severity, dedupe time, routes. Rejected: a small expression DSL (more
   power than seven rules need, and one more thing to audit).
2. **One flat signal shape.** Gate decisions, state changes, ingress rejections, chain verify
   results and drill results come from the evidence chain (already free of PII); tier 2
   verdicts from the `verdict` table; job failures from the scheduler's own `monitor_state`.
   Reading the chain keeps alerts verifiable: each alert points at a lane, a seq and an entry
   hash.
3. **The engine is a pure function.** `evaluate(rules, signals, cursor, last_fired)`. Time comes
   from the signals. Order of input does not matter. Alert ids are SHA-256 of
   `dedupe key | time | signal id`, so a replay or a second replica makes the same id and the
   insert is a no-op. Dedupe and suppression are therefore deterministic and testable without a
   clock. Rejected: counting in the database with SQL windows (hard to test, different on SQLite
   and Delta).
4. **Dedupe is by time after a fire, per rule and group.** Repeats raise `suppressed_count`
   on the open alert, so the analyst sees "still going" without a new page. An acknowledge does
   not reset the dedupe (a person saying "seen" does not mean the cause is gone). A cursor makes
   each signal count once. Planned work uses `suppressions` entries with an end time, never a
   silent threshold change.
5. **Alerts only inform (R1).** Nothing in this package calls the gate, pauses or quarantines.
   A judge verdict can raise an alert (`AL-JUDGE-ESCALATION`), never a block. The mock judge
   verdicts are excluded by the shipped rule (`is_mock: false`).
6. **Routes fail alone.** A route returns a status; a failure is stored in `route_status` and
   retried at the next run; it never stops the other routes, never raises into the scheduler,
   and the alert row is written first. The webhook route and the SIEM http sink use bounded
   retry (3 attempts, 1 s, 2 s), an idempotency key and a dead-letter file. A dead letter counts
   as accepted for the cursor because the batch is kept on disk, and `--replay-dead-letter`
   sends it with the same key.
7. **SIEM sinks and formats.** Sinks `file` (JSONL for a forwarder, size rotation), `http`,
   `delta` (table `siem_event`, insert-only MERGE through the existing SQL adapter). Formats
   `jsonl`, `cef`, `ocsf`. OCSF 1.1: gate decisions, state changes and chain sealing as API
   Activity 6003; cases, alerts and chain anomalies as Detection Finding 2004; ingress
   rejections as Authentication 3002. Supervisor ids sit in `unmapped`. We claim the required base
   attributes and the class fields we have data for, not full conformance. Cursor per lane lives
   in `monitor_state`.
8. **Webhook notifier.** `WebhookNotifier` sends when `NOTIFY_WEBHOOK_ENABLED=1` and the URL is
   filled. With the flag and no URL the old queue-only stub stays. Pager and ITSM stay stubs but
   share the `Notifier` interface through `StubNotifier`.
9. **Only ids and enums leave.** Alert text and SIEM events are built from a fixed field list.
   Titles come from the rule file. Tests plant free text and a phone number in payloads and
   assert they appear in no output.
10. **Acknowledge is a human, audited action.** Permission `alert.ack` (roles `operator`,
    `admin`), two `console_action` rows, an `alert_ack` chain record, optimistic `row_version`.

## Consequences

- New tables: `alert` (state) and `siem_event` (append-only), both DDLs. New scheduler jobs `siem`
  and `alerts`, each behind its flag. New permission and one console route.
- The harness (`python -m supervisor.alerts.harness`) is part of the test suite; a rule or
  threshold change that lowers precision, recall, dedupe or triage completeness fails a test.
- The bank SOC owns the thresholds. Ours are illustrative and tuned on synthetic data.
- `SiemEvent` gained the field `attrs` (null for old event types). Readers of schema
  `supervisor.siem.v1` should ignore unknown keys.

## Open (bank decisions)

1. SIEM product, format and path (file + forwarder, HTTP collector, Delta), and the OCSF version.
2. Real thresholds and severities per rule; who is on call for each route.
3. Whether an unacknowledged critical alert should page again after a time (not built).
4. Whether an alert should open a case by itself (not built; today a human promotes it).
5. Pager and ITSM senders for alerts (stubs today).
