# Risk register fixtures (WP29)

| File | Source | Licence | Labeller | Use |
|---|---|---|---|---|
| `golden.jsonl` | synthetic, written for WP29 by `generate.py` (no real names, no real data) | repo licence | synthetic reference implementation in `generate.py`, under two expert rubrics | 50 scenarios: 20 `score`, 12 `inherit`, 12 `evidence`, 6 `link`; 30 `dev`, 20 `held_out` |
| `generate.py` | WP29 | repo licence | synthetic | writes `golden.jsonl`; `--check` fails when the file is stale |
| `baseline.json` | measured by `python -m supervisor.risk.harness --write-baseline` | repo licence | synthetic | regression baseline with date and base commit |

Every item has `id`, `source`, `licence`, `labeller`, `rubric`, `split`, `task`, `input`, `expected`.

Rubrics:

* **operational risk manager**: the score is likelihood x impact and the band is read from the
  thresholds; an agent is as risky as the worst risk it can reach through active `uses` edges;
  a risk that is retired or draft, on a retired component, or behind an inactive link must not
  count; a risk on a shared component reaches every agent that uses it.
* **internal auditor (Three Lines)**: a lowered residual score needs working evidence and a
  recorded reason; a failing or removed control raises the score again; evidence from SHADOW
  agents, retired agents and mock results does not count; every link points at something that
  exists today.

How the expected values were made: `generate.py` computes them with its own plain-loop reference
(a fixpoint walk for inheritance, a short table for the evidence rule, the thresholds written
out), without importing `supervisor.risk`, so the product code is checked against a separate
statement of the rubric. Never tune the product on the `held_out` split. The 20 adversarial
probes are in `src/supervisor/risk/harness.py` (they need a database) and are reported as a
separate row. Thresholds for GO / NO-GO are ILLUSTRATIVE. There is no model in this capability,
so there is no mock path and no model card (`docs/risk-register.md`, section "Harness").
