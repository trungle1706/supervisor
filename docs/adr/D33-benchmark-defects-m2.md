# D33: Defects of the M2 benchmark on the bank agent

Status: accepted for WP41 (phase 3, after wave 2). No new flag: every change sits behind a flag
that already exists (`DETECTORS_ENABLED`, `SESSION_MONITOR_ENABLED`, `INVENTORY_ENABLED`,
`CONTROLS_ENABLED` / `RISK_REGISTER_ENABLED`, `CONSOLE_TOOLS_ENABLED`) or in an adapter option.
Source: the wave 2 benchmark of `phase3-wave2` (bd270d0) on the real credit memo agent, defects
D18 to D30 and the open M2 exit criterion D04 (`bench/WAVE2_REPORT.md`, outside the repo).

## Context

The benchmark found one defect that broke the agent (D29), two that made detectors expensive
(D30, D18), two that made the session monitor useless on real traffic (D24, D25), the M2 exit
criterion that was not met (D04) and four gaps in registration, tool results, evidence and one
page (D19, D23, D28, D27). Rules R1 to R3 hold: nothing here lets an advisor block, no personal
data reaches the chain or a prompt, and nothing calls out of the host.

## Decisions

1. **`keep_args` for a lookup key (D29).** `agents.<id>.detectors.settings.dlp_vn.keep_args:
   {tool: [argument names]}`. The gate returns the named top-level argument as sent in
   `transformed_args` / `transformed_payload` and keeps the fully masked copy for every record
   (findings, rows, chain, SIEM, the session sketch). The decision lists `kept_args`. The setting
   is part of the policy hash; loading it writes an audit log line and a chain record
   `policy_keep_args`; it is an agent setting (refused in a consumer block); the shape is
   checked at load. *Why not the other options in the report:* typing the tax code is not enough
   (the tool still gets a pseudonym), and a report-only mode on the tool switches protection off
   for every argument of the call. *Why the setting lives under `detectors.settings.dlp_vn` and
   not under `agents.<id>.tools`:* the policy has no per-agent tool table (tools are global, with
   one risk class), and the WP37 override already has the right shape, the right validation path
   and the right hash behaviour.
2. **`pseudonym_mode: typed` (D29).** A text value under an argument whose name says tax or
   account is typed by the name. `generic` stays the default. The masker is unchanged.
3. **Scan limits (D30, D18).** `max_scan_bytes` per detector (16384) and
   `DETECTORS_SCAN_BUDGET_BYTES` per call (65536), arguments first, results last. The cut is a
   coverage reason with byte counts, not an error. A transform of text read only in part is never
   returned: for arguments the detector counts as failed (`payload_too_large`) and the existing
   fail-closed rule applies on money, credit and pii_export tools. *Trade-off:* a legitimate
   pii_export call with an argument above 16 KB is now blocked until the owner raises
   `max_scan_bytes` for `dlp_vn` on that agent; before, it timed out at 500 ms and was blocked
   too, only slower. A memoising masker (masked text, keyed by SHA-256) and an early exit in the
   regex detector reduce the cost of what is scanned.
4. **`mrm_status` per detector (D24, D25).** The session monitor's `findings` signal counts only
   findings of deterministic detectors or of detectors with status GO. Others are recorded on the
   turn and weigh 0. Default `NO-GO`. The status feeds one reader and never changes the decision.
5. **`split_cue` (D04).** A tenth session signal: the head of an injection phrase at the end of
   one call and its tail at the start of a later call of the window, found with the halves of the
   Tier 0b patterns on the same normalised forms. Deterministic, ids only, a solo signal like
   `memory`, weight 300. Default weights: `timing` 400 to 100, `split_cue` 300 (the only change
   that left every harness number as it was). *Why solo:* with the classifier noise gone, the bank
   shape has `drift` and `split_cue` (2 of K=3) and no payment; counters miss a cut phrase by
   construction. *Cost:* a known false positive when a text ends with a head and a later call
   starts with a tail by chance; the look-alike probes show what does not fire.
6. **Registration, tool results, evidence (D19, D23, D28).** The first gate decision of a policy
   agent writes an inventory node (source `gate`) when `INVENTORY_ENABLED=1`. The stock LangGraph
   middleware sends the last 3 tool results, 16 KB each, option `send_tool_results` (default on).
   Pack evidence for risks and controls reads the `agent` and the `traces` target of the agent.
7. **Tools tab (D27).** An agent with a registry row and no policy record gets 200 with a hint;
   `tools_suggest.build_all` reads the served `POLICY_DIR`.

## Consequences

* Policy hash: a policy with `keep_args` hashes differently; a policy without it keeps its hash.
* The Decisions CSV export has a 19th column `kept_arguments` (names only).
* `data/eval/session/` has seven more probes; the session harness baseline was re-recorded for
  that reason (adversarial recall 6250 to 6500 bp; all other numbers unchanged).
* `config/detectors.yaml` has `mrm_status` and `limits.scan_budget_bytes`.

## Not decided

* Whether the next benchmark should run the sensitive session point (K=3, 1500 bp) report-only.
* Whether a `keep_args` entry should need two approvers (today: review of the policy diff).
* Sending `turn_text` from every collector (the stock adapters send none; `expand`, `memory` and
  the topic markers need it).
