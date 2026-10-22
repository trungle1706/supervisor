# Assignment rules (WP-G2)

Off by default. Needs `GOVERNANCE_ENABLED=1` (the Rules tab also needs `CONSOLE_SYSTEMS_ENABLED=1`).
Plan: `docs/phase4/BUILD_PLAN_PHASE4.md` section 4.2 and the Saidot adoption plan, section 6.
Builds on the AI system (`docs/governance.md`).

## 1. What it does

A few intake answers on an AI system decide which duties, controls, risks, tasks and guardian
features it gets. One data-driven file replaces three ad-hoc places. The same system and the same
file always give the same result. No model decides an assignment.

```
 ai_system fields ----+
 effective risk level +--> rules file  --evaluate-->  assignments  --> task list (floor stays)
 parts it reaches ----+   (config/                   (table,         --> control scope
   (agents, tools,         assignment_rules.yaml)      never deleted)  --> obligation matrix (source rule)
    models, ...)                                                      --> guardian floor (WP-S1)
```

## 2. The rules file `config/assignment_rules.yaml`

A list of rules. The schema is strict: an unknown key, field, operator or value stops the load
with a message that names the rule.

```yaml
- id: AR-PDPL-CUSTOMER
  title: Customer personal data duties
  when:
    all:
      - {field: personal_data, in: [identifiable, special]}
      - {field: user_segment, eq: customer}
  assign:
    obligations: [VN-PDPL-2025-*]
    controls: [CTL-PII-MASK, CTL-PII-SWEEP, CTL-BANK-DPIA]
    risks: [RSK-SVC-003]
    tasks: [DES-DPIA, VAL-PII, OPS-MASK]
    guardian_floor: [dlp_vn]
```

| Part | Content |
|---|---|
| `when` | `{all: [...]}`, `{any: [...]}`, `{not: ...}`, or a leaf `{field: F, eq / in / gte / is_true: V}`. Depth at most 8, at most 200 nodes |
| operators | `eq` one value, `in` a list, `gte` on an ordered field or a number, `is_true` on a yes/no field. A missing value makes a leaf false |
| fields | `system_type`, `org_role`, `user_segment`, `personal_data`, `money_movement`, `credit_decision`, `human_control`, `lifecycle_stage`, `risk_level`, `decision33_class`, `business_impact`, `status`, and `effective_risk_level` (manual, inherited and classifier floor, computed on read) |
| derived fields | `component.<kind>.count` (`agent`, `model`, `model_endpoint`, `tool`, `mcp_server`, `dataset`, `prompt`, `supplier`, `entrypoint`, `system`): the agents linked to the system, and the inventory nodes they or the linked nodes reach over `uses` edges. `component.tool.risk_class`: the risk classes of those tools (`eq`/`in` is true when any one matches) |
| ordered fields | `lifecycle_stage`, `risk_level`, `effective_risk_level`, `business_impact`: `gte` uses their order |
| `assign` | `obligations` (regulation KB ids), `controls`, `risks` (starter or stored risk ids), `tasks` (template ids of `config/tasks.yaml`), `guardian_floor` (detector slugs of `config/detectors.yaml`) |
| ids | An id may end in `*` to match a prefix of the listed ids (`VN-PDPL-2025-*`). An exact id passes through even if it is not listed (a bank control may live only in the store) |

Starter rules (ILLUSTRATIVE, the bank sets the real ones): `AR-BASELINE` (every open system),
`AR-PDPL-CUSTOMER`, `AR-PDPL-STAFF`, `AR-C53-MONEY` (Circular 53 money movement),
`AR-D33-HIGH` (Decision 33 high risk), `AR-TOOL-PII-EXPORT` (a reached tool of class `pii_export`).

Check the file against the catalogues: `python -m supervisor.governance.rules check` (a note for an
exact id that is not listed and for a prefix that matches nothing; a test keeps the starter file
free of notes).

## 3. Evaluation

`supervisor.governance.rules.evaluate(ruleset, facts, catalogue)` is pure. Rules run in id order.
Each assignment keeps every rule that gives it and the fields that decided each rule (`support`: for
a true `all` every child, for a true `any` the true children). The list is sorted by kind and id.
A test runs it three times, with the facts in another order, and compares assignments and the
explanation text.

## 4. Table `assignment` and the runs

| Column | Meaning |
|---|---|
| `assignment_id` | hash of (system, kind, ref): a repeat run keeps the row |
| `system_id`, `kind`, `ref_id` | `kind` is `obligation`, `control`, `risk`, `task` or `guardian` |
| `rule_id`, `fired` | the first rule (by id) that gives it; `fired` lists every rule and its fields |
| `active` | false when no rule fires for it any more; true again if a rule fires again |
| `first_seen`, `last_seen` | time stamps |

A run never deletes a row. It runs after register, update (`update_fields`), link and unlink, after a
classification is applied (that is an update), and by hand: the route
`POST /v1/systems/{id}/assignments/run` or the CLI below. A problem in the rules file is logged and
never stops the change that caused the run; the CLI and the route show the message.

Chain record `rule_run` (ref `system:<id>`): system id, trigger, `rules_sha256` (the sha256 of the
rules file), `rules_n`, ids of the rules fired, integer counts (`assigned_n`, `by_kind`, `added_n`,
`reactivated_n`, `changed_n`, `deactivated_n`), `assignments_hash`, a keyed hash of the actor. No
name, no purpose, no user id, no float.

## 5. CLI (ASCII output)

```
python -m supervisor.governance.rules run [--system ID] [--by USER]
python -m supervisor.governance.rules explain --system ID
python -m supervisor.governance.rules check
```

`run` without `--system` evaluates every open system. `explain` prints the facts, every rule with
the trace of its condition (`[x]` true, `[ ]` false, with the value seen) and the assignments with
the rules that gave them. Both need `GOVERNANCE_ENABLED=1` (`[SKIP]` otherwise). `check` needs no
flag.

## 6. Hooks into the existing engines (additive)

| Engine | What the rules add | With the flag off, or an agent on no system |
|---|---|---|
| Task list (`tasks/service.py`) | Assigned task template ids join the planned set of the agents of the system, at their stage. Sizing from `config/tasks.yaml` stays the floor: a template is added, never replaced, and `required` follows its `required_from` at the agent's level | exactly `plan_at` as before |
| Control catalogue (`controls/service.py`, `controls/refs.py`) | Assigned control ids join `controls_for(agent)` and `control_scope(..., settings)` for the agents linked to the system | unchanged |
| Obligation matrix (`obligation_coverage`) | Assigned obligation ids appear with `source: rule` (`control+rule` when a control also holds it) and the system ids. `GET /v1/systems/{id}/obligations` gives the rows of one system | unchanged, no `source` key |
| Guardian floor | `GET /v1/systems/{id}/guardian-floor`: feature slugs the owner cannot switch off, each with the rule ids (read by WP-S1) | not mounted |

The gate and the detectors are not touched. Tests with the current fixtures compare task sets,
`controls_for`, `agent_compliance` and `obligation_coverage` with the flag off and on.

## 7. API (mounted with `/v1/systems`, only when `GOVERNANCE_ENABLED=1`)

| Route | Permission |
|---|---|
| `GET /v1/systems/{id}/assignments` (`?all=1` adds the rows that are off) | `systems.view` |
| `GET /v1/systems/{id}/obligations` | `systems.view` |
| `GET /v1/systems/{id}/guardian-floor` | `systems.view` |
| `GET /v1/systems/{id}/rules/explain` | `systems.view` |
| `POST /v1/systems/{id}/assignments/run` | `systems.edit` |

A system outside the caller's scope answers 404. A bad input is HTTP 400 with a message.

## 8. Console

System page, tab Rules: the guardian floor, the table of assignments (kind, id, rule, fields that
fired, active or off) and a button that runs the rules. EN and VI.

## 9. Open questions

1. Guardian slugs are validated against the detector keys in `config/detectors.yaml`. WP-S1 may
   want the judge sampler, the session monitor and the monitors as slugs too.
2. A rule cannot yet read the Decision 33 draft (only the applied `decision33_class`).
3. Risks are assigned and shown, but no engine reads them yet (the register stays per agent).
