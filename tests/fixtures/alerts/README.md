# Alert rule fixtures (WP21)

Labelled signals for the alert rules in `config/alerts.yaml`. Everything is synthetic.

| Item | Value |
|---|---|
| Source | `generate.py` in this folder (seeded, deterministic; `--check` proves the files match) |
| Licence | same as the repository (MIT); no third-party data |
| Labeller | synthetic (the generator plants the incidents and writes the label) |
| Dev split | `dev.*`, seed 2101. Thresholds in `config/alerts.yaml` were chosen on this split |
| Held-out split | `heldout.*`, seed 2121. Never used to tune anything; only scored |
| Size per split | 570 signals: 500 gate decisions plus state changes, verdicts, job runs, chain verifies, ingress rejections and a drill |
| Planted incidents | 6 per split, 7 expected alerts (INC-1 raises two) |
| Hard negatives | 4 blocks in 9 min, 5 blocks over 20 min, a pause, a mock tier 2 verdict, a tier 1 verdict, 9 ingress rejects in 5 min, good verifies, a good drill, good job runs |

Line format: `{"id","kind","ts","f":{...},"lane","seq","entry_hash","label"}`. `label` is the
incident id or null and is ground truth only; the engine never reads it.

## Rubric (bank SOC analyst and detection engineer)

1. Every incident is seen once (recall): each planted incident raises the alert of its rule.
2. Nothing else fires (precision): the near misses stay quiet.
3. No flood (dedupe): a continuing incident adds to `suppressed_count`, not to the alert count.
   57 (dev) and 55 (held-out) matching signals become 7 alerts.
4. Triage in under two minutes: each alert has rule id, severity, agent or group, window count
   against threshold, first and last time, and the chain lane, seq and entry hash of the trigger.
5. Stable field names: alert columns, SIEM `attrs` keys and the triage text lines are frozen
   by `tests/alerts/test_harness.py::test_stable_field_names`.

## Command

    python -m supervisor.alerts.harness                    # both splits, prints GO / NO-GO
    python -m supervisor.alerts.harness --write-baseline   # rewrite baseline.json (review the diff)
    python tests/fixtures/alerts/generate.py --check       # fixtures match the generator

## Baseline (`baseline.json`)

Recorded 2026-10-20 on the WP21 branch (base commit bf3a23a). Both splits:
precision 10000 bp, recall 10000 bp, dedupe exact 10000 bp, triage complete 10000 bp,
7 alerts for 7 expected, 0 false positives, 0 false negatives.
Wilson 95 percent interval of precision and recall: 6456 to 10000 bp (n = 7 alerts, so the
interval is wide; the false-alert rate over 570 signals has an upper bound of 67 bp).
Thresholds are ILLUSTRATIVE until the bank SOC sets them: GO needs 10000 bp on all four.

## Limits

n = 7 expected alerts per split is small. The fixture proves the logic (window, threshold,
dedupe, grouping, mock exclusion), not real-world alert rates. The bank should replay a week
of its own gate decisions through `python -m supervisor.alerts test <rule_id>` before it
trusts a threshold.
