# Playground samples (WP28)

Ready-to-run inputs for the console Playground. WP38 reads `samples.jsonl` and shows them as
presets. One JSON object per line; synthetic data only (no real name, account or key).

| Field | Meaning |
|---|---|
| `id`, `category`, `lang`, `title` | `category` is injection, pii, jailbreak, secrets, toxicity or split_payment; `lang` is vi or en |
| `agent_id`, `agent_version`, `tool`, `args`, `context` | The Playground form fields, as typed |
| `sequence` | Optional further `{tool, args}` calls. A dry run cannot evaluate window rules; replaying the sequence with the real gate in the sandbox shows them |
| `expect.gate` | `{action, rule_id}` that `Gateway.evaluate_only` answers on the baseline policy |
| `expect.tier0b` | Sorted finding kinds of the Tier 0b regex classifier on the arguments |
| `expect.not_evaluated` | Rule ids a dry run lists as not evaluated |
| `label`, `labeller`, `source`, `licence`, `notes` | attack or benign; labeller is "expert rubric"; own data; one sentence for a tooltip |

The file is generated: `python -m supervisor.redteam.multiturn build-data` (add `--check` to
verify). Edit `src/supervisor/redteam/multiturn/samples.py`, not the JSONL. A test runs every
sample through the real gate and the Tier 0b classifier. Some samples show a gap on purpose
(Tier 0b has no pattern for secrets or insults); their `notes` say so.
