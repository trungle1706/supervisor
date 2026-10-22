# Governance actions: events to actions (WP-G5)

Off by default (`GOVERNANCE_ACTIONS_ENABLED=1`, and `GOVERNANCE_ENABLED=1` too). Plan and reasons:
`docs/phase4/BUILD_PLAN_PHASE4.md` section 4.6 and the Saidot adoption plan section 9
(`~/supervisor-testbed/saidot/ADOPTION_PLAN.md`). Incidents have their own page:
`docs/incidents.md`.

Supervisor already makes runtime evidence: gate decisions, detector findings, pack results,
monitor breaches, the chain. This work package closes the loop. An **event** that is new in
that evidence is matched to a **rule** in `config/governance_actions.yaml`. The rule lists the
**actions** to run: make an incident, tell the owner, raise the risk level, move the system to
re-evaluation, plan a review, fire a webhook event, reopen a control.

```
 alert / verdict / finding / case / eval_result / chain / agent_version      (read only)
                              |
                       event sources  -->  GovernanceEvent(kind, severity, agent, system, ref, at)
                              |                                one event per linked system
                      rules file  (kind, min severity, system class)
                              |
        +-----------+---------+---------+-----------+---------------+-------------+----------------+
   create_incident notify_owner raise_risk_level move_to_re_evaluation create_review fire_webhook reopen_control
        |
   incident (a person closes it)                        marker row per event: processed once
```

## 1. Rules that do not bend

| Rule | How it is kept |
|---|---|
| R1: no action pauses or blocks an agent | The action list has no such kind. The loader refuses `pause`, `block`, `quarantine`, `retire` and similar words by name. The gate already stopped the call; this loop only records and asks people. |
| Deterministic | `actions_model.plan(event, rules, facts)` is pure: same event, same rules, same facts give the same actions in a fixed order. A test asserts it, and the dry run equals the real run. |
| Once per event | A marker row (`governance_event`) is written before the first action. A second run finds it. Before each action an `attempting` entry is saved; after a crash an action found `attempting` is never run again (`skipped`, ref `maybe_done`). `raise_risk_level` also looks for a `system_change` record with the same event key. A runner holds a started event with a lease (`runner_id`, `lease_until`, 120 s, renewed at each save); another runner leaves a held event alone and takes it over only after the lease ran out. |
| A raising action stops nothing | Each action has its own try block. The result (`done`, `skipped`, `refused`, `failed`) goes into the marker. A failed action is tried again on the next runs (3 runs in all, the event stays `started`, also when it is older than the source overlap); then it is `failed_final`, the event is done and the chain record counts it (`failed_final_n`). |
| Incidents are auto-created only | No route and no method makes an incident from a person's input. A person moves one on and closes it (`docs/incidents.md`). |
| Never lower | `raise_risk_level` sets the manual level one step above the effective level, never above `high`, never when the level is already at or above that. |
| Chain payloads | Canonical JSON, no floats, ids and enums only, no title, no free text, no user id (keyed `actor_ref`). Titles come from templates. |

## 2. Switches

| Variable | Default | Meaning |
|---|---|---|
| `GOVERNANCE_ACTIONS_ENABLED` | `0` | Mount `/v1/incidents` and the Incidents tab, and schedule the job. Needs `GOVERNANCE_ENABLED=1`; without it the routes answer HTTP 400 with a message and the job is not listed |
| `GOVERNANCE_ACTIONS_CONFIG` | `config/governance_actions.yaml` | Rules file (resolved to an absolute path at load) |
| `SCHED_GOVERNANCE_S` | `60` | Job interval in seconds (at least 5) |
| `GOVERNANCE_ACTIONS_LOOKBACK_S` | `86400` | How far back the first run of a source looks |
| `WEBHOOKS_ENABLED` | `0` | From WP-G1. With it on, the stub marks a `governance_action` outbound event as delivered and logs it. It sends nothing |

## 3. Event sources

Read-only adapters over tables that exist (`supervisor.governance.event_sources`). Nothing is
captured anew. Each source has its own cursor in `monitor_state` (monitor `governance_actions`,
key `cursor:<source>`), so one broken source never holds back the others. Each run re-reads the
last 300 seconds before the cursor; the markers remove the repeats.

| Event kind | Source | Severity | Notes |
|---|---|---|---|
| `alert` | `alert` rows, every rule id | the alert severity | `rule_id` is the alert rule (`AL-QUARANTINE`...) |
| `gate_stop` | tier 0 `verdict` rows with action `block` or `pause` on a tool of class `money`, `credit` or `pii_export` | block `high`, pause `medium` | One event per agent, action and hour (a burst of blocked calls is one event; the rule and evidence are those of the first stop). Tool from the decision (`agent_event`, read in batches of 200), class from the policy catalogue and the manifests (as tool analytics reads it). A SHADOW would-block, a rule error and a fail-mode row are not events |
| `detector_failed` | `finding` rows of a detector that did not run (`execution_failed`, `timed_out`) | `medium` | One event per agent, detector and hour, so a bad hour is one event |
| `monitor_failing` | cases of type `drift`, `fairness`, `multiagent` (the monitor opened a breach case), and low groundedness verdicts of the quality monitor | case severity; quality `low` | `monitor_status` has no `failing` value (`ok`, `not_applicable`, `no_data` only), so the breach case is the deterministic outcome of a monitor. Quality is advisory: it can open an incident or a notice, never a gate action |
| `pack_no_go` | `eval_result` rows with status `fail` or `error` on a pack whose launch gate is `required`, not mock, target `agent` or `traces` | `high` | `eval_run` has no agent, so the per-agent result row is the source |
| `chain_break` | `chain_verify` and `audit_pack_built` chain records that say the verify failed | `critical` | No agent |
| `model_version_change` | `agent_version` rows whose model endpoint or model family differs from the version before | `medium` | The first version of an agent is no change |
| `judge_escalation` | cases of type `judge` | case severity | A judge asked for a person; the judge itself never calls the gate |

**Systems.** An event has the agent that it names. `system_component` links agents to systems:
the event is copied once for each active, not archived system that holds the agent, or kept once
with no system. The dedupe key is a hash of (kind, ref, system), so the same alert on two systems
is two events. An event with no system gets only `create_incident`, `notify_owner` and
`reopen_control`; the actions that change a system are left out.

## 4. Rules file

`config/governance_actions.yaml`, read with `yaml.safe_load` and checked field by field. An
unknown key, a bad value, a duplicate id or a forbidden action stops the load, and one error
lists every problem.

```yaml
version: 1
rules:
  - id: GA-SECRETS-OUTPUT                 # unique, 1 to 64 characters
    title: A secret is in what an agent said   # text for people, not used by the code
    kind: alert                           # one of the eight event kinds
    alert_rule: AL-SECRETS-OUTPUT         # optional, only for kind alert
    min_severity: critical                # low | medium | high | critical
    system_class:                         # optional filter on the system of the event
      decision33_class: [high_risk]       #   list
      risk_level: [high, prohibited]      #   list, the effective level
      autonomy_level_gte: l3              #   l0 to l5 (WP-G2 column; see below)
    actions: [create_incident, notify_owner, create_review, fire_webhook, reopen_control]
    controls: [CTL-PII-MASK]              # optional, only with reopen_control
    enabled: true                         # optional
```

The starter file mirrors the nine SOC use cases of `docs/alerts.md` (coverage gap, detector
failed, threat not enforced, secrets in output, PII in output, redaction spike, latency, error
rate, ingress anomaly) and adds chain break, pack NO-GO, gate stop on a risky tool, monitor
breach, model version change and judge escalation. It is ILLUSTRATIVE until the second line
agrees the thresholds.

**Matching.** A rule matches when its kind equals the event kind, the event severity is at least
`min_severity`, the `alert_rule` (if set) equals the alert rule of the event, and the
`system_class` filter (if set) holds for the system. A filter on the system never matches an
event with no system. `autonomy_level_gte` reads the `autonomy_level` column that WP-G2 adds; as
long as the column is not there (or not set) an autonomy filter does not match. All matching
rules add their actions; an action asked for by two rules runs once.

## 5. Actions

Run in this fixed order. Result codes are short fixed words, never text from an event.

| Action | What it does | Skipped or refused with |
|---|---|---|
| `create_incident` | `IncidentService.open_from_event`: one incident, id `inc_` + the event key, so a repeat finds the same one. Chain `incident_change` | - |
| `notify_owner` | One `notice` row for the owner of the system (else the owner of the agent), channel `owner:<user>`. Ids and enums only | `no_owner` |
| `raise_risk_level` | `SystemService.raise_risk_from_event`: manual level one step above the effective level, source `event`, chain `system_change` action `risk_raise` with the event key. Never lowers, never above `high` (`prohibited` is a legal finding a person sets) | `not_raised` |
| `move_to_re_evaluation` | `LifecycleService.move` to `re_evaluation`, only from `deployment` or `operation`. Needs no approval with the shipped `config/tasks.yaml`; if the bank marks it `approval: true` the move is refused | `not_deployed`, `move_refused` |
| `create_review` | `ReviewService.create`: kind `internal`, title from a template, scope `[{kind: event, id: <ref>}]`, reviewer the first team member with role `reviewer`, then `oversight_manager`, then `compliance_specialist` (the owner never reviews) | `no_reviewer`, `review_refused` |
| `fire_webhook` | `events.emit` of an `outbound_event` of kind `governance_action` (payload: event kind, severity, event key, first rule id, system id). Delivery is the WP-G1 stub behind `WEBHOOKS_ENABLED` | `failed` if the row cannot be written |
| `reopen_control` | `ControlService.reopen` for each active control in scope of the agent that maps the evidence of the event (`gate_stop`: the rule; `pack_no_go`: the pack; `monitor_failing`: the monitor) or is named in the rule's `controls`. Writes one `failing` row in `control_status` with reason `reopened_by_event` and a `control_reopen` chain record | `controls_off`, `no_agent`, `no_control` |

A reopened control reads `failing` for that agent until a newer status row exists. The evidence
pass skips a control and agent that hold a reopen row of the same window (it is counted as `held`),
whatever the order of the two; the next pass in a later window writes a newer row and the evidence
decides again. Windows end at the last full hour, so "the same window" is the same hour. The control,
its map and its scope are not changed.

## 6. The job

```
python -m supervisor.jobs.governance_actions            one pass
python -m supervisor.jobs.governance_actions --dry-run  print what would fire, write nothing
```

Also in the app scheduler (`SCHED_GOVERNANCE_S`, listed only with both flags on). The chain has
one writer per lane: run the command line only when the app is stopped, or let the scheduler
run it. A pass handles at most 200 new events; the cursor of a source waits at the first event
it could not take, so nothing is skipped. Output is ASCII (`[OK]`, `[SKIP]`, `[FAIL]`, `[PLAN]`).

Result keys: `events`, `unmatched` (no rule), `already` (marker found), `handled`, `done`,
`skipped`, `refused`, `failed` (final), `source_errors`, `deferred`, `busy` (a live runner holds
the event), `retrying` (a failed action will be tried again).

An event that no rule matches leaves no marker. If the cursor is lost, those events are read
again and may match a newer rule; the events with a marker are never repeated.

## 7. Chain records

Ref is `governance_event:<key>` and the record stays on the root lane (the payload holds
`agent`, not `agent_id`).

| Type | Fields |
|---|---|
| `governance_action` | `event_key`, `kind`, `severity`, `agent`, `system_id`, `event_ref`, `rules`, `actions` (`action:status`), `done_n`, `skipped_n`, `refused_n`, `failed_n`, `rules_hash`, `ts` |
| `incident_change` | see `docs/incidents.md` |
| `system_change` (`risk_raise`) | the WP-G0 fields plus `from_level`, `to_level`, `event_key` |
| `control_reopen` (agent lane) | `agent_id`, `control_id`, `event_key`, `reason`, `window_start`, `window_end`, `actor_ref`, `digest`, `ts` |

`rules_hash` is the hash of the rules in force, so an auditor can tie every automatic action to
the version of the rules that fired it.

## 8. Known behaviour

* Reads are bounded: each source reads only its time range in the store (cases by `opened_at`,
  agent versions by `deployed_at`, the rest by `ts`); the incident list filters by status,
  severity, kind, system and agent in the query.
* An event that no rule matches leaves no marker (section 6). A started event is taken up again
  on every run until it is done, at most 100 per run.
* An agent that is part of two systems gives two events (section 3).
* The facts of a system (effective level, class) are read once per run and again after the run
  changed the level or the stage.
* `raise_risk_level` and `move_to_re_evaluation` change a system; a person can set the level
  back or move the stage again. The next event can raise it again.
* A first run reads back `GOVERNANCE_ACTIONS_LOOKBACK_S` (a day). Turn the job on, then use
  `--dry-run` first to see what would fire.

## 9. Open questions

1. `raise_risk_level` moves one step per event. Does the second line want a fixed target level
   per rule instead (for example `to: high`)?
2. A failed action is tried 3 times. Is that the number the SOC wants, and should a final failure
   raise an alert?
3. An agent that is part of two systems gives two events and so two incidents. Is that the
   grouping the SOC wants, or one incident per event with the systems listed?
4. Webhook delivery is the WP-G1 stub. The real HTTP sender is later work.
