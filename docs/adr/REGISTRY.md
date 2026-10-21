# ADR number registry

One row per design decision record in this folder. Parallel work packages reserve a number here
(a row with status `reserved` in their first commit) before they write the ADR, so two branches
never take the same number. The next free number is **D33**.

| No. | File | Title | Work package | Status |
|---|---|---|---|---|
| D01 | `D01-gateway.md` | Gateway | phase 1-2 | accepted |
| D02 | `D02-tier0-split.md` | Tier 0 split | phase 1-2 | accepted |
| D03 | `D03-agent-states-fail-mode.md` | Agent states and fail mode | phase 1-2 | accepted |
| D04 | `D04-pause-resume-authority.md` | Pause and resume authority | phase 1-2 | accepted |
| D05 | `D05-evidence-chain.md` | Evidence chain | phase 1-2 | accepted |
| D06 | `D06-judge-hardening.md` | Judge hardening and governance | phase 1-2 | accepted |
| D07 | `D07-residency.md` | Residency | phase 1-2 | accepted |
| D08 | `D08-trace-store.md` | Trace store | phase 1-2 | accepted |
| D09 | `D09-drift.md` | Drift | phase 1-2 | accepted |
| D10 | `D10-multi-agent.md` | Multi-agent | phase 1-2 | accepted |
| D11 | `D11-policy-language.md` | Policy language | phase 1-2 | accepted |
| D12 | `D12-onboarding-agent-safety.md` | Onboarding Agent safety | phase 1-2 | accepted |
| D13 | `D13-retention.md` | Retention and deletion of personal data | phase 1-2 | accepted |
| D14 | `D14-ingress-auth.md` | Ingress authentication for agents | WP20 (phase 3 wave 1) | accepted |
| D15 | `D15-alerts.md` | SIEM export and alerts | WP21 (wave 1) | accepted |
| D16 | `D16-inventory-graph.md` | Inventory graph and shadow-AI scan | WP24 (wave 1) | accepted |
| D17 | `D17-masker-v3-inline-redaction.md` | Masker `vn_regex-3` and inline redaction at the gate | WP24b (wave 1) | accepted |
| D18 | `D18-tool-analytics.md` | Tool analytics and least-privilege suggestions | WP22 (wave 1) | accepted |
| D19 | `D19-latency-benchmark.md` | Latency benchmark method | WP23 (wave 1) | accepted |
| D20 | `D20-monitor-bindings.md` | Per-agent monitor bindings and explicit monitor status | WP1b-B (wave 1) | accepted |
| D21 | `D21-derived-judge-family-and-served-config.md` | Judge family is derived; challenger scope; strict endpoints; served config | WP1b-A (wave 1) | accepted |
| D22 | `D22-playground-dry-run.md` | Playground dry run (`Gateway.evaluate_only`) | WP-UX3 (wave 1) | accepted |
| D23 | `D23-verdict-contract-v2.md` | Verdict contract v2 and the detector framework | WP37 (wave 2) | accepted |
| D24 | `D24-mcp-http-tool-locking.md` | HTTP MCP gateway and tool locking | WP26 (wave 2) | accepted |
| D25 | `D25-multiturn-redteam.md` | Multi-turn red team with a deterministic oracle and a labelled mock agent | WP28 (wave 2) | accepted |
| D26 | `D26-risk-register.md` | Risk register linked to the inventory, the matrix and the gate | WP29 (wave 2) | accepted |
| D27 | `D27-injection-classifier.md` | Injection classifier, Vietnamese and English | WP25 (wave 2) | accepted, model NO-GO, shipped disabled |
| D28 | `D28-collectors-and-policy-modes.md` | Collectors, observe mode and per-consumer policy | WP38 (wave 3) | accepted |
| D29 | `D29-session-monitor.md` | Session monitor | WP27 (wave 3) | accepted |
| D30 | `D30-control-catalogue-tasks.md` | Control catalogue and right-sized task list | WP30 (wave 3) | accepted |
| D31 | `D31-transparency-report.md` | Transparency report per agent, three variants, signed into the chain | WP31 (wave 3) | accepted |
| D32 | `D32-activity-parity.md` | Activity and analytics parity, nine alert use cases | WP39 (wave 3) | accepted |
| D33 | `D33-benchmark-defects-m2.md` | Defects of the M2 benchmark on the bank agent: keep_args, scan limits, mrm_status, split_cue, gate registration | WP41 | accepted |

Rules: a number is never reused, also when an ADR is withdrawn (set status `superseded by Dnn`
or `withdrawn`). The file name starts with the number. A test does not check this file; the
integrator of each wave does.
