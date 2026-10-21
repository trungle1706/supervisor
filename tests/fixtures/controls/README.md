# Control catalogue and task list fixtures (WP30)

| File | Source | Licence | Labeller | Use |
|---|---|---|---|---|
| `golden.jsonl` | synthetic, written for WP30 by `generate.py` (no real names, no real data) | repo licence | synthetic reference implementation in `generate.py`, under two expert rubrics | 50 scenarios: 12 `status`, 8 `bp`, 12 `plan`, 10 `gate`, 8 `waive`; 30 `dev`, 20 `held_out` |
| `generate.py` | WP30 | repo licence | synthetic | writes `golden.jsonl`; `--check` fails when the file is stale |
| `baseline.json` | measured by `python -m supervisor.controls.harness --write-baseline` | repo licence | synthetic | regression baseline with date, base commit and the hash of `config/tasks.yaml` |

Every item has `id`, `source`, `licence`, `labeller`, `rubric`, `split`, `task`, `input`, `expected`.

Rubrics:

* **compliance officer**: a control is working only on runtime evidence (a quiet rule, a document
  or a shadow agent proves nothing); the figure is working over in-scope controls in whole basis
  points; a Decision 33 high-risk agent never gets the light task set and a larger band never gets
  fewer tasks.
* **internal auditor (Three Lines)**: the lifecycle move is refused while a required task is open
  and needs an approver at high level; a waiver needs a reason and a second person who is a
  signed-in approver or admin and not the person who asked; a failing source beats a working one.

How the expected values were made: `generate.py` computes them with its own plain tables and loops
(and PyYAML on `config/tasks.yaml` for the plans), without importing `supervisor.controls` or
`supervisor.tasks`. Both are by the same author, so the scenarios show the code does what the rubric
says, not that the rubric is right. The `plan` scenarios are tied to the shipped, ILLUSTRATIVE
`config/tasks.yaml`: after a deliberate edit run `generate.py` and `--write-baseline`. Never tune the
product on the `held_out` split. The 24 adversarial probes are in `src/supervisor/controls/harness.py`
(they need a database) and are reported as a separate row. There is no model in this capability, so
there is no mock path and no model card.
