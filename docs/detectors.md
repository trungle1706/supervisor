# Detectors and verdict contract v2 (WP37)

Flag: `DETECTORS_ENABLED` (default `0`). Decision record: `docs/adr/D23-verdict-contract-v2.md`.
Validation report: `docs/detectors-validation-report.md`. API shape: `docs/api.md`.

With the flag off the gate answers and records exactly as in v0.3.0. A test keeps a SHA-256
fingerprint of the answers, the verdict rows, the `agent_event` rows and the chain payloads for a
fixed call sequence (`tests/detectors/test_flag_off_fingerprint.py`).

With the flag on, the gate runs **detectors** on each call. A detector looks at the call and
returns **findings**. The gate adds `status`, `findings`, `not_executed`, `coverage`,
`transformed_payload`, `request_id` and `correlation_id` to its answer. Every old field stays.

```
 call --> deterministic rules (unchanged) --> decision
              |                                  |
              +--> detectors (pre-computed ------+--> fold in: findings, status,
                   outside the lock)                    dlp transform, GATE-DETECTOR-FAILED
```

## 1. The detector contract

`src/supervisor/core/detectors.py`. Pure Python. No model weights, no network.

| Part | Meaning |
|---|---|
| `slug`, `name`, `category`, `version` | Identity. `detector_id` is `slug@version` |
| `sides` | `input` and/or `output`. The registry runs a detector only when the call direction is in `sides` |
| `protocols` | `llm`, `mcp`, `a2a`, or `all` |
| `settings_schema` | Declarative fields: `key`, `label`, `type` (string, integer, number, boolean, enum, array, object), `required`, `default`, `enum`, nested `fields`. The registry adds two common fields: `preset` and `threshold_bp` |
| `presets` | Named thresholds in basis points. Illustrative. Frozen per `version` (a test fails when a number changes without a version change) |
| `evaluate(payload, settings, direction)` | Returns a list of `Finding` |

`payload` has the parts `args`, `tool_results` (input side) or `output` (output side), and `meta`
(`tool_name`, `risk_class`, `agent_id`).

`Finding`:

| Field | Meaning |
|---|---|
| `detector_slug`, `detector_id`, `code` | Who and what. Codes look like `pii.phone`, `injection.instruction_override`, `judge.compliance_bypass` |
| `score_bp`, `threshold_bp` | Integers, 0 to 10000. The finding fires when score is at or above the threshold (a finding that transformed the payload always counts) |
| `entities` | MASKED: type and pseudonym token (`<PHONE:e65362>`), never the value |
| `fragments` | Located on MASKED text only: `part`, `path`, `start`, `end`, `text`. Offsets index the masked leaf at `path`. `precision` is `span` or `leaf` (whole leaf: used when the match came from a normalised form with no offsets) |
| `masked_count` | Number of values masked |
| `action_hint` | `report`, `transform`, `pause`, `block`. See section 4: only `transform` from `dlp_vn` acts |
| `not_executed_reason` | `None`, or one of the fixed list below |

Reasons a detector did not run (fixed list):

| Reason | When |
|---|---|
| `execution_failed` | The detector raised. Only the exception class name is kept, never the message |
| `invalid_config` | The settings do not match the schema |
| `payload_too_large` | The inspected text is longer than `limits.max_payload_chars` |
| `content_uninspectable` | A part has content no detector can read (bytes, an object, nesting deeper than 12) |
| `not_applicable_for_direction` | The detector is enabled but its `sides` do not include this direction. Informational, not a failure |
| `timed_out` | The detector did not answer within `limits.timeout_ms`. Each detector call runs in its own daemon thread and the gate waits at most `timeout_ms` for it, so a hung detector cannot hold a gate worker or delay a money decision past the gate budget. A hung thread stays until it returns (Python cannot kill a thread); at most 32 run at once, and with no free slot the detector is not started and is reported `timed_out` (detail `no free detector slot`) at once. Keep the sum of `timeout_ms` over enabled detectors below the gate timeout (2 s) |

`DetectorRegistry` lists the catalogue from code (`GET /v1/gate/detectors`,
`python -m supervisor.detectors.harness --catalogue`), validates settings against the schema, and
runs the enabled detectors.

## 2. Catalogue (version 1.0.0 of each)

| Slug | Sides | Does | Hint | Presets strict / balanced / lenient (bp) |
|---|---|---|---|---|
| `dlp_vn` | input, output | Wraps the `vn_regex-3` masker. One finding per entity type (`pii.person`, `pii.phone`, `pii.cccd`, ...). The only detector that transforms | `transform` for tools in scope, else `report` | 5000 / 8000 / 9500 |
| `injection_regex` | input | The Tier 0b pattern list as a detector (Vietnamese and English). Scans `args` and `tool_results` (indirect injection). Codes `injection.instruction_override`, `mode_switch`, `prompt_leak`, `policy_override`, `urgent_transfer`, `role_tag` | `report` | 5000 / 7000 / 8500 |
| `judge_advisory` | input, output | The Tier 1 judge. Without a judge model it uses the MockJudge and every finding says `mock: true`. The judge sees masked text only | `report` | 3000 / 5000 / 7000 |

`dlp_vn` settings: `mode` (`transform` or `report`), `transform_risk_classes` (default
`[pii_export]`), `transform_tools`. In transform scope the call carries the masked payload in
`transformed_payload` (and in `transformed_args` when the tool arguments changed, so the SDK and
the MCP proxy apply it as they do for WP24b). Outside the scope `dlp_vn` only reports.

`injection_regex` scores per group (illustrative): override 9000, mode switch 9000, policy
override 8500, role tag 8000, prompt leak 7000, urgent transfer 6500, plus 500 for each extra
hit. At the `balanced` preset an urgent-transfer phrase alone does not fire. Known gaps are in
`BACKLOG.md` and in the validation report (typos, leetspeak, base64, split fields, paraphrase).

## 3. Settings: file and per-agent override

`config/detectors.yaml` holds the defaults (`default_preset`, `limits`, one entry per detector with
`enabled`, `fail_closed`, `settings`). A wrong value stops the start-up with one ASCII line that
names `DETECTORS_CONFIG` (the gateway routes then fail closed until it is fixed), and
`python -m supervisor.preflight` shows it as `[FAIL] detectors` before any start.

A policy file can override per agent (`agents.<id>.detectors`):

```yaml
agents:
  payments:
    detectors:
      preset: strict            # default preset for this agent
      enable: [judge_advisory]
      disable: []
      settings:
        dlp_vn: {mode: report}
      skip_tools: [get_balance] # no detector runs for these tools: status "skip"
```

`skip_tools` may not name a `money`, `credit` or `pii_export` tool: the policy loader refuses such a
policy with a message that names the agent and the tool (a skip would switch off the
`GATE-DETECTOR-FAILED` protection). Read-only tools and tools not listed in `tools:` are allowed.
Until `skip` becomes a rule action with two approvers, this is the only skip.

Every policy reload runs the same check as start-up on the per-agent overrides. A reload with a bad
override (unknown detector, wrong setting value) is rejected: the old policy stays in force, one
ASCII line is logged, and `StorePolicyProvider.rejected_hash` / `rejected_reason` say why. The first
load of a bad policy fails with the same message. A bad override therefore never reaches a money
call as `invalid_config`.

The span attribute `supervisor.gate.correlation_id` is copied into `agent_event.correlation_id` by
the recorder only when `DETECTORS_ENABLED=1`.

Order, strongest first: agent `settings.<slug>`, agent `preset`, `detectors.<slug>` in the file,
`default_preset`, the detector default. The key is left out of the policy hash when unset, so an
existing policy file keeps the hash it had.

## 4. Verdict v2 and precedence

The status of a verdict:

| Rank | Status | When |
|---|---|---|
| 5 | `block` | A deterministic rule, a built-in block or `GATE-DETECTOR-FAILED` denied the call. Also when a block rule matched together with a pause rule that decided first |
| 4 | `pause` | A pause rule denied the call (no block rule matched) |
| 3 | `transform` | The call is allowed and `dlp_vn` (or WP24b redaction) produced a masked payload |
| 2 | `report` | The call is allowed and a finding fired, or a rule with action `log` or `alert` matched |
| 1 | `allow` | None of the above |
| - | `skip` | Only from a policy value (`skip_tools`), only when the deterministic decision would be allow or report. A block or pause is never hidden by skip, and a transform (WP24b inline redaction still runs on a skipped tool) shows as `transform` |

Precedence: **block > pause > transform > report > allow**. The old `action` field keeps the gate
order (a pause rule decides before a block rule), so one call can show `action: pause` and
`status: block`. The agent is paused in that case; the status tells the reader that a block rule
matched too.

What a detector may do to the decision (R1):

1. `dlp_vn` may add a transform to an allowed, non-shadow call.
2. A detector that is `fail_closed` and could not run makes an allowed call to a `money`, `credit`
   or `pii_export` tool a block with rule id **`GATE-DETECTOR-FAILED`** (`fail_mode: closed`).
   On any other tool the failure is only an entry in `not_executed`. An `advisory` detector
   (`judge_advisory`) never fails closed: the registry ignores `fail_closed: true` for it (a
   warning is logged at start-up), so a judge outage never blocks a payment.
3. Nothing else. A finding with `action_hint` `pause` or `block` counts as `report`. A shadow agent
   is never blocked or transformed; the findings are still reported.

Detector results are computed before the gate takes its lock (a masker pass over a 2 KB payload
costs a few milliseconds) and folded in after the deterministic decision exists. The rules do not
read them.

Direction: `direction` is `input` (default) or `output`. An **output check** is not a tool call:
no rule is evaluated, no window changes, no pause. The built-in state checks still apply (a
quarantined agent is blocked). The output text goes in `context.output`. For an input check the
tool results that fed the call go in `context.tool_results`. With the flag off, `direction:
output` is refused with HTTP 400.

## 5. Coverage

`coverage` says which parts of the payload were looked at:

```json
{"direction": "input", "inspected": ["args"],
 "not_inspected": [{"part": "tool_results", "reason": "not_provided"},
                   {"part": "output", "reason": "not_applicable_for_direction"}],
 "chars": 130}
```

Reasons for a part: `not_provided`, `not_applicable_for_direction`, `content_uninspectable`,
`payload_too_large`, `skipped_by_policy`, `execution_failed`, `gate_failed`. A part is `inspected`
when it was provided, every leaf is readable text (or a number) and the total size is within
`limits.max_payload_chars`. Coverage lists parts and reasons only, never text.

## 6. Ids

`request_id` is the HTTP request id (or a generated one). `correlation_id` comes from the
`X-Supervisor-Correlation-Id` request header (1 to 128 characters of `A-Za-z0-9_.:@-`; another
value is HTTP 400) or is generated. It is echoed in the response header and written to the
decision (`agent_event.correlation_id`), the `finding` rows, the chain record and the SIEM event.
The agent SDK runtime sets span attributes `supervisor.gate.correlation_id` and
`supervisor.gate.status` from the answer, so a trace span, a decision and an alert share one id.

## 7. Evidence and persistence

| Where | What (flag on) |
|---|---|
| Table `finding` (`schema/model.yaml`, both DDLs) | One row per fired finding and per detector that did not run. Entities and fragments are masked text. Retention class `masked` (columns `entities_masked`, `fragments_masked`) |
| `agent_event` | New nullable columns `verdict_status`, `correlation_id`, `coverage_json`. The old `status` column keeps `allowed` / `denied` |
| Chain record `gate_decision` | Adds `status`, `direction`, `request_id`, `correlation_id`, `finding_codes`, `finding_hashes` (SHA-256 of each finding without text), `not_executed`, `coverage` (parts and reasons), `transformed` (bool), `detectors`. No text, no token, no path |
| SIEM / OCSF event | `attrs.status`, `attrs.finding_codes`, `attrs.correlation_id` (OCSF `unmapped.attrs`) |

Paths in fragments show dict keys that are plain identifiers; any other key shows as `*`, because a
key could hold a name or a number.

## 8. Evaluation harness

```
python -m supervisor.detectors.harness            # score all detectors, print the table
python -m supervisor.detectors.harness --check    # exit 1 on a drop below the baseline
python -m supervisor.detectors.harness --help
```

Golden set: `data/eval/detectors/` (synthetic, licence "own (synthetic, MIT)"; `MANIFEST.json`
has hashes and counts). Per detector 60 items in `dev` and 60 in `heldout` (different templates;
nobody tunes on held-out), plus `adversarial.jsonl`: 38 hand-written probes the templates do not
generate (typos, leetspeak, Telex, no-diacritic Vietnamese, mixed language, split fields, base64,
reversed text, benign look-alikes). The report gives recall, precision, false-positive rate with
Wilson 95% intervals, typed recall (the expected code fired), fragment exactness (the fragment is
the text at its offsets in the masked leaf), leak items (a raw sensitive string anywhere in an
answer; must be 0), latency per item (p50, p95, max), the failure taxonomy and a GO / NO-GO per
metric against illustrative thresholds. The judge runs on the MockJudge: it proves the harness,
not a model. `tests/detectors/test_harness.py` fails on a drop below `baseline.json`.

Expert rubrics: SOC analyst reading a verdict (typed recall, fragments you can find, false
positives, speed) and data protection officer (no raw personal data in findings, fragments,
entities or the transformed payload).

## 9. How to add a detector

1. Write a class with the attributes of section 1 in `src/supervisor/detectors/<slug>.py`. Keep
   it pure: no network, no file reads, no model download. Return masked entities and fragments.
2. Give it `presets` with a `balanced` entry. Freeze them: add the numbers to
   `test_presets_are_frozen_per_version`.
3. Register it in `build_registry` (`src/supervisor/detectors/__init__.py`) and add an entry to
   `config/detectors.yaml` (`enabled`, `fail_closed`).
4. Add golden items (`golden.py`: dev, held-out, and at least a few probes outside the templates),
   regenerate with `--regenerate`, run the harness and record the baseline with `--record`.
5. Add tests: the contract (fires, does not fire, a failure becomes `execution_failed`), and that
   no raw value reaches a finding. Document the codes here.
6. A detector that uses a model needs a model card and a validation report under `judge/mrm/`
   conventions before it may run outside the mock path (team brief section 3, point 8).

## 10. Not in this version

See `BACKLOG.md` (WP37 rows): a console page for findings (WP39), per-entity mask tokens and
custom keyword rules for `dlp_vn`, tool-description scanning, the ML injection classifier
(WP25), a per-consumer policy binding (WP38).
