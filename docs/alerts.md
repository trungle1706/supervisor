# Alerts (WP21)

A small rule engine turns gate decisions, state changes, judge verdicts, scheduler failures,
chain verify results and ingress rejections into **alerts** for the SOC. Alerts inform. They
never block, pause or quarantine anything (design rule R1: only deterministic gate rules and
humans do that). Off by default. Design choices: `docs/adr/D15-alerts.md`.

Code: `src/supervisor/alerts/` (`rules.py`, `signals.py`, `engine.py`, `service.py`,
`harness.py`, `__main__.py`), job `src/supervisor/jobs/alerts.py`, rules `config/alerts.yaml`.
Tests: `tests/alerts/`, `tests/console/test_alerts_panel.py`. Fixture and baseline:
`tests/fixtures/alerts/`.

```
chain (gate_decision, state change, ingress_reject, chain_verify, drill)  --\
verdict table (tier 2)  ------------------------------------------------------> signals
monitor_state (scheduler job runs)  ----------------------------------------/
signals --> rules (window, threshold, group) --> dedupe --> alert row --> routes
                                                                          inbox | siem | webhook | pager
```

## Switches

| Variable | Default | Meaning |
|---|---|---|
| `ALERTS_ENABLED` | `0` | Run the `alerts` job in the app scheduler |
| `ALERTS_CONFIG` | `config/alerts.yaml` | Rule file |
| `SCHED_ALERTS_S` | `60` | Job interval in seconds |
| `ALERTS_LAG_S` | `30` | Watermark: signals younger than this wait for the next run, so a chain entry that commits after its timestamp is not skipped |
| `SIEM_ENABLED` | `0` | The `siem` route needs it (`docs/siem.md`); without it the route says `off` |
| `NOTIFY_WEBHOOK_ENABLED` + `NOTIFY_WEBHOOK_URL` | `0` / empty | The `webhook` route needs both (`FILL-ME` URL) |
| `NOTIFY_WEBHOOK_TOKEN` | empty | Secret from the bank vault; sent in the `Authorization: Bearer` header |
| `NOTIFY_WEBHOOK_DEAD_LETTER` | `<DATA_DIR>\notify\webhook.dead.jsonl` | Failed sends wait here |
| `SCHED_NOTIFY_S` | `15` | Interval of the `notify` job that sends queued webhook notices |
| `ALERTS_SUPPRESSION_MAX_S` | `2592000` (30 days) | Longest time a `suppressions` entry may end ahead; a longer `until` is a validation error |

Commands (ASCII output, Windows cmd syntax):

    python -m supervisor.alerts validate
    python -m supervisor.alerts list
    python -m supervisor.alerts test AL-BLOCK-BURST --since-s 86400
    python -m supervisor.alerts test AL-BLOCK-BURST --signals tests\fixtures\alerts\dev.signals.jsonl
    python -m supervisor.jobs.alerts
    python -m supervisor.alerts.harness

`test` is a dry run: it reads the signals (live store or a fixture file), runs one rule and
prints the alerts it would raise. It stores nothing, sends nothing, writes no evidence.

## Rules (`config/alerts.yaml`)

Declarative data. The file is read with `yaml.safe_load` and checked field by field; there is
no expression language, no `eval`, no code. An error stops the load and lists every problem.

| Key | Meaning |
|---|---|
| `id` | Stable id, `AL-` style, shown in every alert and SIEM event |
| `title` | Fixed text shown to the analyst (events never supply text) |
| `source` | Signal stream: `gate_decision`, `gate_state_change`, `verdict`, `job_run`, `chain_verify`, `ingress_reject`, `failmode_drill`, `case` |
| `where` | Equality, or any-of list, on fields of that source (table below) |
| `group_by` | `agent_id`, `job`, `rule_id` or `none`: one counter per value |
| `window_s`, `threshold` | Fire when `threshold` matching signals fall in the last `window_s` seconds. `window_s: 0` counts only the signal itself (threshold 1) |
| `severity` | `low`, `medium`, `high`, `critical` |
| `dedupe_s` | After a fire, repeats of the same rule and group inside this time are absorbed |
| `routes` | `inbox`, `siem`, `webhook`, `pager` |
| `enabled` | `true` (default) or `false`: a disabled rule is still validated but never runs |
| `suppressions` (top level) | `rule_id` (or `*`), `agent_id` (or `*`), `until` (RFC 3339 with zone), `reason_code`: planned maintenance, time-boxed |

Unknown keys (in a rule, in a suppression, at the top level) are errors, so a typo never
turns a rule or a suppression off without a message.

Filter fields: `gate_decision` (agent_id, action, rule_id, allow), `gate_state_change`
(agent_id, event, to_state), `verdict` (agent_id, tier, label, action, rule_id, is_mock; only
tier 2 verdicts are read), `job_run` (job, status), `chain_verify` (ok), `ingress_reject`
(agent_id, reason_code), `failmode_drill` (ok), `case` (agent_id, severity).

Shipped rules (thresholds ILLUSTRATIVE until the bank SOC sets them):

| Rule | Fires when | Severity | Window / threshold | Dedupe | Routes |
|---|---|---|---|---|---|
| `AL-BLOCK-BURST` | 5 gate blocks for one agent | high | 600 s / 5 | 1800 s | inbox, siem |
| `AL-QUARANTINE` | any agent quarantined | critical | any | 3600 s | inbox, siem, webhook, pager |
| `AL-CHAIN-VERIFY-FAIL` | a chain verify or audit-pack verify failed | critical | any | 3600 s | inbox, siem, webhook, pager |
| `AL-JUDGE-ESCALATION` | a non-mock tier 2 judge verdict | medium | any | 3600 s | inbox, siem |
| `AL-INGRESS-REJECT-AGENT` | 5 rejected ingress credentials for one agent (a bad or expired key) | high | 300 s / 5 | 1800 s | inbox, siem |
| `AL-INGRESS-REJECT-BURST` | 20 rejected ingress credentials over all agents (credential stuffing) | high | 300 s / 20 | 1800 s | inbox, siem, webhook |
| `AL-FAILCLOSED-DRILL-FAIL` | the fail-closed drill failed | critical | any | 86400 s | inbox, siem, webhook, pager |
| `AL-JOB-FAILURE` | a scheduled job ended in error | medium | any | 3600 s | inbox, siem |

Chain record types read: `gate_decision`, `gate_state_change`, `ingress_reject` (payload
`agent_id`, `reason_code`), `chain_verify` (payload `ok`), `audit_pack_built` (payload
`verify_ok`), `failmode_drill` (payload `ok`), `case`. A record type no component writes yet
simply produces no signals.

Ingress rejections: WP20 ingress auth writes each rejection as a `console_action` row
(permission `ingress.auth`, outcome `denied`, `target_id` = claimed agent, `detail` = reason
code, plus `;suppressed=<n>` when its audit throttle skipped rows). The alert job reads these
rows as `ingress_reject` signals (a throttled row counts 1 + n, at most 1000). The claimed
agent id is unverified, so it is kept only when it looks like an id.

Producers of the two system records: the console **Verify chain** button writes a
`chain_verify` record `{ok, failures, scope}` (root lane) after every verify, and
`python -m supervisor.demo drill` writes a `failmode_drill` record `{ok, failures}` on its
own throwaway chain; with `--record` it also writes it to the configured evidence chain (run
it with the app stopped, or from a one-shot job host). A passing verify or drill is quiet.
Two ingress rules exist on purpose: one agent with an expired key trips the per-agent rule and
cannot hide a credential-stuffing run inside the dedupe window of the global rule.

## Engine semantics (deterministic)

- Signals are sorted by `(ts, kind, id)`. Time comes only from signal timestamps, never the
  wall clock. The same signals give the same alerts, on any machine, in any input order.
- Alert id = first 32 hex of SHA-256 of `rule:group | time | signal id`. A replay of the same
  signals makes the same ids; inserting an id that exists is a no-op.
- Dedupe key = `<rule id>:<group>`. After a fire at time `t`, candidates before
  `t + dedupe_s` do not make an alert: the open alert's `suppressed_count` goes up and its
  `last_ts` moves. The first candidate at or after `t + dedupe_s` fires a new alert. An
  acknowledged alert still dedupes.
- A cursor (`monitor_state`: `alerts` / `cursor`, newest time and signal id judged) makes each
  signal count once. The job also reads the longest rule window before the cursor to fill the
  counters, but only signals after the cursor can fire or be absorbed.
- A suppression entry drops a matching candidate and counts it (`policy_suppressed` in the job
  result). It expires at `until`, and `until` may be at most `ALERTS_SUPPRESSION_MAX_S` (30 days)
  ahead when the file is loaded.

## What an alert carries (stable field names)

Table `alert` (both DDLs, `schema/model.yaml`). Ids, counts and hashes only, never free text.

| Field | What the analyst gets from it |
|---|---|
| `alert_id`, `ts`, `status` | Which alert, when it fired, `open` / `acknowledged` / `closed` |
| `rule_id`, `title`, `severity`, `rule_hash` | Which rule, its fixed title, its severity, which version of the rule |
| `agent_id`, `group_value` | The agent, or the group (job name, `*`) |
| `window_s`, `window_count`, `threshold` | "5 of 5 in 600 s" |
| `first_ts`, `last_ts`, `suppressed_count` | How long it ran and how many repeats were absorbed |
| `case_id` | Linked case (from the trigger, else the oldest open case of the agent opened since the window began) |
| `chain_lane`, `chain_seq`, `entry_hash`, `refs` | Where the trigger is on the evidence chain (verify offline) and the ids of the signals in the window |
| `routes`, `route_status` | Where it was sent: `sent`, `queued` (stub), `off`, `dead_letter`, `failed`, `pending` |
| `acknowledged_by`, `acknowledged_at` | Who acknowledged it |

A webhook notice (case actions) is only queued by the request and sent by the `notify` job, so a
dead hook never slows the console. The inbox, webhook and pager text is the same 14 `key: value` lines: `alert_id`, `rule_id`,
`severity`, `title`, `agent_id`, `group`, `window`, `first_ts`, `last_ts`,
`suppressed_repeats`, `case`, `chain`, `entry_hash`, `console`. Each alert also writes one
`alert` record on the evidence chain (ids and counts), and an acknowledge writes `alert_ack`.

## Routes

| Route | Sends to | Real or stub |
|---|---|---|
| `inbox` | Console Inbox (`notice` row, channel `alert`) | real, always available |
| `siem` | The SIEM sink as an `alert` event (`docs/siem.md`) | real when `SIEM_ENABLED=1`, else `off` |
| `webhook` | `WebhookNotifier`: POST, 3 attempts with back-off, idempotency key = `alert_id`, dead-letter file | real when `NOTIFY_WEBHOOK_ENABLED=1` and the URL is filled, else `off` |
| `pager` | `StubNotifier("pager")`: a `queued` notice `pager:alert` | stub, never sends |

A route that fails never blocks the others and never raises. A row with a `pending` or
`failed` route is retried at the start of the next run. The ITSM stub has the same
`StubNotifier` interface (`itsm`); the case-driven ITSM and pager bridges in
`adapters/integrations` are unchanged.

## Console

Metrics page, section **Alerts**: counts of open and acknowledged alerts and a table (time,
rule, severity, agent, window count, repeats, case link, chain seq and hash, status). The
**Acknowledge** button posts to `/console/alerts/{alert_id}/ack`. Permission `alert.ack`:
roles `operator` and `admin`. A reviewer, approver, owner, auditor or viewer gets HTTP 403
(and a `denied` audit row). Every acknowledge writes two `console_action` rows (`attempted`,
then `ok` with the row hash before and after) and an `alert_ack` evidence record. Only a
signed-in person can acknowledge; an already acknowledged alert gives HTTP 400.

## Harness (SOC and detection-engineering view)

`python -m supervisor.alerts.harness` scores the shipped rules on two labelled synthetic
splits (500 gate decisions each, 6 planted incidents, hard negatives). Baseline
(`tests/fixtures/alerts/baseline.json`, 2026-10-20): precision, recall, exact dedupe and
triage completeness are all 10000 bp on both splits; 8 alerts for 8 expected; about 110 to
115 matching signals collapse into 8 alerts. Wilson 95 percent interval for precision and recall
is 6755 to 10000 bp because only 8 alerts are expected per split; see the baseline file for the
false alert rate bound. Thresholds are ILLUSTRATIVE. Provenance, rubric and
limits: `tests/fixtures/alerts/README.md`. The fixture proves the logic, not real-world alert
rates: replay the bank's own gate decisions through `python -m supervisor.alerts test` before
trusting a threshold.

## Tuning

1. Copy `config/alerts.yaml`, edit thresholds, run `python -m supervisor.alerts validate`.
2. Dry run each rule on a week of real signals (`--since-s 604800`) and read how many alerts it
   would raise. Aim for a count the SOC can triage in a shift.
3. Use `suppressions` for planned tests instead of raising a threshold.
4. Re-run the harness: `precision` and `recall` must stay GO, or change the fixture on purpose
   (and `--write-baseline`) in the same pull request.

## Not done

See `BACKLOG.md` (WP21 lines): auto-close, alert-to-case promotion, real pager and ITSM
senders for alerts, chain entries that commit more
than `ALERTS_LAG_S` after their timestamp, per-tenant rules.
