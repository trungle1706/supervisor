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
| `judge_moderation` (WP-D4, section 3e) | input, output | Toxicity (one yes or no answer) and up to 5 topics with definitions, asked of the judge one question at a time. Codes `moderation.toxic`, `moderation.topic:<name>`. Mock without a judge model, `mock: true` | `report` | 3000 / 5000 / 7000 |

`dlp_vn` settings: `mode` (`transform` or `report`), `transform_risk_classes` (default
`[pii_export]`), `transform_tools`. In transform scope the call carries the masked payload in
`transformed_payload` (and in `transformed_args` when the tool arguments changed, so the SDK and
the MCP proxy apply it as they do for WP24b). Outside the scope `dlp_vn` only reports.

`dlp_vn` also has two WP41 settings (section 3b): `keep_args` and `pseudonym_mode`.

`injection_regex` scores per group (illustrative): override 9000, mode switch 9000, policy
override 8500, role tag 8000, prompt leak 7000, urgent transfer 6500, plus 500 for each extra
hit. At the `balanced` preset an urgent-transfer phrase alone does not fire. Known gaps are in
`BACKLOG.md` and in the validation report (typos, leetspeak, base64, split fields, paraphrase).

`injection_classifier` (WP25, `enabled: false` by default, see `docs/injection-classifier.md`) is a fourth
detector. It is the only one whose `pause` hint the gate obeys: `GATE-CLASSIFIER-PAUSE`, money and credit tools only.

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

## 3b. Benchmark defects fixed in WP41 (ADR D33)

The M2 benchmark on a real bank agent found two defects in this layer. Both fixes are behind the
existing flag (`DETECTORS_ENABLED`) and weaken no control.

### Keep a lookup key unmasked (`keep_args`, D29)

The `dlp_vn` transform replaced the only argument of a `pii_export` lookup tool (a ten digit tax
code in `tax_code`) with a pseudonym, and the tool answered NOT_FOUND on 16 of 16 calls. A tool
that looks a record up by a personal identifier needs that identifier as sent. The policy can say
so, per tool and per argument name:

```yaml
agents:
  credit_memo_agent:
    detectors:
      settings:
        dlp_vn:
          keep_args:
            lookup_customer_basic_info: [tax_code]   # tool: [top-level argument names]
          pseudonym_mode: typed                       # optional, see below
    keep_args_approvals: [dpo.lan, sec.minh]          # WP41 review: two distinct ids
```

What happens on an allowed call to that tool:

| Where | The named argument |
|---|---|
| `transformed_args` and `transformed_payload.args` (what the tool receives) | **as sent** |
| findings (`entities`, `fragments`), `finding` rows, `agent_event`, the chain record, the SIEM event, the session sketch, the `args_hmac` | **masked / hashed**, as without `keep_args` |
| the answer | `kept_args: ["tax_code"]` (also in `coverage.kept_args`, stored in `coverage_json`) |
| Decisions drawer (Detections tab) and the CSV export | the names, in the section "Arguments passed unmasked" and in the column `kept_arguments` |
| chain record `gate_decision` | `kept_args` (names only) |

Rules: it is an agent setting (a `consumers.<id>.detectors` block that names it is refused by
the policy loader, and `config/detectors.yaml` may not set it: the shared file would apply it to
every agent without audit or approval); when it names a `money`, `credit` or `pii_export` tool
the agent needs two distinct approver ids in `keep_args_approvals` (same shape as
`rule_approvals`; left out of the hash when empty), or the policy is refused (WP41 review); it
applies to input checks only (never to an output check, never to `tool_results`, never to a
nested key of the same name); no environment variable or request field can set it; only top-level argument names, at most 8 per tool and 64 tools, plain identifiers. Only
`dlp_vn` honours it (it does nothing when `dlp_vn` is off for the agent). Other arguments of the
same call stay masked. A blocked or paused call has no transformed arguments, so nothing is kept.
**Loading** a policy with a `keep_args` entry writes one WARNING log line (`audit: dlp_vn
keep_args loaded for <agent>: <tool>=<names> (policy <hash16>, approvals <ids>)`) and one chain
record `policy_keep_args` (agent lane; agent, scope, policy hash, tool and argument names,
approver ids) at start and
at every changed reload. The setting is part of the policy hash, so adding or removing a
`keep_args` entry changes the hash. A wrong shape is refused when the policy loads (same path as
any bad override). Use it for a declared lookup key, not for free text: a kept argument is
personal data that reaches the tool in clear. A threat-model note is in `docs/threat-model.md`.

### Typed pseudonyms (`pseudonym_mode`, D29)

`generic` (default): the masker guesses the class from the value, so a bare ten digit tax code is
typed `<BANK_ACCOUNT:...>`. `typed`: a text value that sits directly under an argument whose NAME
says what it is (`tax`, `mst`, `ma_so_thue` / `account`, `acct`, `stk`, `tai_khoan`, as a word of
the name) is typed by the name: `<TAX_CODE:...>`, `<BANK_ACCOUNT:...>`. The class stays visible in
the finding code (`pii.tax_code`), the pseudonym is still keyed and not reversible, and the
nesting is followed (`rows[0].tax_code`).

| Need | Use |
|---|---|
| The tool must receive the real value (a lookup key) | `keep_args` |
| The tool does not need the value but the reviewer must see which class it was | `pseudonym_mode: typed` |
| Neither | the default |

`typed` alone does not repair a lookup: the tool still receives a pseudonym. It makes records,
findings and alerts say TAX_CODE where the digits alone looked like an account number.

### Scan limits (`max_scan_bytes`, `DETECTORS_SCAN_BUDGET_BYTES`, D30 and D18)

With three detectors on, 8 KB of tool results added 72 ms (p50) to a decision, and a 99 KB
argument full of personal data held the gate for 1.7 s. Now:

* every detector has a setting `max_scan_bytes` (default **16384**, 256 to 1,000,000; in the file
  or per agent): the most text it reads in one call;
* all detectors together read at most **`DETECTORS_SCAN_BUDGET_BYTES`** (default **65536**; file
  key `limits.scan_budget_bytes`; the environment value wins) per call. The budget is spent in
  catalogue order: a detector that finds it empty is listed as not executed with the reason
  `payload_too_large`;
* arguments are read first, tool results last (the order of the parts), so a long document
  cannot push the arguments out;
* text beyond the limit is **not scanned**. The coverage says so: the part moves from `inspected`
  to `not_inspected` with `{"reason": "payload_too_large", "bytes": 42000, "scanned_bytes": 16382}`
  (the least any detector read), and `coverage.bytes` holds the total. The chain keeps the same
  integers. The drawer shows `scanned / total B`;
* `dlp_vn` never transforms text it only read in part. If its transform scope covers the call
  and an **argument** or the **output** was cut, it does not run (`payload_too_large`), whether
  or not the part it could read held personal data (WP41 review: before, clean padding followed
  by a phone number passed with `allow` and the raw number reached the tool), and on a `money`, `credit` or `pii_export`
  tool the existing rule `GATE-DETECTOR-FAILED` blocks the call (fail closed: the unmasked rest
  must not reach the tool). A cut **tool result** only drops that part from the transformed
  payload (no caller applies it). To let a larger argument through, raise `max_scan_bytes` for
  `dlp_vn` on that agent and check the latency;
* `limits.max_payload_chars` (100,000) stays as the outer bound: above it no detector runs;
* a shared memoising masker (it keeps the masked text, keyed by SHA-256, never the raw text)
  makes the second and third detector read a long text for the cost of a hash, and
  `injection_regex` stops at its byte budget and when every group is already at the top score.

Measured on the development host (SQLite, two detectors on, `dlp_vn` and `injection_regex`;
numbers in `HANDOFF_WP41.md` and `REVIEW_WP41.md`): 8 KB of tool results cost 20 to 25 ms before
and 12 to 15 ms now (p50, detector time, host load about 3.6), and the 99 KB argument is
answered in under 70 ms instead of 2 s or more. The target "under 10 ms added" is **not met**.

### Cut arguments fail closed on every risky tool (WP41b, D31 and D32)

The second benchmark showed two gaps in the rules above.

* **D31 (High).** Only a detector that would transform the call (`dlp_vn`) failed closed on a
  cut argument. A `credit` or `money` tool whose argument was cut by the scan budget (a 118 KB
  argument, 16 KB read) was allowed with status `report` and 85 percent of the text unread. Now,
  when the scan budget cuts **any argument** of a `money`, `credit` or `pii_export` call, the
  decision is a block with rule `GATE-DETECTOR-FAILED` and the reason
  `*:payload_too_large` (one `not_executed` row with the detector slug `*`, detail "arguments
  cut by scan budget"), whatever detectors are on (at least one enabled detector must be
  `fail_closed`, as for every other failure). A `read_only` tool and a cut tool result stay
  coverage only. Observe mode and the `fail_closed_risk_classes` limit apply as before.
* **D32 (Medium).** The 99 KB `pii_export` call failed closed as designed but took 879 ms p50
  on the benchmark host (18 ms in the lab). The cost was the inline masker (`INLINE_REDACTION_ENABLED`),
  which read all 99 KB before the gate knew the call would be refused; the detectors, the
  record (`args_masked` holds argument names and key hashes, never text) and the SIEM event were
  cheap. With the detector gate on, an argument above the `dlp_vn` `max_scan_bytes` (a check
  that stops at the limit) is not masked **when the detector result already fails the call
  closed**: `GATE-DETECTOR-FAILED` answers in 15 to 17 ms. The full argument is still covered by
  `args_hmac` (a keyed hash of all of it); the record holds the byte count in the coverage
  (`bytes`, `scanned_bytes`). When nothing refuses the call (every detector `fail_closed: false`,
  `pii_export` left out of `fail_closed_risk_classes`, every detector disabled for the agent,
  observe mode lifting the block on a non-pii_export tool in `redact_tools`), the masker runs on
  the full text as in WP24b, so a big `pii_export` argument never reaches the tool unmasked
  (WP41b review). With `dlp_vn` off, or with no detector gate, the masker runs as in WP24b.
* A cut row of a detector that is not `fail_closed` (for example `dlp_vn` with
  `fail_closed: false`) does not replace the `*:payload_too_large` row: the call still fails
  closed when any other enabled detector is `fail_closed` (WP41b review).

## 3c. `mrm_status` per detector (D24, D25)

Each detector entry in `config/detectors.yaml` has `mrm_status: GO | NO-GO` (default `NO-GO`).
It feeds one reader: the session monitor (`docs/session-monitor.md` section 2). Findings of a
detector that is deterministic (`dlp_vn`, `injection_regex`: `deterministic = True` in code) or
has `mrm_status: GO` count in the `findings` signal; findings of any other detector are recorded
on the turn and weigh 0. Shipped: `dlp_vn` GO, `injection_regex` GO, `injection_classifier`
NO-GO (held-out recall 8111 bp, false alarm 2522 bp), `judge_advisory` NO-GO, `judge_moderation` NO-GO. The status never
changes what the gate answers or records for the decision itself.

## 3e. `judge_moderation`: toxicity and topic scope (WP-D4)

Phase 5. A judge detector that answers two kinds of question about text. It advises and reports;
it never blocks, pauses or transforms (R1), it never fails closed, and it is off by default
(`judge_moderation.enabled: false`, `mrm_status: NO-GO`). With the slug absent from
`config/detectors.yaml`, or with `enabled: false`, nothing changes: no judge call, no finding.

| Item | Rule |
|---|---|
| Sides and parts | `input`: the user text in `args` (the latest `role: user` message when `args.messages` is a list, else every string leaf). `output`: the assistant text in `output` |
| Questions | `toxicity: {enabled}`: is the text toxic (abusive, hateful, degrading, threatening)? One answer, no breakdown by kind. `topics: [{name, definition}]`: does the text belong to this subject? One answer per topic; the other topics never change its score |
| Limits | At most 5 topics per detector (add a second detector entry for more). `name` 1 to 120 characters and unique. `definition` up to 400 characters. Unknown keys are errors. Checked when the file loads (`DetectorsFile`, per-agent override too), so a bad topic is a startup error, not a runtime surprise |
| What is scored | The DEFINITION. The name is only the label of the finding |
| Prompts | One prompt per question and per window, on masked text. The judge answers `{answer: yes or no, score_bp, reason}` in a strict schema. A reply with the canary token (the model obeyed the data) is dropped and listed as `not_executed` `execution_failed`; it never becomes a finding |
| Windows | The first 10 000 characters, in windows of 1 200 characters with 200 overlap (at most 10). The highest window score per question wins, so a subject at the end of a long text is found. Text past 10 000 characters is not read |
| Findings | `moderation.toxic`, `moderation.topic:<name>`. Score in basis points. A finding is returned when the score reaches the threshold (strict 3000, balanced 5000, lenient 7000; one threshold for all topics). `action_hint` is always `report`. No text in a finding |
| Judge | The Tier 1 judge the product built for `judge_advisory` (same model, same family rule: the judge family differs from every agent family, checked in `JudgeRouter`). Without a judge model the labelled MockJudge answers (keyword cues; it proves the harness, not a model) and every finding says `mock: true` |
| Cost | Up to 1 + 5 questions times up to 10 windows per call. A real judge adds that latency to the gate answer, so keep the detector off in the hot path until a latency budget is set (same open point as `judge_advisory`) |

Settings, in `config/detectors.yaml` or per agent (`agents.<id>.detectors.settings.judge_moderation`):

```yaml
judge_moderation:
  enabled: true
  settings:
    toxicity: {enabled: true}
    topics:
      - name: Financial advice
        definition: Personal recommendations about what to invest in, buy, sell or borrow ...
```

Ten editable drafts, in Vietnamese and English, are in `config/moderation_topics.yaml` (financial
advice, legal advice, politics, religion, competitor products, internal project names, medical
advice, illegal activity, adult content, code generation). The file is a menu: the detector never
reads it and none of the drafts is enabled. Copy a draft into the settings and edit it. Write one
plain sentence that says what belongs to the topic, in the language of your traffic; do not name a
neighbouring topic to rule it out; do not paste example messages. After a change, run the harness
on sample messages before you turn the topic on.

Harness: `python -m supervisor.detectors.harness --detector judge_moderation` (golden set in
`src/supervisor/detectors/moderation_golden.py`: toxic and benign, on-topic and off-topic, VI and
EN, 21 dev, 20 held-out and 10 adversarial items; the rubric is in that file). Report:
`docs/judge-moderation-validation-report.md`. It ran on the MockJudge, so the numbers prove the
harness; `mrm_status` stays NO-GO until a real judge model runs the set (see `docs/judge-mrm.md`).

## 4. Verdict v2 and precedence

The status of a verdict:

| Rank | Status | When |
|---|---|---|
| 5 | `block` | A deterministic rule, a built-in block or `GATE-DETECTOR-FAILED` denied the call. Also when a block rule matched together with a pause rule that decided first |
| 4 | `pause` | A pause denied the call and no block rule matched: a pause rule, the classifier pause (`GATE-CLASSIFIER-PAUSE`), the state pause of an already paused agent (`GATE-PAUSED`) or the session pause (`GATE-SESSION-PAUSE`) (D26, WP41b). The old `action` field of the two built-in pauses stays `block` |
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
when it was provided, every leaf is readable text (or a number), the total size is within
`limits.max_payload_chars` and every detector could read all of it (section 3b: `max_scan_bytes`
and the scan budget). A part that was read in part is listed with `payload_too_large` and the
integers `bytes` and `scanned_bytes`. Coverage lists parts, reasons and integers only, never text.

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
