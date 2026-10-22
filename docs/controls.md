# Control catalogue and task list (WP30)

Off by default (`CONTROLS_ENABLED=1`). ADR: `docs/adr/D30-control-catalogue-tasks.md`.
Built on the risk register (`docs/risk-register.md`). Numbers and task sets here are ILLUSTRATIVE
until the bank sets its own.

## 1. What it is

```
 obligation (matrix row) --+                      +-- rule hit      (gate, enforced, per agent)
 obligation               -+--> CONTROL <---------+-- pack result   (real, non-mock)
 risk (WP29)              -+   one control,       +-- monitor status (fairness, drift, multiagent)
 risk                     -+   many of each       +-- detector slug / document  (recorded only)
                                  |
                                  v  per agent, per window
                     evidence status: working | failing | no_data
                                  |
                                  v
         compliance bp of the agent = controls with working evidence / controls in scope
```

A task list sits in front of the launch gate:

```
 initiation -> design -> validation -> deployment -> operation -> re-evaluation -> retirement
      each arrow is a task (the lifecycle move). It is done only when no REQUIRED task of the
      stage is open. At high level it needs an approver or an admin (stage approval).
 Launch GO/NO-GO (TASKS_LAUNCH_GATE_ENABLED): NO-GO while the agent has no task list, is before
 the deployment stage, or has a required task of its stage open (the move out of the stage and
 DEP-LAUNCH are done after the launch and do not hold it).
```

## 2. The control

| Field | Meaning |
|---|---|
| `control_id` | `CTL-...`, 1 to 64 characters |
| `title`, `objective` | What the control does, in words of the owner |
| `type` | `preventive`, `detective` or `corrective` |
| `implemented_by` | `product` (Supervisor does it) or `bank` (a bank process; the product cannot observe it) |
| `owner`, `review_date` | Named owner; an active control needs a review date |
| `status` | `draft`, `active`, `retired`. Only an active control has evidence and gives a risk its evidence |
| `agents` | `["*"]` (every agent) or a list of agent ids. A rule limited to some agents (for example `PAY-02` for `payments`) may be used only by a control that names those agents |

The map (table `control_map`): `matrix` (obligation ids of the compliance matrix) and `risk`
(WP29 risk ids) say what the control covers. `rule`, `pack`, `monitor`, `detector`, `document`
say what shows it works. Every target must exist when it is saved. An active control must cover at
least one obligation or risk and name at least one evidence source. A `risk` entry also writes the
WP29 link kind `control` (`RiskService.add_link`), so the risk sees the control, and the risk
evidence pass looks through the control at its runtime sources.

## 3. Evidence status

Computed per control and per agent from the same facts the risk register uses
(`risk.evidence.Collector`; the WP29 review rules apply). Never typed in.

| Source | Counts as |
|---|---|
| rule | working = at least one **enforced** tier-0 hit of the agent in the window (shadow, rule_error, fail-mode and mock rows are not hits); failing = the rule is not in the deployed policy any more |
| pack | newest **non-mock** result of the agent, on its `agent:` target **and** on its `traces:` target (WP41, D28: a fail on either one makes the control failing; a `judge` target is not bound to an agent and never counts): ok working; fail or error failing; warn, skip, none idle. A judge-scored pack (`groundedness_monitor`, `halueval_vi`, ...) is a reference, not evidence, unless `RISK_EVIDENCE_JUDGED_PACKS=1` (rule R1) |
| monitor | only `fairness`, `drift`, `multiagent` can be working (`quality` is an LLM scorer; `oversight` and `sweeps` write no status). They are idle |
| detector, document | recorded and checked for shape or existence; never working |

Status: `failing` if any source fails; `working` if none fails and one works; else `no_data`
(reasons `no_working_source`, `reference_only`, `no_sources`, `no_supervised_agent`). A control
the bank owns (`implemented_by: bank`) is always `no_data` with reason `bank_owned`, whatever
sources it names, and it gives a linked risk no evidence (review WP30). A SHADOW,
RETIRED or unknown agent is not supervised, so its controls are `no_data`.

Windows: rules and monitors use `RISK_EVIDENCE_WINDOW_DAYS` (7); a pack result uses
`CONTROLS_PACK_WINDOW_DAYS` (30), because packs run less often. A status row older than two windows
reads as `no_data` (`stale`). **A change to the control (status, implemented_by, agents, any map
entry) makes the stored status read as `no_data` with reason `changed_since_evidence` until the
next pass**, and the same change changes the evidence basis of every risk that links the control.
A judge-scored pack counts for a control only with `RISK_EVIDENCE_JUDGED_PACKS=1`, the same switch
as the risk register.

**Reopen (WP-G5).** The governance action `reopen_control` (`docs/governance-actions.md`) appends a
`failing` row with reason `reopened_by_event` for one control and agent when an event contradicts
the control (a failed pack, a monitor breach, a rule that had to stop a call). The row reads
`failing` while it is the newest row of the pair; the next pass in a later window writes a newer
row and the evidence decides again. The control, its map and its scope do not change. One chain
record `control_reopen` per row.

`control_status` is append-only (one row per control, agent, window and map fingerprint). One chain
record `control_status` per agent and pass carries counts and the compliance bp, plus a digest.

## 4. Compliance figure

`compliance_bp = working * 10000 // in_scope` in whole basis points; `None` when no control is in
scope (no claim). A control is in scope of an agent when it is active, the agent is not RETIRED and
the control names the agent or `*`. The API also gives `product_bp` and `bank_in_scope`: bank-owned
controls never show working (Supervisor cannot see a bank process), so read the figure with them
apart. `obligation_coverage(agent)` lists, for each obligation, its controls and the best status.

A **product** control needs at least one source that can make it work (a rule, a pack that is not judge-scored, or `fairness`, `drift`, `multiagent`); the harness starter check fails an active product control that has only references (`evidence_capable()` in `controls/model.py`). The starters `CTL-MON-OVERSIGHT`, `CTL-EVD-CHAIN`, `CTL-MON-QUALITY` and `CTL-ASR-GROUNDED` are `draft` for that reason.

Honest limits: a quiet rule is `no_data`, not working (add a pack or a deterministic monitor to the
control); four starter controls are draft until a deterministic source exists for them (BACKLOG).

## 5. Tasks and sizing

`config/tasks.yaml` holds the templates. The set for an agent:

1. **Effective level** = the higher of its band (WP29 register level; else the registry risk tier;
   else `high`) and the floor of its Decision 33 class (`high_risk` -> high, `unclassified` ->
   medium, `not_high_risk` -> low).
   An agent linked to an AI system (`GOVERNANCE_ENABLED`) takes the effective risk level of the
   system instead of its own band (`docs/governance.md` section 12); an unlinked agent is as above.
2. A template is in the set when the level is at least its `min_level` and the class matches.
3. It is **required** when the level is at least its `required_from`.

`python -m supervisor.tasks plan --class high_risk --band low` prints a set. Tasks of a stage are
released when the agent enters the stage (sized again then). **The list never gets lighter**: it
is sized with the highest level the agent had in its task list and every class it had (plus the
current ones), so a class or band that goes down in the middle of the lifecycle does not remove a
task, skip a stage or drop the stage approval (review WP30); a person waives what no longer
applies, with a second person. Evidence of a task: `control` (done only
while the control is working for the agent), `pack` (a real, passed result), `document` (the person
gives the reference), `none`. `python -m supervisor.jobs.task_due` closes control and pack tasks by
itself when their evidence is there, and opens one case (source `task`, no incident clock) for each
overdue required task.

**Who marks a task done.** An `owner` task: anyone with `tasks.edit`. A `reviewer`, `approver`,
`auditor` or `admin` task: a person with that role, or an admin, so a second-line task is not
closed by the first line alone. The approver uses `POST /v1/tasks/{id}/approve` (`tasks.approve`)
for a lifecycle move (stage approval at high level) and for an approver task.

State machine: `open -> in_progress -> done`, or `waived`. **Waiving** needs a reason and a second
person: the first person (`tasks.edit`) asks, a different signed-in approver or admin
(`tasks.approve`) answers; a move cannot be waived. User ids are compared without letter case.
**Laptop posture:** with `AUTH_KIND=dev_header` (ADR D04) the identity is not real: one person at
the keyboard can ask as one user id and answer as another. That is accepted for the laptop only;
the Databricks App uses SSO, where the same identity is always refused. The CLI trusts `--by` and
`--role` in the same way (shell access to the store is write access). A class change in the middle of the lifecycle
is additive: new tasks are added and tasks become required, nothing is removed or relaxed by
itself. **Segregation of duties across the stage:** the person who answers a waiver (approve or reject) or approves a high-level move must not have marked any task done, or asked for a waiver, in the same stage of the same agent (case-insensitive; refusal text starts `segregation of duties:`). A pack task closes only on an `ok` non-mock result newer than `CONTROLS_PACK_WINDOW_DAYS` and not from a judge-scored pack (unless `RISK_EVIDENCE_JUDGED_PACKS=1`). `GET /v1/tasks/export.csv` (`tasks.view`; `?agent=`, `?limit=`, at most 5000 rows, header `X-Rows-Truncated`) gives a formula-safe CSV. A risk that looks through a control reads its sources for the agents the control applies to and in the same per-source windows as control status (`risk.evidence.source_window`). Every change writes a `task_event` row and a `task_change` chain record (hashes and
integers; the reason is a hash on the chain and text in the row).

## 6. Where to use it

| What | How |
|---|---|
| Routes | `/v1/controls...` (`controls.view`, `controls.edit`), `/v1/tasks...` (`tasks.view`, `tasks.edit`, `tasks.approve`) |
| Console | `/console/controls`, `/console/tasks`, Agent tabs Controls and Tasks (`CONSOLE_CONTROLS_ENABLED`) |
| Jobs | `python -m supervisor.jobs.control_status` (scheduler `SCHED_CONTROL_STATUS_S`), `python -m supervisor.jobs.task_due` (`SCHED_TASK_DUE_S`) |
| CLI | `python -m supervisor.controls list\|import\|status\|export` (`--by` for writes); `python -m supervisor.tasks list\|plan\|generate\|done\|waive` |
| Launch gate | `TASKS_LAUNCH_GATE_ENABLED=1` (needs `CONTROLS_ENABLED`; without it Launch is NO-GO): `assurance.gates.task_launch_items`, `TaskService.launch_blockers` |
| Harness | `python -m supervisor.controls.harness` |

On Delta run `python -m supervisor.jobs.bootstrap_schema` first (five new tables).

### How a bank imports its own catalogue

```
python -m supervisor.risk import <bank risks>.yaml --by <you>          # the risks first
python -m supervisor.controls import <bank controls>.yaml --by <you> --dry-run
python -m supervisor.controls import <bank controls>.yaml --by <you>
```

`--by` is your own user id: it goes to a `console_action` row; chain records carry only a keyed hash (`actor_ref`). The task CLI takes `--by` too (`python -m supervisor.tasks generate --agent <id> --by <you>`).

Format (see `config/controls/*.yaml`): a `controls:` list; each item has `id`, `title`,
`objective`, `type`, `implemented_by`, `owner`, `status`, `review_date`, `agents`, `covers:
{matrix: [...], risk: [...]}` and `evidence: {rule, pack, monitor, detector, document}`. Import is
all or nothing and idempotent; a control a person edited by hand is not overwritten unless
`--overwrite-manual`. Put the bank's own task templates in a copy of `config/tasks.yaml` and point
`TASKS_CONFIG` at it; then run `tests/fixtures/controls/generate.py` and the harness
`--write-baseline` for your copy of the golden plans.

## 7. Harness

`python -m supervisor.controls.harness` (no model, no network): 50 golden scenarios (30 dev, 20
held-out; status, bp, plan, gate, waive), 24 adversarial probes, starter consistency (28 starter
controls cover all 19 starter risks and every obligation they cite), determinism, regression
against `tests/fixtures/controls/baseline.json`. Rubrics: **compliance officer** (working only on
runtime evidence, an honest figure, right-sized task set, a high-risk class never gets the light
set) and **internal auditor (Three Lines)** (the move is a gate, a waiver has a reason and a second
person, a failing source beats a working one, shadow agents prove nothing, everything is on the
chain). Wilson 95 percent intervals are printed. Thresholds are ILLUSTRATIVE (10000 bp).
The expected values come from an independent reference (`generate.py`) written by the same author.

## 8. For other modules (WP31 transparency report)

* `ControlService.agent_compliance(agent_id)`: controls in scope, status, bp, product and bank split.
* `ControlService.obligation_coverage(agent_id)`: obligation -> controls -> best status.
* `ControlService.export_json()`; `TaskService.agent_summary(agent_id)`; `TaskService.export_json()`.
* `RiskService.control_links(risk_id)` already expands controls for the risk evidence rule.
* Chain record types: `control_change`, `control_status`, `task_change`, `task_resize`.
