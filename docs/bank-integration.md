# Bank integration contracts (WP11 stubs)

Four integrations connect Supervisor to systems the bank already runs. In this build each
one is a **stub**: a written contract, an adapter that is safe to ship (a file sink or an
in-memory fake) and tests. **All are off by default.** Nothing opens a network connection
until the bank owner turns a transport on and fills the `FILL-ME` values.

Code: `src/supervisor/adapters/integrations/` (`siem.py`, `itsm.py`, `pager.py`,
`scim.py`). Tests: `tests/integrations/test_integrations.py`.

```
Entra ID --SCIM--> workspace groups --(read)--> Supervisor roles (console)
Supervisor evidence chain --events--> SIEM (file tail or HEC-style webhook)
Supervisor case --create/update--> ITSM ticket ; ticket no. --write-back--> case.itsm_ref
Supervisor case (critical) --page--> on-call tool ; ack --write-back--> case comment
```

## Common rules

| Rule | Applied as |
|---|---|
| Off by default | `SIEM_ENABLED`, `ITSM_ENABLED`, `PAGER_ENABLED`, `SCIM_ENABLED` default `0` (`IntegrationSettings`) |
| No PII leaves | Events and tickets carry ids, rule ids, actions, hashes and console links. No case free text, no customer data |
| Auth | Placeholder only. The bank supplies credentials from its vault into the client at run time. Never in git, never logged. Databricks: OAuth only |
| Retry | `RetryPolicy`: 3 attempts, back-off 1 s then 2 s, on transport errors. Then `IntegrationError` (HTTP 400 in the console, `[FAIL]` in the CLI). A failure never blocks a gate decision or a case action |
| Idempotency | Every message has a stable key (`event_id`, `case_id` as `dedup_key` / correlation key) |
| People act, systems report | The case service accepts workflow actions only from a signed-in person. Write-backs (ITSM ref, pager ack) are written in a person's name |

Settings (environment or `.env`):

| Variable | Default | Meaning |
|---|---|---|
| `SIEM_ENABLED` | `0` | Emit SIEM events from the evidence chain |
| `SIEM_SINK` | `file` | `file` (`LogSiemSink`) or `webhook` (`WebhookSiemSink`) |
| `SIEM_FORMAT` | `json` | `json` (one object per line) or `cef` |
| `SIEM_FILE_PATH` | `<DATA_DIR>\siem\events.log` | File the bank's forwarder tails |
| `SIEM_WEBHOOK_URL` | empty | `FILL-ME`; only with `SIEM_SINK=webhook` |
| `ITSM_ENABLED` | `0` | Ticket sync (fake until a client is wired) |
| `PAGER_ENABLED` | `0` | Paging (fake until a client is wired) |
| `SCIM_ENABLED` | `0` | Group to role report (fake directory) |

## 1. SIEM (`siem.py`)

**Direction:** Supervisor to SIEM, one way.
**Source:** the evidence chain (`chain_entry` + `chain_payload`) and the `anchor` table,
read by `ChainEventFeed` with a cursor per lane.

Event schema `supervisor.siem.v1`:

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | `supervisor.siem.v1` |
| `event_id` | string | `<lane>:<seq>` of the chain entry, or `anchor:<id>`. Unique; the SIEM drops duplicates |
| `event_type` | string | `gate_decision`, `gate_state_change`, `case_opened`, `case_event`, `chain_root`, `chain_anchor` |
| `ts` | string | RFC 3339 UTC of the chain entry |
| `severity` | int 0..10 | CEF scale: allow 1, alert 5, block 7, pause 8, quarantine 9; cases by severity (low 3, medium 5, high 8, critical 10) |
| `outcome` | string | allow, block, pause, resume, open, triage, ..., sealed, anchored |
| `agent_id` | string or null | Agent id |
| `rule_id` | string or null | Tier 0 rule id |
| `case_id` | string or null | Case id |
| `actor` | string or null | User id, `rule:<id>` or `supervisor-system` |
| `chain_lane`, `chain_seq`, `entry_hash` | | Where to find and verify the evidence offline |
| `env` | string | `laptop`, `databricks_app`, ... |
| `product`, `vendor`, `version` | string | `Supervisor`, `Supervisor`, package version |

Formats: canonical JSON (sorted keys, one line) or ArcSight `CEF:0` (header escapes `|`
and `\`; extensions escape `=`, `\` and new lines; custom fields `cs1`..`cs6`, `cn1` with
labels).

Sinks:

- `LogSiemSink(path, fmt)`: appends lines to a local file. The bank's log forwarder
  (Splunk UF, Azure Monitor Agent, ...) tails it. No network from Supervisor.
- `WebhookSiemSink(url)`: POST `{"events": [...]}` (HEC style). Refuses an empty or
  `FILL-ME` URL. Retry per the common rule.

**Auth placeholder:** HEC token or Sentinel key from the bank vault, injected into the
transport as a header. **The bank owner provides:** the SIEM product and index, the
forwarder or endpoint, the token, the detection rules the SOC owns (for example: any
`pause`, any `chain_anchor` gap over 24 h, `gate_decision` with `fail_mode` closed).

## 2. ITSM (`itsm.py`)

**Direction:** Supervisor to ITSM (create, update). ITSM to Supervisor: ticket number
written back to `cases.itsm_ref` (`CaseService.set_itsm_ref`, on the evidence chain).

| Message | Fields |
|---|---|
| Create (`TicketRequest`) | `case_id` (correlation key), `title` (`Supervisor case <id>: <severity> <agent> rule <rule>`, no free text), `priority` (critical P1, high P2, medium P3, low P4), `severity`, `agent_id`, `rule_id`, `status`, `console_url`, `opened_at`, `report_due_at` (SBV 24 h clock) |
| Update (`TicketUpdate`) | `status` (open, triaged, contained, closed), `resolution`, `updated_at` |
| Response | ticket reference (for example `INC0001001`) |

Create is idempotent on `case_id`. Create is triggered by a reviewer (the write-back is a
workflow action, written in the reviewer's name). Status pushes run in the background
and need no person. **Auth placeholder:** `FILL-ME` ITSM service account. **The bank owner
provides:** the ITSM product, assignment group, priority mapping, the API account and
whether two-way sync (ITSM closes the case) is wanted (not in this contract).

## 3. Pager (`pager.py`)

**Direction:** Supervisor to on-call tool (page). On-call tool to Supervisor:
acknowledgement, written back as a case comment `Paged: acknowledged by <user> at <ts>
(<pager>)` in the name of that person (resolved to a console identity; an unknown user
is refused).

| Message | Fields |
|---|---|
| Page | `dedup_key` (= case id), `severity`, `agent_id`, `rule_id`, `title` (no free text), `console_url`, `opened_at` |
| Ack | `dedup_key`, `acked_by`, `acked_at` (RFC 3339 UTC) |

Pages only severities in `page_severities` (default `critical`), once per case. The
console inbox notice is always written, paged or not. **Auth placeholder:** `FILL-ME`
routing / integration key. **The bank owner provides:** the paging tool, the on-call
schedule, the routing key, the escalation ladder, and the mapping of on-call people to
console identities.

## 4. SCIM (`scim.py`)

**Direction:** directory to Supervisor, read only. Supervisor never writes the directory.

At request time the console already maps groups to roles (`config/auth.yaml`
`roles.<role>.groups` with `group_lookup: scim_me`). `role_report` is the review
contract: given SCIM 2.0 `Group` resources (`displayName`, `members[].value`), it lists
each user's roles and these findings:

- a role with no mapped group (`FILL-ME` never matches);
- a mapped group that is missing in the directory;
- a user who is both `reviewer` and `approver` (allowed; the two sign-offs of a high case
  must still come from two people);
- only one `admin` (a quarantine release has no second admin).

A failed directory read grants no role (fails closed). **Auth placeholder:** read-only
service principal, OAuth. **The bank owner provides:** the Entra ID groups, SCIM
provisioning into the workspace, and the group names to put in `config/auth.yaml`.

## Not in this build

DR and CI/CD integration (analysis 01 section 4) are process items for the bank owner:
DAB targets dev, uat, prod, CODEOWNERS on `policies/`, and two gate instances with fail
mode per rule. See `docs/RUNBOOK.md` and `docs/threat-model.md`.
