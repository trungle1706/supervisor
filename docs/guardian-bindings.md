# Guardian bindings and the mandatory floor (WP-S1)

Off by default. Needs `GOVERNANCE_ENABLED=1` and `GUARDIAN_BINDINGS_ENABLED=1`. The switches show on
the Catalog page, so `CONSOLE_CATALOG_ENABLED=1` too. Plan: `docs/phase4/BUILD_PLAN_PHASE4.md`
section 4.4. Builds on the AI system (`docs/governance.md`) and the guardian floor of the
assignment rules (`docs/assignment-rules.md`).

## 1. What it does

The product owner of an AI system can switch single guardian features off for the agents of that
system. A few features are locked: the assignment rules put them in the system's guardian floor,
and no one can switch them off. The gate rules are never switchable.

```
 instance has it on ----+
 (flags, detectors.yaml,|--> AND --> effective for the agent
  policy override)      |
 binding on OR in floor-+
```

* No row means on. A binding only narrows. It never turns on a feature the instance has off: the
  engines receive a set of slugs to switch off and add it to what they already switch off, so an
  environment flag or `enabled: false` in `config/detectors.yaml` is never bypassed.
* The floor is read from `RulesService.guardian_floor(system_id)` each time it is needed. It is not
  copied. A floor feature cannot be set off (HTTP 400). If the rules add a feature to the floor
  later, an old `off` row for it stops acting at once (the table keeps the row, the page shows the
  lock).
* The gate rules (`policy_rules`, the pause switch) are never bindable. A binding for
  `policy_rules` is refused with HTTP 400.
* Judges still only advise. Switching a judge sample off removes advice. It cannot block anything.

## 2. Features you can bind

| Slug | Group | Where it acts | Instance has it on when |
|---|---|---|---|
| `dlp_vn`, `injection_regex`, `injection_classifier`, `judge_advisory` (the keys of `config/detectors.yaml`) | detectors | `DetectorGate.prepare`: added to the agent's `disable` list before `ResolvedDetectors.for_agent` | `DETECTORS_ENABLED=1` and `enabled: true` in the file |
| `session_monitor` | gate | `SessionGate.config_for` and `SessionMonitor.config_for`: the agent's session config reads `enabled=false` (same as the per-agent policy switch) | `SESSION_MONITOR_ENABLED=1` |
| `judge_t2_sample` | judge | `JudgeService.evaluate_trace`: the random Tier 2 sample is skipped. A Tier 1 flag still escalates to Tier 2 | `JUDGE_ENABLED=1` and `JUDGE_T2_SAMPLE_BP > 0` |
| `judge_challenger` | judge | `JudgeService.evaluate_trace`: the challenger sample is skipped | `JUDGE_ENABLED=1` and `JUDGE_CHALLENGER_MODEL` set |
| `monitor_quality`, `monitor_fairness`, `monitor_split_payment` | monitor | `BindingResolver.resolve` (WP1b-B): the part reads as unbound with the gap `switched off for the AI system (guardian binding)`, so the monitor writes a `not_applicable` status | `QUALITY_ENABLED`, `FAIRNESS_ENABLED`, `MULTIAGENT_ENABLED` |
| `monitor_drift` | monitor | `DriftMonitor.run`: the agent is skipped and gets the status `not_applicable`, code `switched_off` | `DRIFT_ENABLED=1` |

Floor slugs come from the rules file: detector slugs and `session_monitor` (and `policy_rules`,
which is never bindable). The judge and monitor slugs are never in a floor.

### An agent on several systems

An agent has a feature off only when every AI system it is linked to has it off and none of them
holds it in its floor. If one system keeps it on, it stays on. An agent on no system, and an
archived system, change nothing.

## 3. Table and chain

Table `guardian_binding` (kind state, primary key `system_id`, `feature_slug`):

| Column | Meaning |
|---|---|
| `system_id`, `feature_slug` | the system and the feature |
| `state` | `on` or `off` |
| `mandatory` | the slug was in the floor when the row was written (a snapshot for the audit; resolution reads the floor again) |
| `set_by`, `set_at` | the person and the time |
| `reason` | optional text, at most 500 characters |

A repeat of the current state writes nothing. Every change writes one chain record `binding_change`
(ref `system:<id>`): `system_id`, `feature_slug`, `from_state` (`default` when there was no row),
`to_state`, `mandatory`, `actor_ref`, `reason_sha256` when a reason was given, `ts`. No reason text,
no name, no number that is not an integer.

## 4. API

| Route | Permission | What |
|---|---|---|
| `GET /v1/systems/{id}/guardians` | `systems.view` | every bindable feature: `state`, `default`, `locked`, `floor_rules`, `instance_on`, `effective`, `set_by`, `set_at`, `reason` |
| `PUT /v1/systems/{id}/guardians/{slug}` | `systems.edit` | body `{"state": "on" or "off", "reason": "..."}` |
| `POST /console/systems/{id}/guardians/{slug}` | `systems.edit` | the form post of the Catalog switch (303 back to the Catalog; HTMX gets `HX-Redirect`) |

Mounted only when both flags are on. A system outside the caller's scope answers 404 (the same as a
system that does not exist). Errors are HTTP 400 with a message: a floor feature set off (the
message names the rules), `policy_rules`, an unknown slug, a bad state, a reason too long, an
archived system. Each write makes two `console_action` audit rows (`attempted`, then `ok`).

## 5. Console

The Catalog page (`/console/catalog`) gets a system picker. After a person picks a system
(`?system=<id>`, only systems in their scope are listed), each capability card shows the switch rows
for that system:

* a person with `systems.edit` sees the button (Switch off or Switch on);
* a floor feature shows a lock and the rule ids, with no button;
* a feature the instance has off shows "Off in this instance", with no button;
* the gate rules card shows a lock and one line, with no button;
* other people see the state only.

EN and VI. The same rows for one system are returned by
`supervisor.console.guardians_view.system_panel(ctx, me, system_id)`. A Guardians tab on the system
page (UX4b) can call it. That tab is not part of WP-S1.

## 6. Not here

* A binding does not change a detector's settings, only on or off.
* No per-consumer bindings. A consumer id (`agent/consumer`) uses its agent's bindings.
* The caches: the engines look up the bindings at most once per 5 seconds per agent in each process.
  A change made in this process acts at once. Another process sees it within 5 seconds.
* A lookup that fails leaves every feature as the instance has it (more coverage, never less).
* Switching the session monitor off for an agent also stops its pause enforcement, as the per-agent
  `monitors.session.enabled: false` of the policy file does (`docs/session-monitor.md`).

## Reason and second person for a switch-off (WP-P2, phase 8, `CONSOLE_STATE_ACTIONS`)

With the flag on, a switch-off needs a reason (HTTP 400 `reason_required`). On a system in `deployment`, `operation` or `re_evaluation`, at risk level `high` or `prohibited`, or classed high risk, the switch-off is a request (`guardian_off_request`, status `pending`) and the binding changes only when a second person approves it: `POST /v1/systems/{id}/guardian-off-requests/{request_id}/decide` with `{"decision": "approve"|"reject"}` (permission `systems.approve`), or Approve and Reject on the Catalog page. The requester gets HTTP 400 `same_person`. The floor is read again at approval: a floor feature can never be switched off. `GET /v1/systems/{id}/guardians` adds `pending_off` (only with the flag on). Switching on needs neither. Chain: `binding_change` records for request, approval (with `approver_ref`) and rejection.
