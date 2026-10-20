# Inventory fixtures (WP24)

| File | Source | Licence | Labeller | Use |
|---|---|---|---|---|
| `workspace_7.json` | synthetic, written for WP24 (no real workspace names) | repo licence | synthetic | 7 Apps/endpoints: 3 managed, 1 allow-listed, 3 unmanaged |
| `baseline_counts.json` | measured from the committed manifests and the fixture above | repo licence | synthetic | regression baseline (dated, with commit) |

Provenance of the labels: a managed item is one the three demo manifests name or use
(`payments`, `credit_prequal`, model id `qwen3:4b`); `bi-portal` is on the test allow-list; the
other three have no manifest. The check is a set of deterministic rules (no model, no tuning), so
one split is enough; each rule has a test. Thresholds are ILLUSTRATIVE.
