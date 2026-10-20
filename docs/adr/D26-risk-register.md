# D26 - Risk register linked to the inventory, the matrix and the gate

Status: Accepted (WP29, 2026-10-20). Bank decisions listed under "Open".

## Context

Supervisor knew agents, their parts (WP24 inventory) and what each rule did at runtime, but a risk lived only in a questionnaire or in the head of the risk function. Saidot (item 2 in `saidot/COMPARISON.md`) shows the pattern: risks with likelihood and impact, marginal risk, treatment, residual risk and owner, linked to the system graph. Its gaps for a bank are that residual risk is a manual claim, the score thresholds are not stated, there is no runtime control and no risk appetite object. We take the structure and close those gaps.

## Decision

1. **Three tables** in both DDLs and `schema/model.yaml`: `risk` and `risk_link` (state tables, optimistic concurrency) and `risk_evidence` (append-only, evidence retention). A link is one row per (risk, kind, target) with an `active` flag, so an unlink stays as history and the state store needs no delete.
2. **Integers only.** Likelihood and impact are 1 to 5, score = product. The score and the band are computed when read and never stored. Band thresholds are in `config/risk.yaml` and are ILLUSTRATIVE; every surface says so.
3. **A fixed taxonomy of seven categories** (money movement, credit decision, PII, injection, model behaviour, availability, third party), not Saidot's eleven types. The seven map to the three agent profiles and to the tool risk classes; a bank that needs more asks for a change to the list (a code change, on purpose, so reports compare).
4. **Inheritance reuses the WP24 graph code.** The register builds a copy of the inventory graph whose node levels are the bands of the risks on the node, and calls `Graph.effective_risk`. No second SCC. A second function lists which risks reach an agent; a property test checks that both agree. Only active risks count; `gone` nodes and inactive edges pass nothing (same rules as WP24).
5. **Controls are links of three kinds** (gate rule, assurance pack, monitor); matrix rows and cases are references. A link is accepted only when its target exists today.
6. **Evidence rule: residual may only be lowered by working evidence.** For `mitigate` risks the residual is the declared value only while no linked control is failing and at least one is working in the last window; in every other state it is the inherent score. For other treatments it is the declared value. So the lowest value a risk can show is what its owner declared, and a broken, removed or silent control puts the score back up. Evidence is: tier-0 gate verdicts with a rule id, non-mock assurance results, monitor status. SHADOW, retired and unknown agents are excluded. Judges and classifiers are not inputs (rule R1).
7. **One row and one chain record per risk and window.** The row id is a hash of (risk, window end), so a repeat is a no-op on both SQLite and Delta (insert-only MERGE). Payloads hold integers, fixed reason codes and hashes (rules R2 and R3: no names, no text, no network).
8. **Edits are audited twice**: two `console_action` rows (attempted, outcome with the hash of the risk and its links before and after) through the existing `audited` wrapper, plus a `risk_change` chain record with the actor. Roles: `risks.view` for all, `risks.edit` for reviewer, owner and admin.
9. **Import is the bank's change control.** One YAML format, all or nothing, idempotent; a risk edited by hand is not overwritten unless asked.
10. **Flags** `RISK_REGISTER_ENABLED` (API, job, CLI) and `CONSOLE_RISKS_ENABLED` (page and tab), both off. Off path: tables stay empty, routes answer 400, nav entry and tab hidden.

## Alternatives rejected

| Alternative | Why not |
|---|---|
| Store the score and the effective residual | They go stale when a link, a rule or an edge changes; computing on read is cheap and always right |
| Let the owner's declared residual stand | That is the Saidot weakness: a questionnaire answer. The declared value becomes the floor of the evidence rule, not the answer |
| Lower the residual by a graded amount for each hit | Needs a calibration the bank has not set and makes the number depend on traffic volume. Two states keep the rule auditable |
| Count a rule that never fired as "working" | Silence is not proof. A pack replay or a monitor must show it works; a synthetic gate probe is in the backlog |
| Treat a judge verdict as evidence | Judges advise only (R1); using one to lower a score would let an advisor change a control decision |
| Delete rows for an unlink | The state store port has no delete and the history matters to the auditor |
| A separate risk graph | Duplicates WP24 and drifts from it |

## Consequences

* Mitigated risks start at their inherent score until the first evidence pass shows a working control. This is intended (a claim is not a fact) and the page says so.
* A rarely firing rule alone cannot lower a score; link a pack or monitor too (the starter risks do).
* The evidence reads the agent's gate state now, not at the time of each hit (documented limit).
* Extension points for WP30 (control catalogue feeds `add_link`) and WP31 (transparency report reads `agent_summary`) are named in `docs/risk-register.md`.

## Open (bank decisions)

1. The real band thresholds and the meaning of each likelihood and impact step (risk appetite). Until then every number is labelled illustrative.
2. Who may create or accept a risk, and whether a second person must approve it (four-eyes). Today: reviewer, owner and admin create and edit; there is no approval step.
3. The evidence window (7 days) and the number of working controls required (1).
4. Whether the register is also the system of record for the bank's operational risk tool, or is exported to it (`export` gives JSON and CSV).
