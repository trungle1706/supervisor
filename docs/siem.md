# SIEM export (WP21)

Supervisor sends security events to the bank SIEM. One way, off by default. This page is
the operator and SOC reference: sinks, formats, field mapping, and connection examples for
Splunk, Microsoft Sentinel and Databricks. The older contract text (ITSM, pager, SCIM) is in
`docs/bank-integration.md`. Design choices: `docs/adr/D15-alerts.md`.

Code: `src/supervisor/adapters/integrations/siem.py` (events, sinks, feed), `ocsf.py`,
`transport.py`, `deadletter.py`; jobs `python -m supervisor.jobs.siem` and the alert job
(`docs/alerts.md`). Tests: `tests/integrations/test_siem_wp21.py`.

```
evidence chain --(cursor per lane)--> events --> format (jsonl | cef | ocsf) --> sink
alert rows ----------------------------------------------------------^          file  -> forwarder tails it
                                                                                http  -> POST, retry, dead letter
                                                                                delta -> table siem_event
```

## Switches

| Variable | Default | Meaning |
|---|---|---|
| `SIEM_ENABLED` | `0` | Master switch. Off: no job, no file, no network |
| `SCHED_SIEM_S` | `60` | Job interval in seconds (the app scheduler runs the `siem` job) |
| `SIEM_SINK` | `file` | `file`, `http` or `delta` (`webhook` is the old name of `http`) |
| `SIEM_FORMAT` | `jsonl` | `jsonl` (alias `json`), `cef` or `ocsf` |
| `SIEM_FILE_PATH` | `<DATA_DIR>\siem\events.log` | File sink target |
| `SIEM_FILE_MAX_BYTES` | `0` | Rotate at this size. `0` = never rotate |
| `SIEM_FILE_BACKUPS` | `5` | Rotated files kept: `events.log.1` ... `.5` |
| `SIEM_WEBHOOK_URL` (alias `SIEM_HTTP_URL`) | empty | `FILL-ME`; needed for `SIEM_SINK=http` |
| `SIEM_HTTP_TOKEN` | empty | Secret from the bank vault. Sent as `Authorization: <scheme> <token>`. Never logged, never in the dead-letter file |
| `SIEM_HTTP_AUTH_SCHEME` | `Bearer` | `Splunk` for Splunk HEC |
| `SIEM_SRC_APP`, `SIEM_SRC_HOST` | `supervisor`, this host | OCSF `src_endpoint` of class 6003 |
| `SIEM_DEAD_LETTER_PATH` | `<DATA_DIR>\siem\dead_letter.jsonl` | Where failed batches wait |
| `SIEM_DEAD_LETTER_MAX_BYTES` | `67108864` (64 MiB) | When the file is full the send raises and the cursor stays (the chain is the buffer) |

Run once by hand (the app must be stopped, or let the scheduler do it):

    python -m supervisor.jobs.siem
    python -m supervisor.jobs.siem --replay-dead-letter

## Sinks

| Sink | Use it when | Behaviour |
|---|---|---|
| `file` | The bank already runs a forwarder (Splunk UF, Azure Monitor Agent, Elastic agent, Fluent Bit) | Appends one line per event. Rotation by size between whole batches, so no line is split. Point the forwarder at `events.log*` |
| `http` | The SIEM has an HTTP collector | `POST {"events": [...], "event_ids": [...], "format": "...", "idempotency_key": "..."}`. 3 attempts, back-off 1 s then 2 s. Network errors, timeouts, 429 and 5xx are retried; another 4xx (wrong URL or token) is not. After the last failure the batch goes to the dead-letter file and the job moves on |
| `delta` | Supervisor runs as a Databricks App and the SIEM reads Delta | Appends rows to table `siem_event` through the SQL adapter (an insert-only `MERGE` on Delta, so a repeat adds nothing). Each row has the OCSF document in `ocsf_json` |

Idempotency: every event has a stable `event_id` (`<lane>:<seq>`, `anchor:<id>`,
`alert:<id>`); an HTTP batch lists them in `event_ids` so the receiver can dedupe per event. A batch has `idempotency_key` = first 32 hex of SHA-256 over the event ids,
in the body and in the `Idempotency-Key` header. A replay sends the same key.

Cursor: one per chain lane, stored in `monitor_state` (monitor `siem`, key `cursor:<lane>`),
saved only after the sink accepted the batch. Delivery is **at least once**, not exactly once:
a restart never skips an event, but a crash between the send and the cursor save sends the
last batch again (and a later batch can then hold more events, so its batch key differs). The
receiver must dedupe on `event_id`; the `delta` sink does this itself (primary key). If the
sink raises, nothing is saved and the next run sends the same events again. A batch that
went to the dead-letter file counts as accepted (the file keeps it). When the dead-letter file
is full (`SIEM_DEAD_LETTER_MAX_BYTES`, default 64 MiB) the send raises instead, so the cursor
stays and the evidence chain itself is the buffer until the receiver is back.

## What leaves, and what never leaves

Ids, rule ids, actions, enums, counts and hashes. Never free text, tool arguments, case
comments or personal data: the event builder copies a fixed list of fields from the chain
payload, so a new text field in a payload cannot leak by accident (test:
`test_no_free_text_or_pii_in_any_format`). Alert events carry the rule id and counts only.

## Event types

| `event_type` | Source (chain record type) | Outcome values |
|---|---|---|
| `gate_decision` | `gate_decision` | allow, log, alert, block, pause |
| `gate_state_change` | `gate_state_change` | pause, resume, quarantine, release, ... |
| `case_opened` | `case`, `case_opened` | open |
| `case_event` | `case_event` | assign, triage, close, comment, ... |
| `chain_root` | `root_commit` | sealed |
| `chain_anchor` | `anchor` table | anchored |
| `alert` | `alert` table (pushed by the alert job) | open |
| `ingress_reject` | `ingress_reject` (WP20 ingress auth) | reject |
| `chain_anomaly` | `chain_verify` (console Verify chain button), `audit_pack_built`; only a failed verify is sent | verify_failed |

## Field mapping

| Concept | `jsonl` field | CEF | OCSF 1.1 |
|---|---|---|---|
| Event id (idempotent) | `event_id` | `externalId` | `metadata.uid` |
| Time | `ts` (RFC 3339 UTC) | `rt` (epoch ms) | `time` (epoch ms) |
| Severity | `severity` (0..10) | header severity | `severity_id` (0..5) and `severity` |
| Outcome | `outcome` | `outcome` | `activity_name` (`<event_type>:<outcome>`), `status_id`, `disposition_id`, `action_id` |
| Event kind | `event_type` | header name and signature id | `class_uid`, `category_uid`, `type_uid`, `unmapped.event_type` |
| Agent | `agent_id` | `cs1` (label `agentId`) | `resources[0]` (`type` AI Agent, `uid`); class 3002: `user.uid` |
| Rule id | `rule_id` | `cs2` (`ruleId`) | `unmapped.rule_id`; class 2004: part of `finding_info.title` |
| Case id | `case_id` | `cs3` (`caseId`) | `finding_info.uid` (class 2004), `unmapped.case_id` |
| Actor | `actor` | `suser` | `actor.user.uid` (class 6003) |
| Chain lane | `chain_lane` | `cs4` (`chainLane`) | `unmapped.chain_lane` |
| Chain seq | `chain_seq` | `cn1` (`chainSeq`) | `unmapped.chain_seq` |
| Entry hash | `entry_hash` | `cs5` (`entryHash`) | `unmapped.entry_hash` |
| Environment | `env` | `cs6` (`env`) | `unmapped.env` |
| Alert window count | `attrs.window_count` | `cn2` (`windowCount`) | `unmapped.attrs.window_count` |
| Alert repeats absorbed | `attrs.suppressed_count` | `cn3` (`suppressedCount`) | `unmapped.attrs.suppressed_count` |
| Other alert details | `attrs.alert_id`, `severity_label`, `window_s`, `threshold`, `dedupe_key` | not sent | `unmapped.attrs.*` |
| Ingress reject reason | `attrs.reason_code` | not sent | `unmapped.attrs.reason_code` |
| Verdict v2 (WP37, `DETECTORS_ENABLED`): status, finding codes, correlation id of a gate decision | `attrs.status`, `attrs.finding_codes`, `attrs.correlation_id` | not sent | `unmapped.attrs.*` |
| Product | `product`, `vendor`, `version`, `schema` | header | `metadata.product.name`, `vendor_name`, `version`; `metadata.log_name` |
| Source of the call (class 6003) | - | - | `src_endpoint.svc_name` (`SIEM_SRC_APP`, default `supervisor`), `src_endpoint.hostname` (`SIEM_SRC_HOST`, default this host). Never a user address |

`jsonl` always has the key `attrs` (null when there are no details).

## OCSF class map

OCSF version `1.1.0` (`metadata.version`). Required base attributes are always present:
`activity_id`, `category_uid`, `class_uid`, `severity_id`, `time`, `type_uid`, `metadata`.
`type_uid = class_uid * 100 + activity_id`; `category_uid = class_uid // 1000`. This is a
documented subset, not a full conformance claim: attributes Supervisor has no data for (for
example `src_endpoint`, `api.service`) are left out, and Supervisor-specific ids sit under
`unmapped`.

| Supervisor event | OCSF class | `class_uid` | `category_uid` | `activity_id` |
|---|---|---|---|---|
| `gate_decision` | API Activity | 6003 | 6 | 99 (Other); `api.operation` = `gate_decision:<action>` |
| `gate_state_change` | API Activity | 6003 | 6 | 99; `api.operation` = `gate_state_change:<event>` |
| `chain_root`, `chain_anchor` | API Activity | 6003 | 6 | 99 |
| `case_opened`, `alert`, `chain_anomaly` | Detection Finding | 2004 | 2 | 1 (Create) |
| `case_event` | Detection Finding | 2004 | 2 | 2 (Update) |
| `ingress_reject` | Authentication | 3002 | 3 | 1 (Logon), `status_id` 2 (Failure) |

Disposition for class 6003: allow and log 1 (Allowed), alert 15 (Detected), block and pause 2
(Blocked), quarantine 3 (Quarantined). `action_id` is 1 for allowed and 2 for denied.
Severity: CEF 1-2 to `severity_id` 1, 3-4 to 2, 5-6 to 3, 7-8 to 4, 9-10 to 5.

## Examples (replace every FILL-ME)

### Splunk

Preferred path: file sink plus the Splunk Universal Forwarder (nothing opens a network
connection from Supervisor).

    SIEM_ENABLED=1
    SIEM_SINK=file
    SIEM_FORMAT=jsonl
    SIEM_FILE_PATH=FILL-ME-path-the-forwarder-tails\events.log
    SIEM_FILE_MAX_BYTES=52428800

`inputs.conf` on the forwarder:

    [monitor://FILL-ME-path-the-forwarder-tails\events.log*]
    sourcetype = supervisor:siem:v1
    index = FILL-ME-index
    INDEXED_EXTRACTIONS = json
    TIMESTAMP_FIELDS = ts

HTTP path: Splunk HEC accepts one JSON event object per request, not the batch envelope, so
point `SIEM_WEBHOOK_URL` at a bank relay (or an HEC-compatible collector that accepts
`{"events": [...]}`) and set `SIEM_HTTP_AUTH_SCHEME=Splunk`. Direct HEC batching is in the
backlog.

    SIEM_SINK=http
    SIEM_WEBHOOK_URL=FILL-ME-https://relay.example/services/collector
    SIEM_HTTP_AUTH_SCHEME=Splunk
    SIEM_HTTP_TOKEN=FILL-ME-from-the-bank-vault

Search example for the SOC: `index=FILL-ME-index sourcetype=supervisor:siem:v1 event_type=alert severity>=8 | stats count by rule_id agent_id`.

### Microsoft Sentinel

Option A, CEF through the Azure Monitor Agent (Linux syslog forwarder) or a file with the
custom-log connector:

    SIEM_ENABLED=1
    SIEM_SINK=file
    SIEM_FORMAT=cef
    SIEM_FILE_PATH=FILL-ME-path-the-agent-reads\events.cef

Sentinel then shows the events in `CommonSecurityLog` (`DeviceVendor` = Supervisor,
`DeviceCustomString1` = agent id, `DeviceCustomNumber1` = chain seq).

Option B, OCSF lines in a custom table through a Data Collection Rule (the bank's DCR maps
the JSON fields):

    SIEM_FORMAT=ocsf
    SIEM_FILE_PATH=FILL-ME-path-the-agent-reads\events.ocsf.jsonl

KQL example: `CommonSecurityLog | where DeviceVendor == "Supervisor" and Activity startswith "alert" | summarize count() by DeviceCustomString2`.

### Databricks (Delta, Lakehouse Monitoring or a Databricks-hosted SIEM connector)

For the Databricks App (`SUPERVISOR_MODE=databricks_app`), nothing leaves the workspace:

    SIEM_ENABLED=1
    SIEM_SINK=delta
    SIEM_FORMAT=ocsf

The table is `FILL-ME-catalog.FILL-ME-schema.siem_event` (the app schema; created by the
schema bootstrap). Grant the SIEM connector's principal `SELECT` on it. Example query:

    SELECT ts, event_type, severity, agent_id, rule_id, ocsf_class_uid
    FROM FILL-ME-catalog.FILL-ME-schema.siem_event
    WHERE ocsf_class_uid = 2004 AND severity >= 8
    ORDER BY ts DESC;

`ocsf_json` holds the full OCSF document for a connector that parses OCSF. The table is
append-only (`delta.appendOnly`); the retention job does not touch it (it holds ids only).
Lakehouse Monitoring can profile it like any Delta table.

## Failure handling and replay

| Situation | What happens | What you do |
|---|---|---|
| Receiver down for seconds | 3 attempts, 1 s and 2 s back-off | Nothing |
| Receiver down longer | Batch is appended to the dead-letter file; the job logs and goes on; cursor moves | After the fix: `python -m supervisor.jobs.siem --replay-dead-letter` (same idempotency keys) |
| 4xx from the receiver | Not retried; batch goes to the dead-letter file | Fix the URL or token, replay |
| Sink raises (file system full, delta write fails) | Cursor is not saved; the next run sends the same events | Fix the cause |
| Process restarts | Cursors are read from `monitor_state` | Nothing |
| Windows forwarder holds the file without share-delete | Rotation is skipped (a warning in the log), the live file grows past the limit, rotation is tried again next batch | Open the file with share-delete in the forwarder (the Splunk UF does) |

A SIEM failure never blocks a gate decision, a case action or an alert (the alert is stored
first).

## Not done

See `BACKLOG.md` (WP21 lines): native Splunk HEC batching, QRadar LEEF, live checks against
a real SIEM, a range read instead of a full chain scan per poll, OCSF schema validation
against the official JSON schema (needs the bank to pick the version).

## Alert events and the correlation id (WP39)

An `alert` event now carries `attrs.correlation_id`: the correlation id of the signal that fired the alert (gate findings, requests and decisions have one; ingress rejections and coverage gaps do not, so it is empty). Search the SIEM for that id to see the alert, the gate decision (`attrs.correlation_id` of the `gate_decision` event) and the trace together.
