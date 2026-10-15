# D13 - Retention and deletion of personal data

Status: Accepted (WP18, 2026-10-15). Bank decisions listed under "Open".

## Context

PDPL 91/2025 requires storage limitation: personal data must not be kept longer than the purpose needs. Supervisor stores masked and raw agent text, judge rationales, case comments and inbox notices. At the same time the evidence chain (D05) must verify offline, and `append_only` tables must not be edited (SQLite triggers, Delta `appendOnly`).

## Decision

- Retention classes are declared per table in `schema/model.yaml` (`retention: {class: [columns]}`). The loader rejects unknown classes, unknown or key columns, and non-text columns.

| Class | Columns | Setting (default days) |
|---|---|---|
| `raw` | `agent_event_raw.args_raw`, `result_raw` | `RETENTION_RAW_DAYS` (90) |
| `masked` | `agent_event.args_masked`, `result_masked`; `verdict.rationale_masked`; `case_event.comment_masked` | `RETENTION_MASKED_DAYS` (365) |
| `notice` | `notice.body` | `RETENTION_NOTICE_DAYS` (365) |

- Rows are never deleted. The job sets the listed columns to NULL (empty string where the column is NOT NULL, that is `notice.body`) when the row `ts` is older than now minus the class days. Digest columns (`args_hash`, ids, labels, scores) stay.
- The chain tables (`chain_entry`, `chain_payload`, `chain_signature`, `anchor`) have no retention columns and are never touched. `verify` reads only chain tables and the export files; it does not read `agent_event` or `verdict`, so redaction cannot break it. A test redacts, exports and verifies.
- SQLite triggers for tables with retention columns: `BEFORE UPDATE OF <non-retention columns>` aborts; `BEFORE UPDATE OF <retention columns> WHEN NEW.<col> IS NOT NULL` aborts; DELETE aborts. The only allowed UPDATE sets retention columns to NULL and nothing else.
- Existing databases: `bootstrap_schema` runs the generated DDL again. For retention tables the DDL now starts with `DROP TRIGGER IF EXISTS trg_<table>_no_update` and creates the new triggers, so `python -m supervisor.jobs.bootstrap_schema` refreshes them. If it was not run, the job gets the old trigger error, reports `[FAIL]` with that command and does not crash.
- Port: `TableStore.count_due(table, columns, time_column, before_ts)` and `redact_columns(table, columns, time_column, before_ts, now=None)`. They accept only columns the model lists as retention columns.
- Job `python -m supervisor.jobs.retention` (`run(settings, adapters, chain=None)`): off by default (`RETENTION_ENABLED=0` prints `[SKIP]`). `RETENTION_DRY_RUN=1` counts only. Each run writes one `retention_run` chain entry on the root lane when a chain writer is given: per class and table the cutoff, due count, redacted count and mode. Integers and strings only, no floats, no personal data. The scheduler registers the job (interval `SCHED_RETENTION_S`, default one day) only when `RETENTION_ENABLED=1`.
- Delta (`databricks_rest`): append-only tables have `delta.appendOnly = true`, so UPDATE is refused. In this phase the job counts the due rows and prints `[SKIP] Delta appendOnly: needs bank decision (see ADR D13)`; it changes nothing there. The state table `notice` is updated normally (with `row_version` and `updated_at`).

## Scope decisions

- `signoff.reason` and `cases.summary` are out of scope. They are the human decision record needed for audit and for the regulator; their text is already masked at entry. The bank may overrule this (Open 3).
- Chain payloads are not redacted. Some payloads carry masked excerpts (for example a judge verdict payload has `rationale_masked`). They are masked and hash-linked; nulling them changes `payload_hash` and breaks `verify`. They stay for `EVIDENCE_RETENTION_DAYS` (default 1825).
- Schema rule: a `chain_*` table cannot have a `retention:` block (schema load error naming the table). Chain rows are hash-linked, so nulling a column would break `verify`. (The same rule for `evidence: true` tables is open: `agent_event`, `verdict` and `case_event` carry both today.)

## Consequences

- After the TTL, personal text is gone from the read tables while counts, hashes and the chain remain. Case files built later show empty text for redacted rows.
- Retention is irreversible. Take a backup first if the bank needs one (WP18 backup tooling).
- The chain contains a signed record of every retention run.

## Open (bank decisions)

1. Delta: allow retention on append-only tables? Options: drop `delta.appendOnly` for the listed tables and rely on grants; or a restricted retention role with a separate MERGE path; or rewrite the table. The Delta log and time travel also keep old values until `VACUUM` passes `delta.deletedFileRetentionDuration` (1825 days for evidence tables), so a true deletion on Delta needs a policy for that too.
2. Chain payloads with masked excerpts: keep (current), or stop copying excerpts into payloads in a later chain spec version.
3. Whether `signoff.reason` and `cases.summary` get a retention class.
4. The day counts (90 / 365 / 365 are proposals).
