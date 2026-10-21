# D30 - Control catalogue and right-sized task list

Status: Accepted (WP30, 2026-10-20). Bank decisions listed under "Open". Highest earlier number on
this branch: D26 (D23 to D29 belong to other packages; D30 was chosen by the work package prompt).

## Context

Controls were fields inside compliance matrix rows. One control could not be shown as covering many
obligations and many risks, and nothing said whether it worked for a given agent. Lifecycle work
(who must do what before an agent goes live) lived in people's heads; the launch gate checked the
sandbox but not the process. Saidot (items 3 and 4 of `saidot/COMPARISON.md`) has a catalogue with
cross-mapping and tasks sized by risk level. Its gaps for a bank: status is a count of controls a
person marked done, there is no rule that a control must show runtime proof, no maker-checker rule,
and the task page itself says a gate is a task but gives no refusal rule. We take the structure and
close those gaps.

## Decision

1. **Five tables** in both DDLs and `schema/model.yaml`: `control`, `control_map` (state);
   `control_status`, `task_event` (append-only, evidence retention); `task` (state).
2. **A control covers many obligations and risks** (`control_map` kinds `matrix`, `risk`) and names
   evidence sources (`rule`, `pack`, `monitor`, `detector`, `document`). Targets must exist. A
   rule limited to some agents may be used only by a control that names them.
3. **Status is computed, not typed.** It reuses the WP29 collector (one definition of a hit, a pack
   result and a monitor status, including the review rules), per agent. `working` needs a runtime
   source; a document or a detector slug is a fact about a design, so it is recorded and never
   counts. `no_data` is the default; `failing` beats `working`.
4. **`control` is a WP29 link kind** (`LINK_KINDS`, `CONTROL_KINDS`, `Collector.count` through an
   optional `control_sources` callable). A risk looks through the control at its own runtime
   sources. The control map fingerprint is part of the risk evidence basis, so a map change
   invalidates both the control status and the evidence of the linked risks
   (`changed_since_evidence`).
5. **Windows per source kind**: 7 days for rules and monitors, 30 for packs (`CONTROLS_PACK_WINDOW_DAYS`).
6. **Compliance figure** = integer bp of controls with working evidence over controls in scope;
   None when none is in scope. Bank-owned controls are in the figure but reported apart, since the
   product cannot observe a bank process.
7. **Tasks**: templates by stage in `config/tasks.yaml`; the set is sized by the effective level =
   max(WP29 band, Decision 33 class floor); required tasks are the ones the level makes required.
   Unknown class or tier is sized as more, never less. A stage is released when entered.
8. **The lifecycle move is a task and a gate.** It is refused while a required task of the stage is
   open; at high level it needs an approver or admin. Launch gets one more NO-GO source
   (`assurance.gates.task_launch_items`), behind its own flag; an unreadable task list is NO-GO.
9. **Waiver = reason + second person** (a different, signed-in approver or admin), the same
   maker-checker idea as case sign-off. A move cannot be waived. A class change is additive.
10. **Every change is chained**: `control_change`, `control_status` (one per agent and pass),
    `task_change`, `task_resize`; payloads hold integers, fixed codes and hashes. Reason text is
    stored in the row, only its hash goes to the chain. Overdue required tasks open a case with no
    incident clock (`NO_CLOCK_SOURCES` gets `task`).
11. **Flags** `CONTROLS_ENABLED` (API, jobs, CLI), `CONSOLE_CONTROLS_ENABLED` (pages, tabs),
    `TASKS_LAUNCH_GATE_ENABLED` (launch), all off. Off path: tables empty, routes answer 400.

## Amendment (review WP30, 2026-10-20)

* Point 8: Launch is NO-GO when the agent has no task list, is before the `deployment` stage, has
  a required task of the current stage open (the move out of the stage and templates with
  `blocks_launch: false`, such as DEP-LAUNCH, excluded: they are done after the launch), the
  task list cannot be read, or the gate flag is on while `CONTROLS_ENABLED` is off.
* Point 7: sizing uses the highest level and every class the agent had in its task list, plus
  the current ones (`TaskService.sizing`); a downgrade never relaxes the list.
* Point 9 and Three Lines: a task of role reviewer, approver, auditor or admin needs that role or
  admin; the approver closes a move or an approver task with `POST /v1/tasks/{id}/approve`.
* Point 3 and 6: a bank-owned control is always `no_data` (`bank_owned`) and gives a risk no
  evidence; `implemented_by` is in the control fingerprint.

## Alternatives rejected

* Status as "controls marked done" (Saidot): a claim, not a fact.
* Counting a quiet rule as working: it proves nothing until it fires; the control also names a pack
  or deterministic monitor.
* Creating all stages' tasks at once: a class change would leave stale sizes; releasing by stage
  sizes each stage with the facts of that moment.
* A separate evidence collector for controls: two definitions of "a hit" would drift.

## Open (owner)

Who may waive and approve a stage move (roles now: ask = reviewer, owner, admin; answer = approver,
admin); real task sets and levels; pack window; an agent with no task list is NO-GO at launch
(review; owner to confirm); deterministic monitors for `oversight`, `sweeps`; attestation
evidence for bank controls.
